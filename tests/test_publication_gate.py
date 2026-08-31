from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from pypdf import PdfWriter


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "recordbench_publication_check", ROOT / "scripts" / "publication-check.py"
)
assert SPEC is not None and SPEC.loader is not None
publication = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publication
SPEC.loader.exec_module(publication)


def test_publication_gate_flags_private_networks_keys_and_personal_paths() -> None:
    data = (
        b"service=" + b"10." + b"23.45.67\n"
        b"path=/" + b"home/specific.operator/runtime\n"
        b"-----BEGIN " + b"PRIVATE KEY-----\n"
    )
    rules = {item.rule for item in publication._scan_bytes(data, location="fixture", deny=())}
    assert rules == {
        "private-network-address",
        "personal-home-path",
        "private-key-material",
    }


def test_publication_gate_allows_loopback_and_documentation_addresses() -> None:
    data = (
        b"127.0.0.1 ::1 192.0.2.10 198.51.100.8 203.0.113.4 2001:db8::8 "
        b"reviewer@example.test /home/recordbench/runtime"
    )
    assert publication._scan_bytes(data, location="fixture", deny=()) == []


def test_publication_gate_flags_generic_identity_and_secret_shapes() -> None:
    data = (
        b"endpoint=https://review." + b"agency." + b"internal/api\n"
        b"operator=C:\\" + b"Users\\Specific.Operator\\workspace\n"
        b"network=fd" + b"00::42\n"
        b"Authorization: Bearer " + b"actual-looking-token-value-123456789\n"
        b"api_key=" + b"actual-looking-api-key-value-12345\n"
        b"-----BEGIN " + b"CERTIFICATE-----\n"
    )
    rules = {item.rule for item in publication._scan_bytes(data, location="fixture", deny=())}
    assert rules == {
        "bearer-token",
        "certificate-material",
        "internal-fqdn",
        "literal-secret-shaped-value",
        "personal-home-path",
        "private-network-address",
    }


def test_publication_gate_allows_placeholders_and_code_references() -> None:
    data = (
        b"token=placeholder-token-value-123456789\n"
        b"secret=/run/recordbench-secrets/proxy-secret\n"
        b"secret = self.settings.proxy_secret\n"
    )
    assert publication._scan_bytes(data, location="fixture", deny=()) == []


def test_publication_gate_rejects_runtime_artifacts_and_symlinks(tmp_path) -> None:
    (tmp_path / "safe.txt").write_text("synthetic fixture", encoding="utf-8")
    (tmp_path / "case.sqlite3").write_bytes(b"not-a-real-database")
    (tmp_path / "link").symlink_to(tmp_path / "safe.txt")
    findings = {(item.location, item.rule) for item in publication.scan_tree(tmp_path, ())}
    assert ("case.sqlite3", "runtime-or-credential-file") in findings
    assert ("link", "symbolic-link") in findings


def test_publication_gate_rejects_extended_credential_suffixes(tmp_path) -> None:
    for suffix in (".cer", ".crt", ".der", ".jks", ".keystore"):
        (tmp_path / f"synthetic{suffix}").write_bytes(b"not-a-real-credential")
    rules = [item.rule for item in publication.scan_tree(tmp_path, ())]
    assert rules.count("runtime-or-credential-file") == 5


def test_every_container_context_excludes_private_operator_state() -> None:
    contexts = (
        ROOT / ".dockerignore",
        ROOT / "services" / "transcription" / ".dockerignore",
        ROOT / "deploy" / "kerberos-proxy" / ".dockerignore",
        ROOT / "deploy" / "model-stager" / ".dockerignore",
    )
    required_markers = (
        ".env",
        "secrets",
        "certs",
        "*.keytab",
        "*.keystore",
        "*.sqlite3",
        "*.log",
        "*.zip",
        "runtime",
        "state",
        "backups",
    )
    for dockerignore in contexts:
        rules = dockerignore.read_text(encoding="utf-8")
        for marker in required_markers:
            assert marker in rules, f"{dockerignore} does not exclude {marker}"


def test_operator_deny_terms_are_not_echoed_in_findings() -> None:
    hidden = b"private-organization-marker"
    findings = publication._scan_bytes(
        b"prefix private-organization-marker suffix",
        location="fixture",
        deny=(hidden,),
    )
    assert findings == [publication.Finding("fixture", "operator-deny-term")]
    assert hidden.decode() not in repr(findings)


def test_publication_gate_scans_pdf_metadata_and_archive_members(tmp_path) -> None:
    pdf = tmp_path / "synthetic.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Author": "reviewer@" + "private.invalid"})
    with pdf.open("wb") as handle:
        writer.write(handle)

    archive = tmp_path / "synthetic.docx"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("word/document.xml", "server " + "10." + "42.19.7")

    findings = {(item.location, item.rule) for item in publication.scan_tree(tmp_path, ())}
    assert ("synthetic.pdf#pdf-content", "non-example-email-address") in findings
    assert ("synthetic.docx!member[1]", "private-network-address") in findings


def test_archive_member_names_are_scanned_without_echoing_private_values() -> None:
    payload = __import__("io").BytesIO()
    private_name = "records/" + "10." + "91.8.7" + "/notes.txt"
    with zipfile.ZipFile(payload, "w") as output:
        output.writestr(private_name, "synthetic")

    findings = publication._scan_archive(
        payload.getvalue(), location="fixture.zip", deny=()
    )
    assert publication.Finding(
        "fixture.zip!member[1]-name", "private-network-address"
    ) in findings
    assert private_name not in repr(findings)


def test_media_metadata_is_scanned(monkeypatch) -> None:
    metadata = {
        "format": {
            "tags": {"comment": "reviewer@" + "private.invalid"},
        }
    }
    monkeypatch.setattr(publication.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        publication.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(metadata).encode("utf-8")
        ),
    )

    findings = publication._scan_media(
        b"synthetic-media", name="fixture.wav", location="fixture.wav", deny=()
    )
    assert findings == [
        publication.Finding(
            "fixture.wav#media-metadata", "non-example-email-address"
        )
    ]


def test_history_scan_finds_a_forbidden_blob_after_it_is_deleted(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Synthetic Maintainer"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "maintainer@example.com"],
        cwd=tmp_path,
        check=True,
    )
    residue = tmp_path / "old-config.txt"
    residue.write_text("service=" + "10." + "77.8.9", encoding="utf-8")
    subprocess.run(["git", "add", "old-config.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "synthetic first"], cwd=tmp_path, check=True)
    residue.unlink()
    subprocess.run(["git", "add", "-u"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "remove fixture"], cwd=tmp_path, check=True)

    findings = publication.scan_history(tmp_path, ())
    assert any(item.rule == "private-network-address" for item in findings)
    assert any("old-config.txt" in item.location for item in findings)


def test_history_scan_checks_author_and_committer_identity(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Synthetic Maintainer"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "maintainer@" + "agency.example.org",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "README.md").write_text("synthetic\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "synthetic"], cwd=tmp_path, check=True)

    assert publication.Finding(
        "git-metadata", "non-example-email-address"
    ) in publication.scan_history(tmp_path, ())
