from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
REQUIRED = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/INSTALL.md",
    "docs/ARCHITECTURE.md",
    "docs/AUTHENTICATION.md",
    "docs/CONFIGURATION.md",
    "docs/MODELS.md",
    "docs/OCR_AND_MEDIA.md",
    "docs/STORAGE_AND_BACKUP.md",
    "docs/SECURITY_MODEL.md",
    "docs/PUBLICATION_CHECKLIST.md",
    "services/transcription/README.md",
)


def test_required_operator_and_contributor_documents_exist() -> None:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    assert missing == []


def test_readme_sets_an_honest_prerelease_boundary() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for marker in (
        "prerelease",
        "./install",
        "Local accounts",
        "OIDC",
        "Kerberos",
        "WhisperX",
        "ClamAV",
        "multi-stage retrieval",
        "No case data",
    ):
        assert marker.casefold() in text.casefold()
    assert "production ready" not in text.casefold()


def test_security_and_publication_docs_keep_release_gates_visible() -> None:
    security = (ROOT / "docs/SECURITY_MODEL.md").read_text(encoding="utf-8")
    publication = (ROOT / "docs/PUBLICATION_CHECKLIST.md").read_text(
        encoding="utf-8"
    )
    combined = security + "\n" + publication
    for marker in (
        "synthetic",
        "secret",
        "history",
        "private key",
        "license",
        "restore",
        "loopback",
    ):
        assert marker.casefold() in combined.casefold()


def test_storage_docs_do_not_present_backup_without_restore_as_success() -> None:
    text = (ROOT / "docs/STORAGE_AND_BACKUP.md").read_text(encoding="utf-8")
    assert "restore drill" in text.casefold()
    assert "never declare backup ready" in text.casefold()
    assert "model cache" in text.casefold()
    assert "excluded" in text.casefold()


def test_transcription_is_bundled_but_not_exposed_without_authentication() -> None:
    text = (ROOT / "services/transcription/README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    combined = text + "\n" + architecture
    assert "bundled" in combined.casefold()
    assert "not published" in combined.casefold()
    assert "token" in text.casefold()


def test_pull_request_jobs_test_the_merge_and_scan_the_exact_head_separately() -> None:
    workflow = (ROOT / ".github/workflows/quality-gates.yml").read_text(
        encoding="utf-8"
    )
    exact_ref = "ref: ${{ github.event.pull_request.head.sha || github.sha }}"
    assert workflow.count(exact_ref) == 1
    assert "path: _publication_head" in workflow
    assert "working-directory: _publication_head" in workflow
    assert workflow.count("EXPECTED_INTEGRATION_SHA: ${{ github.sha }}") == 3
    assert workflow.count('test "$(git rev-parse HEAD)" = "$EXPECTED_INTEGRATION_SHA"') == 3
    assert "python scripts/check-publication-candidate.py" in workflow
    assert '--expected-head "$EXPECTED_PUBLICATION_SHA"' in workflow
    assert '--publication-ref "$PUBLICATION_REF"' in workflow
    assert "pull_request_target" not in workflow
    assert "fetch-depth: 0" in workflow
