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


def code_summary():
    code_only = {"user": {"login": GATE.BOT, "type": "Bot"},
                 "updated_at": "2026-01-01T12:00:00Z"}
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
    return code_only


def summary(head=HEAD):
    result = code_summary()
    result["body"] = result["body"].replace(HEAD[:7], head[:7])
    return result


def test_requires_actual_code_review_on_current_head():
    assert evaluate(HEAD, [], [])[0] == "pending"
    assert evaluate(HEAD, [summary("b" * 40)], [])[0] == "pending"
    partial = summary()
    partial["body"] = partial["body"].replace("**Code Review**", "**Security Review**")
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
    broken["body"] = broken["body"].replace('**Completed**', '**Running**')
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


def test_acceptance_must_follow_completed_code_review():
    accepted = approval()
    accepted["updated_at"] = "2026-01-01T11:00:00Z"
    assert GATE.evaluate(HEAD, [summary(), accepted], [])[0] == "pending"
    assert GATE.evaluate(HEAD, [summary()], [])[0] == "pending"


@pytest.mark.parametrize("labels", [[], [{"name": "require-hosted-review"}]])
def test_live_gate_derives_acceptance_from_repository_permission(monkeypatch, labels):
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
                return {"state": "open", "labels": labels, "head": {"sha": HEAD}, "base": {"sha": "b" * 40, "ref": "main", "repo": {"default_branch": "main"}}, "html_url": "https://example.test/pr/1"}
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
                return [summary(), accepted]
            if path == "graphql":
                if "reviews(first:" in data["query"]:
                    return {"data": {"repository": {"pullRequest": {"reviews": {
                        "nodes": [], "pageInfo": {"hasNextPage": False}}}}}}
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
        pr = {"state": "open", "labels": [{"name": "require-hosted-review"}], "head": {"sha": HEAD}, "base": {"sha": "b" * 40,
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
                if "reviews(first:" in data["query"]:
                    return {"data": {"repository": {"pullRequest": {"reviews": {
                        "nodes": [], "pageInfo": {"hasNextPage": False}}}}}}
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
            return {"state": "open", "labels": [{"name": "require-hosted-review"}], "head": {"sha": HEAD}, "base": {
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
            if "reviews(first:" in data["query"]:
                return {"data": {"repository": {"pullRequest": {"reviews": {
                    "nodes": [], "pageInfo": {"hasNextPage": False}}}}}}
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


@pytest.mark.parametrize("index", range(14))
def test_truncated_code_only_summary_cannot_use_review(index):
    comments = [code_summary()]
    lines = [line for line in comments[0]["body"].splitlines() if line.strip()]
    assert len(lines) == 14
    del lines[index]
    comments[0]["body"] = "\n".join(lines)
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_reordered_or_duplicated_known_summary_lines_are_rejected():
    for index in range(13):
        comments = [code_summary()]
        lines = [line for line in comments[0]["body"].splitlines() if line.strip()]
        lines[index], lines[index + 1] = lines[index + 1], lines[index]
        comments[0]["body"] = "\n".join(lines)
        assert evaluate(HEAD, comments, [])[0] == "pending"
    comments = [code_summary()]
    comments[0]["body"] += "\n" + GATE.SECURITY_HELP_LINE
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_malformed_code_row_columns_are_rejected():
    for replacement in ("", "| Manual request | Extra column "):
        comments = [code_summary()]
        comments[0]["body"] = comments[0]["body"].replace("| Manual request ", replacement)
        assert evaluate(HEAD, comments, [])[0] == "pending"


def test_code_review_binds_the_commit_column_not_display_text():
    comments = [code_summary()]
    comments[0]["body"] = comments[0]["body"].replace(
        f"| `{HEAD[:7]}` |", "| `bbbbbbb` |").replace(
        ">2026-01-01T12:00:00Z</relative-time>", f">`{HEAD[:7]}`</relative-time>")
    assert evaluate(HEAD, comments, [])[0] == "pending"


def test_duplicate_or_unrecognized_code_rows_cannot_hide_other_review_state():
    comments = [code_summary()]
    code = next(line for line in comments[0]["body"].splitlines() if "**Code Review**" in line)
    comments[0]["body"] += "\n" + code.replace("**Completed**", "**Running**")
    assert evaluate(HEAD, comments, [])[0] == "pending"
    comments = [code_summary()]
    comments[0]["body"] += "\n" + code.replace("**Code Review**", "Other **Code Review**")
    assert evaluate(HEAD, comments, [])[0] == "pending"


@pytest.mark.parametrize("state", ["running", "failed", "completed", "unknown"])
@pytest.mark.parametrize("security_head", [HEAD, "b" * 40])
def test_security_state_is_advisory_but_cannot_replace_code(state, security_head):
    current = summary()
    current["body"] += ('\n<!-- codex-security-review:v1 {"headSha":"' + security_head
                        + '","status":"' + state + '"} -->')
    row = f"| 🛡️ **Security Review** | **{state}** | `{security_head[:7]}` | Manual request |"
    current["body"] = current["body"].replace("\n<details>", row + "\n<details>")
    assert evaluate(HEAD, [current], [])[0] == "success"
    current["body"] = current["body"].replace("**Code Review**", "**Other**")
    assert evaluate(HEAD, [current], [])[0] == "pending"


@pytest.mark.parametrize("body", [
    "@codex security review",
    "You have reached your Codex usage limits for security reviews. Please try again later.",
    "RecordBench security quota exception: " + HEAD + "; request: 101; response: 102",
])
def test_optional_security_needs_no_quota_receipt_and_cannot_waive_code(body):
    advisory = {"body": body, "author_association": "OWNER", "updated_at": "2026-01-01T14:00:00Z"}
    assert evaluate(HEAD, [summary(), advisory], [])[0] == "success"
    assert evaluate(HEAD, [advisory], [])[0] == "pending"


@pytest.mark.parametrize("change", ["remove", "stale", "running", "forged"])
def test_quota_or_acceptance_cannot_substitute_for_completed_code(change):
    current = summary()
    if change == "remove":
        current["body"] = "No findings"
    elif change == "stale":
        current = summary("b" * 40)
    elif change == "running":
        current["body"] = current["body"].replace("**Completed**", "**Running**")
    else:
        current["user"]["type"] = "User"
    assert evaluate(HEAD, [current], [])[0] == "pending"


def test_new_top_level_bot_finding_requires_fresh_acceptance():
    finding = {"body": "P1 synthetic security finding", "user": {"login": GATE.BOT, "type": "Bot"},
               "updated_at": "2026-01-01T14:00:00Z"}
    assert evaluate(HEAD, [summary(), finding], [])[0] == "pending"
    accepted = approval()
    accepted["updated_at"] = "2026-01-01T14:01:00Z"
    assert GATE.evaluate(HEAD, [summary(), finding, accepted], [])[0] == "success"


@pytest.mark.parametrize("labels", [[], [{"name": "documentation"}], [{"name": "require-hosted-review"}]])
def test_no_label_policy_can_approve_without_code(monkeypatch, labels):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    monkeypatch.setenv("PR_NUMBER", "1")
    statuses, reviews = [], []
    def request(path, data=None, *, method=None):
        if path.endswith("/pulls/1"):
            return {"state": "open", "labels": labels, "head": {"sha": HEAD},
                    "base": {"sha": "b" * 40, "ref": "main", "repo": {"default_branch": "main"}},
                    "html_url": "https://example.test/pr/1"}
        if path.split("?")[0].endswith("/reviews"):
            if data is None:
                return []
            reviews.append(data["event"])
            return {}
        if "/comments?" in path:
            return []
        if "/statuses/" in path:
            statuses.append(data["state"])
            return {}
        if path == "graphql":
            if "reviews(first:" in data["query"]:
                return {"data": {"repository": {"pullRequest": {"reviews": {
                    "nodes": [], "pageInfo": {"hasNextPage": False}}}}}}
            return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [], "pageInfo": {"hasNextPage": False}}}}}}
        raise AssertionError(path)
    monkeypatch.setattr(GATE, "request", request)
    assert GATE.main() == 0
    assert statuses == ["pending", "pending"]
    assert reviews == ["REQUEST_CHANGES"]


@pytest.mark.parametrize("timestamp", ["not-a-time", "2026-01-01T12:00:00"])
def test_invalid_code_completion_time_fails_closed(timestamp):
    current = summary()
    current["body"] = current["body"].replace('datetime="2026-01-01T12:00:00Z"', f'datetime="{timestamp}"')
    assert evaluate(HEAD, [current], [])[0] == "pending"


def test_same_second_code_request_needs_unambiguous_completion():
    request = {"body": "@codex review", "author_association": "OWNER", "updated_at": "2026-01-01T12:00:00Z"}
    assert evaluate(HEAD, [summary(), request], [])[0] == "pending"


def test_workflow_runs_trusted_main_and_does_not_request_reviews():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/hosted-review-gate.yml").read_text()
    assert "ref: ${{ github.event.repository.default_branch }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "pull_request_target:" in workflow
    assert "@codex" not in workflow
    assert "github.event.pull_request.head" not in workflow


@pytest.mark.parametrize("change_at", ["inspection", "approval"])
@pytest.mark.parametrize("field", ["head", "base", "state"])
def test_changed_pr_never_publishes_success(monkeypatch, change_at, field):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    monkeypatch.setenv("PR_NUMBER", "1")
    reads, statuses, reviews = 0, [], []
    accepted = approval()
    accepted["user"] = {"login": "fixture-reviewer"}
    def request(path, data=None, *, method=None):
        nonlocal reads
        if path.endswith("/pulls/1"):
            reads += 1
            pr = {"state": "open", "labels": [], "head": {"sha": HEAD},
                  "base": {"sha": "b" * 40, "ref": "main", "repo": {"default_branch": "main"}},
                  "html_url": "https://example.test/pr/1"}
            if reads >= (2 if change_at == "inspection" else 3):
                if field == "state":
                    pr["state"] = "closed"
                else:
                    pr[field]["sha"] = "c" * 40
            return pr
        if path.split("?")[0].endswith("/reviews"):
            if data is None:
                return []
            reviews.append(data["event"])
            return {}
        if "/comments?" in path:
            return [summary(), accepted]
        if "/statuses/" in path:
            statuses.append(data["state"])
            return {}
        if path.endswith("/permission"):
            return {"permission": "write"}
        if path == "graphql":
            if "reviews(first:" in data["query"]:
                return {"data": {"repository": {"pullRequest": {"reviews": {
                    "nodes": [], "pageInfo": {"hasNextPage": False}}}}}}
            return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [], "pageInfo": {"hasNextPage": False}}}}}}
        raise AssertionError(path)
    monkeypatch.setattr(GATE, "request", request)
    with pytest.raises(RuntimeError, match="changed during"):
        GATE.main()
    assert statuses == ["pending"]
    assert reviews == ["REQUEST_CHANGES"] + ([] if change_at == "inspection" else ["APPROVE", "REQUEST_CHANGES"])


def test_latest_summary_cannot_reuse_an_older_completed_code_review():
    latest = summary()
    latest["updated_at"] = "2026-01-01T12:01:00Z"
    latest["body"] = latest["body"].replace("**Completed**", "**Running**")
    assert evaluate(HEAD, [summary(), latest], [])[0] == "pending"


@pytest.mark.parametrize("extra", [
    '<!-- codex-security-review:v2 {} -->',
    '| **Other Review** | Failed | `aaaaaaa` | Manual request |',
    '**Code Review**: Completed',
])
def test_unknown_summary_extensions_fail_closed(extra):
    current = summary()
    current["body"] += "\n" + extra
    assert evaluate(HEAD, [current], [])[0] == "pending"


def graphql_finding(*, body=None, updated="2026-01-01T14:00:00Z", kind="Bot",
                    login="chatgpt-codex-connector"):
    # The badge shape and GraphQL login match observed official inline findings;
    # the finding itself and all timestamps are synthetic.
    return {"body": body if body is not None else
            "**<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub> Synthetic security finding**",
            "author": {"login": login, "__typename": kind},
            "createdAt": "2026-01-01T12:30:00Z", "updatedAt": updated}


def connection(nodes, cursor=None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


def finding_api(monkeypatch, accepted, surface, *, broken=None):
    """Exercise the live gate through later thread, reply and review pages."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/project")
    monkeypatch.setenv("PR_NUMBER", "1")
    statuses, events, reads = [], [], []
    finding = graphql_finding()
    benign = graphql_finding(body="Synthetic maintainer disposition", kind="User", login="fixture-reviewer")
    accepted["user"] = {"login": "fixture-reviewer"}
    def request(path, data=None, *, method=None):
        if path.endswith("/pulls/1"):
            return {"state": "open", "labels": [], "head": {"sha": HEAD},
                    "base": {"sha": "b" * 40, "ref": "main", "repo": {"default_branch": "main"}},
                    "html_url": "https://example.test/pr/1"}
        if path.split("?")[0].endswith("/reviews"):
            if data is None:
                return []
            events.append(data["event"])
            return {}
        if "/comments?" in path:
            return [summary(), accepted] + ([GATE.finding_comment(finding)] if surface == "issue" else [])
        if "/statuses/" in path:
            statuses.append(data["state"])
            return {}
        if path.endswith("/permission"):
            return {"permission": "write"}
        if path == "graphql":
            query, cursor = data["query"], data["variables"]["cursor"]
            kind = "threads" if "reviewThreads(first:" in query else "replies" if "node(id:" in query else "reviews"
            reads.append((kind, cursor))
            if broken == (kind, cursor):
                return {"data": {}, "errors": [{"message": "Synthetic evidence failure"}]}
            if kind == "threads":
                if cursor is None:
                    nodes = [{"id": "thread-one", "isResolved": True,
                              "resolvedBy": {"login": "fixture-reviewer"},
                              "comments": connection([benign])}]
                    conn = connection(nodes, "next-thread")
                else:
                    node = {"id": "thread-two", "isResolved": True,
                            "resolvedBy": {"login": "fixture-reviewer"},
                            "comments": connection([finding if surface == "inline" else benign], "next-reply")}
                    conn = connection([node])
                return {"data": {"repository": {"pullRequest": {"reviewThreads": conn}}}}
            if kind == "replies":
                assert data["variables"]["id"] == "thread-two"
                assert cursor == "next-reply"
                return {"data": {"node": {"comments": connection([finding if surface == "reply" else benign])}}}
            conn = connection([benign], "next-review") if cursor is None else connection([finding if surface == "review" else benign])
            return {"data": {"repository": {"pullRequest": {"reviews": conn}}}}
        raise AssertionError(path)
    monkeypatch.setattr(GATE, "request", request)
    return statuses, events, reads


@pytest.mark.parametrize("surface", ["issue", "inline", "reply", "review"])
def test_later_resolved_security_finding_requires_new_full_head_acceptance(monkeypatch, surface):
    # Code completed at 12; accepted at 13; a priority finding posted/edited at
    # 14 was resolved by a maintainer. Resolution must not reuse acceptance at 13.
    accepted = approval()
    statuses, events, reads = finding_api(monkeypatch, accepted, surface)
    assert GATE.main() == 0
    assert statuses == ["pending", "pending"]
    assert events == ["REQUEST_CHANGES"]
    assert ("threads", "next-thread") in reads
    assert ("replies", "next-reply") in reads
    assert ("reviews", "next-review") in reads
    accepted["updated_at"] = "2026-01-01T14:00:00Z"
    assert GATE.main() == 0
    assert statuses[-1] == "pending"  # Ties remain ambiguous.
    accepted["updated_at"] = "2026-01-01T14:01:00Z"
    assert GATE.main() == 0
    assert statuses[-1] == "success"
    assert events[-1] == "APPROVE"


@pytest.mark.parametrize("page", [("threads", None), ("threads", "next-thread"),
                                  ("replies", "next-reply"), ("reviews", None),
                                  ("reviews", "next-review")])
def test_incomplete_finding_pages_never_issue_approval(monkeypatch, page):
    statuses, events, _ = finding_api(monkeypatch, approval(), "reply", broken=page)
    with pytest.raises(RuntimeError, match="unavailable"):
        GATE.main()
    assert statuses == ["pending"]
    assert events == ["REQUEST_CHANGES"]


@pytest.mark.parametrize("problem", ["missing", "repeated", "null_node", "null_data", "limit"])
def test_finding_connection_failures_are_closed(monkeypatch, problem):
    calls = 0
    def request(path, data=None, *, method=None):
        nonlocal calls
        calls += 1
        if problem == "null_data":
            return {"data": None}
        if problem == "null_node":
            return {"data": {"items": connection([None])}}
        cursor = None if problem == "missing" else str(calls) if problem == "limit" else "same"
        return {"data": {"items": {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": cursor}}}}
    monkeypatch.setattr(GATE, "request", request)
    with pytest.raises((RuntimeError, TypeError)):
        GATE.graphql_nodes("synthetic query", {}, ("items",))
    assert calls <= 100


@pytest.mark.parametrize("kind,login,expected", [
    ("Bot", "chatgpt-codex-connector", "pending"),
    ("Bot", GATE.BOT, "pending"),
    ("User", "chatgpt-codex-connector", "success"),
    ("User", GATE.BOT, "success"),
    ("Bot", "other-synthetic-bot", "success"),
])
def test_graphql_finding_identity_does_not_trust_display_login_alone(kind, login, expected):
    finding = GATE.finding_comment(graphql_finding(kind=kind, login=login))
    thread = {"isResolved": True, "resolverCanReconcile": True, "comments": [finding]}
    assert evaluate(HEAD, [summary()], [thread])[0] == expected


@pytest.mark.parametrize("field,value", [("updatedAt", None), ("updatedAt", "invalid"),
                                         ("updatedAt", "2026-01-01T14:00:00"),
                                         ("body", None), ("createdAt", None),
                                         ("createdAt", "invalid"),
                                         ("updatedAt", "2026-01-01T12:00:00Z")])
def test_incomplete_finding_fields_fail_closed(field, value):
    node = graphql_finding()
    node[field] = value
    with pytest.raises((RuntimeError, ValueError)):
        GATE.finding_comment(node)


def test_nonfinding_security_activity_does_not_require_new_acceptance():
    node = graphql_finding(body="Security review unavailable; try again later.")
    thread = {"isResolved": True, "resolverCanReconcile": True,
              "comments": [GATE.finding_comment(node)]}
    assert evaluate(HEAD, [summary()], [thread])[0] == "success"
