"""Dry-run by default. Apply requires explicit --apply."""
import argparse
import json
import math
import os
import subprocess
import sys

from .classifier import build_request, parse_response
from .github import GitHub, fingerprint
from .policy import MAX_STATE_BYTES, plan_labels, snapshot
from .review import completed_review, review_identity
from .taxonomy import LABELS
from .transport import request_json


def run(args):
    if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1:
        raise ValueError("Threshold must be finite and between 0 and 1.")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        token = result.stdout.strip() if result.returncode == 0 else ""
    if not token:
        raise ValueError("Set GH_TOKEN/GITHUB_TOKEN or authenticate gh first.")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ValueError("OPENROUTER_API_KEY is required.")
    github = GitHub(args.repo, token)
    pr = github.pull(args.pr)
    require_review = getattr(args, "require_greptile", False)
    review = None
    base_report = {"repository": args.repo, "pull_request": args.pr, "head_sha": pr["head"]["sha"]}
    if require_review:
        if pr["state"] != "open":
            return {**base_report, "status": "skipped_closed"}
        review = completed_review(github, pr, include_comments=False)
        if review is None:
            return {**base_report, "status": "waiting_for_greptile", "reason": "No completed Greptile review for the current head."}
        # Even minimum filename/status/patch JSON cannot fit. This is an evidence
        # capacity check, NEVER a semantic size classification.
        minimum_file_bytes = len(json.dumps({"filename": "x", "status": "x", "patch": ""}))
        if pr["changed_files"] * minimum_file_bytes > MAX_STATE_BYTES:
            return {**base_report, "status": "blocked_evidence", "reason": "Repository-wide diff cannot fit complete evidence budget; review/rebase the PR rather than guess labels."}
    try:
        state = snapshot(pr, github.files(args.pr))
        if require_review:
            review = completed_review(github, pr)
            if review is None:
                return {**base_report, "status": "waiting_for_greptile"}
            state["completed_greptile_review"] = review
    except ValueError as exc:
        if not require_review:
            raise
        return {**base_report, "status": "blocked_evidence", "reason": str(exc)}
    request = build_request(state)
    if len(json.dumps(request).encode()) > 80_000:
        raise ValueError("Request exceeds Jev context budget.")
    if fingerprint(github.pull(args.pr)) != fingerprint(pr):
        raise RuntimeError("PR changed while fetching evidence; retry against a fresh snapshot.")
    response = request_json("https://openrouter.ai/api/alpha/decisions", key, "POST", request, limit=256_000)
    decisions = parse_response(response, request, args.threshold)
    current = {label["name"] for label in pr["labels"]}
    # Only the dedicated bot in Actions owns labels. Interactive runs never remove labels.
    actor = "github-actions[bot]" if os.environ.get("GITHUB_ACTIONS") == "true" else None
    owned = github.owned_labels(args.pr, actor) if actor else set()
    additions, removals = plan_labels(decisions, current, owned)
    report = {"repository": args.repo, "pull_request": args.pr, "head_sha": pr["head"]["sha"],
              "mode": "apply" if args.apply else "dry-run", "add": additions, "remove": removals,
              "review_check_id": None if review is None else review["id"],
              "decisions": decisions, "model": response.get("model"), "usage": response.get("usage")}
    if args.apply:
        if fingerprint(github.pull(args.pr)) != fingerprint(pr):
            raise RuntimeError("PR changed during classification; no labels changed. Retry.")
        if args.ensure_labels:
            github.ensure_labels(LABELS)
        # Preflight the schema so a typo/missing label cannot partially apply.
        available = {label["name"].casefold() for label in github.pages("/labels")}
        if {label.casefold() for label in additions} - available:
            raise ValueError("Repository labels are missing. Rerun with --ensure-labels.")
        if fingerprint(github.pull(args.pr)) != fingerprint(pr):
            raise RuntimeError("PR changed before label writes; retry against fresh evidence.")
        if actor and github.owned_labels(args.pr, actor) != owned:
            raise RuntimeError("Label ownership changed; stopped to preserve manual edits.")
        if require_review and review_identity(completed_review(github, pr, include_comments=False)) != review_identity(review):
            raise RuntimeError("Greptile review changed during classification; no labels changed. Retry after completion.")
        github.apply(args.pr, additions, removals, actor=actor)
        actual = {label["name"].casefold() for label in github.pull(args.pr)["labels"]}
        if not {label.casefold() for label in additions}.issubset(actual) or {label.casefold() for label in removals} & actual:
            raise RuntimeError("GitHub label readback differed. Inspect the PR before retrying.")
        report["verified"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub owner/repository")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--require-greptile", action="store_true", help="Wait for a completed current-head Greptile review and include its findings")
    parser.add_argument("--apply", action="store_true", help="Write labels after validating a fresh PR snapshot")
    parser.add_argument("--ensure-labels", action="store_true", help="Create missing taxonomy labels when applying")
    args = parser.parse_args()
    try:
        report = run(args)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        # Do not print raw model/PR/HTTP data. Exception strings here are authored locally.
        if isinstance(exc, (KeyError, TypeError)):
            message = "Unexpected API response shape; no classification can be trusted."
        elif isinstance(exc, OSError):
            message = "Local credential helper or network operation failed."
        else:
            message = str(exc)
        print(f"jev-pr-labeler: {message}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
