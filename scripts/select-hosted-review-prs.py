#!/usr/bin/env python3
"""Route review wake-ups using metadata only; no artifacts or PR code are consumed."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re

SPEC = importlib.util.spec_from_file_location("hosted_gate", Path(__file__).with_name("hosted-review-gate.py"))
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

RELAY_NAME = "Hosted review events"
REVIEW_EVENTS = {"pull_request_review", "pull_request_review_comment"}


def number(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Invalid PR number")
    return value


def select_prs(event_name: str, event: dict, repo: str, dispatch_number: str = "") -> list[int]:
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            or event["repository"]["full_name"] != repo):
        raise ValueError("Unexpected repository")
    if event_name == "workflow_dispatch":
        if not re.fullmatch(r"[1-9][0-9]*", dispatch_number):
            raise ValueError("Invalid dispatch PR")
        return [int(dispatch_number)]
    if event_name == "pull_request_target":
        return [number(event["pull_request"]["number"])]
    if event_name == "issue_comment":
        return [number(event["issue"]["number"])] if event["issue"].get("pull_request") else []
    if event_name != "workflow_run":
        raise ValueError("Unsupported gate event")
    run = event["workflow_run"]
    if (event["action"] not in {"requested", "completed"}
            or run["name"] != RELAY_NAME or run["event"] not in REVIEW_EVENTS):
        raise ValueError("Unexpected review relay")
    # GitHub's run associations are routing hints, never evidence of review or
    # authority to approve. Ignore stale event head/base SHAs and conclusions.
    associated = run.get("pull_requests")
    if associated is None:
        associated = []
    if not isinstance(associated, list):
        raise ValueError("Missing review relay associations")
    if associated:
        return sorted({number(pr["number"]) for pr in associated})
    # Fork/review runs can omit associations. Reevaluate every currently open
    # default-branch PR rather than leave an old approval untouched indefinitely.
    default = event["repository"]["default_branch"]
    selected = set()
    for page in range(1, 101):
        items = GATE.request(f"repos/{repo}/pulls?state=open&per_page=100&page={page}")
        for pr in items:
            if pr["state"] == "open" and pr["base"]["ref"] == default:
                selected.add(number(pr["number"]))
        if len(items) < 100:
            return sorted(selected)
    raise RuntimeError("Open PR page limit exceeded")


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    selected = select_prs(os.environ["GITHUB_EVENT_NAME"], event,
                          os.environ["GITHUB_REPOSITORY"], os.environ.get("PR_NUMBER", ""))
    if len(selected) > 256:
        raise RuntimeError("Review gate matrix limit exceeded")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("pr_numbers=" + json.dumps(selected) + "\n")


if __name__ == "__main__":
    main()
