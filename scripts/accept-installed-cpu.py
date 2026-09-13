#!/usr/bin/env python3
"""Check an explicitly acknowledged synthetic CPU node through its HTTPS gateway.

Uses only Python's standard library and the repository's verified browser pins.
Prints one content-free JSON receipt; never writes screenshots, DOM, or browser logs.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack, contextmanager
import getpass
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:-(?:alpha|beta|rc)\.[0-9]{1,4})?-[a-f0-9]{12}")
FIXTURES = {
    "01-delivery-note.txt": "5314b53bde76556bf6d358f0f2a95eff6c53178508ce5269ce939ce84011673f",
    "02-inspection-note.txt": "682c35903900b7de70e639a307a01cf3e12e35a410150d89663056a8cdcc5d97",
}
NOTE = "The delivery note counts three batteries; the later inspection counts two. The records do not explain the difference."
PHASES = ("inputs", "tls_and_release", "browser", "administrator_login", "synthetic_node",
          "assets", "reviewer_accounts", "matter_creation", "upload", "word_search", "exact_search",
          "source_review", "note_and_export", "named_grant", "unassigned_denial", "live_revocation")
ELEMENT = "element-6066-11e4-a52e-4f735466cecf"
MAX_RESPONSE = 4 * 1024 * 1024
MAX_EXPORT = 2 * 1024 * 1024
INTERRUPTED = False
WEBDRIVER_ERRORS = frozenset({"element click intercepted", "element not interactable", "insecure certificate",
    "invalid argument", "invalid element state", "invalid selector", "invalid session id", "javascript error",
    "no such element", "no such frame", "no such window", "script timeout", "session not created",
    "stale element reference", "timeout", "unexpected alert open", "unknown command", "unknown error",
    "unsupported operation", "transport_error", "invalid_response", "response_too_large", "unrecognized_error",
    "tab crashed", "disconnected", "chrome not reachable", "target frame detached"})
FAILURE_CODES = frozenset({
    "invalid_arguments", "https_origin_required", "unsafe_input_file", "input_file_unavailable",
    "invalid_installed_release", "expected_release_conflict", "expected_release_required",
    "synthetic_fixture_changed", "unexpected_redirect", "health_unavailable", "tls_or_health_unavailable",
    "unexpected_product", "installed_release_mismatch", "basic_review_not_ready", "cpu_profile_required",
    "linux_nss_tools_required_for_private_ca", "single_ca_certificate_required", "private_ca_import_failed",
    "browser_response_too_large", "browser_command_failed", "browser_phase_timeout",
    "browser_input_not_ready", "browser_input_value_mismatch",
    "browser_left_expected_origin", "unexpected_navigation", "browser_fetch_failed", "local_login_form_required",
    "populated_node_refused", "browser_account_management_required", "same_origin_assets_failed",
    "matter_export_failed", "export_too_large", "saved_note_missing_from_export", "invalid_matter_export",
    "unexpected_matter_path", "unexpected_search_sources", "source_text_missing", "explicit_person_choice_required",
    "ambiguous_person_choices", "selected_account_denied", "selected_export_denied", "unassigned_account_allowed",
    "revoked_session_allowed", "upload_failed", "synthetic_acknowledgment_required", "run_browser_as_unprivileged_user",
    "invalid_administrator_username", "invalid_password_input", "acceptance_interrupted_or_unavailable",
})


class AcceptanceError(Exception):
    """Only a fixed code crosses the public receipt boundary."""


class BrowserCommandError(AcceptanceError):
    def __init__(self, code, method, path):
        super().__init__("browser_command_failed")
        self.diagnostic = {
            "error": code if isinstance(code, str) and code in WEBDRIVER_ERRORS else "unrecognized_error",
            "method": method if method in {"GET", "POST", "DELETE"} else "UNKNOWN",
            "operation": webdriver_operation(method, path),
        }


def webdriver_operation(method, path):
    if path == "/status":
        return "status"
    if path == "/session":
        return "session_start"
    if re.fullmatch(r"/session/[^/]+", path):
        return "session_close" if method == "DELETE" else "unknown"
    route = re.sub(r"^/session/[^/]+", "", path)
    if route == "/url":
        return "navigate" if method == "POST" else "current_url"
    routes = {"/element": "element_find", "/execute/sync": "execute_script",
              "/execute/async": "execute_async", "/timeouts": "timeouts"}
    if route in routes:
        return routes[route]
    match = re.fullmatch(r"/element/[^/]+/(clear|value|click)", route)
    return {"clear": "element_clear", "value": "element_type", "click": "element_click"}[match[1]] if match else "unknown"


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AcceptanceError("invalid_arguments")


@contextmanager
def cleanup_signals():
    """Unwind private profiles and detached child groups on the first signal."""
    global INTERRUPTED
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    INTERRUPTED = False
    def interrupt(_number, _frame):
        global INTERRUPTED
        INTERRUPTED = True
        # A second terminal signal must not interrupt the cleanup it requested.
        for number in previous:
            signal.signal(number, signal.SIG_IGN)
        raise KeyboardInterrupt
    try:
        for number in previous:
            signal.signal(number, interrupt)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        INTERRUPTED = False


def origin(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or any(character.isspace() for character in value) or "\\" in value
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
        hostname = parsed.hostname.lower()
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if port is not None and port != 443:
            authority += f":{port}"
        return "https://" + authority
    except ValueError:
        raise AcceptanceError("https_origin_required") from None


def read_regular(path: Path, limit: int, *, secret: bool = False) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > limit
                    or (secret and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600))):
                raise AcceptanceError("unsafe_input_file")
            value = stream.read(limit + 1)
            if len(value) > limit:
                raise AcceptanceError("unsafe_input_file")
            return value
    except OSError:
        raise AcceptanceError("input_file_unavailable") from None


def expected_release(value: str | None, node_root: Path | None) -> str:
    if node_root is not None:
        try:
            saved = json.loads(read_regular(node_root / "installation.json", 65536))["release_id"]
        except (KeyError, ValueError, TypeError):
            raise AcceptanceError("invalid_installed_release") from None
        if value is not None and value != saved:
            raise AcceptanceError("expected_release_conflict")
        value = saved
    if not isinstance(value, str) or RELEASE.fullmatch(value) is None:
        raise AcceptanceError("expected_release_required")
    return value


def fixture_paths(root: Path, destination: Path) -> list[Path]:
    destination.mkdir(mode=0o700)
    paths = []
    for name, digest in FIXTURES.items():
        path = root / "examples/synthetic-alpha" / name
        contents = read_regular(path, 4096)
        if hashlib.sha256(contents).hexdigest() != digest:
            raise AcceptanceError("synthetic_fixture_changed")
        snapshot = destination / name
        with snapshot.open("xb") as stream:
            stream.write(contents)
        snapshot.chmod(0o600)
        paths.append(snapshot.resolve())
    return paths


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AcceptanceError("unexpected_redirect")


def ca_snapshot(ca_file: Path | None) -> bytes | None:
    if ca_file is None:
        return None
    certificate = read_regular(ca_file, 65536)
    # Compose delimiters as the publication scanner's synthetic parser tests do;
    # this source contains format recognition, never certificate material.
    if (certificate.count(b"-----BEGIN " + b"CERTIFICATE-----") != 1
            or certificate.count(b"-----END " + b"CERTIFICATE-----") != 1
            or b"PRIVATE KEY" in certificate):
        raise AcceptanceError("single_ca_certificate_required")
    return certificate


def tls_health(target: str, certificate: bytes | None, expected: str) -> str:
    context = ssl.create_default_context(cadata=certificate.decode("ascii") if certificate else None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context), NoRedirects())
    try:
        with opener.open(target + "/health", timeout=15) as response:
            data = response.read(65537)
            if response.status != 200 or len(data) > 65536:
                raise AcceptanceError("health_unavailable")
        health = json.loads(data)
    except (OSError, ValueError, urllib.error.URLError):
        raise AcceptanceError("tls_or_health_unavailable") from None
    if not isinstance(health, dict) or health.get("product") != "RecordBench":
        raise AcceptanceError("unexpected_product")
    observed = health.get("release_id")
    if not isinstance(observed, str) or RELEASE.fullmatch(observed) is None or observed != expected:
        raise AcceptanceError("installed_release_mismatch")
    storage, capabilities, selected = (health.get(key) for key in ("storage", "capabilities", "selected_capabilities"))
    if (health.get("status") != "ok" or not isinstance(storage, dict) or not isinstance(capabilities, dict)
            or storage.get("status") != "ready" or capabilities.get("source_review") != "ready"
            or capabilities.get("malware_scan") != "ready"):
        raise AcceptanceError("basic_review_not_ready")
    if (not isinstance(selected, dict) or set(selected) != {"answering", "meaning_search", "transcription"}
            or any(value is not False for value in selected.values())):
        raise AcceptanceError("cpu_profile_required")
    return observed


def browser_environment(scratch: Path, certificate: bytes | None) -> dict[str, str]:
    private_home = scratch / "home"
    private_home.mkdir(mode=0o700)
    environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(private_home),
        "LANG": "C.UTF-8", "TZ": "UTC", "TMPDIR": str(scratch),
        "XDG_CONFIG_HOME": str(private_home / ".config"),
        "XDG_CACHE_HOME": str(private_home / ".cache"), "NO_PROXY": "127.0.0.1,localhost,::1"}
    if certificate is not None:
        if sys.platform != "linux" or shutil.which("certutil") is None:
            raise AcceptanceError("linux_nss_tools_required_for_private_ca")
        # Chromium M146+ uses this NSS path when no older shared database exists.
        database = private_home / ".local/share/pki/nssdb"
        database.mkdir(parents=True, mode=0o700)
        trusted = scratch / "acceptance-ca.crt"
        trusted.write_bytes(certificate)
        trusted.chmod(0o600)
        for command in (["certutil", "-N", "--empty-password", "-d", "sql:" + str(database)],
                        ["certutil", "-A", "-d", "sql:" + str(database), "-n", "synthetic-acceptance-ca",
                         "-t", "C,,", "-i", str(trusted)]):
            try:
                subprocess.run(command, check=True, env=environment, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=20)
            except (OSError, subprocess.SubprocessError):
                raise AcceptanceError("private_ca_import_failed") from None
    return environment


def browser_tools():
    spec = importlib.util.spec_from_file_location("recordbench_browser_pins", ROOT / "scripts/run-browser-acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Browser:
    def __init__(self, chrome: Path, driver: Path, profile: Path, environment: dict, target: str, tools):
        self.target, self.tools, self.session, self.process = target, tools, None, None
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())
        try:
            self.process = subprocess.Popen([str(driver), f"--port={port}", "--allowed-ips=127.0.0.1"],
                env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.wait(lambda: self.command("GET", "/status").get("ready") is True, seconds=20)
            arguments = ["--headless=new", "--window-size=1440,1000", "--no-first-run",
                "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
                "--disable-sync", "--no-proxy-server", "--password-store=basic", "--user-data-dir=" + str(profile)]
            if sys.platform == "linux":
                # Chromium uses our private TMPDIR instead of a container's small
                # /dev/shm mount. This does not disable its sandbox or TLS checks.
                arguments.append("--disable-dev-shm-usage")
            capabilities = {"browserName": "chrome", "acceptInsecureCerts": False,
                "goog:chromeOptions": {"binary": str(chrome), "args": arguments}}
            self.session = self.command("POST", "/session", {"capabilities": {"alwaysMatch": capabilities}})["sessionId"]
            self.call("POST", "/timeouts", {"implicit": 0, "pageLoad": 30000, "script": 30000})
        except BaseException:
            self.close()
            raise

    def command(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.endpoint + path, data=data, method=method,
                                        headers={"Content-Type": "application/json"})
        try:
            failed_http = False
            try:
                response = self.opener.open(request, timeout=35)
            except urllib.error.HTTPError as error:
                response, failed_http = error, True
            with response:
                body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise BrowserCommandError("response_too_large", method, path)
            value = json.loads(body)["value"]
            if failed_http or (isinstance(value, dict) and value.get("error")):
                raise BrowserCommandError(value.get("error") if isinstance(value, dict) else None, method, path)
            return value
        except (ValueError, KeyError, TypeError):
            raise BrowserCommandError("invalid_response", method, path) from None
        except (OSError, urllib.error.URLError):
            raise BrowserCommandError("transport_error", method, path) from None

    def call(self, method, path, payload=None):
        return self.command(method, "/session/" + self.session + path, payload)

    def execute(self, script, *args):
        return self.call("POST", "/execute/sync", {"script": script, "args": list(args)})

    def wait(self, predicate, seconds=30):
        deadline = time.monotonic() + seconds
        last_error = None
        while time.monotonic() < deadline:
            try:
                result = predicate()
                if result:
                    return result
            except AcceptanceError as exc:
                if not isinstance(exc, BrowserCommandError) or not (
                        exc.diagnostic["error"] in {"no such element", "stale element reference"}
                        or (exc.diagnostic["error"] == "transport_error" and exc.diagnostic["operation"] == "status")):
                    raise
                last_error = exc
            time.sleep(0.2)
        if last_error is not None:
            raise last_error
        raise AcceptanceError("browser_phase_timeout")

    def require_origin(self):
        current = urllib.parse.urlsplit(self.call("GET", "/url"))
        if urllib.parse.urlunsplit((current.scheme, current.netloc, "", "", "")) != self.target:
            raise AcceptanceError("browser_left_expected_origin")

    def go(self, path):
        if not path.startswith("/") or path.startswith("//"):
            raise AcceptanceError("unexpected_navigation")
        self.call("POST", "/url", {"url": self.target + path})
        self.require_origin()

    def element(self, selector):
        self.require_origin()
        return self.call("POST", "/element", {"using": "css selector", "value": selector})[ELEMENT]

    def fill(self, selector, text):
        element = self.element(selector)
        reference = {ELEMENT: element}
        if selector == "#source-files":
            self.call("POST", f"/element/{element}/value", {"text": text})
            return
        state = self.execute("""const input = arguments[0]; const rect = input.getBoundingClientRect();
            const editable = (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement)
              && input.isConnected && !input.disabled && !input.readOnly && rect.width > 0 && rect.height > 0;
            if (editable) { input.scrollIntoView({block: 'center', behavior: 'instant'}); input.focus({preventScroll: true}); }
            return {ready: editable && document.activeElement === input, empty: input.value === ''};""", reference)
        require(isinstance(state, dict) and state.get("ready") is True, "browser_input_not_ready")
        if state.get("empty") is not True:
            self.call("POST", f"/element/{element}/clear", {})
            require(self.execute("arguments[0].focus({preventScroll: true}); return document.activeElement === arguments[0] && arguments[0].value === '';",
                                 reference), "browser_input_not_ready")
        self.call("POST", f"/element/{element}/value", {"text": text})
        require(self.execute("return arguments[0].value === arguments[1];", reference, text), "browser_input_value_mismatch")

    def click(self, selector):
        element = self.element(selector)
        self.execute("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", {ELEMENT: element})
        self.call("POST", f"/element/{element}/click", {})
        self.require_origin()

    def fetch(self, path, *, content=False):
        self.require_origin()
        result = self.call("POST", "/execute/async", {"script": """
          const path = arguments[0], content = arguments[1], limit = arguments[2], done = arguments[3];
          const url = new URL(path, location.origin);
          if (url.origin !== location.origin) { done({error: true}); return; }
          fetch(url, {redirect: 'error', cache: 'no-store'}).then(async response => {
            if (!content) { await response.body?.cancel(); done({status: response.status}); return; }
            const reader = response.body.getReader(); const chunks = []; let count = 0;
            while (true) { const {done: ended, value} = await reader.read(); if (ended) break;
              count += value.length; if (count > limit) { await reader.cancel(); done({error: true}); return; } chunks.push(value); }
            let binary = ''; for (const chunk of chunks) { for (const byte of chunk) binary += String.fromCharCode(byte); }
            done({status: response.status, content_type: response.headers.get('content-type'), data: btoa(binary)});
          }).catch(() => done({error: true}));
        """, "args": [path, content, MAX_EXPORT]})
        if not isinstance(result, dict) or result.get("error"):
            raise AcceptanceError("browser_fetch_failed")
        return result

    def close(self):
        try:
            if self.session and not INTERRUPTED:
                self.call("DELETE", "")
        except AcceptanceError:
            pass
        finally:
            if self.process:
                self.tools.terminate_group(self.process)
                self.process = None
            self.session = None


def require(condition, code):
    if not condition:
        raise AcceptanceError(code)


def login(browser, username, password):
    browser.go("/auth/login")
    require(browser.execute("""const form = document.querySelector('.local-login-form');
        if (!form || form.method.toLowerCase() !== 'post') return false;
        const action = new URL(form.action);
        return action.origin === location.origin && action.pathname === '/auth/local'
          && Boolean(form.querySelector('input[name=login_challenge]')?.value);"""), "local_login_form_required")
    browser.fill("#local-username", username)
    browser.fill("#local-password", password)
    browser.click(".local-login-form button[type=submit]")
    browser.wait(lambda: browser.execute("return !location.pathname.startsWith('/auth/');"))


def check_node(browser, admin_username, allow_previous):
    browser.go("/admin")
    state = browser.execute("""const section = document.querySelector('[aria-labelledby="admin-matters-heading"]');
        const table = section?.querySelector('.matter-oversight-table[role=table]');
        const matters = Array.from(table?.querySelectorAll('.administrator-table-row') || [])
          .map(row => row.querySelector('[role=cell] strong')?.textContent || '');
        const empty = section?.querySelector('.administrator-empty')?.textContent.trim() === 'There are no active matters.';
        return {recovery: Boolean(document.querySelector('#closure-recovery-heading')),
          recognized: Boolean(section && ((table && matters.length && !empty) || (!table && empty))), matters};""")
    require(isinstance(state, dict) and state.get("recognized") is True and state.get("recovery") is False,
            "populated_node_refused")
    matters = state.get("matters")
    require(isinstance(matters, list) and len(matters) <= 10 and (not matters or allow_previous)
            and all(re.fullmatch(r"Synthetic CPU acceptance [a-f0-9]{12}", name) for name in matters), "populated_node_refused")
    browser.go("/admin/people")
    require(browser.execute("return Boolean(document.querySelector('#new-username'));"), "browser_account_management_required")
    accounts = browser.execute("""return Array.from(document.querySelectorAll('.people-list a[href*="/admin/people/accounts/"]'))
        .map(link => new URL(link.href).pathname.split('/').pop());""")
    require(isinstance(accounts, list) and admin_username in accounts and len(accounts) <= 21
            and all(name == admin_username or (allow_previous and re.fullmatch(r"rb-synthetic-[a-f0-9]{12}-[ab]", name)) for name in accounts),
            "populated_node_refused")


def check_assets(browser):
    require(browser.execute("""const assets = Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]'));
        return assets.length >= 4 && assets.every(item => new URL(item.href || item.src).origin === location.origin
          && (item.tagName !== 'LINK' || Boolean(item.sheet)));"""), "same_origin_assets_failed")
    browser.click("[data-activity-toggle]")
    browser.wait(lambda: browser.execute("return document.querySelector('[data-activity-drawer]').getAttribute('aria-hidden') === 'false';"))
    browser.click("[data-activity-toggle]")


def check_export(result):
    require(result.get("status") == 200 and "zip" in result.get("content_type", ""), "matter_export_failed")
    try:
        data = base64.b64decode(result["data"], validate=True)
        require(len(data) <= MAX_EXPORT, "export_too_large")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            require(len(members) <= 100 and sum(member.file_size for member in members) <= 4 * MAX_EXPORT, "export_too_large")
            note = archive.read("notebook/matter-notebook.md").decode("utf-8")
            require("battery count difference" in note and NOTE in note, "saved_note_missing_from_export")
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, UnicodeError):
        raise AcceptanceError("invalid_matter_export") from None


def create_reviewers(admin, open_browser, names, password, display):
    for name in names:
        admin.go("/admin/people")
        for selector, value in (("#new-display-name", display), ("#new-username", name),
                                ("#new-password", password), ("#new-password-confirm", password)):
            admin.fill(selector, value)
        admin.click("#add-person button[type=submit]")
        admin.wait(lambda: admin.execute("return location.pathname === arguments[0];", "/admin/people/accounts/" + name))
        # Local accounts enter the team picker after their first real sign-in.
        # Register one at a time; matrix sessions below use fresh profiles.
        reviewer = open_browser()
        try:
            login(reviewer, name, password)
        finally:
            reviewer.close()


def run_journey(admin, open_browser, username, password, fixtures, allow_previous, phase):
    phase("administrator_login", lambda: login(admin, username, password))
    phase("synthetic_node", lambda: check_node(admin, username, allow_previous))
    phase("assets", lambda: check_assets(admin))
    run_id = secrets.token_hex(6)
    reviewer_names = [f"rb-synthetic-{run_id}-{suffix}" for suffix in ("a", "b")]
    reviewer_password = secrets.token_urlsafe(24)
    display = "Synthetic CPU Reviewer"
    phase("reviewer_accounts", lambda: create_reviewers(admin, open_browser, reviewer_names, reviewer_password, display))
    def matter():
        admin.go("/matters/new")
        admin.fill("#matter-name", "Synthetic CPU acceptance " + run_id)
        admin.click(".matter-form button[type=submit]")
        admin.wait(lambda: admin.execute(r"return /^\/matters\/[^/]+\/setup$/.test(location.pathname);"))
        path = admin.execute(r"return location.pathname.replace(/\/setup$/, '');")
        require(isinstance(path, str) and re.fullmatch(r"/matters/[a-zA-Z0-9_-]{1,120}", path), "unexpected_matter_path")
        return path
    prefix = phase("matter_creation", matter)

    def upload():
        admin.fill("#source-files", "\n".join(str(path) for path in fixtures))
        admin.wait(lambda: admin.execute("return document.querySelector('[data-upload-preflight-confirm]')?.disabled === false;"))
        admin.click("[data-upload-preflight-confirm]")
        def transferred():
            state = admin.execute("""return {ready: document.querySelector('[data-upload-review]')?.hidden === false,
              paused: document.querySelector('[data-upload-title]')?.textContent.trim() === 'Upload paused'};""")
            require(not state.get("paused"), "upload_failed")
            return state.get("ready")
        admin.wait(transferred, seconds=180)
        # Query the rendered index until both known records are searchable. Poll
        # only this new synthetic matter; no privileged diagnostics are needed.
        def ready():
            admin.go(prefix + "/exact-search?words=lantern")
            return admin.execute("return document.getElementById('find-results-heading')?.textContent.trim() === '2 sources found';")
        admin.wait(ready, seconds=180)
    phase("upload", upload)

    def words():
        admin.go(prefix + "?mode=search")
        admin.fill("#matter-search", "lantern")
        admin.click(".matter-search-form button[type=submit]")
        admin.wait(lambda: admin.execute("return document.querySelectorAll('.search-result').length >= 2;"))
    phase("word_search", words)

    def exact():
        admin.go(prefix + "/exact-search")
        admin.fill("#find-words", "lantern")
        admin.click(".find-refinements > summary")
        admin.fill("#find-phrase", "blue lantern")
        admin.click("#find-basic-form button[type=submit]")
        admin.wait(lambda: admin.execute("return document.getElementById('find-results-heading')?.textContent.trim() === '2 sources found';"))
        require(admin.execute("return Array.from(document.querySelectorAll('.find-document-title h3')).map(e => e.textContent.trim()).sort();") == sorted(FIXTURES), "unexpected_search_sources")
    phase("exact_search", exact)

    def source():
        admin.click(".find-location")
        admin.wait(lambda: admin.execute("return location.pathname.includes('/sources/');"))
        require(admin.execute("return document.body.innerText.includes('blue lantern');"), "source_text_missing")
    phase("source_review", source)

    def note_export():
        admin.go(prefix + "/notebook")
        admin.fill(".notebook-item-form input[name=title]", "battery count difference")
        admin.fill(".notebook-item-form textarea[name=body]", NOTE)
        admin.click(".notebook-item-form button[type=submit]")
        admin.wait(lambda: admin.execute("return Array.from(document.querySelectorAll('.notebook-item h3')).some(e => e.textContent === 'battery count difference');"))
        admin.go(prefix + "/work-product")
        export_path = admin.execute("""const link = Array.from(document.querySelectorAll('.report-export-actions a'))
          .find(item => new URL(item.href).pathname === arguments[0]);
          return link && link.getBoundingClientRect().height > 0 ? new URL(link.href).pathname : null;""", prefix + "/export")
        require(export_path == prefix + "/export", "matter_export_failed")
        check_export(admin.fetch(export_path, content=True))
    phase("note_and_export", note_export)

    check_team_access(admin, open_browser, prefix, reviewer_names, reviewer_password, display, phase)


def check_team_access(admin, open_browser, prefix, reviewer_names, reviewer_password, display, phase):

    selected = None
    def named_grant():
        nonlocal selected
        admin.go(prefix + "/setup")
        require(admin.execute("return document.querySelector('#new-member')?.value === '';"), "explicit_person_choice_required")
        choices = admin.execute("return Array.from(document.querySelectorAll('#new-member option')).filter(o => o.value).map(o => ({value: o.value, label: o.textContent}));")
        expected = [f"{display} ({name})" for name in reviewer_names]
        choices = [choice for choice in choices if choice.get("label") in expected]
        require(len(choices) == 2 and {item["label"] for item in choices} == set(expected), "ambiguous_person_choices")
        choice = choices[1]
        selected = reviewer_names[0] if choice["label"] == expected[0] else reviewer_names[1]
        admin.execute("const select = document.querySelector('#new-member'); select.value = arguments[0]; select.dispatchEvent(new Event('change', {bubbles: true}));", choice["value"])
        admin.click("form[action$='/members'] button[type=submit]")
        admin.wait(lambda: admin.execute("return Array.from(document.querySelectorAll('.case-team-list strong')).some(e => e.textContent === arguments[0]);", choice["label"]))
        require(admin.execute("return Array.from(document.querySelectorAll('.notice-success')).some(e => e.textContent.includes(arguments[0]));", choice["label"] + " added to the case team"), "ambiguous_person_choices")
    phase("named_grant", named_grant)

    def denied():
        unassigned = open_browser()
        try:
            name = next(name for name in reviewer_names if name != selected)
            login(unassigned, name, reviewer_password)
            for path in (prefix + "/home", prefix + "/notebook/export?format=markdown"):
                require(unassigned.fetch(path)["status"] == 404, "unassigned_account_allowed")
        finally:
            unassigned.close()
    phase("unassigned_denial", denied)

    def revoke():
        reviewer = open_browser()
        try:
            login(reviewer, selected, reviewer_password)
            reviewer.go(prefix + "/home")
            require(reviewer.fetch(prefix + "/home")["status"] == 200, "selected_account_denied")
            require(reviewer.fetch(prefix + "/notebook/export?format=markdown")["status"] == 200, "selected_export_denied")
            admin.click(".case-team-list form[action$='/remove'] button")
            admin.wait(lambda: admin.execute("return document.querySelectorAll('.case-team-list form[action$=\"/remove\"]').length === 0;"))
            for path in (prefix + "/home", prefix + "/notebook/export?format=markdown"):
                require(reviewer.fetch(path)["status"] == 404, "revoked_session_allowed")
        finally:
            reviewer.close()
    phase("live_revocation", revoke)


def run(argv=None):
    started = time.monotonic()
    receipt = {"format_version": 1, "synthetic_evaluation_acknowledged": False, "passed": False,
               "phases": {name: "not-run" for name in PHASES},
               "phase_seconds": {name: None for name in PHASES}, "first_export_seconds": None,
               "counts": {"uploaded_sources": None, "created_reviewers": None}}
    active_phase = "inputs"
    phase_started = started
    def phase(name, function):
        nonlocal active_phase, phase_started
        active_phase = name
        phase_started = time.monotonic()
        try:
            result = function()
        finally:
            receipt["phase_seconds"][name] = round(time.monotonic() - phase_started, 3)
        receipt["phases"][name] = "passed"
        if name == "reviewer_accounts":
            receipt["counts"]["created_reviewers"] = 2
        elif name == "upload":
            receipt["counts"]["uploaded_sources"] = 2
        elif name == "note_and_export":
            receipt["first_export_seconds"] = round(time.monotonic() - started, 3)
        return result
    parser = Parser(description=__doc__)
    parser.add_argument("--url", required=True, help="Installed HTTPS origin including its port; no path.")
    parser.add_argument("--ca-file", type=Path, help="Single private CA PEM, trusted only inside the Linux runner.")
    parser.add_argument("--node-root", type=Path, help="Read the expected release from this node's installation.json.")
    parser.add_argument("--expected-release-id", help="Required when node-root is absent; checked against /health.")
    parser.add_argument("--admin-username", required=True)
    parser.add_argument("--admin-password-file", type=Path, help="Owner-only mode-0600 file; otherwise prompt privately.")
    parser.add_argument("--acknowledge-synthetic-evaluation", action="store_true", help="Confirm the entire target node contains only invented evaluation material.")
    parser.add_argument("--allow-previous-synthetic-runs", action="store_true", help="Permit only bounded prior runs created by this runner.")
    parser.add_argument("--archives", type=Path, help="Optional offline Chrome/driver archive directory; hashes still verified.")
    try:
        args = parser.parse_args(argv)
        require(args.acknowledge_synthetic_evaluation, "synthetic_acknowledgment_required")
        receipt["synthetic_evaluation_acknowledged"] = True
        require(os.geteuid() != 0, "run_browser_as_unprivileged_user")
        target = origin(args.url)
        expected = expected_release(args.expected_release_id, args.node_root)
        receipt["expected_release_id"] = expected
        certificate = ca_snapshot(args.ca_file)
        require(re.fullmatch(r"[a-z0-9][a-z0-9._@-]{2,127}", args.admin_username), "invalid_administrator_username")
        password = (read_regular(args.admin_password_file, 4097, secret=True).decode("utf-8").rstrip("\r\n")
                    if args.admin_password_file else getpass.getpass("Synthetic node administrator password: "))
        require(14 <= len(password) <= 1024, "invalid_password_input")
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
            if re.fullmatch(r"[a-f0-9]{40}", commit):
                receipt["runner_commit"] = commit
                receipt["runner_working_tree_clean"] = not subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
        except (OSError, subprocess.SubprocessError):
            pass
        receipt["phases"]["inputs"] = "passed"
        receipt["phase_seconds"]["inputs"] = round(time.monotonic() - started, 3)
        receipt["observed_release_id"] = phase("tls_and_release", lambda: tls_health(target, certificate, expected))
        with tempfile.TemporaryDirectory(prefix="recordbench-installed-cpu-") as temporary, ExitStack() as stack:
            scratch = Path(temporary).resolve()
            def prepare_browser():
                tools = browser_tools()
                fixtures = fixture_paths(ROOT, scratch / "fixtures")
                environment = browser_environment(scratch, certificate)
                platform_name = tools.host_platform()
                directory = scratch / "browser"
                directory.mkdir()
                chrome, driver, version = tools.install_browser(directory, platform_name, args.archives)
                receipt.update(browser_version=version, browser_platform=platform_name)
                number = 0
                def open_browser():
                    nonlocal number
                    browser = Browser(chrome, driver, scratch / f"profile-{number}", environment, target, tools)
                    stack.callback(browser.close)
                    number += 1
                    return browser
                return open_browser(), open_browser, fixtures
            admin, open_browser, fixtures = phase("browser", prepare_browser)
            run_journey(admin, open_browser, args.admin_username, password, fixtures, args.allow_previous_synthetic_runs, phase)
            receipt["counts"] = {"uploaded_sources": 2, "created_reviewers": 2}
            receipt["passed"] = all(value == "passed" for value in receipt["phases"].values())
    except AcceptanceError as exc:
        receipt["passed"] = False
        receipt["phases"][active_phase] = "failed"
        receipt["failure_code"] = str(exc) if str(exc) in FAILURE_CODES else "acceptance_interrupted_or_unavailable"
        if isinstance(exc, BrowserCommandError):
            receipt["webdriver"] = exc.diagnostic
    except (Exception, KeyboardInterrupt):
        receipt["passed"] = False
        receipt["phases"][active_phase] = "failed"
        receipt["failure_code"] = "acceptance_interrupted_or_unavailable"
    if receipt["phase_seconds"][active_phase] is None:
        receipt["phase_seconds"][active_phase] = round(time.monotonic() - phase_started, 3)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["passed"] else 1


def main(argv=None):
    with cleanup_signals():
        return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
