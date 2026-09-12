#!/usr/bin/env python3
"""Publish a merge status from GitHub-hosted Codex reviews, without running PR code."""
from __future__ import annotations

from datetime import datetime
import json
import os
import re
import sys
import urllib.request

BOT = "chatgpt-codex-connector[bot]"
SUMMARY = "<!-- codex-pull-request-review-summary -->"
CONTEXT = "hosted-review-gate"
APPROVAL_PREFIX = "RecordBench hosted review gate:"
ACCEPTANCE = re.compile(r"RecordBench maintainer acceptance: ([0-9a-f]{40})")
QUOTA_REQUEST = re.compile(r"@codex security review\n\nRecordBench security review head: ([0-9a-f]{40})")
QUOTA_EXCEPTION = re.compile(
    r"RecordBench security quota exception: ([0-9a-f]{40}); request: ([1-9][0-9]*); response: ([1-9][0-9]*)")
QUOTA_RESPONSE = "You have reached your Codex usage limits for security reviews. Please try again later."


def comment_time(comment: dict) -> datetime:
    value = datetime.fromisoformat((comment.get("updated_at") or comment["created_at"]).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Review timestamps must include a timezone")
    return value


def quota_exception(head: str, comments: list[dict]) -> tuple[datetime, datetime] | None:
    """Verify an explicit, privileged full-head exception against the bot receipt."""
    by_id = {c.get("id"): c for c in comments if c.get("id") is not None}
    valid = []
    for c in comments:
        match = QUOTA_EXCEPTION.fullmatch(c.get("body", "").strip())
        if not match or match.group(1) != head or not c.get("maintainerCanAccept"):
            continue
        requested = by_id.get(int(match.group(2)), {})
        response = by_id.get(int(match.group(3)), {})
        request_match = QUOTA_REQUEST.fullmatch(requested.get("body", "").strip())
        if (not request_match or request_match.group(1) != head
                or not requested.get("maintainerCanAccept")
                or response.get("user", {}).get("login") != BOT
                or response.get("user", {}).get("type") != "Bot"
                or response.get("body", "").strip() != QUOTA_RESPONSE):
            continue
        # The request must already bind this full head when the bot responds.
        # Editing an old request cannot recycle an earlier quota receipt.
        if comment_time(requested) < comment_time(response) < comment_time(c):
            valid.append((comment_time(c), comment_time(response)))
    return max(valid, default=None)


def evaluate(head: str, comments: list[dict], threads: list[dict]) -> tuple[str, str]:
    summaries = [c for c in comments if c.get("user", {}).get("login") == BOT
                 and c.get("user", {}).get("type") == "Bot" and SUMMARY in c.get("body", "")]
    if not summaries:
        return "pending", "Waiting for GitHub Codex code and security reviews"
    body = max(summaries, key=lambda c: c.get("updated_at", ""))["body"]
    marker = re.search(r"<!-- codex-security-review:v1 (\{[^\n]*\}) -->", body)
    # A quota exception is deliberately limited to an absent security review.
    # Recorded running, failed, stale or malformed security state still blocks.
    exception = None
    if "codex-security-review:" in body or "**Security Review**" in body:
        if not marker:
            return "pending", "Review summary has no verifiable commit binding"
        try:
            metadata = json.loads(marker.group(1))
        except ValueError:
            return "pending", "Review metadata is invalid"
        if metadata.get("headSha") != head or metadata.get("status") != "completed":
            return "pending", "Waiting for security review of the current commit"
    else:
        exception = quota_exception(head, comments)
        if exception is None:
            return "pending", "Waiting for security review or a verified maintainer quota exception"
    waived_at, receipt_at = exception if exception else (None, None)
    completed = {}
    for label in (("Code Review",) if waived_at else ("Code Review", "Security Review")):
        row = next((line for line in body.splitlines() if f"**{label}**" in line), "")
        time = re.search(r'datetime="([^\"]+)"', row)
        sha = re.search(r"`([0-9a-f]{7,40})`", row)
        if "**Completed**" not in row or not time or not sha or not head.startswith(sha.group(1)):
            return "pending", "Waiting for both reviews on the current commit"
        try:
            completed[label] = datetime.fromisoformat(time.group(1).replace("Z", "+00:00"))
        except ValueError:
            return "pending", "Review completion time is invalid"
    if waived_at:
        completed["Security Review"] = waived_at
    for c in comments:
        if c.get("author_association") not in {"OWNER", "MEMBER", "COLLABORATOR"}:
            continue
        for command in re.finditer(r"@codex\s+(security\s+)?review\b", c.get("body", ""), re.I):
            requested = comment_time(c)
            label = "Security Review" if command.group(1) else "Code Review"
            if waived_at and label == "Security Review":
                # A new request after the bound receipt needs its own response,
                # even if it was made before the maintainer wrote the exception.
                if requested > receipt_at:
                    return "pending", "A newer security request needs a new quota receipt or completed review"
            if requested > completed[label]:
                return "pending", "A newer review request is still awaiting completion"
    if any(not thread.get("isResolved", False) or not thread.get("resolverCanReconcile", False)
           for thread in threads):
        return "failure", "A maintainer must reconcile every review discussion"
    # The bot abbreviates the code-review SHA. A separate privileged acceptance
    # binds both completed reviews to the full head, including prefix collisions.
    for c in comments:
        acceptance = ACCEPTANCE.fullmatch(c.get("body", "").strip())
        if not c.get("maintainerCanAccept") or not acceptance or acceptance.group(1) != head:
            continue
        accepted = comment_time(c)
        if accepted > max(completed.values()):
            if waived_at:
                return "success", "Code reviewed; maintainer accepted full commit with verified security quota exception"
            return "success", "Both reviews completed; maintainer accepted the full commit"
    return "pending", "Waiting for maintainer acceptance of the full reviewed commit"


def request(path: str, data=None, *, method=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request("https://api.github.com/" + path, data=body, method=method,
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    number = int(os.environ["PR_NUMBER"])
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or number <= 0:
        raise ValueError("Invalid repository or PR")
    prefix = f"repos/{repo}"
    pr = request(f"{prefix}/pulls/{number}")
    if pr["state"] != "open":
        return 0
    head = pr["head"]["sha"]
    base = pr["base"]["sha"]
    review_path = f"{prefix}/pulls/{number}/reviews"
    request(f"{prefix}/statuses/{head}", {"state": "pending", "context": CONTEXT,
        "description": "Rechecking current-commit hosted reviews and discussions",
        "target_url": pr["html_url"]})
    # Native approvals belong to one PR. Withdraw the prior gate opinion using
    # a new review; this needs pull-request write permission, not admin dismissal.
    gate_reviews = []
    for page in range(1, 101):
        reviews = request(f"{review_path}?per_page=100&page={page}")
        gate_reviews.extend(review for review in reviews
            if review.get("user", {}).get("login") == "github-actions[bot]"
            and review.get("body", "").startswith(APPROVAL_PREFIX)
            and review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})
        if len(reviews) < 100:
            break
    else:
        raise RuntimeError("Review limit exceeded")
    previous = max(gate_reviews, key=lambda review: review["id"], default=None)
    if previous and previous["state"] == "APPROVED":
        request(review_path, {"commit_id": head, "event": "REQUEST_CHANGES",
            "body": f"{APPROVAL_PREFIX} PR #{number} requires gate revalidation before approval."})
    if pr["base"]["ref"] != pr["base"]["repo"]["default_branch"]:
        return 0
    comments = []
    for page in range(1, 101):
        items = request(f"{prefix}/issues/{number}/comments?per_page=100&page={page}")
        comments.extend(items)
        if len(items) < 100:
            break
    else:
        raise RuntimeError("Comment limit exceeded")
    owner, name = repo.split("/")
    threads = []
    cursor = None
    query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) {
        reviewThreads(first:100,after:$cursor) { nodes { isResolved resolvedBy { login } }
          pageInfo { hasNextPage endCursor } }
      } }
    }"""
    for _ in range(100):
        result = request("graphql", {"query": query, "variables": {
            "owner": owner, "name": name, "number": number, "cursor": cursor}})
        if result.get("errors"):
            raise RuntimeError("Review discussions unavailable")
        connection = result["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]
    else:
        raise RuntimeError("Discussion limit exceeded")
    resolver_permissions = {}
    def can_reconcile(login):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
            return False
        if login not in resolver_permissions:
            permission = request(f"{prefix}/collaborators/{login}/permission")
            resolver_permissions[login] = permission.get("permission") in {"admin", "maintain", "write"}
        return resolver_permissions[login]

    for comment in comments:
        comment["maintainerCanAccept"] = False
        if any(pattern.fullmatch(comment.get("body", "").strip())
               for pattern in (ACCEPTANCE, QUOTA_REQUEST, QUOTA_EXCEPTION)):
            comment["maintainerCanAccept"] = can_reconcile(comment.get("user", {}).get("login", ""))
    for thread in threads:
        resolver = (thread.get("resolvedBy") or {}).get("login", "")
        thread["resolverCanReconcile"] = False
        if not thread.get("isResolved") or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", resolver):
            continue
        thread["resolverCanReconcile"] = can_reconcile(resolver)
    state, description = evaluate(head, comments, threads)
    def unchanged():
        current = request(f"{prefix}/pulls/{number}")
        return (current["state"] == "open" and current["head"]["sha"] == head
                and current["base"]["sha"] == base and current["base"]["ref"] == pr["base"]["ref"])

    if not unchanged():
        raise RuntimeError("PR or base changed during inspection; rerun the gate")
    if state == "success":
        request(review_path, {"commit_id": head, "event": "APPROVE",
            "body": f"{APPROVAL_PREFIX} PR #{number}, head {head}, base {base}. {description}."})
        if not unchanged():
            current = request(f"{prefix}/pulls/{number}")
            request(review_path, {"commit_id": current["head"]["sha"], "event": "REQUEST_CHANGES",
                "body": f"{APPROVAL_PREFIX} PR #{number} changed during approval; gate revalidation is required."})
            raise RuntimeError("PR changed during approval; rerun the gate")
    request(f"{prefix}/statuses/{head}", {"state": state, "context": CONTEXT,
        "description": description, "target_url": pr["html_url"]})
    print(json.dumps({"pr": number, "state": state, "head": head}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Never print API payloads, tokens, comments, or raw exception bodies.
        print("Hosted review gate could not complete; no passing status issued.", file=sys.stderr)
        raise SystemExit(1)
