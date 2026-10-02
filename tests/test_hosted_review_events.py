"""Contracts for trusted explicit revalidation without PR-ref review relays."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gate_has_only_trusted_event_paths():
    gate = (ROOT / ".github/workflows/hosted-review-gate.yml").read_text()
    assert "  pull_request_target:" in gate
    assert "  issue_comment:" in gate
    assert "  workflow_dispatch:" in gate
    for unsafe in ("pull_request_review:", "pull_request_review_comment:",
                   "pull_request_review_thread:", "workflow_run:"):
        assert unsafe not in gate
    assert not (ROOT / ".github/workflows/hosted-review-events.yml").exists()
    assert not (ROOT / "scripts/select-hosted-review-prs.py").exists()
    assert "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)" in gate
    assert "ref: ${{ github.event.repository.default_branch }}" in gate
    assert "persist-credentials: false" in gate
    assert "cancel-in-progress: false" in gate
    assert "github.event.pull_request.head" not in gate
    assert "@codex" not in gate


def test_explicit_protocol_documents_unobserved_mutations_and_provider_blocker():
    policy = (ROOT / "docs/PUBLIC_ALPHA.md").read_text()
    for contract in ("Do not use auto-merge", "default branch", "Abbreviated",
                     "not an atomic merge barrier", "40-character", "remain blocked"):
        assert contract in policy
