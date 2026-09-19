import importlib.util
from pathlib import Path
from copy import deepcopy

import pytest

SPEC = importlib.util.spec_from_file_location("hosted_gate", Path(__file__).resolve().parents[1] / "scripts/hosted-review-gate.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
HEAD = "a" * 40


def approval(head=HEAD, permitted=True):
    return {"body": "RecordBench maintainer acceptance: " + head,
            "maintainerCanAccept": permitted, "updated_at": "2026-01-01T13:00:00Z"}


def evaluate(head, comments, threads):
    return GATE.evaluate(head, [*comments, approval()], threads)


def summary(head=HEAD):
    return {"user": {"login": GATE.BOT, "type": "Bot"}, "updated_at": "2026-01-01T12:00:00Z",
        "body": GATE.SUMMARY + '\n<!-- codex-security-review:v1 {"headSha":"' + head + '","status":"completed"} -->\n' +
        '\n'.join(f'| **{label}** | ✅ **Completed** <relative-time datetime="2026-01-01T12:00:00Z">done</relative-time> | `{head[:7]}` |'
                   for label in ("Code Review", "Security Review"))}


def test_requires_both_reviews_on_current_head():
    assert evaluate(HEAD, [], [])[0] == "pending"
    assert evaluate(HEAD, [summary("b" * 40)], [])[0] == "pending"
    partial = summary()
    partial["body"] = partial["body"].replace("**Code Review**", "**Other**")
    assert evaluate(HEAD, [partial], [])[0] == "pending"
    assert evaluate(HEAD, [summary()], [])[0] == "success"


def test_unresolved_discussion_blocks_until_reconciled():
    assert evaluate(HEAD, [summary()], [{"isResolved": False}])[0] == "failure"
    assert evaluate(HEAD, [summary()], [{"isResolved": True, "resolverCanReconcile": True}])[0] == "success"


def test_forged_summary_and_new_review_request_do_not_pass():
    forged = summary()
    forged["user"] = {"login": "synthetic-user", "type": "User"}
    assert evaluate(HEAD, [forged], [])[0] == "pending"
    requested = {"body": "@codex review", "author_association": "OWNER", "created_at": "2026-01-01T12:01:00Z"}
    assert evaluate(HEAD, [summary(), requested], [])[0] == "pending"


def test_malformed_summary_never_passes():
    broken = summary()
    broken["body"] = broken["body"].replace('"status":"completed"', '"status":"running"')
    assert evaluate(HEAD, [broken], [])[0] == "pending"


def test_edited_request_invalidates_previous_completion():
    requested = {"body": "@codex review", "author_association": "OWNER",
                 "created_at": "2026-01-01T11:00:00Z", "updated_at": "2026-01-01T12:01:00Z"}
    assert evaluate(HEAD, [summary(), requested], [])[0] == "pending"


def test_single_review_rerun_is_compared_with_its_own_completion():
    for command, label in (("review", "Code Review"), ("security review", "Security Review")):
        current = summary()
        current["body"] = '\n'.join(line.replace('12:00:00Z', '12:02:00Z') if f'**{label}**' in line else line for line in current["body"].splitlines())
        requested = {"body": "@codex " + command, "author_association": "OWNER", "created_at": "2026-01-01T12:01:00Z"}
        assert evaluate(HEAD, [current, requested], [])[0] == "success"


def test_contributor_cannot_self_reconcile_findings():
    assert evaluate(HEAD, [summary()], [{"isResolved": True}])[0] == "failure"
    assert evaluate(HEAD, [summary()], [{"isResolved": True, "resolverCanReconcile": False}])[0] == "failure"
    assert evaluate(HEAD, [summary()], [{"isResolved": True, "resolverCanReconcile": True}])[0] == "success"


def test_short_hash_collision_requires_independent_full_head_acceptance():
    collision = HEAD[:7] + "b" * 33
    assert GATE.evaluate(collision, [summary(collision), approval(HEAD)], [])[0] == "pending"
    assert GATE.evaluate(collision, [summary(collision), approval(collision, False)], [])[0] == "pending"
    assert GATE.evaluate(collision, [summary(collision), approval(collision)], [])[0] == "success"


def test_acceptance_must_follow_both_completed_reviews():
    accepted = approval()
    accepted["updated_at"] = "2026-01-01T11:00:00Z"
    assert GATE.evaluate(HEAD, [summary(), accepted], [])[0] == "pending"
    assert GATE.evaluate(HEAD, [summary()], [])[0] == "pending"


@pytest.mark.parametrize("quota", [False, True])
def test_live_gate_derives_acceptance_from_repository_permission(monkeypatch, quota):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    monkeypatch.setenv("PR_NUMBER", "1")
    for permission, expected in (("read", "pending"), ("write", "success")):
        statuses = []
        approvals = []
        accepted = approval()
        accepted["user"] = {"login": "fixture-reviewer"}
        accepted["maintainerCanAccept"] = True  # Never trust a supplied flag.

        def request(path, data=None, *, method=None):
            if path.endswith("/pulls/1"):
                return {"state": "open", "labels": [{"name": GATE.REQUIRED_LABEL}], "head": {"sha": HEAD}, "base": {"sha": "b" * 40, "ref": "main", "repo": {"default_branch": "main"}}, "html_url": "https://example.test/pr/1"}
            if path.split("?")[0].endswith("/reviews"):
                if data is None:
                    return [{"id": 10, "state": "APPROVED", "user": {"login": "github-actions[bot]"},
                             "body": "RecordBench hosted review gate: previous acceptance"}]
                approvals.append((path, data))
                return {"id": 11}
            if "/events?" in path:
                return []
            if "/statuses/" in path:
                statuses.append(data["state"])
                return {}
            if "/comments?" in path:
                if quota:
                    comments = quota_comments()
                    for comment in comments:
                        if comment.get("maintainerCanAccept"):
                            comment["user"] = {"login": "fixture-reviewer"}
                    return [*comments, accepted]
                return [summary(), accepted]
            if path == "graphql":
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                    "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
            if path.endswith("/collaborators/fixture-reviewer/permission"):
                return {"permission": permission}
            raise AssertionError(path)

        monkeypatch.setattr(GATE, "request", request)
        assert GATE.main() == 0
        assert statuses == ["pending", expected]
        expected_events = ["REQUEST_CHANGES"] + (["APPROVE"] if expected == "success" else [])
        assert [data["event"] for path, data in approvals] == expected_events
        assert all(path.endswith("/pulls/1/reviews") and data["commit_id"] == HEAD for path, data in approvals)
        if expected == "success":
            assert "b" * 40 in approvals[-1][1]["body"]


def test_shared_head_does_not_share_native_approval_or_approve_another_base(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    issued = []
    for number in (1, 2, 3, 4):
        monkeypatch.setenv("PR_NUMBER", str(number))
        accepted = approval()
        accepted["user"] = {"login": "fixture-reviewer"}
        pr = {"state": "open", "labels": [{"name": GATE.REQUIRED_LABEL}], "head": {"sha": HEAD}, "base": {"sha": "b" * 40,
              "ref": "other" if number >= 3 else "main", "repo": {"default_branch": "main"}},
              "html_url": "https://example.test/pr/" + str(number)}

        def request(path, data=None, *, method=None):
            if path.endswith("/pulls/" + str(number)):
                return pr
            if path.split("?")[0].endswith("/reviews"):
                if data is None:
                    return ([{"id": 10, "state": "APPROVED", "user": {"login": "github-actions[bot]"},
                              "body": "RecordBench hosted review gate: prior default-branch approval"}]
                            if number == 4 else [])
                issued.append((number, data["event"], data["commit_id"]))
                return {"id": number}
            if "/events?" in path:
                return []
            if "/statuses/" in path:
                return {}
            if "/comments?" in path:
                return [summary()] + ([accepted] if number != 2 else [])
            if path == "graphql":
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                    "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
            if path.endswith("/collaborators/fixture-reviewer/permission"):
                return {"permission": "write"}
            raise AssertionError(path)

        monkeypatch.setattr(GATE, "request", request)
        assert GATE.main() == 0
    assert issued == [(1, "REQUEST_CHANGES", HEAD), (1, "APPROVE", HEAD),
                      (2, "REQUEST_CHANGES", HEAD), (4, "REQUEST_CHANGES", HEAD)]


def test_base_change_during_approval_withdraws_the_new_review(monkeypatch):
    import pytest
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    monkeypatch.setenv("PR_NUMBER", "1")
    changed = False
    withdrawn = []
    statuses = []
    accepted = approval()
    accepted["user"] = {"login": "fixture-reviewer"}

    def request(path, data=None, *, method=None):
        nonlocal changed
        if path.endswith("/pulls/1"):
            return {"state": "open", "labels": [{"name": GATE.REQUIRED_LABEL}], "head": {"sha": HEAD}, "base": {
                "sha": ("c" if changed else "b") * 40, "ref": "main", "repo": {"default_branch": "main"}},
                "html_url": "https://example.test/pr/1"}
        if path.split("?")[0].endswith("/reviews"):
            if data is None:
                return []
            if data["event"] == "APPROVE":
                changed = True
            else:
                assert data["event"] == "REQUEST_CHANGES"
                withdrawn.append(data["commit_id"])
            return {"id": 11}
        if "/events?" in path:
            return []
        if "/statuses/" in path:
            statuses.append(data["state"])
            return {}
        if "/comments?" in path:
            return [summary(), accepted]
        if path == "graphql":
            return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
        if path.endswith("/collaborators/fixture-reviewer/permission"):
            return {"permission": "write"}
        raise AssertionError(path)

    monkeypatch.setattr(GATE, "request", request)
    with pytest.raises(RuntimeError, match="changed during approval"):
        GATE.main()
    assert withdrawn == [HEAD, HEAD]
    assert statuses == ["pending"]


def test_acceptance_timestamp_tie_is_ambiguous():
    accepted = approval()
    accepted["updated_at"] = "2026-01-01T12:00:00Z"
    assert GATE.evaluate(HEAD, [summary(), accepted], [])[0] == "pending"
    accepted["updated_at"] = "2026-01-01T12:00:01Z"
    assert GATE.evaluate(HEAD, [summary(), accepted], [])[0] == "success"


def quota_comments():
    code_only = summary()
    # Complete observed bot format, with synthetic commit and timestamps.
    code_only["body"] = f'''{GATE.SUMMARY}

## Codex Review Summary

This comment shows the latest Codex review activity on this pull request.

| Review | Status | Commit | Review trigger |
| --- | --- | --- | --- |
| 📝 **Code Review** | ✅ **Completed** <relative-time datetime="2026-01-01T12:00:00Z">2026-01-01T12:00:00Z</relative-time> | `{HEAD[:7]}` | Manual request |

<details> <summary>ℹ️ About Codex in GitHub</summary>
<br/>

[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you
- Open a pull request for review
- Mark a draft as ready
- Comment "@codex review" or "@codex security review".

Codex reacts with 👀 while any review is running, comments if it has suggestions, and reacts with 👍 once all reviews finish with no findings.

</details>'''
    return [code_only,
        {"id": 101, "body": "@codex security review\n\nRecordBench security review head: " + HEAD,
         "maintainerCanAccept": True, "author_association": "OWNER", "updated_at": "2026-01-01T12:01:00Z"},
        {"id": 102, "body": GATE.QUOTA_RESPONSE, "user": {"login": GATE.BOT, "type": "Bot"},
         "updated_at": "2026-01-01T12:02:00Z"},
        {"id": 103, "body": "RecordBench security quota exception: " + HEAD + "; request: 101; response: 102",
         "maintainerCanAccept": True, "updated_at": "2026-01-01T12:03:00Z"}]


def test_quota_requires_explicit_exception_and_later_separate_acceptance():
    comments = quota_comments()
    assert evaluate(HEAD, comments, [])[0] == "success"
    assert "quota exception" in evaluate(HEAD, comments, [])[1]
    assert GATE.evaluate(HEAD, comments, [])[0] == "pending"
    assert evaluate(HEAD, comments[:-1], [])[0] == "pending"
    tied = approval()
    tied["updated_at"] = comments[-1]["updated_at"]
    assert GATE.evaluate(HEAD, [*comments, tied], [])[0] == "pending"
    assert GATE.evaluate(HEAD, [*comments, approval(permitted=False)], [])[0] == "pending"


@pytest.mark.parametrize("index,field,value", [
    (1, "maintainerCanAccept", False),
    (3, "maintainerCanAccept", False),
    (2, "user", {"login": "synthetic-contributor", "type": "User"}),
    (2, "user", {"login": GATE.BOT, "type": "User"}),
    (2, "body", "Security review failed"),
    (1, "body", "@codex security review"),
    (1, "body", "@codex security review\n\nRecordBench security review head: " + "b" * 40),
    (3, "body", "RecordBench security quota exception: " + "b" * 40 + "; request: 101; response: 102"),
    (3, "body", "RecordBench security quota exception: " + HEAD + "; request: 999; response: 102"),
    (3, "body", "RecordBench security quota exception: " + HEAD + "; request: 101; response: 999"),
    (1, "updated_at", "2026-01-01T12:02:00Z"),
    (1, "updated_at", "2026-01-01T12:02:01Z"),
    (3, "updated_at", "2026-01-01T12:02:00Z"),
])
def test_quota_rejects_forged_missing_stale_or_edited_evidence(index, field, value):
    comments = quota_comments()
    comments[index][field] = value
    assert evaluate(HEAD, comments, [])[0] == "pending"


@pytest.mark.parametrize("remove", [0, 1, 2, 3])
def test_removed_quota_evidence_invalidates_exception(remove):
    comments = quota_comments()
    comments.pop(remove)
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_quota_does_not_override_code_review_or_unreconciled_findings():
    comments = quota_comments()
    comments[0]["body"] = comments[0]["body"].replace("**Completed**", "**Running**")
    assert evaluate(HEAD, comments, [])[0] == "pending"
    comments = quota_comments()
    comments[0]["body"] = comments[0]["body"].replace(HEAD[:7], "b" * 7)
    assert evaluate(HEAD, comments, [])[0] == "pending"
    assert evaluate(HEAD, quota_comments(), [{"isResolved": False}])[0] == "failure"
    assert evaluate(HEAD, quota_comments(), [{"isResolved": True}])[0] == "failure"
    assert evaluate(HEAD, quota_comments(), [{"isResolved": True, "resolverCanReconcile": True}])[0] == "success"


@pytest.mark.parametrize("state", ["running", "failed", "unknown"])
def test_recorded_security_state_cannot_be_waived(state):
    comments = quota_comments()
    comments[0] = summary()
    comments[0]["body"] = comments[0]["body"].replace('"status":"completed"', '"status":"' + state + '"')
    assert evaluate(HEAD, comments, [])[0] == "pending"


@pytest.mark.parametrize("state", [
    '<!-- codex-security-review:v1 malformed -->',
    '<!-- codex-security-review:v2 {} -->',
    '| **Security Review** | **Running** |',
    '| **Security review** | **Running** |',
    '| <strong>SECURITY REVIEW</strong> | Failed |',
    '| **Safety Review** | **Running** |',
    '**Security Review**: Failed',
    'SECURITY REVIEW\nRunning',
    '<h4>Security review</h4><p>Failed</p>',
    '- Comment "@codex review" or "@codex security review". Failed',
    '"@codex security review": Failed',
    '**Safety check**: Failed',
    '<!-- unrecognized-review-state -->',
])
def test_unrecognized_security_state_cannot_be_waived(state):
    comments = quota_comments()
    comments[0]["body"] += "\n" + state
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_exact_bot_help_line_is_not_security_state():
    comments = quota_comments()
    assert GATE.SECURITY_HELP_LINE in comments[0]["body"]
    assert evaluate(HEAD, comments, [])[0] == "success"
    comments[0]["body"] += "\n**Security Review**: Failed"
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_known_full_bot_summary_remains_eligible_for_quota_exception():
    comments = quota_comments()
    comments[0]["body"] = "\n\n".join("  " + line for line in comments[0]["body"].splitlines())
    assert evaluate(HEAD, comments, [])[0] == "success"


@pytest.mark.parametrize("index", range(14))
def test_truncated_code_only_summary_cannot_use_quota_exception(index):
    comments = quota_comments()
    lines = [line for line in comments[0]["body"].splitlines() if line.strip()]
    assert len(lines) == 14
    del lines[index]
    comments[0]["body"] = "\n".join(lines)
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_reordered_or_duplicated_known_summary_lines_are_rejected():
    for index in range(13):
        comments = quota_comments()
        lines = [line for line in comments[0]["body"].splitlines() if line.strip()]
        lines[index], lines[index + 1] = lines[index + 1], lines[index]
        comments[0]["body"] = "\n".join(lines)
        assert evaluate(HEAD, comments, [])[0] == "pending"
    comments = quota_comments()
    comments[0]["body"] += "\n" + GATE.SECURITY_HELP_LINE
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_malformed_code_row_columns_are_rejected():
    for replacement in ("", "| Manual request | Extra column "):
        comments = quota_comments()
        comments[0]["body"] = comments[0]["body"].replace("| Manual request ", replacement)
        assert evaluate(HEAD, comments, [])[0] == "pending"


def test_quota_binds_the_commit_column_not_display_text():
    comments = quota_comments()
    comments[0]["body"] = comments[0]["body"].replace(
        f"| `{HEAD[:7]}` |", "| `bbbbbbb` |").replace(
        ">2026-01-01T12:00:00Z</relative-time>", f">`{HEAD[:7]}`</relative-time>")
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_duplicate_or_unrecognized_code_rows_cannot_hide_other_review_state():
    comments = quota_comments()
    code = next(line for line in comments[0]["body"].splitlines() if "**Code Review**" in line)
    comments[0]["body"] += "\n" + code.replace("**Completed**", "**Running**")
    assert evaluate(HEAD, comments, [])[0] == "pending"
    comments = quota_comments()
    comments[0]["body"] += "\n" + code.replace("**Code Review**", "Other **Code Review**")
    assert evaluate(HEAD, comments, [])[0] == "pending"


@pytest.mark.parametrize("command,when", [
    ("review", "2026-01-01T12:01:30Z"),
    ("security review", "2026-01-01T12:01:30Z"),
    ("security review", "2026-01-01T12:01:00Z"),
    ("security review", "2026-01-01T12:02:30Z"),
    ("security review", "2026-01-01T12:02:00Z"),
    ("security review", "2026-01-01T12:04:00Z"),
])
def test_quota_does_not_ignore_newer_review_requests(command, when):
    comments = quota_comments()
    comments.append({"body": "@codex " + command, "author_association": "OWNER", "updated_at": when})
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_new_quota_receipt_allows_deliberate_retry():
    comments = quota_comments()
    newer = deepcopy(comments[1:])
    for index, comment in enumerate(newer):
        comment["id"] += 100
        comment["updated_at"] = f"2026-01-01T12:0{index + 4}:00Z"
    newer[-1]["body"] = newer[-1]["body"].replace("101", "201").replace("102", "202")
    assert evaluate(HEAD, [*comments, *newer], [])[0] == "success"


@pytest.mark.parametrize("labels", [[], [{"name": "documentation"}], [{"name": "product"}]])
def test_optional_policy_passes_without_fetching_reviews_or_requesting_codex(monkeypatch, labels):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    monkeypatch.setenv("PR_NUMBER", "1")
    statuses, reviews = [], []
    pr = {"state": "open", "labels": labels, "head": {"sha": HEAD},
          "base": {"sha": "b" * 40, "ref": "main", "repo": {"default_branch": "main"}},
          "html_url": "https://example.test/pr/1"}

    def request(path, data=None, *, method=None):
        if path.endswith("/pulls/1"):
            return deepcopy(pr)
        if path.split("?")[0].endswith("/reviews"):
            if data is None:
                # A strict-mode gate may previously have requested changes.
                return [{"id": 10, "state": "CHANGES_REQUESTED",
                         "user": {"login": "github-actions[bot]"},
                         "body": GATE.APPROVAL_PREFIX + " revalidation required"}]
            reviews.append(data)
            return {"id": 11}
        if "/events?" in path:
            return []
        if "/statuses/" in path:
            statuses.append(data)
            return {}
        # No comment, discussion, permission or review-launch API is needed.
        raise AssertionError(path)

    monkeypatch.setattr(GATE, "request", request)
    assert GATE.main() == 0
    assert [status["state"] for status in statuses] == ["pending", "success"]
    assert statuses[-1]["context"] == "hosted-review-gate"
    assert "not required" in statuses[-1]["description"]
    assert [review["event"] for review in reviews] == ["REQUEST_CHANGES", "APPROVE"]
    assert reviews[0]["commit_id"] == HEAD
    assert "not required" in reviews[-1]["body"]
    assert "@codex" not in reviews[0]["body"]


@pytest.mark.parametrize("change_at", ["inspection", "approval"])
@pytest.mark.parametrize("initially_required", [False, True])
def test_opt_in_change_during_gate_never_publishes_success(monkeypatch, change_at, initially_required):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    monkeypatch.setenv("PR_NUMBER", "1")
    reads, statuses, reviews = 0, [], []
    accepted = approval()
    accepted["user"] = {"login": "fixture-reviewer"}

    def request(path, data=None, *, method=None):
        nonlocal reads
        if path.endswith("/pulls/1"):
            reads += 1
            changed = reads >= (2 if change_at == "inspection" else 3)
            required = initially_required != changed
            return {"state": "open", "labels": [{"name": GATE.REQUIRED_LABEL}] if required else [],
                    "head": {"sha": HEAD}, "base": {"sha": "b" * 40, "ref": "main",
                    "repo": {"default_branch": "main"}}, "html_url": "https://example.test/pr/1"}
        if path.split("?")[0].endswith("/reviews"):
            if data is None:
                return []
            reviews.append(data["event"])
            return {"id": 11}
        if "/events?" in path:
            return []
        if "/statuses/" in path:
            statuses.append(data["state"])
            return {}
        if "/comments?" in path:
            return [summary(), accepted]
        if path == "graphql":
            return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
        if path.endswith("/collaborators/fixture-reviewer/permission"):
            return {"permission": "write"}
        raise AssertionError(path)

    monkeypatch.setattr(GATE, "request", request)
    with pytest.raises(RuntimeError, match="changed during"):
        GATE.main()
    assert statuses == ["pending"]
    assert reviews == ["REQUEST_CHANGES"] + ([] if change_at == "inspection" else ["APPROVE", "REQUEST_CHANGES"])


@pytest.mark.parametrize("permission,expected", [
    ("read", True), ("triage", True), ("write", False), ("maintain", False), ("admin", False),
])
def test_label_removal_requires_live_maintainer_permission(monkeypatch, permission, expected):
    events = [
        {"id": 1, "event": "labeled", "label": {"name": GATE.REQUIRED_LABEL}},
        {"id": 2, "event": "unlabeled", "label": {"name": GATE.REQUIRED_LABEL},
         "actor": {"login": "fixture-reviewer"}},
    ]

    def request(path, data=None, *, method=None):
        if "/events?" in path:
            return events
        if path.endswith("/collaborators/fixture-reviewer/permission"):
            return {"permission": permission}
        raise AssertionError(path)

    monkeypatch.setattr(GATE, "request", request)
    assert GATE.effective_hosted_review("repos/fixture/project", 1, {"labels": []}) is expected


def test_label_event_history_is_paginated_and_readding_opts_in(monkeypatch):
    unrelated = {"id": 1, "event": "labeled", "label": {"name": "documentation"}}
    events = [
        {"id": 101, "event": "labeled", "label": {"name": GATE.REQUIRED_LABEL}},
        {"id": 102, "event": "unlabeled", "label": {"name": GATE.REQUIRED_LABEL},
         "actor": {"login": "fixture-reviewer"}},
        {"id": 103, "event": "labeled", "label": {"name": GATE.REQUIRED_LABEL}},
        {"id": 104, "event": "unlabeled", "label": {"name": GATE.REQUIRED_LABEL}, "actor": None},
    ]

    def request(path, data=None, *, method=None):
        if path.endswith("page=1"):
            return [unrelated] * 100
        if path.endswith("page=2"):
            return events
        if path.endswith("/collaborators/fixture-reviewer/permission"):
            return {"permission": "write"}
        raise AssertionError(path)

    monkeypatch.setattr(GATE, "request", request)
    assert GATE.effective_hosted_review("repos/fixture/project", 1, {"labels": []})


def test_missing_label_history_fails_closed(monkeypatch):
    def request(path, data=None, *, method=None):
        raise RuntimeError("History unavailable")

    monkeypatch.setattr(GATE, "request", request)
    with pytest.raises(RuntimeError, match="History unavailable"):
        GATE.effective_hosted_review("repos/fixture/project", 1, {"labels": []})


def test_optional_shared_sha_success_leaves_strict_pr_blocked(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    latest_gate_review = {}
    status = None
    for number in (1, 2):
        monkeypatch.setenv("PR_NUMBER", str(number))
        pr = {"state": "open", "labels": [{"name": GATE.REQUIRED_LABEL}] if number == 1 else [],
              "head": {"sha": HEAD}, "base": {"sha": "b" * 40, "ref": "main",
              "repo": {"default_branch": "main"}}, "html_url": f"https://example.test/pr/{number}"}

        def request(path, data=None, *, method=None):
            nonlocal status
            if path.endswith(f"/pulls/{number}"):
                return deepcopy(pr)
            if path.split("?")[0].endswith("/reviews"):
                if data is None:
                    return [{"id": 1, "state": "APPROVED", "user": {"login": "fixture-reviewer"},
                             "body": "Ordinary maintainer review"}]
                latest_gate_review[number] = data["event"]
                return {"id": 2}
            if "/statuses/" in path:
                status = data["state"]
                return {}
            if "/events?" in path or "/comments?" in path:
                return []
            if path == "graphql":
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                    "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
            raise AssertionError(path)

        monkeypatch.setattr(GATE, "request", request)
        assert GATE.main() == 0
    assert status == "success"  # Optional PR overwrites the shared commit status.
    assert latest_gate_review == {1: "REQUEST_CHANGES", 2: "APPROVE"}


@pytest.mark.parametrize("later_maintainer", [False, True])
def test_missing_former_collaborator_preserves_strict_policy_until_maintainer_removal(monkeypatch, later_maintainer):
    events = [
        {"id": 1, "event": "labeled", "label": {"name": GATE.REQUIRED_LABEL}},
        {"id": 2, "event": "unlabeled", "label": {"name": GATE.REQUIRED_LABEL},
         "actor": {"login": "former-reviewer"}},
    ]
    if later_maintainer:
        events += [
            {"id": 3, "event": "labeled", "label": {"name": GATE.REQUIRED_LABEL}},
            {"id": 4, "event": "unlabeled", "label": {"name": GATE.REQUIRED_LABEL},
             "actor": {"login": "current-reviewer"}},
        ]

    def request(path, data=None, *, method=None):
        if "/events?" in path:
            return events
        if path.endswith("/collaborators/former-reviewer/permission"):
            raise GATE.urllib.error.HTTPError(path, 404, "Not Found", {}, None)
        if path.endswith("/collaborators/current-reviewer/permission"):
            return {"permission": "write"}
        raise AssertionError(path)

    monkeypatch.setattr(GATE, "request", request)
    assert GATE.effective_hosted_review("repos/fixture/project", 1, {"labels": []}) is (not later_maintainer)


@pytest.mark.parametrize("code", [401, 403, 429, 500])
def test_permission_service_errors_still_fail_closed(monkeypatch, code):
    def request(path, data=None, *, method=None):
        if "/events?" in path:
            return [{"id": 1, "event": "unlabeled", "label": {"name": GATE.REQUIRED_LABEL},
                     "actor": {"login": "fixture-reviewer"}}]
        raise GATE.urllib.error.HTTPError(path, code, "Unavailable", {}, None)

    monkeypatch.setattr(GATE, "request", request)
    with pytest.raises(GATE.urllib.error.HTTPError):
        GATE.effective_hosted_review("repos/fixture/project", 1, {"labels": []})
