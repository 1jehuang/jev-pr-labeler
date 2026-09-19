"""Only trust a completed Greptile-app check on this exact current PR head."""
import json
import re

GREPTILE_APP_ID = 867647
GREPTILE_CHECK = "Greptile Review"


def review_identity(review):
    if review is None:
        return None
    return tuple(review[key] for key in ("id", "head_sha", "started_at", "completed_at", "conclusion"))


def completed_review(github, pr, include_comments=True):
    sha = pr["head"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid PR head SHA.")
    checks = github.pages(f"/commits/{sha}/check-runs", key="check_runs")
    candidates = [check for check in checks if (check.get("app") or {}).get("id") == GREPTILE_APP_ID
                  and check.get("name") == GREPTILE_CHECK and check.get("head_sha") == sha]
    if not candidates:
        return None
    # A rerequest can reset the suite to queued before the app updates its run.
    # Checking only old completed runs would incorrectly pass during that window.
    suites = github.pages(f"/commits/{sha}/check-suites", key="check_suites")
    suites = [suite for suite in suites if (suite.get("app") or {}).get("id") == GREPTILE_APP_ID
              and suite.get("head_sha") == sha]
    if not suites or any(suite.get("status") != "completed" for suite in suites):
        return None
    suite_ids = {suite["id"] for suite in suites}
    if any(run.get("status") != "completed" for run in candidates):
        return None
    # Apps can reuse an older check-run ID when rerunning. Execution timestamps,
    # not ID order alone, determine the most recent completed review.
    check = max(candidates, key=lambda value: (max(value.get("started_at") or "", value.get("completed_at") or ""), value["id"]))
    if (check.get("check_suite") or {}).get("id") not in suite_ids:
        return None
    if check.get("status") != "completed" or check.get("conclusion") not in {"success", "neutral", "failure"}:
        return None
    if not check.get("started_at") or not check.get("completed_at"):
        return None
    result = {key: check[key] for key in ("id", "head_sha", "started_at", "completed_at", "conclusion")}
    if not include_comments:
        return result
    output = check.get("output") or {}
    result["check_output"] = {key: output.get(key) for key in ("title", "summary", "text")}
    result["findings"] = []
    # Issue summaries lack commit IDs, so require the official app and this check's time window.
    for comment in github.pages(f"/issues/{pr['number']}/comments"):
        if ((comment.get("performed_via_github_app") or {}).get("id") == GREPTILE_APP_ID
                and check["started_at"] <= comment.get("updated_at", "") <= check["completed_at"]):
            result["findings"].append({"kind": "review_summary", "body": comment.get("body", "")})
    for comment in github.pages(f"/pulls/{pr['number']}/comments"):
        if ((comment.get("performed_via_github_app") or {}).get("id") == GREPTILE_APP_ID
                and comment.get("commit_id") == sha
                and check["started_at"] <= comment.get("updated_at", "") <= check["completed_at"]):
            result["findings"].append({"kind": "inline", "path": comment.get("path"), "body": comment.get("body", "")})
    if len(json.dumps(result).encode()) > 20_000:
        raise ValueError("Completed review exceeds evidence budget; manual labeling required.")
    return result
