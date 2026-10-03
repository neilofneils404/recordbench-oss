#!/usr/bin/env python3
"""Check the assistant dock's Close control and page-aware suggestions with synthetic records."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading

import uvicorn
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from case_intelligence.generation import UnavailableGenerator
from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.workbench import create_workbench_app

ACTOR = "development-taylor-morgan"
SOURCE_NAME = "Synthetic dock journey — North Annex receiving notes with a long recognizable filename.txt"
SOURCE_TEXT = "The blue crate arrived at the North Annex on 2026-03-05 at 09:15, signed for by Alex Example."


def prepare_output(output: Path) -> None:
    """Accept the runner's new empty directory, never overwrite older evidence."""
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ValueError("Choose a fresh or empty output directory; existing results were preserved.")
    output.mkdir(parents=True, exist_ok=True)


def failure_evidence(output: Path, driver, report: dict, error: Exception) -> None:
    report.update(passed=False, error={"type": type(error).__name__, "message": str(error)[:2000]})
    if driver is not None:
        try:
            driver.save_screenshot(str(output / "failure.png"))
        except Exception as capture_error:
            report["screenshot_error"] = type(capture_error).__name__
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")


def seed(bench):
    matter = bench.create_matter("Synthetic dock review", "Invented records for dock acceptance", ACTOR)
    store = bench.source_store(matter)
    document, _ = store.store_stream(SOURCE_NAME, "text/plain", io.BytesIO(SOURCE_TEXT.encode()))
    return f"/matters/{matter.slug}", f"/matters/{matter.slug}/sources/{store.action_token(document)}"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome-binary", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    prepare_output(args.output)
    from synthetic_browser_environment import isolate_environment
    isolate_environment()
    checks = []
    receipt = {"passed": False, "synthetic_only": True,
        "provenance": "temporary synthetic records; no model or live storage",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "checks": checks,
        "unrun_checks": ["screen reader", "WebKit", "physical mobile", "submitted answers (no model)"]}

    with tempfile.TemporaryDirectory(prefix="recordbench-dock-") as temporary:
        app = create_workbench_app(Path(temporary).resolve() / "runtime", auth_mode="test",
            generator=UnavailableGenerator(), learned_retrieval=False, background_ingestion=False,
            storage_policy=StoragePolicy(reserve_bytes=0))
        prefix, reader = seed(app.state.workbench)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        options = Options()
        options.binary_location = str(args.chrome_binary)
        if sys.platform == "linux":
            options.add_argument("--no-sandbox")
        for flag in ("--headless=new", "--disable-dev-shm-usage", "--window-size=1440,900"):
            options.add_argument(flag)
        driver = None
        try:
            driver = webdriver.Chrome(service=Service(str(args.chromedriver)), options=options)
            wait = WebDriverWait(driver, 15)
            receipt["browser"] = {"name": driver.capabilities["browserName"], "version": driver.capabilities["browserVersion"]}
            wait.until(lambda _: server.started)
            js = driver.execute_script
            find = lambda selector: driver.find_element(By.CSS_SELECTOR, selector)
            rect = lambda element: js("return arguments[0].getBoundingClientRect().toJSON()", element)

            def viewport(width, height):
                driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

            def open_page(path):
                driver.get(base + path)
                wait.until(lambda _: js("return document.readyState") == "complete")
                # A remembered collapsed dock must not hide the controls under test.
                if "assistant-collapsed" in find("body").get_attribute("class"):
                    find("[data-assistant-expand]").click()
                    wait.until(lambda _: "assistant-collapsed" not in find("body").get_attribute("class"))

            def no_page_overflow():
                assert js("return document.documentElement.scrollWidth <= innerWidth"), "page scrolls sideways"

            def header_fits():
                dock = rect(find(".assistant-panel"))
                close = rect(find("[data-assistant-collapse]"))
                assert close["right"] <= dock["right"] + 1 and close["left"] >= dock["left"] - 1, (close, dock)

            def suggestions():
                heading = find("#assistant-suggestions-heading").text
                buttons = driver.find_elements(By.CSS_SELECTOR, "[data-assistant-suggestion]")
                return heading, [button for button in buttons if button.is_displayed()]

            viewport(1440, 900)
            open_page(reader)
            wait.until(lambda _: driver.find_elements(By.CSS_SELECTOR, "[data-assistant-suggestion]"))
            heading, buttons = suggestions()
            assert heading == "Suggested for this source", heading
            assert [button.text for button in buttons] == [
                "Summarize this source", "Who and what appears here", "What dates appear here"]
            scope = lambda: js("const s=document.querySelector('select[name=source_set]');"
                               "return s.selectedOptions[0] ? s.selectedOptions[0].textContent : ''")
            assert scope().startswith("All searchable sources"), scope()
            close = find("[data-assistant-collapse]")
            assert close.text.strip() == "Close" and "Close" in close.get_attribute("aria-label")
            no_page_overflow()
            header_fits()
            driver.save_screenshot(str(args.output / "dock-source-1440.png"))
            checks.append("At 1440px with a source open, the dock offers three questions about that source and a visible Close control")

            # Native keyboard: Tab from the start of the page reaches a suggestion; Enter fills, never sends.
            js("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)")
            find("body").send_keys(Keys.TAB)
            for _ in range(250):
                active = driver.switch_to.active_element
                if active.get_attribute("data-assistant-suggestion"):
                    break
                active.send_keys(Keys.TAB)
            else:
                raise AssertionError("No suggestion is reachable with Tab")
            question = active.get_attribute("data-assistant-suggestion")
            active.send_keys(Keys.ENTER)
            textarea = find("#assistant-question")
            wait.until(lambda _: textarea.get_attribute("value") == question)
            # The question was filled only after the next question was limited to this source.
            assert scope() == "Only · " + SOURCE_NAME, scope()
            assert "limited to this source" in find("[data-assistant-suggestion-status]").text
            wait.until(lambda _: driver.switch_to.active_element == textarea)
            assert not find("[data-assistant-status]").is_displayed(), "a suggestion submitted a question"
            assert app.state.workbench.workspace.latest_answer_job(
                app.state.workbench.matter(prefix.split("/")[2], ACTOR).matter_id,
                find("[data-assistant-dock]").get_attribute("data-conversation-id"), ACTOR) is None
            checks.append("Tab reaches a suggestion; Enter limits the next question to this source, then fills and focuses the question box without creating an answer request")

            close = find("[data-assistant-collapse]")
            js("arguments[0].focus()", close)
            close.send_keys(Keys.ENTER)
            wait.until(lambda _: "assistant-collapsed" in find("body").get_attribute("class"))
            expand = find("[data-assistant-expand]")
            wait.until(lambda _: driver.switch_to.active_element == expand)
            expand.send_keys(Keys.ENTER)
            wait.until(lambda _: "assistant-collapsed" not in find("body").get_attribute("class"))
            wait.until(lambda _: driver.switch_to.active_element == find("#assistant-question"))
            assert find("#assistant-question").get_attribute("value") == question
            checks.append("Close and reopen work from the keyboard, move focus to the reopen tab and back to the kept question")

            # A new chat drafted in the browser offers the same source suggestions.
            find("[data-assistant-new-chat]").click()
            wait.until(lambda _: driver.find_elements(By.CSS_SELECTOR, ".assistant-draft-empty [data-assistant-suggestion]"))
            draft = find(".assistant-draft-empty")
            assert draft.find_element(By.CSS_SELECTOR, ".assistant-suggestions-heading").text == "Suggested for this source"
            assert scope().startswith("All searchable sources"), scope()
            # A slow scope response must hold the composer: nothing can be sent or typed meanwhile.
            js("const original = window.fetch; window.fetch = (url, init) => /\\/sources\\/[^/]+\\/ask/.test(String(url))"
               " ? new Promise((resolve) => setTimeout(resolve, 1500)).then(() => original(url, init)) : original(url, init);")
            find("#assistant-question").send_keys("Synthetic unsent draft")
            draft.find_elements(By.CSS_SELECTOR, "[data-assistant-suggestion]")[2].click()
            composer = js("const t=document.querySelector('#assistant-question'), b=t.form.querySelector('button[type=submit]');"
                          "return [t.disabled, b.disabled, t.value, document.querySelector('.assistant-draft-empty .assistant-suggestions').getAttribute('aria-busy')]")
            assert composer == [True, True, "Synthetic unsent draft", "true"], composer
            wait.until(lambda _: find("#assistant-question").get_attribute("value")
                       == "Which dates appear in this source, and what happened on each?")
            assert scope() == "Only · " + SOURCE_NAME, scope()
            assert js("const t=document.querySelector('#assistant-question');"
                      "return !t.disabled && !t.form.querySelector('button[type=submit]').disabled")
            ids = js("return [...document.querySelectorAll('[id]')].map(e => e.id)")
            assert len(ids) == len(set(ids)), "duplicate ids after drafting a new chat"
            checks.append("New chat offers the same source suggestions; while a slow scope response is pending the question box, Send and suggestions are held, then the box is filled with the scope applied")

            open_page(prefix + "/notebook")
            wait.until(lambda _: driver.find_elements(By.CSS_SELECTOR, "[data-assistant-suggestion]"))
            heading, buttons = suggestions()
            assert heading == "Suggested questions" and [button.text for button in buttons] == [
                "Summarize the records", "Find people and organizations", "Review dates and events"]
            buttons[0].click()
            wait.until(lambda _: find("#assistant-question").get_attribute("value") == "Summarize the records in this matter.")
            assert scope().startswith("All searchable sources"), scope()
            checks.append("Pages without an open source keep the general suggestions, which fill the box without changing scope")

            for width, height in ((390, 844), (320, 640)):
                viewport(width, height)
                open_page(reader)
                wait.until(lambda _: driver.find_elements(By.CSS_SELECTOR, "[data-assistant-suggestion]"))
                no_page_overflow()
                header_fits()
                for button in suggestions()[1]:
                    box = rect(button)
                    assert box["right"] <= width + 1, (width, box)
                driver.save_screenshot(str(args.output / f"dock-source-{width}.png"))
            checks.append("At 390px and 320px the dock, its Close control and source suggestions fit without sideways scrolling")

            receipt["passed"] = True
            (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt))
        except Exception as exc:
            failure_evidence(args.output, driver, receipt, exc)
            raise
        finally:
            if driver is not None:
                driver.quit()
            server.should_exit = True
            thread.join(10)


if __name__ == "__main__":
    main()
