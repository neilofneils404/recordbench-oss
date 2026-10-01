"""Synthetic event contracts for the unprivileged relay and trusted revalidation."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("review_selector", ROOT / "scripts/select-hosted-review-prs.py")
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)
REPO = "fixture/project"


def event():
    return {"repository": {"full_name": REPO, "default_branch": "main"},
            "action": "requested", "workflow_run": {
                "name": "Hosted review events", "event": "pull_request_review",
                "path": ".github/workflows/hosted-review-events.yml",
                "pull_requests": [{"number": 7, "head": {"sha": "old"}, "base": {"sha": "old"}}],
                "conclusion": None}}


def workflow(name):
    return (ROOT / ".github/workflows" / name).read_text()


def test_review_event_workflow_never_receives_write_credentials_or_executes_pr_code():
    relay = workflow("hosted-review-events.yml")
    assert "name: " + SELECTOR.RELAY_NAME in relay
    assert "  pull_request_review:\n    types: [submitted, edited, dismissed]" in relay
    assert "  pull_request_review_comment:\n    types: [created, edited, deleted]" in relay
    assert "\npermissions: {}\n" in relay
    assert relay.split("jobs:\n")[1] == """  signal:
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    steps:
      - run: ':'
"""
    assert "${{" not in relay
    assert "uses:" not in relay


def test_only_default_branch_gate_has_privileged_execution_and_per_pr_serialization():
    gate = workflow("hosted-review-gate.yml")
    assert "  pull_request_review:" not in gate
    assert "  pull_request_review_comment:" not in gate
    assert "  workflow_run:\n    workflows: [Hosted review events]\n    types: [requested, completed]" in gate
    assert """permissions:
  contents: read
  issues: read
  pull-requests: write
  statuses: write
""" in gate
    assert """    permissions:
      contents: read
      pull-requests: read
""" in gate
    assert "    needs: select-prs" in gate
    assert "pr_number: ${{ fromJSON(needs.select-prs.outputs.pr_numbers) }}" in gate
    assert "group: hosted-review-${{ matrix.pr_number }}\n      cancel-in-progress: false" in gate
    assert gate.count("ref: ${{ github.event.repository.default_branch }}") == 2
    assert gate.count("persist-credentials: false") == 2
    assert gate.count("- uses:") == 2
    assert gate.count("actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd") == 2
    assert [line.strip() for line in gate.splitlines() if "run:" in line and "workflow_run:" not in line] == [
        "run: python3 scripts/select-hosted-review-prs.py",
        "run: python3 scripts/hosted-review-gate.py"]
    assert "PR_NUMBER: ${{ matrix.pr_number }}" in gate
    assert "conclusion" not in gate  # Failed/cancelled relays still revalidate.
    assert "download-artifact" not in gate
    assert "head_sha" not in gate
    assert "pull_request.head" not in gate


@pytest.mark.parametrize("source", sorted(SELECTOR.REVIEW_EVENTS))
@pytest.mark.parametrize("action", ["requested", "completed"])
@pytest.mark.parametrize("conclusion", [None, "success", "failure", "cancelled", "skipped"])
def test_review_wakeups_never_trust_relay_conclusion_or_stale_head(source, action, conclusion):
    payload = event()
    payload["action"] = action
    payload["workflow_run"].update(event=source, conclusion=conclusion)
    assert SELECTOR.select_prs("workflow_run", payload, REPO) == [7]


@pytest.mark.parametrize("associations", [[], None, "missing"])
def test_fork_or_missing_run_associations_rechecks_all_live_default_branch_prs(monkeypatch, associations):
    payload = event()
    if associations == "missing":
        payload["workflow_run"].pop("pull_requests")
    else:
        payload["workflow_run"]["pull_requests"] = associations
    seen = []
    def request(path):
        seen.append(path)
        if path.endswith("page=1"):
            return [{"number": 7, "state": "open", "base": {"ref": "main"}}] * 100
        return [{"number": 8, "state": "open", "base": {"ref": "main"}},
                {"number": 9, "state": "open", "base": {"ref": "other"}},
                {"number": 10, "state": "closed", "base": {"ref": "main"}}]
    monkeypatch.setattr(SELECTOR.GATE, "request", request)
    assert SELECTOR.select_prs("workflow_run", payload, REPO) == [7, 8]
    assert seen == [f"repos/{REPO}/pulls?state=open&per_page=100&page={page}" for page in (1, 2)]


@pytest.mark.parametrize("name,updates", [
    ("pull_request_target", {"pull_request": {"number": 7}}),
    ("issue_comment", {"issue": {"number": 7, "pull_request": {"url": "synthetic"}}}),
    ("workflow_dispatch", {}),
])
def test_original_gate_events_keep_pr_routing(name, updates):
    payload = event()
    payload.update(updates)
    assert SELECTOR.select_prs(name, payload, REPO, "7") == [7]
    if name == "issue_comment":
        payload["issue"].pop("pull_request")
        assert SELECTOR.select_prs(name, payload, REPO) == []


@pytest.mark.parametrize("field,value", [("name", "other"), ("event", "push"),
                                         ("pull_requests", [{"number": "7; malicious"}]),
                                         ("pull_requests", [{"number": True}])])
def test_malformed_or_unrelated_run_metadata_cannot_select_prs(field, value):
    payload = event()
    payload["workflow_run"][field] = value
    with pytest.raises(ValueError):
        SELECTOR.select_prs("workflow_run", payload, REPO)


def test_api_failure_does_not_silently_skip_fallback_invalidation(monkeypatch):
    payload = event()
    payload["workflow_run"]["pull_requests"] = []
    def request(path):
        raise RuntimeError("Synthetic API failure")
    monkeypatch.setattr(SELECTOR.GATE, "request", request)
    with pytest.raises(RuntimeError):
        SELECTOR.select_prs("workflow_run", payload, REPO)


def test_selector_output_is_numeric_json_not_executable_event_content(monkeypatch, tmp_path):
    payload = event()
    payload["workflow_run"]["pull_requests"] = [{"number": 8}, {"number": 7}, {"number": 8}]
    payload["workflow_run"]["head_branch"] = "$(synthetic-command)"
    event_path, output = tmp_path / "event.json", tmp_path / "output"
    event_path.write_text(json.dumps(payload))
    for key, value in {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REPOSITORY": REPO,
                       "GITHUB_EVENT_PATH": str(event_path), "GITHUB_OUTPUT": str(output)}.items():
        monkeypatch.setenv(key, value)
    SELECTOR.main()
    assert output.read_text() == "pr_numbers=[7, 8]\n"
