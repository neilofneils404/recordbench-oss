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


def evaluate(head: str, comments: list[dict], threads: list[dict]) -> tuple[str, str]:
    summaries = [c for c in comments if c.get("user", {}).get("login") == BOT
                 and c.get("user", {}).get("type") == "Bot" and SUMMARY in c.get("body", "")]
    if not summaries:
        return "pending", "Waiting for GitHub Codex code and security reviews"
    body = max(summaries, key=lambda c: c.get("updated_at", ""))["body"]
    marker = re.search(r"<!-- codex-security-review:v1 (\{[^\n]*\}) -->", body)
    if not marker:
        return "pending", "Review summary has no verifiable commit binding"
    try:
        metadata = json.loads(marker.group(1))
    except ValueError:
        return "pending", "Review metadata is invalid"
    if metadata.get("headSha") != head or metadata.get("status") != "completed":
        return "pending", "Waiting for security review of the current commit"
    completed = {}
    for label in ("Code Review", "Security Review"):
        row = next((line for line in body.splitlines() if f"**{label}**" in line), "")
        time = re.search(r'datetime="([^\"]+)"', row)
        sha = re.search(r"`([0-9a-f]{7,40})`", row)
        if "**Completed**" not in row or not time or not sha or not head.startswith(sha.group(1)):
            return "pending", "Waiting for both reviews on the current commit"
        try:
            completed[label] = datetime.fromisoformat(time.group(1).replace("Z", "+00:00"))
        except ValueError:
            return "pending", "Review completion time is invalid"
    for c in comments:
        if c.get("author_association") not in {"OWNER", "MEMBER", "COLLABORATOR"}:
            continue
        for command in re.finditer(r"@codex\s+(security\s+)?review\b", c.get("body", ""), re.I):
            requested = datetime.fromisoformat((c.get("updated_at") or c["created_at"]).replace("Z", "+00:00"))
            label = "Security Review" if command.group(1) else "Code Review"
            if requested > completed[label]:
                return "pending", "A newer review request is still awaiting completion"
    if any(not thread.get("isResolved", False) for thread in threads):
        return "failure", "Resolve or explicitly reconcile every review discussion"
    return "success", "Current-commit code/security reviews completed; discussions resolved"


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
    request(f"{prefix}/statuses/{head}", {"state": "pending", "context": CONTEXT,
        "description": "Rechecking current-commit hosted reviews and discussions",
        "target_url": pr["html_url"]})
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
        reviewThreads(first:100,after:$cursor) { nodes { isResolved }
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
    state, description = evaluate(head, comments, threads)
    if request(f"{prefix}/pulls/{number}")["head"]["sha"] != head:
        raise RuntimeError("PR changed during inspection; rerun the gate")
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
