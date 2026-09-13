#!/usr/bin/env python3
"""Create short-lived localhost TLS material for an isolated synthetic evaluation."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHILD = "import os, sys; os.fchdir(int(sys.argv[1])); os.execv(sys.argv[2], sys.argv[2:])"


def _open_private_output(output: Path) -> int:
    """Create output through a held, validated no-follow directory chain."""
    if ".." in output.parts:
        raise ValueError("Certificate output must not contain parent-directory traversal.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for component in output.parts[1:-1]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            if (metadata.st_uid not in {0, os.geteuid()}
                    or metadata.st_mode & 0o022 and not metadata.st_mode & stat.S_ISVTX):
                raise ValueError("Certificate directory ancestry must be root/account-owned and protected from other writers.")
        parent = os.fstat(descriptor)
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
            raise ValueError("Use an account-owned parent directory that others cannot write.")
        os.mkdir(output.name, mode=0o700, dir_fd=descriptor)
        result = os.open(output.name, flags, dir_fd=descriptor)
        metadata = os.fstat(result)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            os.close(result)
            raise ValueError("The new certificate directory changed before it could be opened.")
        return result
    except OSError as exc:
        raise ValueError("Use an existing protected parent chain without symbolic links and a new output directory.") from exc
    finally:
        os.close(descriptor)


def create_certificate(output: Path) -> str:
    executable = shutil.which("openssl")
    if executable is None:
        raise ValueError("OpenSSL is required; install it and rerun.")
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new certificate directory; existing files were preserved.")
    if not output.parent.is_dir():
        raise ValueError("Create the parent directory first, outside the source checkout and node root.")
    if output.resolve().is_relative_to(ROOT):
        raise ValueError("Certificate keys must stay outside the source checkout.")
    # All writes use a pinned directory, even if a trusted account renames an
    # ancestor after validation. OpenSSL's child changes cwd through that FD;
    # passing its pathname as cwd would follow a replacement symlink.
    directory = _open_private_output(output)
    old_mask = os.umask(0o077)
    try:
        def openssl(*args: str) -> str:
            return subprocess.run([sys.executable, "-I", "-S", "-c", CHILD,
                                   str(directory), executable, *args],
                                  pass_fds=(directory,), check=True, capture_output=True,
                                  text=True, timeout=60).stdout

        openssl("req", "-x509", "-newkey", "rsa:3072", "-sha256", "-nodes",
                "-days", "30", "-subj", "/CN=RecordBench synthetic evaluation CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-keyout", ".ca.key", "-out", "ca.crt")
        openssl("req", "-new", "-newkey", "rsa:3072", "-sha256", "-nodes",
                "-subj", "/CN=localhost", "-keyout", "tls.key", "-out", ".localhost.csr")
        extension_fd = os.open(".localhost.ext", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600, dir_fd=directory)
        with os.fdopen(extension_fd, "w", encoding="ascii") as extensions:
            extensions.write("basicConstraints=critical,CA:FALSE\n"
                             "keyUsage=critical,digitalSignature,keyEncipherment\n"
                             "extendedKeyUsage=serverAuth\n"
                             "subjectAltName=DNS:localhost,IP:127.0.0.1\n")
        openssl("x509", "-req", "-in", ".localhost.csr", "-CA", "ca.crt", "-CAkey", ".ca.key",
                "-set_serial", "0x" + os.urandom(16).hex(), "-days", "30", "-sha256",
                "-extfile", ".localhost.ext", "-out", "tls.crt")
        openssl("verify", "-CAfile", "ca.crt", "-purpose", "sslserver",
                "-verify_hostname", "localhost", "tls.crt")
        fingerprint = openssl("x509", "-in", "ca.crt", "-noout", "-fingerprint", "-sha256").strip()
        current, pinned = output.stat(follow_symlinks=False), os.fstat(directory)
        if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise ValueError("Certificate output moved during generation; no success is claimed. Inspect the retained private directory.")
        return fingerprint
    finally:
        for name in (".ca.key", ".localhost.csr", ".localhost.ext"):
            try:
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)
        os.umask(old_mask)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="new private directory outside the source checkout and node root")
    args = parser.parse_args(argv)
    try:
        fingerprint = create_certificate(args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else (
            "Certificate creation failed. Preserve the partial directory for diagnosis; "
            "correct the cause and choose a new --output directory.")
        print(message, file=sys.stderr)
        return 1
    print("Created ca.crt (public trust certificate), tls.crt and tls.key (private server key).")
    print("Valid for 30 days, localhost/127.0.0.1 only. The CA signing key was discarded.")
    print("Trust ca.crt only in a separate synthetic evaluation browser profile.")
    print("Compare this public CA fingerprint after copying it over verified SSH:")
    print(fingerprint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
