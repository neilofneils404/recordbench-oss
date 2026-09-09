#!/usr/bin/env python3
"""Check shared alignment and independent scrolling using synthetic records."""
from __future__ import annotations

import argparse
import io
import json
import os
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
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from case_intelligence.generation import UnavailableGenerator
from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.workbench import create_workbench_app

ACTOR = "development-taylor-morgan"


def seed(bench):
    for index in range(36):
        bench.create_matter(f"Synthetic workspace {index:02}", "Invented layout acceptance", ACTOR)
    matter = bench.create_matter("Synthetic long review", "Invented records for layout acceptance", ACTOR)
    document, _ = bench.source_store(matter).store_stream("Synthetic source.txt", "text/plain",
        io.BytesIO(b"The blue crate arrived at the North Annex at 09:15."))
    for index in range(32):
        bench.workspace.create_notebook_item(matter.matter_id, ACTOR, item_type="note", status="needs_review",
            title=f"Synthetic observation {index:02}", body="The invented reviewer is checking the blue crate against the source record. " * 18)
    for index in range(28):
        conversation = bench.workspace.create_conversation(matter.matter_id, f"Synthetic conversation {index:02}", actor_id=ACTOR)
    for index in range(16):
        bench.workspace.append_message(matter.matter_id, conversation.conversation_id, "user", f"What does synthetic passage {index + 1} say?")
        bench.workspace.append_message(matter.matter_id, conversation.conversation_id, "assistant",
            "This invented response exercises a long review page. " * 6)
    candidate = bench._candidate(matter, document, document.parsed_units()[0], 1)
    return f"/matters/{matter.slug}", conversation.conversation_id, bench._support_token(candidate)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome-binary", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name in tuple(os.environ):
        if name.startswith(("CASE_INTELLIGENCE_", "CASE_REVIEW_")):
            os.environ.pop(name)
    checks, alignment, conversation_layouts = [], {}, {}
    with tempfile.TemporaryDirectory(prefix="recordbench-layout-") as temporary:
        app = create_workbench_app(Path(temporary).resolve() / "runtime", auth_mode="test",
            generator=UnavailableGenerator(), learned_retrieval=False, background_ingestion=False,
            storage_policy=StoragePolicy(reserve_bytes=0))
        prefix, conversation, support = seed(app.state.workbench)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        options = Options()
        options.binary_location = str(args.chrome_binary)
        for flag in ("--headless=new", "--disable-dev-shm-usage", "--window-size=1440,900"):
            options.add_argument(flag)
        driver = None
        try:
            driver = webdriver.Chrome(service=Service(str(args.chromedriver)), options=options)
            wait = WebDriverWait(driver, 15)
            wait.until(lambda _: server.started)
            find = lambda selector: driver.find_element(By.CSS_SELECTOR, selector)
            js = driver.execute_script
            rect = lambda element: js("return arguments[0].getBoundingClientRect().toJSON()", element)
            scroll = lambda element: js("return arguments[0].scrollTop", element)

            def viewport(width, height):
                driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

            def go(suffix):
                driver.get(base + prefix + suffix)
                # Use the existing dock control so all pages expose their main
                # working area; this preference is retained across navigation.
                buttons = driver.find_elements(By.CSS_SELECTOR, "[data-assistant-collapse]")
                if buttons and buttons[0].is_displayed():
                    buttons[0].click()
                wait.until(lambda _: js("return document.documentElement.scrollWidth <= innerWidth"))

            def wheel(x, y, amount):
                ActionChains(driver).scroll_from_origin(ScrollOrigin.from_viewport(round(x), round(y)), 0, amount).perform()

            def screenshot(name):
                driver.save_screenshot(str(args.output / f"{name}.png"))

            paths = {"review": f"?conversation={conversation}", "work-product": "/work-product", "notes": "/notebook"}
            for width, height in ((1800, 1000), (1440, 480), (390, 844)):
                viewport(width, height)
                edges = []
                for name, suffix in paths.items():
                    go(suffix)
                    edge = rect(find("main .matter-section-tabs"))["left"]
                    edges.append(edge)
                    screenshot(f"{name}-{width}x{height}")
                    if width == 390 and name == "notes":
                        assert js("return getComputedStyle(arguments[0]).position", find(".notebook-tools")) == "static"
                        assert js("return arguments[0].clientHeight >= arguments[0].scrollHeight - 1", find(".notebook-tools"))
                assert max(edges) - min(edges) <= 1, edges
                alignment[f"{width}x{height}"] = edges
            checks.append("Review, Work product and Case notes share a left edge at wide, short and mobile sizes")
            checks.append("Narrow Case notes tools stay in ordinary page flow without a nested scroll viewport")

            for height in (900, 480):
                viewport(1440, height)
                go(paths["review"])
                pane = find(".workspace-main")
                wheel(1200, height // 2, 1900)
                wait.until(lambda _: scroll(pane) > 1000)
                history = find(".conversation-history")
                history_bounds = rect(history)
                assert history_bounds["top"] >= rect(find(".topbar"))["bottom"]
                assert history_bounds["bottom"] <= rect(find(".composer-wrap"))["top"] - 5
                nav = find("[data-conversation-list]")
                previous_pane = scroll(pane)
                bounds = rect(nav)
                wheel(bounds["right"] - 8, (bounds["top"] + bounds["bottom"]) / 2, 700)
                wait.until(lambda _: scroll(nav) > 0)
                assert abs(scroll(pane) - previous_pane) <= 1
                nav.send_keys(Keys.END)
                wait.until(lambda _: js("return arguments[0].scrollTop + arguments[0].clientHeight >= arguments[0].scrollHeight - 2", nav))
                last = nav.find_elements(By.CSS_SELECTOR, "a")[-1]
                assert rect(last)["bottom"] <= rect(nav)["bottom"] + 1
                screenshot(f"review-independent-history-{height}")

                go(paths["notes"])
                wheel(1200, height // 2, 1900)
                wait.until(lambda _: js("return scrollY") > 1000)
                tools = find(".notebook-tools")
                assert rect(tools)["top"] >= rect(find(".topbar"))["bottom"]
                assert rect(tools)["bottom"] <= height - 8
                previous_page = js("return scrollY")
                bounds = rect(tools)
                wheel(bounds["right"] - 8, (bounds["top"] + bounds["bottom"]) / 2, 1200)
                wait.until(lambda _: scroll(tools) > 0)
                assert abs(js("return scrollY") - previous_page) <= 1
                tools.send_keys(Keys.END)
                wait.until(lambda _: rect(find(".suggestion-tool button"))["bottom"] <= rect(tools)["bottom"])
                assert rect(find(".suggestion-tool button"))["top"] >= rect(tools)["top"]

                rail, matter_list = find(".matter-rail"), find(".matter-list")
                rail_before = rect(rail)
                bounds = rect(matter_list)
                wheel(bounds["right"] - 8, (bounds["top"] + bounds["bottom"]) / 2, 1600)
                wait.until(lambda _: scroll(matter_list) > 0)
                matter_list.send_keys(Keys.END)
                wait.until(lambda _: js("return arguments[0].scrollTop + arguments[0].clientHeight >= arguments[0].scrollHeight - 2", matter_list))
                assert rect(matter_list.find_elements(By.CSS_SELECTOR, "a")[-1])["bottom"] <= rect(matter_list)["bottom"] + 1
                assert abs(js("return scrollY") - previous_page) <= 1
                assert rect(rail) == rail_before
                assert rect(find("[data-rail-collapse]"))["bottom"] <= height
                screenshot(f"notes-and-matter-rail-independent-{height}")
            checks.append("Native wheel scrolls long right-hand content while Review history remains above the composer")
            checks.append("Native wheel and End key reach the bottom of conversation history without moving the review pane")
            checks.append("Native wheel and End key reach Case notes tools without moving the long notes page")
            checks.append("37-matter rail scrolls independently, remains fixed and keeps its bottom control reachable")
            for width in (761, 820, 900):
                viewport(width, 900)
                go(paths["review"])
                pane = find(".workspace-main")
                wheel(width - 30, 300, 1900)
                wait.until(lambda _: scroll(pane) > 1000)
                history, active = find(".conversation-history"), find(".conversation-active")
                composer = find(".composer-wrap")
                history_bounds, active_bounds = rect(history), rect(active)
                assert history_bounds["right"] + 16 <= active_bounds["left"]
                assert history_bounds["bottom"] <= rect(composer)["top"] - 5
                assert js("const r=arguments[0].getBoundingClientRect(); return arguments[0].contains(document.elementFromPoint(r.left+r.width/2, arguments[1]))", active, history_bounds["top"] + 100)
                conversation_layouts[str(width)] = {
                    "columns": js("return getComputedStyle(arguments[0]).gridTemplateColumns", find(".conversation-workspace")),
                    "history_right": history_bounds["right"], "active_left": active_bounds["left"],
                    "history_bottom": history_bounds["bottom"], "composer_top": rect(composer)["top"],
                }
                nav = find("[data-conversation-list]")
                previous_pane, bounds = scroll(pane), rect(nav)
                wheel(bounds["right"] - 8, (bounds["top"] + bounds["bottom"]) / 2, 700)
                wait.until(lambda _: scroll(nav) > 0)
                nav.send_keys(Keys.END)
                wait.until(lambda _: js("return arguments[0].scrollTop + arguments[0].clientHeight >= arguments[0].scrollHeight - 2", nav))
                assert abs(scroll(pane) - previous_pane) <= 1
                screenshot(f"review-support-closed-{width}")
            viewport(760, 900)
            go(paths["review"])
            pane, history, active, nav = find(".workspace-main"), find(".conversation-history"), find(".conversation-active"), find("[data-conversation-list]")
            assert js("return getComputedStyle(arguments[0]).position", history) == "static"
            assert js("return getComputedStyle(arguments[0]).maxHeight", nav) == "250px"
            assert rect(history)["bottom"] <= rect(active)["top"]
            assert abs(rect(history)["left"] - rect(active)["left"]) <= 1
            wheel(730, 300, 1900)
            wait.until(lambda _: scroll(pane) > 1000)
            assert rect(history)["bottom"] <= rect(find(".topbar"))["bottom"]
            assert js("const r=arguments[0].getBoundingClientRect(); return arguments[0].contains(document.elementFromPoint(r.left+r.width/2, 200))", active)
            conversation_layouts["760"] = {"history_position": "static", "list_max_height": "250px", "history_bottom_after_scroll": rect(history)["bottom"]}
            screenshot("review-support-closed-760-stacked")
            checks.append("Without support, 761/820/900px history stays beside clickable active content and scrolls independently; at760px capped static history scrolls away above the conversation")
            for width in (761, 820, 900):
                viewport(width, 900)
                go(paths["review"] + f"&support={support}")
                pane = find(".workspace-main")
                # Scroll the review itself, above the open support drawer.
                wheel(width - 30, 180, 1900)
                wait.until(lambda _: scroll(pane) > 1000)
                history, composer, drawer = find(".conversation-history"), find(".composer-wrap"), find(".support-pane")
                assert rect(history)["top"] >= rect(find(".topbar"))["bottom"]
                assert rect(history)["bottom"] <= rect(composer)["top"] - 5, (width, rect(history), rect(composer))
                assert rect(composer)["bottom"] <= rect(drawer)["top"] + 1
                nav = find("[data-conversation-list]")
                bounds, previous_pane = rect(nav), scroll(pane)
                wheel(bounds["right"] - 8, (bounds["top"] + bounds["bottom"]) / 2, 700)
                wait.until(lambda _: scroll(nav) > 0)
                nav.send_keys(Keys.END)
                wait.until(lambda _: js("return arguments[0].scrollTop + arguments[0].clientHeight >= arguments[0].scrollHeight - 2", nav))
                assert abs(scroll(pane) - previous_pane) <= 1
                assert rect(nav.find_elements(By.CSS_SELECTOR, "a")[-1])["bottom"] <= rect(nav)["bottom"] + 1
                screenshot(f"review-support-open-{width}")
            viewport(820, 650)
            # Resize the open page without navigation: the drawer offset changes
            # independently of the composer's intrinsic dimensions.
            wait.until(lambda _: rect(find(".conversation-history"))["bottom"] <= rect(find(".composer-wrap"))["top"] - 5)
            history, nav = find(".conversation-history"), find("[data-conversation-list]")
            previous_pane = scroll(find(".workspace-main"))
            bounds = rect(history)
            wheel(bounds["right"] - 8, (bounds["top"] + bounds["bottom"]) / 2, 1900)
            nav.send_keys(Keys.END)
            last = nav.find_elements(By.CSS_SELECTOR, "a")[-1]
            wait.until(lambda _: rect(last)["bottom"] <= rect(history)["bottom"] + 1)
            assert rect(last)["top"] >= rect(history)["top"]
            assert js("const r=arguments[0].getBoundingClientRect(); return arguments[0].contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))", last)
            assert abs(scroll(find(".workspace-main")) - previous_pane) <= 1
            screenshot("review-support-open-short-tablet")
            checks.append("Tablet support drawer and composer leave conversation navigation independently scrollable at 761, 820 and 900 pixels")
            checks.append("Resizing open support to 820x650 keeps the whole history scrollable and its final link clickable above the composer")
            receipt = {"provenance": "temporary synthetic records; no model or live storage", "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "working_tree_clean": not bool(subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()), "checks": checks, "left_edges": alignment, "conversation_layouts": conversation_layouts}
            (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt))
        finally:
            if driver is not None:
                driver.quit()
            server.should_exit = True
            thread.join(10)


if __name__ == "__main__":
    main()
