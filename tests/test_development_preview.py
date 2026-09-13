"""The contributor command exercises a real disposable preview, never a node."""
from __future__ import annotations

from contextlib import contextmanager
import html
import io
import os
from pathlib import Path
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import zipfile

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dev-server.py"


@contextmanager
def running_preview(tmp_path, stop_signal=signal.SIGTERM):
    forbidden = tmp_path / "existing-node"
    forbidden.mkdir()
    sentinel = forbidden / "keep.txt"
    sentinel.write_text("Existing synthetic node must remain untouched.")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    env = dict(os.environ, TMPDIR=str(temporary),
               CASE_INTELLIGENCE_AUTH_MODE="kerberos",
               CASE_INTELLIGENCE_MANAGED_STORAGE_ROOT=str(forbidden),
               CASE_INTELLIGENCE_GENERATOR_URL="http://127.0.0.1:1",
               CASE_INTELLIGENCE_RETRIEVAL_WORKER_URL="http://127.0.0.1:1",
               CASE_INTELLIGENCE_POSTGRES_DSN="host=127.0.0.1 port=1 dbname=synthetic",
               CASE_INTELLIGENCE_STORAGE_RESERVE_GIB="999999")
    process = subprocess.Popen([sys.executable, str(SCRIPT), "--port", "0"],
                               cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    lines = queue.Queue()
    output = []

    def read_output():
        for line in process.stdout:
            output.append(line)
            lines.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 30
        base = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Preview exited before startup: " + "".join(output))
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line.startswith("Preview URL: "):
                base = line.strip().split(" ", 2)[2]
                break
        assert base, "Preview did not print its loopback URL: " + "".join(output)
        assert base.startswith("http://127.0.0.1:")
        with httpx.Client(base_url=base, timeout=5, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get("/health")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("Preview health did not answer: " + "".join(output))
            yield client, response.json()
    finally:
        process.send_signal(stop_signal)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            pytest.fail("Preview did not stop and clean up on SIGTERM")
        reader.join(timeout=2)
        assert "Traceback" not in "".join(output), "".join(output)
        assert sentinel.read_text() == "Existing synthetic node must remain untouched."
        assert list(forbidden.iterdir()) == [sentinel]
        assert not list(temporary.glob("recordbench-synthetic-preview-*"))


def field(body, name):
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]+)"', body)
    assert match, name
    return html.unescape(match.group(1))


def test_preview_ignores_node_settings_and_supports_first_synthetic_review(tmp_path):
    with running_preview(tmp_path) as (client, health):
        assert health["storage"]["reserve_satisfied"] is True
        login = client.get("/auth/login")
        assert "Temporary evaluation access" in login.text
        assert "Taylor Morgan" in login.text
        signed_in = client.post("/auth/login", data={
            "login_challenge": field(login.text, "login_challenge"),
            "identity_subject": "taylor-morgan", "next": "/matters/new",
        })
        assert signed_in.status_code == 303
        new = client.get("/matters/new")
        csrf = field(new.text, "csrf_token")
        created = client.post("/matters", data={
            "name": "Lantern practice", "descriptor": "Synthetic contributor exercise",
            "retention_days": "7", "csrf_token": csrf,
        })
        assert created.status_code == 303, created.text
        prefix = created.headers["location"].removesuffix("/setup")
        fixtures = sorted((ROOT / "examples" / "synthetic-alpha").glob("*.txt"))
        assert len(fixtures) == 2
        uploaded = client.post(prefix + "/uploads", data={"csrf_token": csrf}, files=[
            ("files", (path.name, path.read_bytes(), "text/plain")) for path in fixtures
        ])
        assert uploaded.status_code in (200, 303), uploaded.text
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            results = client.get(prefix + "/exact-search", params={"words": "lantern", "search": "1"})
            if all(path.name in results.text for path in fixtures):
                break
            time.sleep(0.05)
        else:
            pytest.fail("Both practice originals did not become searchable")
        note = "The delivery note counts three batteries; the later inspection counts two."
        saved = client.post(prefix + "/notebook/items", data={
            "csrf_token": csrf, "item_type": "note", "status": "needs_review",
            "title": "Battery count", "body": note,
        })
        assert saved.status_code == 303
        bundle = client.get(prefix + "/export")
        assert bundle.status_code == 200, bundle.text[:200] if bundle.status_code != 200 else ""
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert note in archive.read("notebook/matter-notebook.md").decode("utf-8")


@pytest.mark.parametrize("args", [["--host", "0.0.0.0"], ["--runtime", "/srv/recordbench"],
                                  ["--port", "-1"], ["--port", "65536"]])
def test_unsafe_or_invalid_options_rejected_before_runtime_creation(tmp_path, args):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT,
                            env=dict(os.environ, TMPDIR=str(tmp_path)),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert not list(tmp_path.iterdir())
    assert "Preview URL" not in result.stdout


def test_busy_port_has_actionable_failure_without_creating_runtime(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        result = subprocess.run([sys.executable, str(SCRIPT), "--port", str(listener.getsockname()[1])],
                                env=dict(os.environ, TMPDIR=str(tmp_path)),
                                capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "choose --port 0" in result.stderr
    assert not list(tmp_path.iterdir())


def test_make_dev_honors_selected_python_and_ephemeral_port():
    result = subprocess.run(["make", "-n", "dev", "PYTHON=/synthetic environment/bin/python", "DEV_PORT=0"],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    assert '"/synthetic environment/bin/python" scripts/dev-server.py --port "0"' in result.stdout


def test_ctrl_c_stops_workers_and_removes_temporary_runtime(tmp_path):
    with running_preview(tmp_path, stop_signal=signal.SIGINT) as (client, _):
        assert client.get("/auth/login").status_code == 200


def test_sigterm_during_application_construction_removes_temporary_state(tmp_path):
    marker = tmp_path / "constructing"
    # Pause inside construction after its first write. This catches the earlier
    # window before Uvicorn's serving-time signal handling was installed.
    program = """
import pathlib, runpy, sys, time, types
module = types.ModuleType('case_intelligence.workbench')
marker = pathlib.Path(sys.argv[2])
def construct(runtime, **kwargs):
    runtime.mkdir()
    (runtime / 'synthetic.txt').write_text('Synthetic incomplete startup')
    marker.touch()
    time.sleep(30)
module.create_workbench_app = construct
sys.modules['case_intelligence.workbench'] = module
script = sys.argv[1]
sys.argv = [script, '--port', '0']
runpy.run_path(script, run_name='__main__')
"""
    process = subprocess.Popen([sys.executable, "-c", program, str(SCRIPT), str(marker)],
                               env=dict(os.environ, TMPDIR=str(tmp_path)),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.05)
        assert marker.exists()
        process.terminate()
        output, error = process.communicate(timeout=5)
        assert process.returncode == 0, error
        assert "Preview URL" not in output
        assert not list(tmp_path.glob("recordbench-synthetic-preview-*"))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
