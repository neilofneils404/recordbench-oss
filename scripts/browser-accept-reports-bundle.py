#!/usr/bin/env python3
"""Exercise saved Report downloads and deliberate synthetic closure in Chrome."""
from __future__ import annotations

import argparse
import io
import json
import socket
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from case_intelligence.generation import UnavailableGenerator  # noqa: E402
from case_intelligence.workbench import create_workbench_app  # noqa: E402

ACTOR = "development-taylor-morgan"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome-binary", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-readiness", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    checks = []

    with tempfile.TemporaryDirectory(prefix="recordbench-reports-browser-") as temporary:
        root = Path(temporary)
        downloads = root / "downloads"
        downloads.mkdir()
        original = root / "generated-note.txt"
        original.write_bytes(b"Synthetic source: the blue vehicle arrived at noon.\n")
        original_bytes = original.read_bytes()
        app = create_workbench_app(
            root / "runtime", generator=UnavailableGenerator(), auth_mode="test",
            background_ingestion=True,
        )
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        options = Options()
        options.binary_location = str(args.chrome_binary)
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1440,1000"):
            options.add_argument(flag)
        options.add_experimental_option("prefs", {
            "download.default_directory": str(downloads), "download.prompt_for_download": False,
        })
        driver = None
        try:
            driver = webdriver.Chrome(service=Service(str(args.chromedriver)), options=options)
            driver.implicitly_wait(3)
            wait = WebDriverWait(driver, 20)
            wait.until(lambda _: server.started)

            def go(path):
                driver.get(base + path)

            def detached(element):
                try:
                    return EC.staleness_of(element)(driver)
                except WebDriverException as exc:
                    if "Node with given id does not belong to the document" not in exc.msg:
                        raise
                    return True

            def click(selector):
                element = driver.find_element(By.CSS_SELECTOR, selector)
                driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'});", element)
                submits = element.tag_name == "button" and element.get_attribute("type") == "submit"
                element.click()
                if submits:
                    wait.until(lambda _: detached(element))

            def fill(selector, value):
                element = driver.find_element(By.CSS_SELECTOR, selector)
                element.clear()
                element.send_keys(value)

            def download(selector, suffix):
                before = set(downloads.iterdir())
                click(selector)
                return wait.until(lambda _: next((path for path in downloads.iterdir()
                    if path not in before and path.suffix == suffix), None))

            go("/matters/new")
            fill("#matter-name", "Synthetic report acceptance")
            click(".matter-form button[type=submit]")
            wait.until(lambda d: "/setup" in d.current_url)
            slug = urlparse(driver.current_url).path.split("/")[2]
            prefix = f"/matters/{slug}"
            click("[data-assistant-collapse]")
            # Real selection, preflight, and confirmed browser upload.
            driver.find_element(By.ID, "source-files").send_keys(str(original))
            wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "[data-upload-preflight-confirm]").is_enabled())
            click("[data-upload-preflight-confirm]")
            bench = app.state.workbench
            matter = bench.matter(slug, ACTOR)
            document = wait.until(lambda _: next((item for item in bench.source_store(matter).documents.values()
                                                  if item.state == "ready"), None))
            candidate = bench._candidate(matter, document, document.parsed_units()[0], 1)
            token = bench._support_token(candidate)
            go(prefix + f"?support={token}#support-pane")
            assert "the blue vehicle arrived at noon" in driver.find_element(By.ID, "support-pane").text
            click(".support-save-button")
            wait.until(lambda d: "/notebook" in d.current_url)
            checks.append("Upload, exact source passage, and save to case notes")

            go(prefix + "/reports")
            fill(".report-create-card input[name=title]", "Synthetic review memo")
            fill(".report-create-card textarea[name=purpose]", "Preserve edited source-supported work.")
            click(".report-create-card button[type=submit]")
            wait.until(lambda d: bool(d.find_elements(By.CSS_SELECTOR, ".report-settings")))
            click(".report-add-material details:nth-child(2) summary")
            click("form[action*='/from-notebook/'] button")
            fill(".report-add-material input[name=heading]", "Human conclusion")
            fill(".report-add-material textarea[name=body]", "Original draft text.")
            click(".report-add-material details:first-child button")
            cards = driver.find_elements(By.CSS_SELECTOR, ".report-section-card")
            assert len(cards) == 2
            fill(f"#{cards[1].get_attribute('id')} textarea[name=body]", "Edited conclusion retained in both exports.")
            click(f"#{cards[1].get_attribute('id')} .report-section-content form:first-child button")
            move = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Move Human conclusion up']")
            move.send_keys(Keys.ENTER)
            wait.until(lambda _: detached(move))
            assert driver.find_elements(By.CSS_SELECTOR, ".report-section-card input[name=heading]")[0].get_attribute("value") == "Human conclusion"
            Select(driver.find_element(By.CSS_SELECTOR, ".report-settings select")).select_by_value("final")
            click(".report-settings form:first-child button")
            checks.append("Create, edit, reorder by keyboard, and finalize Report")

            individual_md = download(".report-export-actions a[href$='markdown']", ".md").read_text()
            individual_docx = download(".report-export-actions a[href$='docx']", ".docx").read_bytes()
            click(".report-citations a")
            assert "the blue vehicle arrived at noon" in driver.find_element(By.ID, "support-pane").text
            checks.append("Individual Markdown/Word download and Report citation opens exact source")

            source_support_expected = True
            def check_bundle(path):
                with zipfile.ZipFile(path) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    assert manifest["report_count"] == 1
                    item = manifest["reports"][0]
                    assert item["status"] == "final" and item["section_count"] == (2 if source_support_expected else 1)
                    markdown = archive.read(item["markdown"]).decode()
                    normalize = lambda text: [line for line in text.splitlines()
                                             if "work product exported from" not in line]
                    assert normalize(markdown) == normalize(individual_md)
                    with zipfile.ZipFile(io.BytesIO(archive.read(item["docx"]))) as word:
                        xml = word.read("word/document.xml").decode()
                    assert "Edited conclusion retained in both exports." in xml
                    if source_support_expected:
                        assert "generated-note.txt" in xml and "Line 1" in xml
                        assert markdown.index("Human conclusion") < markdown.index("the blue vehicle")
                    else:
                        assert "generated-note.txt" not in xml
                    assert not manifest["original_source_files_included"]

            go(prefix + "/settings")
            bundle = download(f"a[href='{prefix}/export']", ".zip")
            check_bundle(bundle)
            checks.append("Ordinary complete bundle inventory and reopened Markdown/Word match individual Report")
            go(prefix + "/reports")
            driver.save_screenshot(str(args.output / "reports-desktop.png"))
            driver.set_window_size(390, 844)
            if driver.find_element(By.CSS_SELECTOR, "[data-rail-toggle]").get_attribute("aria-expanded") == "true":
                click("[data-rail-toggle]")
            wait.until(lambda d: d.execute_script(
                "return document.querySelector('[data-matter-rail]').getBoundingClientRect().right <= 1;"
            ))
            driver.execute_script("window.scrollTo({top:0,left:0,behavior:'instant'});")
            driver.save_screenshot(str(args.output / "reports-mobile.png"))
            # Exercise the same reachable download at a narrow viewport.
            assert download(".report-export-actions a[href$='markdown']", ".md").read_text()
            checks.append("Mobile Report download")

            # A bad saved citation must show recovery and produce no new ZIP.
            original_support = bench._find_support
            def unavailable(*_args, **_kwargs):
                raise KeyError("synthetic-unavailable-source")
            bench._find_support = unavailable
            go(prefix + "/settings")
            before = set(downloads.glob("*.zip"))
            click(f"a[href='{prefix}/export']")
            wait.until(lambda d: "no longer resolves" in d.find_element(By.TAG_NAME, "body").text)
            assert "Open the Report" in driver.find_element(By.TAG_NAME, "body").text
            assert set(downloads.glob("*.zip")) == before
            bench._find_support = original_support
            checks.append("Visible source failure with no misleading complete download")

            if args.verify_readiness:
                driver.set_window_size(1440, 1000)
                before = set(downloads.iterdir())
                report = bench.workspace.reports(matter.matter_id, ACTOR)[0]
                before_revision = report.updated_at
                go(prefix + "/work-product")
                click(f'a[href="{prefix}/export-readiness"]')
                assert "Ready to download" in driver.find_element(By.TAG_NAME, "body").text
                assert "Checked at" in driver.find_element(By.TAG_NAME, "body").text
                assert set(downloads.iterdir()) == before
                assert bench.workspace.report(matter.matter_id, report.report_id).updated_at == before_revision
                for width in (1440, 430):
                    driver.set_window_size(width, 1000)
                    if width < 901:
                        wait.until(lambda d: d.execute_script("return document.querySelector('[data-matter-rail]').getBoundingClientRect().right <= 1"))
                    assert driver.execute_script("return document.documentElement.scrollWidth <= innerWidth + 2")
                    driver.save_screenshot(str(args.output / f"export-ready-{width}.png"))
                checks.append("Deliberate export check shows its inspection time at desktop and narrow widths without a download or Report edit")
                driver.set_window_size(1440, 1000)

                go(prefix + "/setup?view=list")
                click(".source-table-row .remove-action")
                assert document.document_id not in bench.source_store(matter).documents
                go(prefix + "/work-product")
                click(f'a[href="{prefix}/export-readiness"]')
                assert "Export needs attention" in driver.find_element(By.TAG_NAME, "body").text
                assert "Remaining bundle checks did not finish" in driver.find_element(By.TAG_NAME, "body").text
                assert "Synthetic review memo" in driver.find_element(By.CSS_SELECTOR, ".close-matter-card li a").text
                driver.save_screenshot(str(args.output / "export-needs-attention.png"))
                click(".close-matter-card li a")
                assert "This Report needs attention before export" in driver.find_element(By.TAG_NAME, "body").text
                assert report.report_id in driver.current_url
                Select(driver.find_element(By.CSS_SELECTOR, ".report-settings select")).select_by_value("draft")
                click(".report-settings form:first-child button")
                cited_card = driver.find_element(By.CSS_SELECTOR, ".report-citations").find_element(By.XPATH, "ancestor::article")
                remove = cited_card.find_element(By.CSS_SELECTOR, 'form[action$="/delete"] button')
                driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'});", remove)
                remove.click()
                wait.until(EC.alert_is_present()).accept()
                wait.until(lambda _: detached(remove))
                assert len(driver.find_elements(By.CSS_SELECTOR, ".report-section-card")) == 1
                assert driver.find_element(By.CSS_SELECTOR, ".report-section-card textarea").get_attribute("value") == "Edited conclusion retained in both exports."
                Select(driver.find_element(By.CSS_SELECTOR, ".report-settings select")).select_by_value("final")
                click(".report-settings form:first-child button")
                source_support_expected = False
                individual_md = download(".report-export-actions a[href$='markdown']", ".md").read_text()
                individual_docx = download(".report-export-actions a[href$='docx']", ".docx").read_bytes()
                checks.append("A newly removed source blocks readiness and the repair link opens the affected Report; deliberate section removal preserves the human conclusion")

                go(prefix + "/work-product")
                click(f'a[href="{prefix}/export-readiness"]')
                assert "Ready to download" in driver.find_element(By.TAG_NAME, "body").text
                checked_bundle = download(f'a[href="{prefix}/export"]', ".zip")
                check_bundle(checked_bundle)
                checks.append("Rechecking after repair passes and the actual download contains the current final Report")

                other = "generated-export-foreign-owner"
                bench.workspace.upsert_principal("test", other, "Generated foreign owner", other, preferred_principal_id=other)
                foreign = bench.create_matter("Generated foreign preview boundary", "", other)
                bench.workspace.create_report(foreign.matter_id, other, "Foreign preview Report canary")
                go(f"/matters/{foreign.slug}/export-readiness")
                assert "Foreign preview Report canary" not in driver.find_element(By.TAG_NAME, "body").text
                assert "Matter not found" in driver.find_element(By.TAG_NAME, "body").text
                checks.append("A foreign owner's export preview remains inaccessible")

                # Generated recovery fixture: valid cited work, then an injected
                # unavailable derived-store condition during ordinary UI closure.
                recovery = bench.create_matter("Generated interrupted close", "", ACTOR)
                recovery_prefix = f"/matters/{recovery.slug}"
                recovery_document, _ = bench.source_store(recovery).store_stream(
                    "generated-recovery.txt", "text/plain", io.BytesIO(b"Generated recovery source passage."))
                recovery_unit = recovery_document.parsed_units()[0]
                recovery_candidate = bench._candidate(recovery, recovery_document, recovery_unit, 1)
                recovery_report = bench.workspace.create_report(recovery.matter_id, ACTOR, "Generated recovery Report")
                bench.workspace.add_report_section(recovery.matter_id, recovery_report.report_id, ACTOR,
                    expected_status="draft", heading="Generated supported finding", body="Preserve generated review work.",
                    citations=({"kind": "source", "document_id": recovery_document.document_id,
                        "source_version_id": recovery_document.version_id, "source_name": recovery_document.display_name,
                        "location": recovery_candidate.citation, "support_token": bench._support_token(recovery_candidate),
                        "excerpt": recovery_unit.text},))
                go(recovery_prefix + "/close")
                prior_projection = bench._postgres_projection_configured, bench.postgres_connection, bench.postgres_ready
                try:
                    bench._postgres_projection_configured, bench.postgres_connection, bench.postgres_ready = True, None, False
                    fill("#confirmed-name", recovery.display_name)
                    click("input[name=acknowledge]")
                    click(".close-matter-form button[type=submit]")
                    wait.until(lambda _: bench.workspace.matter_lifecycle(recovery.matter_id).state == "purge_failed")
                finally:
                    bench._postgres_projection_configured, bench.postgres_connection, bench.postgres_ready = prior_projection
                go(recovery_prefix + "/export-readiness")
                body = driver.find_element(By.TAG_NAME, "body").text
                assert "Export needs attention" in body and recovery_report.title in body
                assert "Reports cannot be edited" in body
                assert not driver.find_elements(By.CSS_SELECTOR, f'a[href^="{recovery_prefix}/reports"]')
                for width in (1440, 430):
                    driver.set_window_size(width, 1000)
                    if width < 901:
                        wait.until(lambda d: d.execute_script("return document.querySelector('[data-matter-rail]').getBoundingClientRect().right <= 1"))
                    wait.until(lambda d: d.execute_script("const box = document.querySelector('.close-matter-card').getBoundingClientRect(); return box.left >= 0 && box.right <= innerWidth + 1 && document.documentElement.scrollWidth <= innerWidth + 1"))
                    driver.execute_async_script("const done = arguments[arguments.length - 1]; requestAnimationFrame(() => requestAnimationFrame(done));")
                    driver.save_screenshot(str(args.output / f"readiness-failed-close-{width}.png"))
                click(f'a[href="{recovery_prefix}/close"]')
                assert driver.find_element(By.ID, "close-matter-heading").is_displayed()
                assert "Try deletion again" in driver.find_element(By.TAG_NAME, "body").text
                fill("#confirmed-name", recovery.display_name)
                click("input[name=acknowledge]")
                click(".close-matter-form button[type=submit]")
                wait.until(lambda _: bench.workspace.matter_lifecycle(recovery.matter_id).state == "deleted")
                checks.append("Failed-close readiness retains Report details without unavailable edit links; Close matter recovery opens and deliberate retry completes")

            go(prefix + "/close")
            final_bundle = download(f"a[href='{prefix}/export']", ".zip")
            check_bundle(final_bundle)
            fill("#confirmed-name", matter.display_name)
            click("input[name=acknowledge]")
            click(".close-matter-form button[type=submit]")
            wait.until(lambda _: bench.workspace.matter_lifecycle(matter.matter_id).state == "deleted")
            check_bundle(final_bundle)
            assert original.read_bytes() == original_bytes
            with zipfile.ZipFile(io.BytesIO(individual_docx)) as word:
                assert "Edited conclusion retained" in word.read("word/document.xml").decode()
            checks.append("Close-offer final bundle, deliberate deletion, retained downloads, unchanged external original")
            (args.output / "receipt.json").write_text(json.dumps({
                "synthetic_only": True, "passed": True, "checks": checks,
            }, indent=2) + "\n")
            print(json.dumps({"passed": True, "checks": len(checks)}))
        except Exception:
            if driver is not None:
                driver.save_screenshot(str(args.output / "failure.png"))
                (args.output / "failure.html").write_text(driver.page_source)
            raise
        finally:
            if driver is not None:
                driver.quit()
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()


if __name__ == "__main__":
    main()
