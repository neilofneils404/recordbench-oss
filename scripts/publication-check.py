#!/usr/bin/env python3
"""Fail closed when an OSS candidate contains deployment or secret residue."""
from __future__ import annotations

import argparse
import io
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {".git", ".venv", ".pytest_cache", "__pycache__", "node_modules"}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".cer",
    ".crt",
    ".der",
    ".jks",
    ".key",
    ".keytab",
    ".keystore",
    ".p12",
    ".pfx",
    ".pem",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "secrets.json",
}
ALLOWED_DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "2001:db8::/32",
    )
)
IPV4 = re.compile(rb"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
IPV6 = re.compile(
    rb"(?<![A-Za-z0-9_:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}"
    rb"(?![A-Za-z0-9_:])"
)
EMAIL = re.compile(
    rb"(?i)(?<![a-z0-9._%+-])[a-z0-9._%+-]{1,64}@([a-z0-9.-]{1,253}\.[a-z]{2,63})(?![a-z0-9.-])"
)
HOME_PATH = re.compile(rb"(?i)/(?:home|users)/([A-Za-z0-9._-]{1,64})/")
WINDOWS_HOME_PATH = re.compile(
    rb"(?i)(?:[A-Z]:)?\\(?:Users|Documents[ ]and[ ]Settings)\\([^\\/\r\n]{1,128})\\"
)
INTERNAL_FQDN = re.compile(
    rb"(?i)(?<![A-Za-z0-9_-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    rb"(?:corp|internal|intranet|lan|local|localdomain|pvt)(?![A-Za-z0-9_.(-])"
)
QUOTED_SECRET_ASSIGNMENT = re.compile(
    rb"(?i)(?:access[_-]?token|api[_-]?key|client[_-]?secret|password|passwd|secret|token)"
    rb"\s*[:=]\s*(['\"])([A-Za-z0-9_./+%@=:-]{20,4096})\1"
)
UNQUOTED_SECRET_ASSIGNMENT = re.compile(
    rb"(?im)(?:access[_-]?token|api[_-]?key|client[_-]?secret|password|passwd|secret|token)"
    rb"\s*[:=]\s*([A-Za-z0-9_./+%@=:-]{20,4096})[ \t]*(?:[#;][^\r\n]*)?$"
)
BEARER_TOKEN = re.compile(
    rb"(?i)\bbearer[ \t]+([A-Za-z0-9._~+/=-]{20,4096})(?![A-Za-z0-9._~+/=-])"
)
PEM_MARKERS = tuple(
    (rule, b"-----BEGIN " + label + b"-----")
    for rule, label in (
        ("private-key-material", b"PRIVATE KEY"),
        ("private-key-material", b"RSA PRIVATE KEY"),
        ("private-key-material", b"EC PRIVATE KEY"),
        ("private-key-material", b"OPENSSH PRIVATE KEY"),
        ("private-key-material", b"ENCRYPTED PRIVATE KEY"),
        ("certificate-material", b"CERTIFICATE"),
        ("certificate-material", b"X509 CERTIFICATE"),
        ("certificate-material", b"CERTIFICATE REQUEST"),
        ("certificate-material", b"NEW CERTIFICATE REQUEST"),
        ("certificate-material", b"PKCS7"),
    )
)
SAFE_LITERAL_PREFIXES = (
    b"synthetic",
    b"example",
    b"placeholder",
    b"change-me",
    b"changeme",
    b"not-a-real",
    b"dry-run",
    b"dummy",
    b"fake-",
    b"fixture-",
    b"test-",
)
SAFE_UNQUOTED_VALUE_PREFIXES = (
    b"/",
    b"./",
    b"../",
    b"self.",
    b"settings.",
    b"config.",
    b"options.",
    b"args.",
)
MEDIA_SUFFIXES = {
    ".avi",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
    ".wmv",
}
MAX_DERIVED_SCAN_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5_000


@dataclass(frozen=True)
class Finding:
    location: str
    rule: str


def _candidate_files(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in IGNORED_DIRECTORIES)
        base = Path(directory)
        for name in sorted(files):
            if name in IGNORED_DIRECTORIES:
                continue
            yield base / name


def _safe_example_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return any(address in network for network in ALLOWED_DOCUMENTATION_NETWORKS)


def _scan_bytes(data: bytes, *, location: str, deny: tuple[bytes, ...]) -> list[Finding]:
    findings: list[Finding] = []
    lowered = data.lower()
    pem_rules: set[str] = set()
    for rule, marker in PEM_MARKERS:
        if marker.lower() in lowered:
            pem_rules.add(rule)
    findings.extend(Finding(location, rule) for rule in sorted(pem_rules))
    for raw in (*IPV4.findall(data), *IPV6.findall(data)):
        try:
            address = ipaddress.ip_address(raw.decode("ascii"))
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or _safe_example_ip(address):
            continue
        if address.is_private or address.is_link_local:
            findings.append(Finding(location, "private-network-address"))
            break
    for match in EMAIL.finditer(data):
        domain = match.group(1).decode("ascii", "ignore").casefold()
        if domain not in {
            "example.com",
            "example.net",
            "example.org",
            "example.test",
            "example.invalid",
            "users.noreply.github.com",
        } and not domain.endswith(
            ".example.test"
        ):
            findings.append(Finding(location, "non-example-email-address"))
            break
    for match in HOME_PATH.finditer(data):
        owner = match.group(1).decode("ascii", "ignore").casefold()
        if owner not in {"recordbench", "user", "example"}:
            findings.append(Finding(location, "personal-home-path"))
            break
    for match in WINDOWS_HOME_PATH.finditer(data):
        owner = match.group(1).decode("ascii", "ignore").casefold()
        if owner not in {"default", "example", "public", "recordbench", "user"}:
            findings.append(Finding(location, "personal-home-path"))
            break
    if INTERNAL_FQDN.search(data):
        findings.append(Finding(location, "internal-fqdn"))
    quoted_values = (
        match.group(2) for match in QUOTED_SECRET_ASSIGNMENT.finditer(data)
    )
    unquoted_values = (
        match.group(1) for match in UNQUOTED_SECRET_ASSIGNMENT.finditer(data)
    )
    for literal in quoted_values:
        if not literal.lower().startswith(SAFE_LITERAL_PREFIXES):
            findings.append(Finding(location, "literal-secret-shaped-value"))
            break
    else:
        for literal in unquoted_values:
            lowered_literal = literal.lower()
            if lowered_literal.startswith(
                (*SAFE_LITERAL_PREFIXES, *SAFE_UNQUOTED_VALUE_PREFIXES)
            ):
                continue
            findings.append(Finding(location, "literal-secret-shaped-value"))
            break
    for match in BEARER_TOKEN.finditer(data):
        literal = match.group(1).lower()
        if not literal.startswith(SAFE_LITERAL_PREFIXES):
            findings.append(Finding(location, "bearer-token"))
            break
    for term in deny:
        if term and term.lower() in lowered:
            findings.append(Finding(location, "operator-deny-term"))
            break
    return findings


def _scan_pdf(data: bytes, *, location: str, deny: tuple[bytes, ...]) -> list[Finding]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return [Finding(location, "encrypted-document")]
        parts: list[str] = []
        if reader.metadata is not None:
            parts.extend(str(value) for value in reader.metadata.values() if value)
        size = sum(len(value.encode("utf-8", errors="replace")) for value in parts)
        for page in reader.pages:
            value = page.extract_text() or ""
            size += len(value.encode("utf-8", errors="replace"))
            if size > MAX_DERIVED_SCAN_BYTES:
                return [Finding(location, "expanded-document-too-large")]
            parts.append(value)
    except Exception:
        return [Finding(location, "document-inspection-failed")]
    return _scan_bytes(
        "\n".join(parts).encode("utf-8", errors="replace"),
        location=f"{location}#pdf-content",
        deny=deny,
    )


def _scan_media(
    data: bytes,
    *,
    name: str,
    location: str,
    deny: tuple[bytes, ...],
) -> list[Finding]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return [Finding(location, "media-inspection-unavailable")]
    try:
        with tempfile.NamedTemporaryFile(
            prefix="recordbench-publication-",
            suffix=Path(name).suffix.casefold(),
        ) as handle:
            handle.write(data)
            handle.flush()
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format_tags:stream_tags",
                    "-of",
                    "json",
                    handle.name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
    except (OSError, subprocess.TimeoutExpired):
        return [Finding(location, "media-inspection-failed")]
    if result.returncode != 0 or len(result.stdout) > MAX_DERIVED_SCAN_BYTES:
        return [Finding(location, "media-inspection-failed")]
    try:
        json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [Finding(location, "media-inspection-failed")]
    return _scan_bytes(
        result.stdout,
        location=f"{location}#media-metadata",
        deny=deny,
    )


def _scan_archive(data: bytes, *, location: str, deny: tuple[bytes, ...]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                return [Finding(location, "archive-member-limit")]
            expanded = 0
            for index, member in enumerate(members, start=1):
                member_location = f"{location}!member[{index}]"
                findings.extend(
                    _scan_bytes(
                        member.filename.encode("utf-8", errors="surrogateescape"),
                        location=f"{member_location}-name",
                        deny=deny,
                    )
                )
                member_path = PurePosixPath(member.filename)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or "\\" in member.filename
                    or "\x00" in member.filename
                ):
                    findings.append(Finding(member_location, "unsafe-archive-member-name"))
                member_mode = member.external_attr >> 16
                if stat.S_ISLNK(member_mode):
                    findings.append(Finding(member_location, "symbolic-link"))
                if member.is_dir():
                    continue
                if (
                    member_path.name in FORBIDDEN_NAMES
                    or member_path.suffix.casefold() in FORBIDDEN_SUFFIXES
                ):
                    findings.append(Finding(member_location, "runtime-or-credential-file"))
                    continue
                if member.flag_bits & 0x1:
                    return [Finding(location, "encrypted-document")]
                expanded += member.file_size
                if (
                    member.file_size > MAX_DERIVED_SCAN_BYTES
                    or expanded > MAX_DERIVED_SCAN_BYTES
                ):
                    return [Finding(location, "expanded-document-too-large")]
                findings.extend(
                    _scan_bytes(
                        archive.read(member),
                        location=member_location,
                        deny=deny,
                    )
                )
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return [Finding(location, "document-inspection-failed")]
    return findings


def _scan_content(
    data: bytes,
    *,
    name: str,
    location: str,
    deny: tuple[bytes, ...],
) -> list[Finding]:
    findings = _scan_bytes(data, location=location, deny=deny)
    if Path(name).suffix.casefold() == ".pdf":
        findings.extend(_scan_pdf(data, location=location, deny=deny))
    elif zipfile.is_zipfile(io.BytesIO(data)):
        findings.extend(_scan_archive(data, location=location, deny=deny))
    elif Path(name).suffix.casefold() in MEDIA_SUFFIXES:
        findings.extend(
            _scan_media(data, name=name, location=location, deny=deny)
        )
    return findings


def scan_tree(root: Path, deny: tuple[bytes, ...]) -> list[Finding]:
    findings: list[Finding] = []
    for index, path in enumerate(_candidate_files(root), start=1):
        relative = path.relative_to(root).as_posix()
        name_findings = _scan_bytes(
            relative.encode("utf-8", errors="surrogateescape"),
            location=f"tree-entry[{index}]-name",
            deny=deny,
        )
        findings.extend(name_findings)
        location = relative if not name_findings else f"tree-entry[{index}]"
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            findings.append(Finding(location, "symbolic-link"))
            continue
        if not stat.S_ISREG(metadata.st_mode):
            findings.append(Finding(location, "non-regular-file"))
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            findings.append(Finding(location, "runtime-or-credential-file"))
            continue
        if metadata.st_size > 25 * 1024 * 1024:
            findings.append(Finding(location, "unexpected-large-file"))
            continue
        try:
            data = path.read_bytes()
        except OSError:
            findings.append(Finding(location, "unreadable-file"))
            continue
        findings.extend(
            _scan_content(data, name=relative, location=location, deny=deny)
        )
    return findings


def scan_history(root: Path, deny: tuple[bytes, ...]) -> list[Finding]:
    if not (root / ".git").exists():
        return [Finding(".git", "git-history-unavailable")]
    check = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode != 0:
        return []
    revisions = subprocess.run(
        ["git", "rev-list", "--all"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if revisions.returncode != 0:
        return [Finding("git-history", "history-scan-failed")]
    findings: list[Finding] = []
    scanned: set[tuple[str, str]] = set()
    for raw_commit in revisions.stdout.splitlines():
        commit = raw_commit.decode("ascii", errors="strict")
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "--long", commit],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if tree.returncode != 0:
            findings.append(Finding(f"git:{commit[:12]}", "history-scan-failed"))
            continue
        for index, entry in enumerate(tree.stdout.split(b"\0"), start=1):
            if not entry:
                continue
            try:
                metadata, raw_name = entry.split(b"\t", 1)
                mode, kind, raw_oid, raw_size = metadata.split(b" ", 3)
                name = raw_name.decode("utf-8", errors="surrogateescape")
                oid = raw_oid.decode("ascii")
                size = int(raw_size)
            except (ValueError, UnicodeError):
                findings.append(Finding(f"git:{commit[:12]}", "history-scan-failed"))
                continue
            name_findings = _scan_bytes(
                raw_name,
                location=f"git:{commit[:12]}:entry[{index}]-name",
                deny=deny,
            )
            findings.extend(name_findings)
            location = (
                f"git:{commit[:12]}:{name}"
                if not name_findings
                else f"git:{commit[:12]}:entry[{index}]"
            )
            if mode == b"120000":
                findings.append(Finding(location, "symbolic-link"))
                continue
            if kind != b"blob":
                findings.append(Finding(location, "non-regular-file"))
                continue
            path = Path(name)
            if path.name in FORBIDDEN_NAMES or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
                findings.append(Finding(location, "runtime-or-credential-file"))
                continue
            if size > 25 * 1024 * 1024:
                findings.append(Finding(location, "unexpected-large-file"))
                continue
            identity = (oid, name)
            if identity in scanned:
                continue
            scanned.add(identity)
            blob = subprocess.run(
                ["git", "cat-file", "blob", oid],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if blob.returncode != 0:
                findings.append(Finding(location, "history-scan-failed"))
                continue
            findings.extend(
                _scan_content(blob.stdout, name=name, location=location, deny=deny)
            )
    metadata = subprocess.run(
        [
            "git",
            "log",
            "--format=%an%x00%ae%x00%cn%x00%ce%x00%B%x00",
            "--all",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if metadata.returncode != 0:
        findings.append(Finding("git-metadata", "history-scan-failed"))
    else:
        findings.extend(
            _scan_bytes(metadata.stdout, location="git-metadata", deny=deny)
        )
    refs = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname)%00%(taggername)%00%(taggeremail)%00%(contents)%00",
            "refs/heads",
            "refs/tags",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if refs.returncode != 0:
        findings.append(Finding("git-refs", "history-scan-failed"))
    else:
        findings.extend(_scan_bytes(refs.stdout, location="git-refs", deny=deny))
    return findings


def _deny_terms(path: Path | None) -> tuple[bytes, ...]:
    if path is None:
        return ()
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("deny-term file is unsafe")
    result = []
    for raw in path.read_bytes().splitlines():
        value = raw.strip()
        if value and not value.startswith(b"#"):
            if len(value) < 3 or len(value) > 512:
                raise RuntimeError("deny-term file contains an invalid entry")
            result.append(value)
    return tuple(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--deny-file", type=Path)
    parser.add_argument("--skip-history", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve(strict=True)
    deny = _deny_terms(args.deny_file.expanduser()) if args.deny_file else ()
    findings = scan_tree(root, deny)
    if not args.skip_history:
        findings.extend(scan_history(root, deny))
    unique = sorted(set(findings), key=lambda item: (item.location, item.rule))
    if unique:
        print("PUBLICATION GATE: BLOCKED", file=sys.stderr)
        for finding in unique:
            print(f"  {finding.rule}: {finding.location}", file=sys.stderr)
        print("No matched secret value was printed.", file=sys.stderr)
        return 1
    print("PUBLICATION GATE: CLEAN")
    if args.skip_history:
        print("Working tree passed generic residue checks; Git history was not scanned.")
    else:
        print("Tree and available Git history passed generic residue checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
