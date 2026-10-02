#!/usr/bin/env python3
"""Require hosted code review without running PR code."""
from __future__ import annotations

from datetime import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

BOT = "chatgpt-codex-connector[bot]"
SUMMARY = "<!-- codex-pull-request-review-summary -->"
CONTEXT = "hosted-review-gate"
APPROVAL_PREFIX = "RecordBench hosted review gate:"
ACCEPTANCE = re.compile(
    r"RecordBench maintainer acceptance: ([0-9a-f]{40})"
    r"(?:\nCODE verification: request ([1-9][0-9]*); result ([1-9][0-9]*); "
    r"(execution-context|observed-unchanged-head))?")
SECURITY_HELP_LINE = '- Comment "@codex review" or "@codex security review".'
CODE_ONLY_PREFIX = (
    SUMMARY,
    "## Codex Review Summary",
    "This comment shows the latest Codex review activity on this pull request.",
    "| Review | Status | Commit | Review trigger |",
    "| --- | --- | --- | --- |",
)
CODE_ONLY_SUFFIX = (
    "<details> <summary>ℹ️ About Codex in GitHub</summary>",
    "<br/>",
    "[Your team has set up Codex to review pull requests in this repo]"
    "(https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you",
    "- Open a pull request for review",
    "- Mark a draft as ready",
    SECURITY_HELP_LINE,
    "Codex reacts with 👀 while any review is running, comments if it has suggestions, "
    "and reacts with 👍 once all reviews finish with no findings.",
    "</details>",
)
CODE_ONLY_ROW = re.compile(
    r'\| 📝 \*\*Code Review\*\* \| ✅ \*\*Completed\*\* '
    r'<relative-time datetime="(?P<completed_at>[^"<>]+)">[^<>]+</relative-time> '
    r'\| `(?P<reviewed_head>[0-9a-f]{7,40})` \| [^|\r\n]+ \|')


def comment_time(comment: dict) -> datetime:
    value = datetime.fromisoformat((comment.get("updated_at") or comment["created_at"]).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Review timestamps must include a timezone")
    return value


def evaluate(head: str, comments: list[dict], threads: list[dict],
             review_findings: list[dict] | None = None,
             native_reviews: list[dict] | None = None) -> tuple[str, str]:
    summaries = [c for c in comments if c.get("user", {}).get("login") == BOT
                 and c.get("user", {}).get("type") == "Bot" and SUMMARY in c.get("body", "")]
    if not summaries:
        return "pending", "Waiting for GitHub Codex code review of the current commit"
    body = max(summaries, key=comment_time)["body"]
    # Security is advisory. Recognize its separate row/metadata without using
    # availability, status, quota or commit binding to waive or block code review.
    # Everything else must match the complete known summary, including exactly
    # one completed code row. Unknown/truncated code evidence fails closed.
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    security_rows = [line for line in lines if re.fullmatch(
        r"\| (?:🛡️ )?\*\*Security Review\*\* \| [^|]+ \| [^|]+ \| [^|]+ \|", line)]
    security_metadata = [line for line in lines if re.fullmatch(
        r"<!-- codex-security-review:v1 [^\r\n]* -->", line)]
    if len(security_rows) > 1 or len(security_metadata) > 1:
        return "pending", "Unrecognized review summary"
    lines = [line for line in lines if line not in security_rows + security_metadata]
    if (len(lines) != len(CODE_ONLY_PREFIX) + 1 + len(CODE_ONLY_SUFFIX)
            or tuple(lines[:len(CODE_ONLY_PREFIX)]) != CODE_ONLY_PREFIX
            or tuple(lines[-len(CODE_ONLY_SUFFIX):]) != CODE_ONLY_SUFFIX
            or (code_match := CODE_ONLY_ROW.fullmatch(lines[len(CODE_ONLY_PREFIX)])) is None):
        return "pending", "Unrecognized or incomplete code review summary"
    if not head.startswith(code_match.group("reviewed_head")):
        return "pending", "Waiting for code review of the current commit"
    try:
        completed = datetime.fromisoformat(code_match.group("completed_at").replace("Z", "+00:00"))
        if completed.tzinfo is None:
            raise ValueError("Review timestamp requires a timezone")
    except ValueError:
        return "pending", "Review completion time is invalid"
    for c in comments:
        if c.get("author_association") not in {"OWNER", "MEMBER", "COLLABORATOR"}:
            continue
        if re.search(r"@codex\s+review\b", c.get("body", ""), re.I):
            if comment_time(c) >= completed:
                return "pending", "A newer code review request is still awaiting completion"
    if any(not thread.get("isResolved", False) for thread in threads):
        return "failure", "Every review discussion must be resolved"
    # Prefix consistency is not binding. Prefer the provider's native full
    # commit_id; clean comment-only reviews need explicit trusted attestation.
    requests = [c for c in comments if c.get("user", {}).get("type") != "Bot"
                and re.search(r"^@codex\s+review\b", c.get("body", ""), re.I | re.M)]
    requested_at = max((comment_time(c) for c in requests), default=datetime.min.replace(tzinfo=completed.tzinfo))
    native_bound = code_match.group("reviewed_head") == head
    for review in native_reviews or []:
        if (review.get("user", {}).get("login") != BOT
                or review.get("user", {}).get("type") != "Bot"
                or review.get("state") != "COMMENTED"
                or not review.get("submitted_at")
                or not review.get("body", "").lstrip().startswith("### 💡 Codex Review\n")):
            continue
        submitted = comment_time({"created_at": review["submitted_at"]})
        if requested_at < submitted <= completed:
            if review.get("commit_id") != head:
                return "pending", "Native CODE review identifies a different commit"
            if re.search(r"\*\*Reviewed commit:\*\* `" + re.escape(head[:10]) + r"`", review["body"]):
                native_bound = True
    inline_comments = [comment for thread in threads for comment in thread.get("comments", [])]
    # GitHub Actions has no review-thread resolved/unresolved trigger. Last-
    # resolver identity is therefore not durable authorization. The existing
    # privileged full-head acceptance reconciles all inline content; toggling
    # the UI cannot create, revoke or replace that authorization. Native branch
    # protection independently blocks unresolved conversations at merge time.
    reconciled_after = max((comment_time(c) for c in inline_comments), default=completed)
    findings = [*comments, *(review_findings or []), *inline_comments]
    findings_at = max((comment_time(c) for c in findings
                       if c.get("user", {}).get("login") == BOT
                       and c.get("user", {}).get("type") == "Bot"
                       and (re.search(r"\bP[0-3]\b", c.get("body", ""))
                            or c.get("body", "").lstrip().startswith("### 💡 Codex Review\n"))), default=completed)
    for c in comments:
        acceptance = ACCEPTANCE.fullmatch(c.get("body", "").strip())
        if not c.get("maintainerCanAccept") or not acceptance or acceptance.group(1) != head:
            continue
        bound = native_bound
        evidence_at = completed
        if not bound and acceptance.group(2):
            request_id, result_id = map(int, acceptance.group(2, 3))
            request_comment = next((x for x in requests if x.get("id") == request_id), None)
            result = next((x for x in comments if x.get("id") == result_id), None)
            if (request_comment and result
                    and re.search(r"(?<![0-9a-f])" + head + r"(?![0-9a-f])", request_comment["body"])
                    and request_comment.get("created_at") == request_comment.get("updated_at")
                    and result.get("user", {}).get("login") == BOT
                    and result.get("user", {}).get("type") == "Bot"
                    and result.get("body", "").startswith("Codex Review: Didn't find any major issues.")
                    and re.search(r"\*\*Reviewed commit:\*\* `" + re.escape(head[:10]) + r"`", result["body"])
                    and comment_time(request_comment) == requested_at
                    and requested_at < comment_time(result) <= completed
                    and result.get("created_at") == result.get("updated_at")):
                # This explicitly trusts the accepting maintainer's verified
                # execution context or observation, not the abbreviated hash.
                bound = True
                evidence_at = comment_time(result)
        if bound and comment_time(c) > max(completed, findings_at, reconciled_after, evidence_at):
            return "success", "Code reviewed; maintainer accepted full commit; hosted security review optional"
    return "pending", "Waiting for maintainer acceptance of the full reviewed commit"


def request(path: str, data=None, *, method=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request("https://api.github.com/" + path, data=body, method=method,
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def graphql_nodes(query: str, variables: dict, path: tuple[str, ...], *, initial=None) -> list[dict]:
    """Read a complete bounded connection; never accept partial GraphQL evidence."""
    nodes = []
    cursor = None
    seen = set()
    for page in range(100):
        if page == 0 and initial is not None:
            connection = initial
        else:
            result = request("graphql", {"query": query, "variables": {**variables, "cursor": cursor}})
            if result.get("errors"):
                raise RuntimeError("Review evidence unavailable")
            connection = result["data"]
            for key in path:
                connection = connection[key]
        items = connection["nodes"]
        info = connection["pageInfo"]
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise RuntimeError("Incomplete review evidence")
        nodes.extend(items)
        if info["hasNextPage"] is False:
            return nodes
        cursor = info["endCursor"]
        if (info["hasNextPage"] is not True or not isinstance(cursor, str)
                or not cursor or cursor in seen):
            raise RuntimeError("Invalid review evidence cursor")
        seen.add(cursor)
    raise RuntimeError("Review evidence page limit exceeded")


def finding_comment(node: dict) -> dict:
    """Normalize GraphQL authors explicitly; a similarly named User is not Codex."""
    author = node["author"]
    body, created = node["body"], node["createdAt"]
    if not isinstance(body, str) or not isinstance(created, str):
        raise RuntimeError("Incomplete finding evidence")
    # Use content/publication timestamps, not generic updatedAt: reaction or
    # resolution metadata must not silently change reconciliation authority.
    created_time = comment_time({"created_at": created})
    times = [created_time]
    values = [node["publishedAt"], node["lastEditedAt"]]
    if "submittedAt" in node:
        values.append(node["submittedAt"])
    for value in values:
        if value is None:
            continue
        if not isinstance(value, str):
            raise RuntimeError("Incomplete finding evidence")
        timestamp = comment_time({"created_at": value})
        if timestamp < created_time:
            raise RuntimeError("Invalid finding timestamps")
        times.append(timestamp)
    official = (author is not None and author["__typename"] == "Bot"
                and author["login"] in {BOT, BOT.removesuffix("[bot]")})
    return {"body": body, "created_at": created, "updated_at": max(times).isoformat(),
            "user": {"login": BOT if official else "", "type": "Bot" if official else "User"}}


def review_evidence(repo: str, number: int) -> tuple[list[dict], list[dict]]:
    owner, name = repo.split("/")
    variables = {"owner": owner, "name": name, "number": number}
    fields = "body createdAt publishedAt lastEditedAt author { login __typename }"
    query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) {
        reviewThreads(first:100,after:$cursor) { nodes { id isResolved
          comments(first:100) { nodes { FIELDS } pageInfo { hasNextPage endCursor } } }
          pageInfo { hasNextPage endCursor } }
      } }
    }""".replace("FIELDS", fields)
    threads = graphql_nodes(query, variables, ("repository", "pullRequest", "reviewThreads"))
    comment_query = """query($id:ID!,$cursor:String) {
      node(id:$id) { ... on PullRequestReviewThread {
        comments(first:100,after:$cursor) { nodes { FIELDS } pageInfo { hasNextPage endCursor } }
      } }
    }""".replace("FIELDS", fields)
    for thread in threads:
        comments = graphql_nodes(comment_query, {"id": thread["id"]}, ("node", "comments"),
                                 initial=thread["comments"])
        thread["comments"] = [finding_comment(comment) for comment in comments]
    review_query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) {
        reviews(first:100,after:$cursor) { nodes { FIELDS submittedAt } pageInfo { hasNextPage endCursor } }
      } }
    }""".replace("FIELDS", fields)
    reviews = graphql_nodes(review_query, variables, ("repository", "pullRequest", "reviews"))
    return threads, [finding_comment(review) for review in reviews]


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
        "description": "Rechecking current-commit hosted review policy",
        "target_url": pr["html_url"]})
    # Native approvals belong to one PR. Withdraw the prior gate opinion using
    # a new review; this needs pull-request write permission, not admin dismissal.
    gate_reviews = []
    native_reviews = []
    for page in range(1, 101):
        reviews = request(f"{review_path}?per_page=100&page={page}")
        native_reviews.extend(reviews)
        gate_reviews.extend(review for review in reviews
            if review.get("user", {}).get("login") == "github-actions[bot]"
            and review.get("body", "").startswith(APPROVAL_PREFIX)
            and review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})
        if len(reviews) < 100:
            break
    else:
        raise RuntimeError("Review limit exceeded")
    previous = max(gate_reviews, key=lambda review: review["id"], default=None)
    default_base = pr["base"]["ref"] == pr["base"]["repo"]["default_branch"]
    # Statuses are shared by commit SHA across PRs. Block this PR even on its
    # first evaluation so another PR cannot satisfy its strict review policy.
    if default_base or (previous and previous["state"] == "APPROVED"):
        request(review_path, {"commit_id": head, "event": "REQUEST_CHANGES",
            "body": f"{APPROVAL_PREFIX} PR #{number} requires gate revalidation before approval."})
    if not default_base:
        return 0
    comments = []
    for page in range(1, 101):
        items = request(f"{prefix}/issues/{number}/comments?per_page=100&page={page}")
        comments.extend(items)
        if len(items) < 100:
            break
    else:
        raise RuntimeError("Comment limit exceeded")
    threads, review_findings = review_evidence(repo, number)
    maintainer_permissions = {}
    def can_accept(login):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
            return False
        if login not in maintainer_permissions:
            permission = request(f"{prefix}/collaborators/{login}/permission")
            maintainer_permissions[login] = permission.get("permission") in {"admin", "maintain", "write"}
        return maintainer_permissions[login]

    for comment in comments:
        comment["maintainerCanAccept"] = False
        if ACCEPTANCE.fullmatch(comment.get("body", "").strip()):
            comment["maintainerCanAccept"] = can_accept(comment.get("user", {}).get("login", ""))
    state, description = evaluate(head, comments, threads, review_findings, native_reviews)
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
