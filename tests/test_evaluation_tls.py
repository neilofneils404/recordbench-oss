"""Verify the actual evaluation certificate chain, hostname and trust boundary."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
import socket
import ssl
import stat
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluation-tls.py"


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic-tls") / "certificates"
    result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(path)],
                            capture_output=True, text=True, check=True, timeout=90)
    assert "30 days" in result.stdout
    assert "PRIVATE KEY" not in result.stdout
    return path


def test_explicit_ca_leaf_names_expiry_and_private_key_disposal(certificates):
    assert {p.name for p in certificates.iterdir()} == {"ca.crt", "tls.crt", "tls.key"}
    assert stat.S_IMODE(certificates.stat().st_mode) == 0o700
    assert stat.S_IMODE((certificates / "tls.key").stat().st_mode) == 0o600
    ca = subprocess.check_output(["openssl", "x509", "-in", str(certificates / "ca.crt"), "-noout", "-text"], text=True)
    leaf = subprocess.check_output(["openssl", "x509", "-in", str(certificates / "tls.crt"), "-noout", "-text"], text=True)
    assert "CA:TRUE, pathlen:0" in ca
    assert "CA:FALSE" in leaf
    assert "DNS:localhost, IP Address:127.0.0.1" in leaf
    assert "TLS Web Server Authentication" in leaf
    subprocess.run(["openssl", "verify", "-CAfile", str(certificates / "ca.crt"),
                    "-verify_hostname", "localhost", str(certificates / "tls.crt")], check=True, capture_output=True)
    wrong_name = subprocess.run(["openssl", "verify", "-CAfile", str(certificates / "ca.crt"),
                                "-verify_hostname", "unrelated.example.test", str(certificates / "tls.crt")], capture_output=True)
    assert wrong_name.returncode != 0
    # It remains valid tomorrow and expires before day 31.
    for seconds, expected in [(86400, 0), (31 * 86400, 1)]:
        result = subprocess.run(["openssl", "x509", "-in", str(certificates / "tls.crt"),
                                 "-checkend", str(seconds), "-noout"], capture_output=True)
        assert result.returncode == expected


def test_tls_requires_explicit_trust_and_matching_hostname(certificates):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Synthetic localhost transport")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificates / "tls.crt", certificates / "tls.key")
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def connect(context, hostname):
        with socket.create_connection(server.server_address, timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as stream:
                stream.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
                assert b"200 OK" in stream.recv(1024)

    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            connect(ssl.create_default_context(), "localhost")
        trusted = ssl.create_default_context(cafile=str(certificates / "ca.crt"))
        assert trusted.check_hostname is True
        connect(trusted, "localhost")
        with pytest.raises(ssl.SSLCertVerificationError):
            connect(trusted, "unrelated.example.test")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_existing_directory_and_symlink_are_preserved(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("Synthetic retained file")
    link = tmp_path / "link"
    link.symlink_to(existing, target_is_directory=True)
    for path in (existing, link):
        result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(path)], capture_output=True, text=True)
        assert result.returncode == 1
        assert "existing files were preserved" in result.stderr
    assert list(existing.iterdir()) == [marker]
    assert marker.read_text() == "Synthetic retained file"


def test_failed_generation_has_no_success_claim_or_key_in_output(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("evaluation_tls", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/synthetic/openssl")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["openssl"], stderr="synthetic private diagnostic")

    monkeypatch.setattr(module.subprocess, "run", fail)
    output = tmp_path / "failed"
    assert module.main(["--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert "Created" not in captured.out
    assert "synthetic private diagnostic" not in captured.err
    assert "choose a new --output" in captured.err
    assert not list(output.iterdir())


def test_source_checkout_and_writable_parent_rejected_before_key_creation(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("evaluation_tls_boundaries", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(module, "ROOT", checkout)
    with pytest.raises(ValueError, match="outside the source checkout"):
        module.create_certificate(checkout / "keys")
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o700)
    shared.chmod(0o777)
    with pytest.raises(ValueError, match="protected|others cannot write"):
        module.create_certificate(shared / "keys")
    assert not list(checkout.iterdir())
    assert not list(shared.iterdir())


@pytest.mark.parametrize("problem", ["symlink", "writable", "foreign"])
def test_every_ancestor_is_checked_before_openssl(tmp_path, monkeypatch, problem):
    spec = importlib.util.spec_from_file_location("evaluation_tls_ancestry", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ancestor = tmp_path / "ancestor"
    parent = ancestor / "private"
    parent.mkdir(parents=True, mode=0o700)
    output = parent / "keys"
    if problem == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(ancestor, target_is_directory=True)
        output = alias / "private" / "keys"
    elif problem == "writable":
        ancestor.chmod(0o777)
    else:
        inode = ancestor.stat().st_ino
        fstat = module.os.fstat

        def foreign_owner(descriptor):
            result = fstat(descriptor)
            if result.st_ino == inode:
                fields = list(result)
                fields[4] = 100000  # Synthetic different principal; no chown required.
                return module.os.stat_result(fields)
            return result

        monkeypatch.setattr(module.os, "fstat", foreign_owner)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("unsafe path reached OpenSSL"))
    with pytest.raises(ValueError, match="protected|symbolic"):
        module.create_certificate(output)
    assert not (parent / "keys").exists()


def test_ancestor_replacement_cannot_redirect_key_writes(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("evaluation_tls_replacement", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parent, moved, replacement = (tmp_path / name for name in ("parent", "moved", "replacement"))
    parent.mkdir(mode=0o700)
    replacement.mkdir(mode=0o700)
    (replacement / "keys").mkdir(mode=0o700)
    sentinel = replacement / "keys" / "keep.txt"
    sentinel.write_text("Synthetic retained file")
    run = module.subprocess.run
    swapped = False

    def replace_ancestor(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            parent.rename(moved)
            parent.symlink_to(replacement, target_is_directory=True)
            swapped = True
        return run(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", replace_ancestor)
    assert module.main(["--output", str(parent / "keys")]) == 1
    assert "Created" not in capsys.readouterr().out
    assert list((replacement / "keys").iterdir()) == [sentinel]
    assert sentinel.read_text() == "Synthetic retained file"
    assert {p.name for p in (moved / "keys").iterdir()} == {"ca.crt", "tls.crt", "tls.key"}
