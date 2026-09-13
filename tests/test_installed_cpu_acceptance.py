"""Installed-node runner gates and receipts use synthetic inputs only."""
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, HTTPServer
import base64
import importlib.util
import io
import json
import os
import signal
import sys
import time
from pathlib import Path
import ssl
import subprocess
import threading
from unittest.mock import Mock
import zipfile

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).parents[1] / "scripts/accept-installed-cpu.py"
    spec = importlib.util.spec_from_file_location("installed_cpu_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("url", ["http://localhost:8443", "https://user:password@example.test",
    "https://example.test/path", "https://example.test?secret=value", "https://example.test#fragment",
    "https://example.test:99999", "https://example.test\\path", "https://example.test\n"])
def test_rejects_non_origin_or_credential_urls(runner, url):
    with pytest.raises(runner.AcceptanceError, match="https_origin_required"):
        runner.origin(url)


@pytest.mark.parametrize("supplied,canonical", [("https://LOCALHOST:443/", "https://localhost"),
    ("https://EXAMPLE.test:8443", "https://example.test:8443"), ("https://[::1]:443", "https://[::1]")])
def test_origin_matches_browser_canonicalization(runner, supplied, canonical):
    browser = object.__new__(runner.Browser)
    browser.target = runner.origin(supplied)
    browser.call = Mock(return_value=canonical + "/auth/login")
    browser.require_origin()
    assert browser.target == canonical


def test_release_expected_and_local_node_must_agree(runner, tmp_path):
    release = "0.1.0-alpha.2-" + "a" * 12
    (tmp_path / "installation.json").write_text(json.dumps({"release_id": release, "private_path": "not-for-receipt"}))
    assert runner.expected_release(None, tmp_path) == release
    assert runner.expected_release(release, tmp_path) == release
    for value in ("development", "a" * 40, "private.example.test"):
        with pytest.raises(runner.AcceptanceError):
            runner.expected_release(value, None)
    with pytest.raises(runner.AcceptanceError, match="expected_release_conflict"):
        runner.expected_release("0.1.0-alpha.2-" + "b" * 12, tmp_path)


def test_secret_input_refuses_symlink_wrong_mode_and_oversize(runner, tmp_path):
    source = tmp_path / "password"
    source.write_bytes(b"synthetic-password-only")
    source.chmod(0o600)
    assert runner.read_regular(source, 100, secret=True) == source.read_bytes()
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(runner.AcceptanceError):
        runner.read_regular(link, 100, secret=True)
    source.chmod(0o644)
    with pytest.raises(runner.AcceptanceError):
        runner.read_regular(source, 100, secret=True)
    source.chmod(0o600)
    with pytest.raises(runner.AcceptanceError):
        runner.read_regular(source, 1, secret=True)


def test_modified_synthetic_fixture_is_refused(runner, tmp_path, monkeypatch):
    directory = tmp_path / "examples/synthetic-alpha"
    directory.mkdir(parents=True)
    monkeypatch.setattr(runner, "FIXTURES", {"generated.txt": runner.hashlib.sha256(b"Synthetic bytes").hexdigest()})
    source = directory / "generated.txt"
    source.write_bytes(b"Synthetic bytes")
    snapshot = runner.fixture_paths(tmp_path, tmp_path / "snapshot")[0]
    assert snapshot.read_bytes() == source.read_bytes()
    source.write_bytes(b"Changed synthetic bytes")
    with pytest.raises(runner.AcceptanceError, match="synthetic_fixture_changed"):
        runner.fixture_paths(tmp_path, tmp_path / "changed-snapshot")
    assert snapshot.read_bytes() == b"Synthetic bytes"


@contextmanager
def tls_node(tmp_path, payload, *, redirect=False):
    cert, key = tmp_path / "test.crt", tmp_path / "test.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost", "-keyout", str(key), "-out", str(cert)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if redirect else 200)
            if redirect:
                self.send_header("Location", "https://outside.example.test/health")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self, *_args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_port}", cert
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_tls_requires_trusted_ca_hostname_and_exact_installed_release(runner, tmp_path):
    release = "0.1.0-alpha.2-" + "a" * 12
    payload = {"product": "RecordBench", "release_id": release,
               "storage": {"status": "ready"}, "capabilities": {"source_review": "ready", "malware_scan": "ready"}, "status": "ok",
               "selected_capabilities": {name: False for name in ("answering", "meaning_search", "transcription")}}
    with tls_node(tmp_path, payload) as (target, ca):
        assert runner.tls_health(target, runner.ca_snapshot(ca), release) == release
        with pytest.raises(runner.AcceptanceError, match="tls_or_health_unavailable"):
            runner.tls_health(target, None, release)
        with pytest.raises(runner.AcceptanceError, match="tls_or_health_unavailable"):
            runner.tls_health(target.replace("localhost", "127.0.0.1"), runner.ca_snapshot(ca), release)
        with pytest.raises(runner.AcceptanceError, match="installed_release_mismatch"):
            runner.tls_health(target, runner.ca_snapshot(ca), "0.1.0-alpha.2-" + "b" * 12)


def test_health_redirect_is_not_followed(runner, tmp_path):
    with tls_node(tmp_path, {}, redirect=True) as (target, ca):
        with pytest.raises(runner.AcceptanceError, match="unexpected_redirect"):
            runner.tls_health(target, runner.ca_snapshot(ca), "0.1.0-alpha.2-" + "a" * 12)


@pytest.mark.parametrize("key,value,code", [
    ("status", "degraded", "basic_review_not_ready"),
    ("capabilities", {"source_review": "ready", "malware_scan": "not-required"}, "basic_review_not_ready"),
    ("capabilities", {"source_review": "ready", "malware_scan": "unavailable"}, "basic_review_not_ready"),
    ("storage", None, "basic_review_not_ready"),
    ("selected_capabilities", None, "cpu_profile_required"),
    ("selected_capabilities", {"answering": False, "meaning_search": False}, "cpu_profile_required"),
    ("selected_capabilities", {"answering": 0, "meaning_search": False, "transcription": False}, "cpu_profile_required"),
    ("selected_capabilities", {"answering": True, "meaning_search": False, "transcription": False}, "cpu_profile_required"),
])
def test_cpu_health_requires_ready_scanner_and_exact_false_selections(runner, monkeypatch, key, value, code):
    release = "0.1.0-alpha.2-" + "a" * 12
    health = {"product": "RecordBench", "release_id": release, "status": "ok", "storage": {"status": "ready"},
              "capabilities": {"source_review": "ready", "malware_scan": "ready"},
              "selected_capabilities": {name: False for name in ("answering", "meaning_search", "transcription")}}
    health[key] = value
    response = Mock(status=200)
    response.read.return_value = json.dumps(health).encode()
    opener = Mock()
    opener.open.return_value = nullcontext(response)
    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *_: opener)
    with pytest.raises(runner.AcceptanceError, match=code):
        runner.tls_health("https://synthetic.example.test", None, release)


def test_ca_snapshot_refuses_fifo_symlink_and_multiple_certificates(runner, tmp_path):
    fifo = tmp_path / "input-fifo"
    os.mkfifo(fifo)
    with pytest.raises(runner.AcceptanceError, match="unsafe_input_file"):
        runner.ca_snapshot(fifo)
    source = tmp_path / "ca-input"
    source.write_bytes(b"-----BEGIN " + b"CERTIFICATE-----\nSynthetic\n-----END " + b"CERTIFICATE-----\n")
    snapshot = runner.ca_snapshot(source)
    link = tmp_path / "ca-link"
    link.symlink_to(source)
    with pytest.raises(runner.AcceptanceError):
        runner.ca_snapshot(link)
    source.write_bytes(snapshot + snapshot)
    with pytest.raises(runner.AcceptanceError, match="single_ca_certificate_required"):
        runner.ca_snapshot(source)
    assert snapshot.count(b"Synthetic") == 1


def test_private_ca_import_changes_only_temporary_nss_db(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/synthetic/certutil")
    run = Mock()
    monkeypatch.setattr(runner.subprocess, "run", run)
    certificate = tmp_path / "ca.crt"
    certificate.write_bytes(b"-----BEGIN " + b"CERTIFICATE-----\nSynthetic\n-----END " + b"CERTIFICATE-----\n")
    snapshot = runner.ca_snapshot(certificate)
    certificate.write_bytes(b"Changed after capture")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    environment = runner.browser_environment(scratch, snapshot)
    assert (scratch / "acceptance-ca.crt").read_bytes() == snapshot
    assert environment["HOME"] == str(scratch / "home")
    assert len(run.call_args_list) == 2
    first, second = [call.args[0] for call in run.call_args_list]
    assert first == ["certutil", "-N", "--empty-password", "-d", "sql:" + str(scratch / "home/.local/share/pki/nssdb")]
    assert second[second.index("-t") + 1] == "C,,"
    assert run.call_args.kwargs["stdout"] == subprocess.DEVNULL
    assert "CASE_INTELLIGENCE_STORAGE_RESERVE_GIB" not in environment


def test_browser_uses_normal_tls_and_sandbox_with_private_profile(runner, tmp_path, monkeypatch):
    commands = []
    def command(browser, method, path, payload=None):
        commands.append((method, path, payload))
        if path == "/status":
            return {"ready": True}
        if path == "/session":
            return {"sessionId": "synthetic-session"}
        return None
    monkeypatch.setattr(runner.Browser, "command", command)
    process = Mock()
    monkeypatch.setattr(runner.subprocess, "Popen", Mock(return_value=process))
    tools = Mock()
    browser = runner.Browser(tmp_path / "chrome", tmp_path / "driver", tmp_path / "private-profile",
                             {"HOME": str(tmp_path)}, "https://synthetic.example.test", tools)
    capabilities = next(payload for _, path, payload in commands if path == "/session")["capabilities"]["alwaysMatch"]
    assert capabilities["acceptInsecureCerts"] is False
    arguments = capabilities["goog:chromeOptions"]["args"]
    assert "--user-data-dir=" + str(tmp_path / "private-profile") in arguments
    assert not any("ignore-certificate" in argument or "no-sandbox" in argument for argument in arguments)
    browser.close()
    tools.terminate_group.assert_called_once_with(process)


def test_browser_refuses_cross_origin_before_typing_credentials(runner):
    browser = object.__new__(runner.Browser)
    browser.target = "https://synthetic.example.test"
    browser.call = Mock(return_value="https://outside.example.test/auth/login")
    with pytest.raises(runner.AcceptanceError, match="browser_left_expected_origin"):
        browser.fill("#local-password", "synthetic-password-only")
    browser.call.assert_called_once_with("GET", "/url")


@pytest.mark.parametrize("empty", [True, False])
def test_fill_skips_empty_clear_and_verifies_focused_input_value(runner, empty):
    browser = object.__new__(runner.Browser)
    browser.element = Mock(return_value="synthetic-element")
    browser.execute = Mock(side_effect=[{"ready": True, "empty": empty}] + ([True] if not empty else []) + [True])
    browser.call = Mock()
    browser.fill("#local-password", "synthetic-password-only")
    calls = [(call.args[0], call.args[1]) for call in browser.call.call_args_list]
    assert calls == ([] if empty else [("POST", "/element/synthetic-element/clear")]) + [
        ("POST", "/element/synthetic-element/value")]
    assert "document.activeElement === input" in browser.execute.call_args_list[0].args[0]
    assert browser.execute.call_args.args[1:] == ({runner.ELEMENT: "synthetic-element"}, "synthetic-password-only")


@pytest.mark.parametrize("state,results,code", [
    ({"ready": False, "empty": True}, [], "browser_input_not_ready"),
    ({"ready": True, "empty": False}, [False], "browser_input_not_ready"),
    ({"ready": True, "empty": True}, [False], "browser_input_value_mismatch"),
])
def test_fill_refuses_unready_or_inexact_control_without_retry(runner, state, results, code):
    browser = object.__new__(runner.Browser)
    browser.element = Mock(return_value="synthetic-element")
    browser.execute = Mock(side_effect=[state, *results])
    browser.call = Mock()
    with pytest.raises(runner.AcceptanceError, match=code):
        browser.fill("#local-password", "synthetic-password-only")
    assert browser.call.call_count <= 1


def test_fill_preserves_clear_error_without_fallback_typing(runner):
    browser = object.__new__(runner.Browser)
    browser.element = Mock(return_value="synthetic-element")
    browser.execute = Mock(return_value={"ready": True, "empty": False})
    browser.call = Mock(side_effect=runner.BrowserCommandError("invalid element state", "POST", "/session/synthetic/element/synthetic/clear"))
    with pytest.raises(runner.BrowserCommandError) as failure:
        browser.fill("#local-password", "synthetic-password-only")
    assert failure.value.diagnostic["operation"] == "element_clear"
    browser.call.assert_called_once_with("POST", "/element/synthetic-element/clear", {})


@pytest.mark.parametrize("error,expected", [("invalid element state", "invalid element state"),
    ("unknown error", "unknown error"), ("Synthetic private account/path details", "unrecognized_error")])
def test_http_webdriver_errors_keep_only_fixed_code_method_and_operation(runner, error, expected):
    browser = object.__new__(runner.Browser)
    browser.endpoint = "http://127.0.0.1:12345"
    body = json.dumps({"value": {"error": error, "message": "Synthetic private password and account details",
                                "stacktrace": "Synthetic private path"}}).encode()
    response = runner.urllib.error.HTTPError(browser.endpoint, 500, "Synthetic private reason", {}, io.BytesIO(body))
    browser.opener = Mock()
    browser.opener.open.side_effect = response
    with pytest.raises(runner.BrowserCommandError) as failure:
        browser.command("POST", "/session/synthetic-private-session/element/synthetic-private-element/clear", {})
    assert failure.value.diagnostic == {"error": expected, "method": "POST", "operation": "element_clear"}
    assert "private" not in json.dumps(failure.value.diagnostic)
    assert str(failure.value) == "browser_command_failed"


@pytest.mark.parametrize("body,code", [(b"Synthetic non-JSON response", "invalid_response"),
    (b"x" * (4 * 1024 * 1024 + 1), "response_too_large")])
def test_webdriver_error_payloads_are_bounded_and_never_echoed(runner, body, code):
    browser = object.__new__(runner.Browser)
    browser.endpoint = "http://127.0.0.1:12345"
    browser.opener = Mock()
    browser.opener.open.side_effect = runner.urllib.error.HTTPError(browser.endpoint, 500, "private", {}, io.BytesIO(body))
    with pytest.raises(runner.BrowserCommandError) as failure:
        browser.command("POST", "/session/synthetic/element/synthetic/value", {"text": "synthetic-password-only"})
    assert failure.value.diagnostic == {"error": code, "method": "POST", "operation": "element_type"}


def test_wait_does_not_swallow_real_webdriver_failure(runner):
    browser = object.__new__(runner.Browser)
    error = runner.BrowserCommandError("unknown error", "POST", "/session/synthetic/execute/sync")
    predicate = Mock(side_effect=error)
    with pytest.raises(runner.BrowserCommandError) as failure:
        browser.wait(predicate)
    assert failure.value is error
    predicate.assert_called_once_with()


@pytest.mark.parametrize("reverse_choices", [True, False])
def test_registration_and_access_matrix_keep_only_one_reviewer_open(runner, monkeypatch, reverse_choices):
    names, display = ["rb-synthetic-aaaaaaaaaaaa-a", "rb-synthetic-aaaaaaaaaaaa-b"], "Synthetic CPU Reviewer"
    options = [{"value": f"synthetic-{number}", "label": f"{display} ({name})"} for number, name in enumerate(names)]
    if reverse_choices:
        options.reverse()
    selected_name = names[0] if reverse_choices else names[1]
    events, opened, active = [], [], []
    revoked = False
    admin = Mock()
    admin.execute.side_effect = lambda script, *_: options if "#new-member option" in script else True
    admin.wait.side_effect = lambda predicate: predicate()
    def click(selector):
        nonlocal revoked
        if selector.startswith(".case-team-list"):
            revoked = True
    admin.click.side_effect = click
    class Reviewer:
        name = None
        def go(self, _path):
            pass
        def fetch(self, path):
            assert self in active
            status = 200 if self.name == selected_name and not revoked else 404
            events.append((self, "fetch", status, path))
            return {"status": status}
        def close(self):
            events.append((self, "close"))
            active.remove(self)
    def open_browser():
        assert not active, "The unassigned session must close before the selected session opens"
        browser = Reviewer()
        opened.append(browser)
        active.append(browser)
        return browser
    def login(browser, name, _password):
        assert browser.name is None, "The revocation check must not sign in again"
        browser.name = name
        events.append((browser, "login", name))
    monkeypatch.setattr(runner, "login", login)
    runner.create_reviewers(admin, open_browser, names, "synthetic-password-only", display)
    assert len(opened) == 2 and {browser.name for browser in opened} == set(names) and not active
    phases = []
    def phase(name, function):
        function()
        phases.append(name)
    runner.check_team_access(admin, open_browser, "/matters/synthetic", names, "synthetic-password-only", display, phase)
    assert phases == ["named_grant", "unassigned_denial", "live_revocation"]
    assert len(opened) == 4 and not active
    assert opened[2].name != selected_name and opened[3].name == selected_name
    assert [event[2] for event in events if event[0] is opened[2] and event[1] == "fetch"] == [404, 404]
    assert [event[2] for event in events if event[0] is opened[3] and event[1] == "fetch"] == [200, 200, 404, 404]
    assert sum(event[1] == "login" for event in events) == 4


@pytest.mark.parametrize("matters,accounts,allow,accepted", [
    ([], ["synthetic.admin"], False, True),
    (["Unrelated synthetic matter"], ["synthetic.admin"], True, False),
    ([], ["synthetic.admin", "unrelated.account"], True, False),
    (["Synthetic CPU acceptance " + "a" * 12], ["synthetic.admin", "rb-synthetic-" + "a" * 12 + "-a"], True, True),
    (["Synthetic CPU acceptance " + "a" * 12], ["synthetic.admin"], False, False),
])
def test_node_gate_refuses_unknown_populated_state(runner, matters, accounts, allow, accepted):
    browser = Mock()
    browser.execute.side_effect = [{"matters": matters, "recognized": True, "recovery": False}, True, accounts]
    if accepted:
        runner.check_node(browser, "synthetic.admin", allow)
    else:
        with pytest.raises(runner.AcceptanceError, match="populated_node_refused"):
            runner.check_node(browser, "synthetic.admin", allow)
    browser.fill.assert_not_called()
    browser.click.assert_not_called()


@pytest.mark.parametrize("state", [{"recognized": False, "recovery": False, "matters": []},
                                  {"recognized": True, "recovery": True, "matters": []}, None])
def test_node_gate_refuses_unrecognized_admin_or_retained_deletions(runner, state):
    browser = Mock()
    browser.execute.return_value = state
    with pytest.raises(runner.AcceptanceError, match="populated_node_refused"):
        runner.check_node(browser, "synthetic.admin", True)
    assert browser.go.call_count == 1


def test_export_requires_the_saved_note_and_bounds_contents(runner):
    def result(text):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("notebook/matter-notebook.md", text)
        return {"status": 200, "content_type": "application/zip", "data": base64.b64encode(data.getvalue()).decode()}
    runner.check_export(result("battery count difference\n" + runner.NOTE))
    with pytest.raises(runner.AcceptanceError, match="saved_note_missing_from_export"):
        runner.check_export(result("A different synthetic note"))
    with pytest.raises(runner.AcceptanceError):
        runner.check_export({"status": 200, "content_type": "text/html", "data": ""})


def test_missing_acknowledgment_refuses_every_network_and_mutation(runner, monkeypatch, capsys):
    network = Mock(side_effect=AssertionError("Network must not run"))
    monkeypatch.setattr(runner, "tls_health", network)
    assert runner.main(["--url", "https://synthetic.example.test", "--admin-username", "synthetic.admin"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["failure_code"] == "synthetic_acknowledgment_required"
    assert output["phases"]["inputs"] == "failed"
    assert output["passed"] is False
    network.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeError("Synthetic private exception details"),
                                     "custom-acceptance-error"])
def test_failures_emit_only_whitelisted_receipt_fields(runner, monkeypatch, capsys, tmp_path, failure):
    monkeypatch.setattr(runner.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(runner, "fixture_paths", lambda *_: [])
    monkeypatch.setattr(runner.getpass, "getpass", lambda _: "synthetic-password-not-for-output")
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **kw: "a" * 40)
    error = runner.AcceptanceError("Synthetic private exception details") if isinstance(failure, str) else failure
    monkeypatch.setattr(runner, "tls_health", Mock(side_effect=error))
    assert runner.main(["--url", "https://synthetic.example.test:8443", "--admin-username", "synthetic.admin",
        "--expected-release-id", "0.1.0-alpha.2-" + "a" * 12, "--acknowledge-synthetic-evaluation"]) == 1
    rendered = capsys.readouterr().out
    output = json.loads(rendered)
    assert output["failure_code"] == "acceptance_interrupted_or_unavailable"
    assert output["phases"]["tls_and_release"] == "failed"
    assert output["passed"] is False
    assert all(value not in rendered for value in ("exception details", "synthetic.example.test", "synthetic.admin", "synthetic-password-not-for-output"))
    assert set(output) <= {"format_version", "synthetic_evaluation_acknowledged", "passed", "phases", "counts",
                          "runner_commit", "runner_working_tree_clean", "expected_release_id", "observed_release_id", "failure_code",
                          "phase_seconds", "first_export_seconds"}


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_cleans_private_profiles_and_detached_browser_groups(runner, tmp_path, signum):
    harness = tmp_path / "interrupt-runner.py"
    state_file = tmp_path / "synthetic-state.json"
    harness.write_text('''import importlib.util, json, os, subprocess, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("acceptance", sys.argv[1])
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.os.geteuid = lambda: 1000
runner.fixture_paths = lambda *_: []
runner.getpass.getpass = lambda _: "synthetic-password-only"
runner.tls_health = lambda _target, _certificate, expected: expected
tools = runner.browser_tools()
tools.host_platform = lambda: "linux64"
tools.install_browser = lambda *a: (Path("synthetic-chrome"), Path("synthetic-driver"), "1.2.3.4")
runner.browser_tools = lambda: tools
instances = []
class SyntheticBrowser(runner.Browser):
    def __init__(self, _chrome, _driver, profile, environment, target, tools):
        self.target, self.tools, self.session = target, tools, "synthetic-session"
        profile.mkdir()
        (profile / "synthetic-cookie").write_text("synthetic-private-test-state")
        self.profile = profile
        self.process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
        instances.append(self)
    def call(self, *_args):
        raise AssertionError("Interrupted cleanup must terminate without a WebDriver timeout")
runner.Browser = SyntheticBrowser
def pause(_admin, open_browser, *_args):
    open_browser()
    Path(sys.argv[2]).write_text(json.dumps({"pids": [item.process.pid for item in instances],
        "scratch": str(instances[0].profile.parent)}))
    time.sleep(120)
runner.run_journey = pause
raise SystemExit(runner.main(["--url", "https://synthetic.example.test", "--admin-username", "synthetic.admin",
    "--expected-release-id", "0.1.0-alpha.2-" + "a" * 12, "--acknowledge-synthetic-evaluation"]))
''')
    child = subprocess.Popen([sys.executable, str(harness), str(Path(runner.__file__)), str(state_file)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    state = None
    try:
        deadline = time.monotonic() + 10
        while not state_file.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state_file.exists(), "Synthetic harness did not reach the interruption point"
        state = json.loads(state_file.read_text())
        assert len(state["pids"]) == 2
        child.send_signal(signum)
        output, errors = child.communicate(timeout=10)
        assert child.returncode == 1 and errors == ""
        receipt = json.loads(output)
        assert receipt["passed"] is False
        assert receipt["failure_code"] == "acceptance_interrupted_or_unavailable"
        assert not Path(state["scratch"]).exists()
        for pid in state["pids"]:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        if state:
            for pid in state["pids"]:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_phase_timings_use_monotonic_clock_and_first_verified_export(runner, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(runner.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(runner, "fixture_paths", lambda *_: [])
    monkeypatch.setattr(runner.getpass, "getpass", lambda _: "synthetic-password-only")
    monkeypatch.setattr(runner, "tls_health", lambda _target, _ca, expected: expected)
    tools = Mock()
    tools.host_platform.return_value = "linux64"
    tools.install_browser.return_value = (tmp_path / "chrome", tmp_path / "driver", "1.2.3.4")
    monkeypatch.setattr(runner, "browser_tools", lambda: tools)
    browser_constructor = Mock()
    monkeypatch.setattr(runner, "Browser", browser_constructor)
    def journey(_admin, _open_browser, _username, _password, _fixtures, _previous, phase):
        assert browser_constructor.call_count == 1
        for name in runner.PHASES[3:]:
            phase(name, lambda: None)
    monkeypatch.setattr(runner, "run_journey", journey)
    values = iter(range(200))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(values))
    assert runner.main(["--url", "https://synthetic.example.test", "--admin-username", "synthetic.admin",
        "--expected-release-id", "0.1.0-alpha.2-" + "a" * 12, "--acknowledge-synthetic-evaluation"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert set(receipt["phase_seconds"]) == set(runner.PHASES)
    assert all(value == 1 for value in receipt["phase_seconds"].values())
    assert receipt["first_export_seconds"] == 26
    assert receipt["passed"] is True


def test_receipt_contains_only_sanitized_webdriver_diagnostics(runner, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(runner.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(runner, "fixture_paths", lambda *_: [])
    monkeypatch.setattr(runner.getpass, "getpass", lambda _: "synthetic-password-only")
    monkeypatch.setattr(runner, "tls_health", lambda _target, _ca, expected: expected)
    tools = Mock()
    tools.host_platform.return_value = "linux64"
    tools.install_browser.return_value = (tmp_path / "chrome", tmp_path / "driver", "1.2.3.4")
    monkeypatch.setattr(runner, "browser_tools", lambda: tools)
    error = runner.BrowserCommandError("Synthetic private driver error", "POST", "/session/private-session/element/private-element/clear")
    monkeypatch.setattr(runner, "Browser", Mock(side_effect=error))
    assert runner.main(["--url", "https://synthetic.example.test", "--admin-username", "synthetic.admin",
        "--expected-release-id", "0.1.0-alpha.2-" + "a" * 12, "--acknowledge-synthetic-evaluation"]) == 1
    rendered = capsys.readouterr().out
    receipt = json.loads(rendered)
    assert receipt["phases"]["browser"] == "failed"
    assert receipt["webdriver"] == {"error": "unrecognized_error", "method": "POST", "operation": "element_clear"}
    assert "private" not in rendered and "synthetic-password-only" not in rendered
