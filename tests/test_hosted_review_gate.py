import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("hosted_gate", Path(__file__).resolve().parents[1] / "scripts/hosted-review-gate.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
HEAD = "a" * 40


def summary(head=HEAD):
    return {"user": {"login": GATE.BOT, "type": "Bot"}, "updated_at": "2026-01-01T12:00:00Z",
        "body": GATE.SUMMARY + '\n<!-- codex-security-review:v1 {"headSha":"' + head + '","status":"completed"} -->\n' +
        '\n'.join(f'| **{label}** | ✅ **Completed** <relative-time datetime="2026-01-01T12:00:00Z">done</relative-time> | `{head[:7]}` |'
                   for label in ("Code Review", "Security Review"))}


def test_requires_both_reviews_on_current_head():
    assert GATE.evaluate(HEAD, [], [])[0] == "pending"
    assert GATE.evaluate(HEAD, [summary("b" * 40)], [])[0] == "pending"
    partial = summary()
    partial["body"] = partial["body"].replace("**Code Review**", "**Other**")
    assert GATE.evaluate(HEAD, [partial], [])[0] == "pending"
    assert GATE.evaluate(HEAD, [summary()], [])[0] == "success"


def test_unresolved_discussion_blocks_until_reconciled():
    assert GATE.evaluate(HEAD, [summary()], [{"isResolved": False}])[0] == "failure"
    assert GATE.evaluate(HEAD, [summary()], [{"isResolved": True}])[0] == "success"


def test_forged_summary_and_new_review_request_do_not_pass():
    forged = summary()
    forged["user"] = {"login": "synthetic-user", "type": "User"}
    assert GATE.evaluate(HEAD, [forged], [])[0] == "pending"
    requested = {"body": "@codex review", "author_association": "OWNER", "created_at": "2026-01-01T12:01:00Z"}
    assert GATE.evaluate(HEAD, [summary(), requested], [])[0] == "pending"


def test_malformed_summary_never_passes():
    broken = summary()
    broken["body"] = broken["body"].replace('"status":"completed"', '"status":"running"')
    assert GATE.evaluate(HEAD, [broken], [])[0] == "pending"


def test_edited_request_invalidates_previous_completion():
    requested = {"body": "@codex review", "author_association": "OWNER",
                 "created_at": "2026-01-01T11:00:00Z", "updated_at": "2026-01-01T12:01:00Z"}
    assert GATE.evaluate(HEAD, [summary(), requested], [])[0] == "pending"


def test_single_review_rerun_is_compared_with_its_own_completion():
    for command, label in (("review", "Code Review"), ("security review", "Security Review")):
        current = summary()
        current["body"] = '\n'.join(line.replace('12:00:00Z', '12:02:00Z') if f'**{label}**' in line else line for line in current["body"].splitlines())
        requested = {"body": "@codex " + command, "author_association": "OWNER", "created_at": "2026-01-01T12:01:00Z"}
        assert GATE.evaluate(HEAD, [current, requested], [])[0] == "success"
