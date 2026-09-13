"""Verify the connected WebDriver peer against the owned child before sending HTTP.

The established TCP tuple cannot be transferred to a replacement listener. Every
new connection is verified; unavailable ownership evidence fails closed. Root and
processes able to inspect/control this user's processes remain trusted.
"""
from __future__ import annotations

import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def _linux_peer_owned(process, local, remote) -> bool:
    descriptors = Path(f"/proc/{process.pid}/fd")
    inodes = set()
    for index, descriptor in enumerate(descriptors.iterdir()):
        if index >= 4096:
            return False
        try:
            link = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        if link.startswith("socket:["):
            inodes.add(link[8:-1])
    for protocol in ("tcp", "tcp6"):
        with Path(f"/proc/{process.pid}/net/{protocol}").open() as table:
            for index, line in enumerate(table):
                if index >= 65536 or len(line) > 4096:
                    return False
                fields = line.split()
                if len(fields) < 10 or fields[3] != "01" or fields[9] not in inodes:
                    continue
                def endpoint(value):
                    address, port = value.split(":")
                    raw = bytes.fromhex(address)
                    raw = b"".join(raw[i:i+4][::-1] if sys.byteorder == "little" else raw[i:i+4]
                                   for i in range(0, len(raw), 4))
                    if len(raw) == 16:
                        if raw[:12] != b"\x00" * 10 + b"\xff\xff":
                            return None
                        raw = raw[12:]
                    return socket.inet_ntop(socket.AF_INET, raw), int(port, 16)
                if endpoint(fields[1]) == remote and endpoint(fields[2]) == local:
                    return True
    return False


def peer_owned(process, connection) -> bool:
    if process.poll() is not None:
        return False
    local, remote = connection.getsockname(), connection.getpeername()
    if sys.platform == "linux":
        owned = _linux_peer_owned(process, local, remote)
    elif sys.platform == "darwin":
        # lsof reads kernel socket ownership; never infer identity from HTTP data.
        result = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", str(process.pid),
                                 "-iTCP", "-sTCP:ESTABLISHED", "-Fn"],
                                capture_output=True, timeout=2, check=False)
        expected = f"n{remote[0]}:{remote[1]}->{local[0]}:{local[1]}".encode()
        owned = result.returncode == 0 and expected in result.stdout.splitlines()
    else:
        owned = False
    return owned and process.poll() is None


class OwnedDriverConnection(http.client.HTTPConnection):
    def __init__(self, host, *, process, **kwargs):
        super().__init__(host, **kwargs)
        self.process = process

    def connect(self):
        super().connect()
        deadline = time.monotonic() + 2
        try:
            while self.process.poll() is None:
                if peer_owned(self.process, self.sock):
                    return
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            raise OSError("WebDriver peer ownership could not be verified")
        except BaseException:
            self.close()
            raise


class OwnedDriverHandler(urllib.request.HTTPHandler):
    def __init__(self, process):
        super().__init__()
        self.process = process

    def http_open(self, request):
        return self.do_open(lambda host, **kw: OwnedDriverConnection(host, process=self.process, **kw), request)
