"""Synthetic peer impersonation tests; no application credentials or browser needed."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import urllib.request

import pytest

spec = importlib.util.spec_from_file_location("owned_driver", Path(__file__).parents[1] / "scripts/owned_webdriver.py")
owned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned)

SERVER = '''import socket
with socket.socket() as server:
    server.bind(("127.0.0.1", 0))
    server.listen()
    print(server.getsockname()[1], flush=True)
    connection, _ = server.accept()
    with connection:
        connection.settimeout(5)
        data = connection.recv(65536)
        print(len(data), flush=True)
        if data:
            connection.sendall(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\nOK")
'''


@pytest.mark.parametrize("impostor", [False, True])
def test_only_owned_connected_peer_receives_http_bytes(impostor):
    server = subprocess.Popen([sys.executable, "-u", "-c", SERVER], stdout=subprocess.PIPE, text=True)
    decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        port = int(server.stdout.readline())
        process = decoy if impostor else server
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), owned.OwnedDriverHandler(process))
        request = urllib.request.Request(f"http://127.0.0.1:{port}/session/value", data=b"synthetic-password-only")
        if impostor:
            with pytest.raises(urllib.error.URLError):
                opener.open(request, timeout=5)
        else:
            with opener.open(request, timeout=5) as response:
                assert response.read() == b"OK"
        assert (int(server.stdout.readline()) > 0) is not impostor
    finally:
        for process in (server, decoy):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        server.stdout.close()


@pytest.mark.parametrize("protocol,address", [("tcp", "0100007F"),
    ("tcp6", "0000000000000000FFFF00000100007F")])
@pytest.mark.parametrize("problem", [None, "wrong-inode", "wrong-peer", "not-established"])
def test_linux_matches_established_tuple_and_owned_inode(tmp_path, monkeypatch, protocol, address, problem):
    from types import SimpleNamespace
    import os
    (tmp_path / "fd").mkdir()
    (tmp_path / "net").mkdir()
    os.symlink("socket:[123]", tmp_path / "fd/5")
    for name in ("tcp", "tcp6"):
        (tmp_path / "net" / name).write_text("header\n")
    inode = "456" if problem == "wrong-inode" else "123"
    peer_port = 7001 if problem == "wrong-peer" else 7000
    state = "0A" if problem == "not-established" else "01"
    (tmp_path / "net" / protocol).write_text(
        f"header\n0: {address}:1770 {address}:{peer_port:04X} {state} 0 0 0 0 0 {inode}\n")
    monkeypatch.setattr(owned, "Path", lambda path: tmp_path / str(path).removeprefix("/proc/99/"))
    assert owned._linux_peer_owned(SimpleNamespace(pid=99), ("127.0.0.1", 7000),
        ("127.0.0.1", 6000)) is (problem is None)
