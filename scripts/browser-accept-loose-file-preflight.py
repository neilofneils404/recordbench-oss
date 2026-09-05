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
        self.scripted_statuses: list[str] = []

    def status(self, *, force: bool = False) -> MalwareScannerStatus:
        del force
        self.status_calls += 1
        state = (
            self.scripted_statuses.pop(0)
            if self.scripted_statuses
            else "unavailable"
        )
        return MalwareScannerStatus(
            state,
            "synthetic",
            message=f"Synthetic scanner is {state}.",
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


def _synthetic_selection(
    driver: webdriver.Chrome,
    input_element,
    count: int,
    *,
    long_paths: bool,
    cross_boundary_duplicate: bool = True,
    file_size: int = 1,
    suffix: str = "txt",
    media_type: str = "text/plain",
) -> dict[str, int]:
    return driver.execute_script(
        """
        const input = arguments[0];
        const count = arguments[1];
        const longPaths = arguments[2];
        const crossBoundaryDuplicate = arguments[3];
        const fileSize = arguments[4];
        const suffix = arguments[5];
        const mediaType = arguments[6];
        const transfer = new DataTransfer();
        const segments = ["a", "b", "c", "d"].map((value) => value.repeat(180));
        const descriptors = [];
        for (let index = 0; index < count; index += 1) {
          let name = `record-${String(index).padStart(5, "0")}.${suffix}`;
          if (crossBoundaryDuplicate && count > 2000 && index === 1999) name = `Straße.${suffix}`;
          if (crossBoundaryDuplicate && count > 2000 && index === 2000) name = `STRASSE.${suffix}`;
          const folder = longPaths ? `Production/${segments.join("/")}` : "Production";
          const relativePath = `${folder}/${name}`;
          const file = new File(["x".repeat(fileSize)], name, {
            type: mediaType,
            lastModified: 1700000000000 + index,
          });
          Object.defineProperty(file, "webkitRelativePath", { value: relativePath });
          transfer.items.add(file);
          descriptors.push({
            name: file.name,
            relative_path: relativePath,
            size: file.size,
            media_type: file.type,
          });
        }
        const serializedBytes = new TextEncoder().encode(JSON.stringify({
          selection_nonce: "0".repeat(32),
          files: descriptors,
        })).byteLength;
        input.value = "";
        input.files = transfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return { count: transfer.files.length, serialized_bytes: serializedBytes };
        """,
        input_element,
        count,
        long_paths,
        cross_boundary_duplicate,
        file_size,
        suffix,
        media_type,
    )


def _upload_plan_fingerprint(driver: webdriver.Chrome, input_element) -> str:
    fingerprint = driver.execute_async_script(
        """
        const input = arguments[0];
        const done = arguments[arguments.length - 1];
        const form = document.querySelector('[data-upload-form]');
        const maximumItems = Number(form.dataset.maxUploadBatchItems);
        const maximumBytes = Number(form.dataset.maxCollectionBytes);
        const batches = [];
        let batch = [];
        let bytes = 0;
        Array.from(input.files).forEach((file) => {
          if (batch.length && (batch.length >= maximumItems || bytes + file.size > maximumBytes)) {
            batches.push(batch);
            batch = [];
            bytes = 0;
          }
          batch.push(file);
          bytes += file.size;
        });
        if (batch.length) batches.push(batch);
        const plan = batches.map((files) => files.map((file) => ({
          name: String(file.name || '').normalize('NFC'),
          relative_path: String(file.webkitRelativePath || file.name || '').normalize('NFC'),
          size: Number(file.size),
          media_type: String(file.type || '').trim().toLowerCase(),
          last_modified: Number(file.lastModified),
        })));
        crypto.subtle.digest(
          'SHA-256',
          new TextEncoder().encode(JSON.stringify({ version: 1, batches: plan })),
        ).then((digest) => done(
          Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('')
        )).catch((error) => done({ error: String(error) }));
        """,
        input_element,
    )
    _require(
        isinstance(fingerprint, str) and len(fingerprint) == 64,
        "browser could not reproduce the deterministic upload-plan fingerprint",
    )
    return fingerprint


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
            driver.set_script_timeout(60)
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
            panel = driver.find_element(By.CSS_SELECTOR, "[data-upload-preflight]")
            review_finding_failures: list[str] = []
            scanner.scripted_statuses = ["ready", "unavailable"]
            scanner_snapshot_calls = scanner.status_calls
            _synthetic_selection(
                driver,
                file_input,
                2_001,
                long_paths=False,
                cross_boundary_duplicate=False,
                suffix="png",
                media_type="image/png",
            )
            WebDriverWait(driver, 60).until(
                lambda current: len(
                    current.find_elements(
                        By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                    )
                )
                == 2_001
                and panel.get_attribute("aria-busy") is None
            )
            scanner_snapshot_rows = driver.find_elements(
                By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
            )
            scanner_snapshot_states = {
                row.get_attribute("data-state") for row in scanner_snapshot_rows
            }
            if not (
                scanner_snapshot_states == {"valid"}
                and driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 2,001 ready files"
                and "Security scan required and not run yet"
                in scanner_snapshot_rows[0].text
                and "Security scan required and not run yet"
                in scanner_snapshot_rows[-1].text
                and scanner.status_calls == scanner_snapshot_calls + 2
                and not scanner.scripted_statuses
            ):
                review_finding_failures.append(
                    "one logical selection displayed mixed scanner availability across batches"
                )

            driver.execute_script(
                """
                const input = arguments[0];
                const transfer = new DataTransfer();
                ["Folder Alpha", "Folder Beta"].forEach((folder, index) => {
                  const file = new File([`synthetic-${index}`], "same-name.txt", {
                    type: "text/plain",
                    lastModified: 1700000100000 + index,
                  });
                  Object.defineProperty(file, "webkitRelativePath", {
                    value: `${folder}/same-name.txt`,
                  });
                  transfer.items.add(file);
                });
                input.value = "";
                input.files = transfer.files;
                input.dispatchEvent(new Event("change", { bubbles: true }));
                """,
                file_input,
            )
            WebDriverWait(driver, 30).until(
                lambda current: len(
                    current.find_elements(
                        By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                    )
                )
                == 2
                and panel.get_attribute("aria-busy") is None
            )
            folder_labels = [
                row.find_element(By.TAG_NAME, "strong").text
                for row in driver.find_elements(
                    By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                )
            ]
            if not (
                folder_labels
                == [
                    "Folder Alpha/same-name.txt",
                    "Folder Beta/same-name.txt",
                ]
                and all(
                    not label.startswith(("/", "\\"))
                    and ":" not in label
                    and str(temporary_root) not in label
                    for label in folder_labels
                )
            ):
                review_finding_failures.append(
                    "folder selection did not safely disambiguate duplicate leaf names"
                )
            _require(
                not review_finding_failures,
                "; ".join(review_finding_failures),
            )

            driver.execute_script(
                """
                window.__slice1aScaleOriginalFetch = window.fetch;
                window.__slice1aScaleRequests = [];
                window.fetch = (...args) => {
                  if (String(args[0]).includes('/upload-preflight')) {
                    const body = String(args[1]?.body || '');
                    const payload = JSON.parse(body);
                    window.__slice1aScaleRequests.push({
                      bytes: new TextEncoder().encode(body).byteLength,
                      count: payload.files.length,
                      nonce: payload.selection_nonce,
                    });
                  }
                  return window.__slice1aScaleOriginalFetch(...args);
                };
                """
            )
            scale_status_calls = scanner.status_calls
            scale_selection = _synthetic_selection(
                driver, file_input, 10_000, long_paths=True
            )
            _require(
                scale_selection["serialized_bytes"] > 6 * 1024 * 1024,
                "ten-thousand-row fixture did not exceed the one-request cap",
            )
            WebDriverWait(driver, 120).until(
                lambda current: len(
                    current.find_elements(
                        By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                    )
                )
                == 10_000
                and current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 9,999 ready files"
            )
            scale_requests = driver.execute_script(
                "return window.__slice1aScaleRequests;"
            )
            _require(len(scale_requests) > 1, "large selection used only one request")
            _require(
                sum(request["count"] for request in scale_requests) == 10_000,
                "large selection did not account for exactly ten thousand rows",
            )
            _require(
                all(request["count"] <= 2_000 for request in scale_requests),
                "a preflight request exceeded the two-thousand-row cap",
            )
            _require(
                all(request["bytes"] <= 6 * 1024 * 1024 for request in scale_requests),
                "a preflight request exceeded the six-MiB cap",
            )
            _require(
                len({request["nonce"] for request in scale_requests}) == 1,
                "large selection did not retain one selection nonce",
            )
            scale_rows = driver.find_elements(
                By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
            )
            _require(
                scale_rows[1999].get_attribute("data-state") == "valid"
                and scale_rows[2000].get_attribute("data-state")
                == "duplicate_candidate",
                "server-canonical duplicate across the batch boundary was not preserved",
            )
            _require(
                scale_rows[0].find_element(By.TAG_NAME, "strong").text.endswith(
                    "/record-00000.txt"
                )
                and scale_rows[-1]
                .find_element(By.TAG_NAME, "strong")
                .text.endswith("/record-09999.txt"),
                "consolidated preview did not preserve global selection order",
            )
            _require(
                "1 repeated path"
                in driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-counts]"
                ).text,
                "consolidated preview did not report the cross-batch duplicate",
            )
            _require(
                scanner.status_calls == scale_status_calls + len(scale_requests),
                "large preview did not perform one scanner-status check per bounded request",
            )
            _require(
                bench.workspace.source_collections(matter.matter_id) == ()
                and bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR)
                == ()
                and bench.workspace.pending_upload_bytes(matter.matter_id) == 0,
                "large preflight created durable upload state before confirmation",
            )
            driver.execute_script(
                """
                window.fetch = window.__slice1aScaleOriginalFetch;
                delete window.__slice1aScaleOriginalFetch;
                delete window.__slice1aScaleRequests;
                """
            )

            oversized_status_calls = scanner.status_calls
            driver.execute_script(
                """
                window.__slice1aOversizedOriginalFetch = window.fetch;
                window.__slice1aOversizedFetchCount = 0;
                window.fetch = (...args) => {
                  if (String(args[0]).includes('/upload-preflight')) {
                    window.__slice1aOversizedFetchCount += 1;
                  }
                  return window.__slice1aOversizedOriginalFetch(...args);
                };
                const input = arguments[0];
                const transfer = new DataTransfer();
                const file = new File(['x'], 'synthetic.txt', {
                  type: 'text/plain',
                  lastModified: 1700000000000,
                });
                Object.defineProperty(file, 'webkitRelativePath', {
                  value: `Synthetic/${'x'.repeat(6 * 1024 * 1024)}.txt`,
                });
                transfer.items.add(file);
                input.value = '';
                input.files = transfer.files;
                input.dispatchEvent(new Event('change', { bubbles: true }));
                """,
                file_input,
            )
            wait.until(
                lambda current: len(
                    current.find_elements(
                        By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                    )
                )
                == 1
                and current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 0 ready files"
            )
            oversized_row = driver.find_element(
                By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
            )
            _require(
                oversized_row.get_attribute("data-state") == "failed"
                and oversized_row.text.startswith("Selected file 1")
                and driver.execute_script(
                    "return window.__slice1aOversizedFetchCount;"
                )
                == 0
                and scanner.status_calls == oversized_status_calls,
                "one oversized descriptor was not handled locally and content-free",
            )
            driver.execute_script(
                """
                window.fetch = window.__slice1aOversizedOriginalFetch;
                delete window.__slice1aOversizedOriginalFetch;
                delete window.__slice1aOversizedFetchCount;
                """
            )

            driver.execute_script(
                """
                window.__slice1aBatchOriginalFetch = window.fetch;
                window.__slice1aBatchRequestCount = 0;
                window.__slice1aSecondBatchPending = false;
                window.fetch = (...args) => {
                  if (!String(args[0]).includes('/upload-preflight')) {
                    return window.__slice1aBatchOriginalFetch(...args);
                  }
                  window.__slice1aBatchRequestCount += 1;
                  if (window.__slice1aBatchRequestCount !== 2) {
                    return window.__slice1aBatchOriginalFetch(...args);
                  }
                  window.__slice1aSecondBatchPending = true;
                  return new Promise((_resolve, reject) => {
                    const signal = args[1]?.signal;
                    signal?.addEventListener(
                      'abort',
                      () => reject(new DOMException('Aborted', 'AbortError')),
                      { once: true },
                    );
                  });
                };
                """
            )
            _synthetic_selection(driver, file_input, 2_001, long_paths=False)
            wait.until(
                lambda current: current.execute_script(
                    "return window.__slice1aSecondBatchPending === true;"
                )
                and panel.get_attribute("aria-busy") == "true"
            )
            _require(
                not driver.find_elements(
                    By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                ),
                "partial first-batch rows became visible before consolidated completion",
            )
            _replace_selection(driver, file_input, [files[0]])
            wait.until(
                lambda current: len(
                    current.find_elements(
                        By.CSS_SELECTOR, "[data-upload-preflight-items] > li"
                    )
                )
                == 1
                and current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 1 ready file"
            )
            driver.execute_script(
                """
                window.fetch = window.__slice1aBatchOriginalFetch;
                delete window.__slice1aBatchOriginalFetch;
                delete window.__slice1aBatchRequestCount;
                delete window.__slice1aSecondBatchPending;
                """
            )

            checkpoint_matter = bench.create_matter(
                "Synthetic multi-batch checkpoint matter",
                "Generated resume checkpoint isolation acceptance",
                ACTOR,
            )
            driver.get(f"{base_url}/matters/{checkpoint_matter.slug}/setup")
            file_input = wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-file-input]"
                )
            )
            panel = driver.find_element(By.CSS_SELECTOR, "[data-upload-preflight]")
            _synthetic_selection(
                driver,
                file_input,
                2_001,
                long_paths=False,
                cross_boundary_duplicate=False,
            )
            WebDriverWait(driver, 60).until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 2,001 ready files"
            )
            corrupt_plan_fingerprint = _upload_plan_fingerprint(driver, file_input)
            stale_files = [
                {
                    "display_name": f"record-{ordinal:05d}.txt",
                    "relative_path": f"Production/record-{ordinal:05d}.txt",
                    "media_type": "text/plain",
                    "expected_size": 1,
                }
                for ordinal in range(512, 1_024)
            ]
            stale_session, _ = bench.create_upload_session(
                checkpoint_matter,
                ACTOR,
                "Synthetic cancelled resume checkpoint",
                stale_files,
            )
            bench.workspace.cancel_upload_session(
                checkpoint_matter.matter_id, ACTOR, stale_session.upload_session_id
            )
            stale_session, _ = bench.workspace.upload_session(
                checkpoint_matter.matter_id, ACTOR, stale_session.upload_session_id
            )
            stale_collections = bench.workspace.source_collections(
                checkpoint_matter.matter_id
            )
            stale_sessions = bench.workspace.recent_upload_sessions(
                checkpoint_matter.matter_id, ACTOR
            )
            stale_collection = bench.workspace.source_collection(
                checkpoint_matter.matter_id, stale_session.collection_id
            )
            upload_session_key = (
                f"case-intelligence:upload:{checkpoint_matter.slug}"
            )
            driver.execute_script(
                "window.localStorage.setItem(arguments[0], arguments[1]);",
                upload_session_key,
                json.dumps(
                    {
                        "version": 3,
                        "plan_fingerprint": corrupt_plan_fingerprint,
                        "session_id": "",
                        "collection_id": stale_session.collection_id,
                        "batch_index": 1,
                    }
                ),
            )
            driver.execute_script(
                """
                window.__slice1aCorruptOriginalFetch = window.fetch;
                window.__slice1aCorruptBodies = [];
                window.fetch = (...args) => {
                  const method = String(args[1]?.method || 'GET').toUpperCase();
                  if (String(args[0]).includes('/upload-sessions') && method === 'POST') {
                    window.__slice1aCorruptBodies.push(JSON.parse(String(args[1].body)));
                    return Promise.reject(new Error('Synthetic corrupt-state stop'));
                  }
                  return window.__slice1aCorruptOriginalFetch(...args);
                };
                """
            )
            driver.execute_script(
                "arguments[0].click();",
                driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ),
            )
            corrupt_body = WebDriverWait(driver, 30).until(
                lambda current: (
                    bodies[0]
                    if (
                        bodies
                        := current.execute_script(
                            "return window.__slice1aCorruptBodies;"
                        )
                    )
                    else None
                )
            )
            _require(
                corrupt_body["resume_session_id"] == ""
                and corrupt_body["collection_id"] == ""
                and corrupt_body["files"][0]["relative_path"].endswith(
                    "/record-00000.txt"
                )
                and bench.workspace.source_collections(checkpoint_matter.matter_id)
                == stale_collections
                and bench.workspace.recent_upload_sessions(
                    checkpoint_matter.matter_id, ACTOR
                )
                == stale_sessions
                and len(
                    driver.execute_script(
                        "return window.__slice1aCorruptBodies;"
                    )
                )
                == 1,
                "collection-only matching-fingerprint state skipped batch zero or mutated its stale collection",
            )
            driver.execute_script(
                """
                window.fetch = window.__slice1aCorruptOriginalFetch;
                delete window.__slice1aCorruptOriginalFetch;
                delete window.__slice1aCorruptBodies;
                window.localStorage.removeItem(arguments[0]);
                """,
                upload_session_key,
            )
            wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-form]"
                ).get_attribute("aria-busy")
                is None
            )

            _synthetic_selection(
                driver,
                file_input,
                2_001,
                long_paths=False,
                cross_boundary_duplicate=False,
            )
            WebDriverWait(driver, 60).until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).is_enabled()
                and current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 2,001 ready files"
            )
            driver.execute_script(
                "window.localStorage.setItem(arguments[0], arguments[1]);",
                upload_session_key,
                json.dumps(
                    {
                        "version": 3,
                        "plan_fingerprint": corrupt_plan_fingerprint,
                        "session_id": stale_session.upload_session_id,
                        "collection_id": stale_session.collection_id,
                        "batch_index": 1,
                    }
                ),
            )
            driver.execute_script(
                """
                window.__slice1aCancelledOriginalFetch = window.fetch;
                window.__slice1aCancelledBodies = [];
                window.fetch = (...args) => {
                  const method = String(args[1]?.method || 'GET').toUpperCase();
                  if (String(args[0]).includes('/upload-sessions') && method === 'POST') {
                    window.__slice1aCancelledBodies.push(JSON.parse(String(args[1].body)));
                  }
                  if (method === 'PUT') {
                    return new Promise((_resolve, reject) => {
                      args[1]?.signal?.addEventListener(
                        'abort',
                        () => reject(new DOMException('Aborted', 'AbortError')),
                        { once: true },
                      );
                    });
                  }
                  return window.__slice1aCancelledOriginalFetch(...args);
                };
                """
            )
            driver.execute_script(
                "arguments[0].click();",
                driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ),
            )
            cancelled_bodies = WebDriverWait(driver, 30).until(
                lambda current: (
                    bodies
                    if len(
                        bodies
                        := current.execute_script(
                            "return window.__slice1aCancelledBodies;"
                        )
                    )
                    == 2
                    else None
                )
            )
            recovered_checkpoint = json.loads(
                WebDriverWait(driver, 30).until(
                    lambda current: (
                        value
                        if (
                            value
                            := current.execute_script(
                                "return window.localStorage.getItem(arguments[0]);",
                                upload_session_key,
                            )
                        )
                        and json.loads(value)["session_id"]
                        != stale_session.upload_session_id
                        else None
                    )
                )
            )
            _require(
                cancelled_bodies[0]["resume_session_id"]
                == stale_session.upload_session_id
                and cancelled_bodies[0]["collection_id"]
                == stale_session.collection_id
                and cancelled_bodies[0]["files"][0]["relative_path"].endswith(
                    "/record-00512.txt"
                )
                and cancelled_bodies[1]["resume_session_id"] == ""
                and cancelled_bodies[1]["collection_id"] == ""
                and cancelled_bodies[1]["files"][0]["relative_path"].endswith(
                    "/record-00000.txt"
                )
                and recovered_checkpoint["batch_index"] == 0
                and recovered_checkpoint["collection_id"]
                != stale_session.collection_id
                and bench.workspace.source_collection(
                    checkpoint_matter.matter_id, stale_session.collection_id
                )
                == stale_collection
                and len(
                    bench.workspace.recent_upload_sessions(
                        checkpoint_matter.matter_id, ACTOR
                    )
                )
                == len(stale_sessions) + 1,
                "cancelled later-batch checkpoint did not retry once from a new batch-zero collection",
            )

            partial_matter = bench.create_matter(
                "Synthetic partial checkpoint matter",
                "Generated completed-batch advancement acceptance",
                ACTOR,
            )
            partial_key = f"case-intelligence:upload:{partial_matter.slug}"
            driver.get(f"{base_url}/matters/{partial_matter.slug}/setup")
            partial_input = wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-file-input]"
                )
            )
            _synthetic_selection(
                driver,
                partial_input,
                5,
                long_paths=False,
                cross_boundary_duplicate=False,
                file_size=128,
            )
            wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 5 ready files"
            )
            partial_fingerprint = _upload_plan_fingerprint(driver, partial_input)
            partial_session, partial_items = bench.create_upload_session(
                partial_matter,
                ACTOR,
                "Synthetic partial first batch",
                [
                    {
                        "display_name": f"record-{ordinal:05d}.txt",
                        "relative_path": f"Production/record-{ordinal:05d}.txt",
                        "media_type": "text/plain",
                        "expected_size": 128,
                    }
                    for ordinal in range(4)
                ],
            )
            for item in partial_items:
                bench.workspace.fail_upload_item(
                    partial_matter.matter_id,
                    ACTOR,
                    partial_session.upload_session_id,
                    item.upload_item_id,
                    "Synthetic completed-batch failure",
                )
            partial_session, partial_items = bench.workspace.upload_session(
                partial_matter.matter_id,
                ACTOR,
                partial_session.upload_session_id,
            )
            _require(
                partial_session.state == "partial"
                and all(item.state == "failed" for item in partial_items),
                "synthetic partial checkpoint was not prepared",
            )
            driver.execute_script(
                "window.localStorage.setItem(arguments[0], arguments[1]);",
                partial_key,
                json.dumps(
                    {
                        "version": 3,
                        "plan_fingerprint": partial_fingerprint,
                        "session_id": partial_session.upload_session_id,
                        "collection_id": partial_session.collection_id,
                        "batch_index": 0,
                    }
                ),
            )
            driver.execute_script(
                """
                window.__slice1aPartialOriginalFetch = window.fetch;
                window.__slice1aPartialBodies = [];
                window.fetch = (...args) => {
                  const method = String(args[1]?.method || 'GET').toUpperCase();
                  if (String(args[0]).includes('/upload-sessions') && method === 'POST') {
                    window.__slice1aPartialBodies.push(JSON.parse(String(args[1].body)));
                  }
                  if (method === 'PUT') {
                    return new Promise((_resolve, reject) => {
                      args[1]?.signal?.addEventListener(
                        'abort',
                        () => reject(new DOMException('Aborted', 'AbortError')),
                        { once: true },
                      );
                    });
                  }
                  return window.__slice1aPartialOriginalFetch(...args);
                };
                """
            )
            driver.execute_script(
                "arguments[0].click();",
                driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ),
            )
            partial_bodies = WebDriverWait(driver, 30).until(
                lambda current: (
                    bodies
                    if len(
                        bodies
                        := current.execute_script(
                            "return window.__slice1aPartialBodies;"
                        )
                    )
                    == 2
                    else None
                )
            )
            advanced_checkpoint = json.loads(
                WebDriverWait(driver, 30).until(
                    lambda current: (
                        value
                        if (
                            value
                            := current.execute_script(
                                "return window.localStorage.getItem(arguments[0]);",
                                partial_key,
                            )
                        )
                        and json.loads(value)["session_id"]
                        != partial_session.upload_session_id
                        else None
                    )
                )
            )
            _require(
                partial_bodies[0]["resume_session_id"]
                == partial_session.upload_session_id
                and partial_bodies[0]["collection_id"]
                == partial_session.collection_id
                and len(partial_bodies[0]["files"]) == 4
                and partial_bodies[1]["resume_session_id"] == ""
                and partial_bodies[1]["collection_id"]
                == partial_session.collection_id
                and len(partial_bodies[1]["files"]) == 1
                and partial_bodies[1]["files"][0]["relative_path"].endswith(
                    "/record-00004.txt"
                )
                and advanced_checkpoint["batch_index"] == 1
                and advanced_checkpoint["collection_id"]
                == partial_session.collection_id
                and advanced_checkpoint["session_id"]
                != partial_session.upload_session_id
                and bench.workspace.upload_session(
                    partial_matter.matter_id,
                    ACTOR,
                    partial_session.upload_session_id,
                )[0].state
                == "partial"
                and len(
                    bench.workspace.recent_upload_sessions(
                        partial_matter.matter_id, ACTOR
                    )
                )
                == 2,
                "exact partial checkpoint was duplicated or did not advance to the next batch",
            )

            driver.get(f"{base_url}/matters/{slug}/setup")
            file_input = wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-file-input]"
                )
            )
            panel = driver.find_element(By.CSS_SELECTOR, "[data-upload-preflight]")
            if "assistant-collapsed" not in driver.find_element(
                By.TAG_NAME, "body"
            ).get_attribute("class").split():
                driver.find_element(
                    By.CSS_SELECTOR, "[data-assistant-collapse]"
                ).click()
                wait.until(
                    lambda current: "assistant-collapsed"
                    in current.find_element(By.TAG_NAME, "body")
                    .get_attribute("class")
                    .split()
                )
            _network_urls(driver)

            status_calls_before_preview = scanner.status_calls
            driver.execute_script("arguments[0].focus({preventScroll: true});", file_input)
            _replace_selection(driver, file_input, files)
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

            driver.set_window_size(1536, 1024)
            resume_matter = bench.create_matter(
                "Synthetic cross-refresh resume matter",
                "Generated exact-plan resume acceptance",
                ACTOR,
            )
            resume_key = f"case-intelligence:upload:{resume_matter.slug}"
            driver.get(f"{base_url}/matters/{resume_matter.slug}/setup")
            resume_input = wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-file-input]"
                )
            )
            _select(resume_input, [files[0]])
            wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 1 ready file"
            )
            driver.execute_script(
                """
                window.__slice1aResumeOriginalFetch = window.fetch;
                window.fetch = (...args) => {
                  if (String(args[1]?.method || '').toUpperCase() === 'PUT') {
                    return new Promise((_resolve, reject) => {
                      args[1]?.signal?.addEventListener(
                        'abort',
                        () => reject(new DOMException('Aborted', 'AbortError')),
                        { once: true },
                      );
                    });
                  }
                  return window.__slice1aResumeOriginalFetch(...args);
                };
                """
            )
            driver.execute_script(
                "arguments[0].click();",
                driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ),
            )
            saved_resume = WebDriverWait(driver, 30).until(
                lambda current: current.execute_script(
                    "return window.localStorage.getItem(arguments[0]);", resume_key
                )
            )
            saved_resume_state = json.loads(saved_resume)
            _require(saved_resume_state["version"] == 3, "resume state was not v3")
            _require(
                len(saved_resume_state["plan_fingerprint"]) == 64,
                "resume state did not bind the exact upload plan",
            )
            original_resume_session = saved_resume_state["session_id"]
            original_resume_collection = saved_resume_state["collection_id"]

            driver.refresh()
            resume_input = wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-file-input]"
                )
            )
            _select(resume_input, [files[0]])
            wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 1 ready file"
            )
            driver.execute_script(
                """
                window.__slice1aResumeOriginalFetch = window.fetch;
                window.__slice1aResumeBodies = [];
                window.fetch = (...args) => {
                  const method = String(args[1]?.method || 'GET').toUpperCase();
                  if (String(args[0]).includes('/upload-sessions') && method === 'POST') {
                    window.__slice1aResumeBodies.push(JSON.parse(String(args[1].body)));
                  }
                  if (method === 'PUT') {
                    return new Promise((_resolve, reject) => {
                      args[1]?.signal?.addEventListener(
                        'abort',
                        () => reject(new DOMException('Aborted', 'AbortError')),
                        { once: true },
                      );
                    });
                  }
                  return window.__slice1aResumeOriginalFetch(...args);
                };
                """
            )
            driver.execute_script(
                "arguments[0].click();",
                driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ),
            )
            resumed_body = WebDriverWait(driver, 30).until(
                lambda current: (
                    bodies[0]
                    if (
                        bodies
                        := current.execute_script(
                            "return window.__slice1aResumeBodies;"
                        )
                    )
                    else None
                )
            )
            _require(
                resumed_body["resume_session_id"] == original_resume_session
                and resumed_body["collection_id"] == original_resume_collection,
                "same-subset cross-refresh did not resume the exact saved session",
            )
            _require(
                len(
                    bench.workspace.recent_upload_sessions(
                        resume_matter.matter_id, ACTOR
                    )
                )
                == 1,
                "exact resume created a second upload session",
            )

            driver.refresh()
            missing_resume_state = {
                **saved_resume_state,
                "session_id": "upload-session-ffffffffffffffffffffffffffffffff",
            }
            driver.execute_script(
                "window.localStorage.setItem(arguments[0], arguments[1]);",
                resume_key,
                json.dumps(missing_resume_state),
            )
            resume_input = driver.find_element(By.CSS_SELECTOR, "[data-file-input]")
            _select(resume_input, [files[0]])
            wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 1 ready file"
            )
            driver.execute_script(
                """
                window.__slice1aRetryOriginalFetch = window.fetch;
                window.__slice1aRetryBodies = [];
                window.fetch = (...args) => {
                  const method = String(args[1]?.method || 'GET').toUpperCase();
                  if (String(args[0]).includes('/upload-sessions') && method === 'POST') {
                    window.__slice1aRetryBodies.push(JSON.parse(String(args[1].body)));
                  }
                  if (method === 'PUT') {
                    return new Promise((_resolve, reject) => {
                      args[1]?.signal?.addEventListener(
                        'abort',
                        () => reject(new DOMException('Aborted', 'AbortError')),
                        { once: true },
                      );
                    });
                  }
                  return window.__slice1aRetryOriginalFetch(...args);
                };
                """
            )
            driver.execute_script(
                "arguments[0].click();",
                driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ),
            )
            retry_bodies = WebDriverWait(driver, 30).until(
                lambda current: (
                    bodies
                    if len(
                        bodies
                        := current.execute_script(
                            "return window.__slice1aRetryBodies;"
                        )
                    )
                    == 2
                    else None
                )
            )
            _require(
                retry_bodies[0]["resume_session_id"]
                == missing_resume_state["session_id"]
                and retry_bodies[1]["resume_session_id"] == ""
                and retry_bodies[1]["collection_id"] == "",
                "resume mismatch did not clear identifiers and retry fresh exactly once",
            )
            WebDriverWait(driver, 30).until(
                lambda current: (
                    value
                    if (
                        value
                        := current.execute_script(
                            "return window.localStorage.getItem(arguments[0]);",
                            resume_key,
                        )
                    )
                    and json.loads(value)["session_id"]
                    != missing_resume_state["session_id"]
                    else None
                )
            )

            driver.refresh()
            driver.execute_script(
                "window.localStorage.setItem(arguments[0], arguments[1]);",
                resume_key,
                saved_resume,
            )
            changed_input = driver.find_element(By.CSS_SELECTOR, "[data-file-input]")
            _select(changed_input, [files[0], files[1]])
            wait.until(
                lambda current: current.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ).text
                == "Upload 2 ready files"
            )
            sessions_before_changed_plan = len(
                bench.workspace.recent_upload_sessions(
                    resume_matter.matter_id, ACTOR
                )
            )
            driver.execute_script(
                """
                window.__slice1aChangedOriginalFetch = window.fetch;
                window.__slice1aChangedBodies = [];
                window.fetch = (...args) => {
                  const method = String(args[1]?.method || 'GET').toUpperCase();
                  if (String(args[0]).includes('/upload-sessions') && method === 'POST') {
                    window.__slice1aChangedBodies.push(JSON.parse(String(args[1].body)));
                  }
                  if (method === 'PUT') {
                    return new Promise((_resolve, reject) => {
                      args[1]?.signal?.addEventListener(
                        'abort',
                        () => reject(new DOMException('Aborted', 'AbortError')),
                        { once: true },
                      );
                    });
                  }
                  return window.__slice1aChangedOriginalFetch(...args);
                };
                """
            )
            driver.execute_script(
                "arguments[0].click();",
                driver.find_element(
                    By.CSS_SELECTOR, "[data-upload-preflight-confirm]"
                ),
            )
            changed_body = WebDriverWait(driver, 30).until(
                lambda current: (
                    bodies[0]
                    if (
                        bodies
                        := current.execute_script(
                            "return window.__slice1aChangedBodies;"
                        )
                    )
                    else None
                )
            )
            changed_saved = json.loads(
                WebDriverWait(driver, 30).until(
                    lambda current: current.execute_script(
                        "return window.localStorage.getItem(arguments[0]);",
                        resume_key,
                    )
                )
            )
            _require(
                changed_body["resume_session_id"] == ""
                and changed_body["collection_id"] == ""
                and changed_saved["collection_id"] != original_resume_collection
                and len(
                    bench.workspace.recent_upload_sessions(
                        resume_matter.matter_id, ACTOR
                    )
                )
                == sessions_before_changed_plan + 1
                and len(
                    driver.execute_script(
                        "return window.__slice1aChangedBodies;"
                    )
                )
                == 1,
                "changed eligible subset did not start once in a new collection",
            )

            javascript_errors = [
                entry
                for entry in driver.get_log("browser")
                if entry.get("level") == "SEVERE" and entry.get("source") == "javascript"
            ]
            _require(not javascript_errors, f"browser JavaScript errors: {javascript_errors}")
            report["checks"] = [
                "real matter creation and setup route",
                "metadata-only API before bytes",
                "one scanner-availability snapshot across a logical multi-batch review",
                "safe folder-relative labels disambiguate duplicate leaf names",
                "ten-thousand-row preview uses bounded requests and one consolidated ordered result",
                "cross-batch canonical duplicate accounting",
                "oversized single descriptor fails locally without echo or request",
                "in-flight later batch aborts without exposing partial results",
                "all five synthetic rows and exact category totals",
                "truthful pending and not-run states",
                "one capability-status check and no content scan before initial confirmation",
                "selection change invalidates and replaces prior preview",
                "failed reselection clears stale rows and totals",
                "clearing an in-flight selection clears busy state",
                "keyboard confirmation uploads only the two eligible files",
                "retained upload path reports malformed PDF as partial",
                "exact-plan cross-refresh resume and one-shot mismatch recovery",
                "changed eligible subset clears stale resume identifiers",
                "collection-only checkpoint cannot skip batch zero or mutate a stale collection",
                "cancelled later-batch checkpoint retries once from a fresh collection",
                "exact partial checkpoint advances without duplicating its completed batch",
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
