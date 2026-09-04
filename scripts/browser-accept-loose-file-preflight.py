#!/usr/bin/env python3
"""Run the synthetic loose-file preflight through the real browser path."""
from __future__ import annotations

import argparse
import base64
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from case_intelligence.generation import UnavailableGenerator  # noqa: E402
from case_intelligence.malware_scan import (  # noqa: E402
    MalwareScanResult,
    MalwareScannerStatus,
)
from case_intelligence.managed_storage import StoragePolicy  # noqa: E402
from case_intelligence.source_locations import SourceLocationRegistry  # noqa: E402
from case_intelligence.workbench import create_workbench_app  # noqa: E402


ACTOR = "development-taylor-morgan"


class SyntheticUnavailableScanner:
    def __init__(self) -> None:
        self.status_calls = 0
        self.scan_calls = 0

    def status(self, *, force: bool = False) -> MalwareScannerStatus:
        del force
        self.status_calls += 1
        return MalwareScannerStatus(
            "unavailable",
            "synthetic",
            message="Synthetic scanner is unavailable.",
        )

    def scan(self, _path: Path) -> MalwareScanResult:
        self.scan_calls += 1
        return MalwareScanResult("unavailable", "synthetic")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _wait_until(predicate, message: str, *, seconds: float = 15.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(message)


def _fixtures(root: Path) -> list[Path]:
    ready = root / "ready"
    attention = root / "attention"
    unsupported = root / "unsupported"
    over_limit = root / "over-limit"
    for directory in (ready, attention, unsupported, over_limit):
        directory.mkdir(parents=True)
    files = [
        ready / "incident-notes.txt",
        ready / "damaged.pdf",
        attention / "scan.png",
        unsupported / "messages.zip",
        over_limit / "oversize.txt",
    ]
    files[0].write_bytes(b"Synthetic intake note.\n")
    files[1].write_bytes(b"not-a-valid-pdf!!!!")
    files[2].write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    files[3].write_bytes(b"PK\x03\x04")
    files[4].write_bytes(b"x" * 129)
    _require([path.stat().st_size for path in files] == [23, 19, 68, 4, 129], "fixture byte sizes changed")
    return files


def _network_urls(driver: webdriver.Chrome) -> list[str]:
    urls: list[str] = []
    for entry in driver.get_log("performance"):
        try:
            message = json.loads(entry["message"])["message"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if message.get("method") != "Network.requestWillBeSent":
            continue
        url = message.get("params", {}).get("request", {}).get("url")
        if isinstance(url, str):
            urls.append(url)
    return urls


def _select(input_element, files: list[Path]) -> None:
    input_element.send_keys("\n".join(str(path.resolve()) for path in files))


def _replace_selection(driver: webdriver.Chrome, input_element, files: list[Path]) -> None:
    driver.execute_script("arguments[0].value = '';", input_element)
    _select(input_element, files)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome-binary", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    for label, executable in (
        ("Chrome", args.chrome_binary),
        ("ChromeDriver", args.chromedriver),
    ):
        if not executable.is_file():
            raise SystemExit(f"{label} executable does not exist: {executable}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    scanner = SyntheticUnavailableScanner()
    report: dict[str, object] = {
        "schema_version": 1,
        "acceptance": "slice1a-loose-file-preflight",
        "synthetic_only": True,
        "passed": False,
        "checks": [],
    }
    driver: webdriver.Chrome | None = None
    server: uvicorn.Server | None = None
    server_thread: threading.Thread | None = None
    server_socket: socket.socket | None = None

    with tempfile.TemporaryDirectory(prefix="recordbench-slice1a-browser-") as temporary:
        temporary_root = Path(temporary)
        files = _fixtures(temporary_root / "fixtures")
        app = create_workbench_app(
            temporary_root / "runtime",
            generator=UnavailableGenerator(),
            auth_mode="test",
            background_ingestion=True,
            source_registry=SourceLocationRegistry(),
            storage_policy=StoragePolicy(
                matter_quota_bytes=4_096,
                upload_session_bytes=512,
                media_file_bytes=256,
                document_file_bytes=128,
                reserve_bytes=0,
            ),
            malware_scanner=scanner,
            malware_scan_mode="extended",
        )

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        port = int(server_socket.getsockname()[1])
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [server_socket]},
            name="slice1a-browser-server",
            daemon=True,
        )
        server_thread.start()
        _wait_until(lambda: server.started, "synthetic loopback server did not start")

        options = Options()
        options.binary_location = str(args.chrome_binary)
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1536,1024")
        options.set_capability(
            "goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"}
        )
        try:
            driver = webdriver.Chrome(
                service=Service(executable_path=str(args.chromedriver)),
                options=options,
            )
            driver.set_page_load_timeout(20)
            wait = WebDriverWait(driver, 20)
            base_url = f"http://127.0.0.1:{port}"
            driver.get(f"{base_url}/matters/new")
            driver.find_element(By.ID, "matter-name").send_keys(
                "Synthetic Slice 1A Browser Matter"
            )
            driver.find_element(By.ID, "matter-descriptor").send_keys(
                "Generated selection preflight acceptance"
            )
            driver.find_element(By.CSS_SELECTOR, ".matter-form button[type='submit']").click()
            wait.until(lambda current: "/setup" in current.current_url)
            slug = urlparse(driver.current_url).path.split("/")[2]
            driver.find_element(By.CSS_SELECTOR, "[data-assistant-collapse]").click()
            wait.until(
                lambda current: "assistant-collapsed"
                in current.find_element(By.TAG_NAME, "body").get_attribute("class").split()
            )
            bench = app.state.workbench
            matter = bench.matter(slug, ACTOR)
            _require(bench.workspace.source_collections(matter.matter_id) == (), "new matter unexpectedly has a collection")
            _require(bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR) == (), "new matter unexpectedly has an upload session")

            file_input = driver.find_element(By.CSS_SELECTOR, "[data-file-input]")
            status_calls_before_preview = scanner.status_calls
            driver.execute_script("arguments[0].focus({preventScroll: true});", file_input)
            _select(file_input, files)
            panel = wait.until(
                lambda current: current.find_element(By.CSS_SELECTOR, "[data-upload-preflight]:not([hidden])")
            )
            wait.until(
                lambda current: "2 of 5 selected files can proceed"
                in current.find_element(By.CSS_SELECTOR, "[data-upload-preflight-status]").text
            )
            rows = driver.find_elements(By.CSS_SELECTOR, "[data-upload-preflight-items] > li")
            states = [row.get_attribute("data-state") for row in rows]
            _require(
                states == ["valid", "valid", "needs_attention", "unsupported", "over_limit"],
                f"unexpected preflight states: {states}",
            )
            count_text = driver.find_element(By.CSS_SELECTOR, "[data-upload-preflight-counts]").text
            for expected in (
                "2 ready",
                "1 need attention",
                "1 unsupported",
                "0 repeated paths",
                "1 over limit",
                "0 cannot use",
            ):
                _require(expected in count_text, f"missing count: {expected}")
            panel_text = panel.text
            for expected in (
                "Expected from filename",
                "Detected type, readability, source version, and content duplicates pending upload",
                "Security scan required, unavailable, and not run",
            ):
                _require(expected in panel_text, f"missing truthful preview text: {expected}")
            confirm = driver.find_element(By.CSS_SELECTOR, "[data-upload-preflight-confirm]")
            _require(confirm.text == "Upload 2 ready files", "confirmation count is wrong")
            _require(confirm.is_enabled(), "confirmation should be enabled")

            preconfirm_urls = _network_urls(driver)
            _require(any("/upload-preflight" in url for url in preconfirm_urls), "browser did not call preflight API")
            _require(not any("/upload-sessions" in url for url in preconfirm_urls), "upload session began before confirmation")
            _require(bench.workspace.source_collections(matter.matter_id) == (), "preflight created a collection")
            _require(bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR) == (), "preflight created a session")
            _require(bench.workspace.pending_upload_bytes(matter.matter_id) == 0, "preflight reserved upload bytes")
            _require(
                scanner.status_calls == status_calls_before_preview + 1,
                "preflight did not perform exactly one capability-status check",
            )
            _require(scanner.scan_calls == 0, "preflight invoked a content scan")
            wait.until(
                lambda current: current.execute_script(
                    """
                    const panel = arguments[0];
                    const header = document.querySelector('.topbar');
                    const panelRect = panel.getBoundingClientRect();
                    const headerBottom = header ? header.getBoundingClientRect().bottom : 0;
                    return panelRect.top >= headerBottom
                      && panelRect.top < window.innerHeight
                      && panelRect.bottom > headerBottom;
                    """,
                    panel,
                )
            )
            _require(
                driver.execute_script(
                    "return document.activeElement === arguments[0];", file_input
                ),
                "completed preflight stole focus from the selection control",
            )
            desktop_overflow = driver.execute_script(
                "return document.documentElement.scrollWidth - document.documentElement.clientWidth;"
            )
            _require(
                desktop_overflow <= 0,
                f"desktop page overflows horizontally by {desktop_overflow}px",
            )
            driver.save_screenshot(str(output / "desktop-preflight.png"))

            _replace_selection(driver, file_input, [files[0]])
            wait.until(
                lambda current: len(
                    current.find_elements(By.CSS_SELECTOR, "[data-upload-preflight-items] > li")
                )
                == 1
                and current.find_element(By.CSS_SELECTOR, "[data-upload-preflight-confirm]").text
                == "Upload 1 ready file"
            )
            _replace_selection(driver, file_input, files)
            wait.until(
                lambda current: len(
                    current.find_elements(By.CSS_SELECTOR, "[data-upload-preflight-items] > li")
                )
                == 5
                and current.find_element(By.CSS_SELECTOR, "[data-upload-preflight-confirm]").text
                == "Upload 2 ready files"
            )

            driver.execute_script(
                """
                window.__slice1aOriginalFetch = window.fetch;
                window.fetch = (...args) => String(args[0]).includes('/upload-preflight')
                  ? Promise.reject(new Error('Synthetic preflight interruption'))
                  : window.__slice1aOriginalFetch(...args);
                """
            )
            _replace_selection(driver, file_input, [files[0]])
            wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-state]"
                ).text
                == "Selection review paused"
            )
            _require(
                not driver.find_elements(
                    By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                ),
                "failed reselection retained stale rows",
            )
            _require(
                not driver.find_elements(
                    By.CSS_SELECTOR, "[data-upload-preflight-counts] > span"
                ),
                "failed reselection retained stale totals",
            )
            _require(
                not driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).is_enabled(),
                "failed reselection left confirmation enabled",
            )
            _require(
                panel.get_attribute("aria-busy") is None,
                "failed reselection left the panel busy",
            )
            driver.execute_script(
                "window.fetch = window.__slice1aOriginalFetch; delete window.__slice1aOriginalFetch;"
            )

            driver.execute_script(
                """
                window.__slice1aOriginalFetch = window.fetch;
                window.__slice1aPendingFetch = false;
                window.fetch = (...args) => {
                  if (!String(args[0]).includes('/upload-preflight')) {
                    return window.__slice1aOriginalFetch(...args);
                  }
                  window.__slice1aPendingFetch = true;
                  return new Promise((_resolve, reject) => {
                    const signal = args[1] && args[1].signal;
                    if (signal) {
                      signal.addEventListener(
                        'abort',
                        () => reject(new DOMException('Aborted', 'AbortError')),
                        { once: true },
                      );
                    }
                  });
                };
                """
            )
            _replace_selection(driver, file_input, [files[0]])
            wait.until(
                lambda current: current.execute_script(
                    "return window.__slice1aPendingFetch === true;"
                )
                and panel.get_attribute("aria-busy") == "true"
            )
            driver.execute_script(
                """
                arguments[0].value = '';
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                """,
                file_input,
            )
            wait.until(
                lambda current: panel.get_attribute("aria-busy") is None
                and current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-state]"
                ).text
                == "Waiting for a selection"
            )
            _require(
                not driver.find_elements(
                    By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                ),
                "clearing an in-flight selection retained stale rows",
            )
            _require(
                not driver.find_elements(
                    By.CSS_SELECTOR, "[data-upload-preflight-counts] > span"
                ),
                "clearing an in-flight selection retained stale totals",
            )
            _require(
                not driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).is_enabled(),
                "clearing an in-flight selection left confirmation enabled",
            )
            driver.execute_script(
                """
                window.fetch = window.__slice1aOriginalFetch;
                delete window.__slice1aOriginalFetch;
                delete window.__slice1aPendingFetch;
                """
            )
            _replace_selection(driver, file_input, files)
            wait.until(
                lambda current: len(
                    current.find_elements(By.CSS_SELECTOR, "[data-upload-preflight-items] > li")
                )
                == 5
                and current.find_element(By.CSS_SELECTOR, "[data-upload-preflight-confirm]").text
                == "Upload 2 ready files"
            )

            driver.set_window_size(390, 844)
            wait.until(lambda current: current.execute_script("return window.innerWidth") <= 390)
            wait.until(
                lambda current: current.execute_script(
                    "return document.querySelector('.matter-rail').getBoundingClientRect().right;"
                )
                <= 1
            )
            overflow = driver.execute_script(
                "return document.documentElement.scrollWidth - document.documentElement.clientWidth;"
            )
            _require(overflow <= 0, f"mobile page overflows horizontally by {overflow}px")
            confirm = driver.find_element(By.CSS_SELECTOR, "[data-upload-preflight-confirm]")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", confirm)
            driver.save_screenshot(str(output / "mobile-preflight.png"))
            confirm.send_keys(Keys.ENTER)
            _wait_until(
                lambda: bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR),
                "confirmation did not create an upload session",
            )
            session = _wait_until(
                lambda: (
                    candidate
                    if (candidate := bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR)[0]).state
                    in {"complete", "partial"}
                    else None
                ),
                "retained upload path did not reach a terminal session",
            )
            _require(session.item_count == 2, "ineligible files entered the upload session")
            _require(session.state == "partial", "malformed synthetic PDF did not remain visible as partial")
            _, upload_items = bench.workspace.upload_session(
                matter.matter_id, ACTOR, session.upload_session_id
            )
            _require(
                [item.state for item in upload_items] == ["queued", "failed"],
                f"unexpected retained upload states: {[item.state for item in upload_items]}",
            )
            _require(scanner.scan_calls == 0, "excluded scanner-gated file received a content scan")
            _require(
                len(driver.find_elements(By.CSS_SELECTOR, "[data-upload-preflight-items] > li")) == 5,
                "ineligible preview rows disappeared after confirmation",
            )
            progress = wait.until(
                lambda current: (
                    candidate
                    if (candidate := current.find_element(By.CSS_SELECTOR, "[data-upload-progress]")).is_displayed()
                    else None
                )
            )
            postconfirm_urls = _network_urls(driver)
            _require(any("/upload-sessions" in url for url in postconfirm_urls), "browser did not use retained upload API")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", progress)
            driver.save_screenshot(str(output / "mobile-partial-upload.png"))

            javascript_errors = [
                entry
                for entry in driver.get_log("browser")
                if entry.get("level") == "SEVERE" and entry.get("source") == "javascript"
            ]
            _require(not javascript_errors, f"browser JavaScript errors: {javascript_errors}")
            report["checks"] = [
                "real matter creation and setup route",
                "metadata-only API before bytes",
                "all five synthetic rows and exact category totals",
                "truthful pending and not-run states",
                "one capability-status check and no content scan before initial confirmation",
                "selection change invalidates and replaces prior preview",
                "failed reselection clears stale rows and totals",
                "clearing an in-flight selection clears busy state",
                "keyboard confirmation uploads only the two eligible files",
                "retained upload path reports malformed PDF as partial",
                "desktop and 390px mobile views have no horizontal overflow",
                "no severe browser JavaScript error",
            ]
            report["matter_slug"] = slug
            report["selected_count"] = 5
            report["eligible_count"] = 2
            report["upload_session_state"] = session.state
            report["upload_item_states"] = [item.state for item in upload_items]
            report["scanner_status_calls"] = scanner.status_calls
            report["content_scan_calls"] = scanner.scan_calls
            report["passed"] = True
        finally:
            if driver is not None:
                driver.quit()
            if server is not None:
                server.should_exit = True
            if server_thread is not None:
                server_thread.join(timeout=10)
            if server_socket is not None:
                server_socket.close()
            if server_thread is not None and server_thread.is_alive():
                raise RuntimeError("synthetic loopback server did not stop")

    (output / "result.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
