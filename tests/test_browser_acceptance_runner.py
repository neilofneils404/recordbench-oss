"""A browser command exit alone is not evidence that its journey completed."""
import importlib.util
import json
from pathlib import Path
import socket
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/browser-acceptance.py"
spec = importlib.util.spec_from_file_location("browser_acceptance_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def command(body):
    return [sys.executable, "-c", body]


def run(tmp_path, body, *, timeout=5):
    return runner.run_journey(command(body), output=tmp_path / "journey",
        receipt_name="receipt.json", minimum_checks=2, timeout=timeout)


def test_success_requires_complete_fresh_receipt(tmp_path):
    result = run(tmp_path, "from pathlib import Path; "
        "Path('receipt.json').write_text(" + repr(json.dumps({
            "synthetic_only": True, "passed": True, "checks": ["source opened", "export verified"]
        })) + ")")
    assert result["passed"] is True and result["checks"] == 2
    assert (tmp_path / "journey" / "runner.log").exists()


@pytest.mark.parametrize("receipt,exit_code", [
    (None, 0), ("not json", 0),
    ({"synthetic_only": True, "passed": False, "checks": ["one", "two"]}, 0),
    ({"synthetic_only": True, "passed": True, "checks": []}, 0),
    ({"synthetic_only": True, "passed": True, "checks": ["one", "two"]}, 1),
])
def test_missing_failed_incomplete_or_error_results_cannot_pass(tmp_path, receipt, exit_code):
    body = "import sys; from pathlib import Path; "
    if receipt is not None:
        payload = receipt if isinstance(receipt, str) else json.dumps(receipt)
        body += "Path('receipt.json').write_text(" + repr(payload) + "); "
    body += f"sys.exit({exit_code})"
    result = run(tmp_path, body)
    assert result["passed"] is False
    assert result["problem"]


def test_old_pass_is_preserved_but_cannot_authorize_a_new_run(tmp_path):
    output = tmp_path / "journey"
    output.mkdir()
    receipt = output / "receipt.json"
    receipt.write_text('{"synthetic_only":true,"passed":true,"checks":["one","two"]}')
    original = receipt.read_bytes()
    with pytest.raises(FileExistsError):
        run(tmp_path, "raise SystemExit(0)")
    assert receipt.read_bytes() == original


def test_timeout_stops_descendant_listener_and_records_failure(tmp_path):
    child = "import socket; from pathlib import Path; " \
        "s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); " \
        "Path('port').write_text(str(s.getsockname()[1])); s.accept()"
    parent = "import subprocess,sys,time; " \
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    result = run(tmp_path, parent, timeout=3)
    assert result["passed"] is False and result["timed_out"] is True
    port = int((tmp_path / "journey" / "port").read_text())
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_completed_command_also_cleans_its_descendant_listener(tmp_path):
    child = "import socket; from pathlib import Path; " \
        "s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); " \
        "Path('port').write_text(str(s.getsockname()[1])); s.accept()"
    parent = "import subprocess,sys,time; from pathlib import Path; " \
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); " \
        "\nwhile not Path('port').exists(): time.sleep(.01)\n" \
        "Path('receipt.json').write_text(" + repr(json.dumps({
            "synthetic_only": True, "passed": True, "checks": ["one", "two"]
        })) + ")"
    result = run(tmp_path, parent)
    assert result["passed"] is True
    port = int((tmp_path / "journey" / "port").read_text())
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_browser_installer_rejects_corrupt_archives_before_extraction(tmp_path):
    import os
    import subprocess
    commands = tmp_path / "bin"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text("#!/bin/sh\nfor argument do destination=$argument; done\nprintf corrupt > \"$destination\"\n")
    curl.chmod(0o755)
    marker = tmp_path / "extraction-attempted"
    unzip = commands / "unzip"
    unzip.write_text("#!/bin/sh\ntouch \"$EXTRACTION_MARKER\"\n")
    unzip.chmod(0o755)
    destination = tmp_path / "browser"
    result = subprocess.run(["bash", str(SCRIPT.parent / "install-test-browser.sh"), str(destination)],
        env=dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
            EXTRACTION_MARKER=str(marker)), capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "FAILED" in result.stdout
    assert not marker.exists()
