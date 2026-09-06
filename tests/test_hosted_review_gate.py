import importlib.util
from pathlib import Path

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


def test_live_gate_derives_acceptance_from_repository_permission(monkeypatch):
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
                return {"state": "open", "head": {"sha": HEAD}, "base": {"sha": "b" * 40, "ref": "main", "repo": {"default_branch": "main"}}, "html_url": "https://example.test/pr/1"}
            if path.split("?")[0].endswith("/reviews"):
                if data is None:
                    return [{"id": 10, "state": "APPROVED", "user": {"login": "github-actions[bot]"},
                             "body": "RecordBench hosted review gate: previous acceptance"}]
                approvals.append((path, data))
                return {"id": 11}
            if "/statuses/" in path:
                statuses.append(data["state"])
                return {}
            if "/comments?" in path:
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
        pr = {"state": "open", "head": {"sha": HEAD}, "base": {"sha": "b" * 40,
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
    assert issued == [(1, "APPROVE", HEAD), (4, "REQUEST_CHANGES", HEAD)]


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
            return {"state": "open", "head": {"sha": HEAD}, "base": {
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
    assert withdrawn == [HEAD]
    assert statuses == ["pending"]
