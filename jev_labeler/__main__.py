"""Dry-run by default. Apply requires explicit --apply."""
import argparse
import json
import math
import os
import subprocess
import sys

from .evidence import EvidenceBudgetError, classify
from .github import GitHub, fingerprint
from .policy import MAX_SOURCE_BYTES, plan_labels, snapshot
from .review import completed_review, review_identity
from .taxonomy import LABELS


def run(args):
    if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1:
        raise ValueError("Threshold must be finite and between 0 and 1.")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        token = result.stdout.strip() if result.returncode == 0 else ""
    if not token:
        raise ValueError("Set GH_TOKEN/GITHUB_TOKEN or authenticate gh first.")
    github = GitHub(args.repo, token)
    pr = github.pull(args.pr)
    require_review = getattr(args, "require_greptile", False)
    review = None
    base_report = {"repository": args.repo, "pull_request": args.pr, "head_sha": pr["head"]["sha"]}
    if pr["state"] != "open":
        return {**base_report, "status": "skipped_closed"}
    if require_review:
        review = completed_review(github, pr, include_comments=False)
        if review is None:
            return {**base_report, "status": "waiting_for_greptile", "reason": "No completed Greptile review for the current head."}
    try:
        base_sha = github.base_sha(pr)
        files, provenance = github.compare_files(base_sha, pr["head"]["sha"])
        base_report["evidence"] = provenance
        if not files:
            return {**base_report, "status": "skipped_no_changes"}
        state = snapshot({**pr, "changed_files": len(files)}, files, max_bytes=MAX_SOURCE_BYTES)
        if require_review:
            review = completed_review(github, pr)
            if review is None:
                return {**base_report, "status": "waiting_for_greptile"}
            state["completed_greptile_review"] = review
    except ValueError as exc:
        if not require_review:
            raise
        return {**base_report, "status": "blocked_evidence", "reason": str(exc)}
    def unchanged():
        return (fingerprint(github.pull(args.pr)) == fingerprint(pr)
                and github.base_sha(pr) == base_sha)

    if not unchanged():
        raise RuntimeError("PR changed while fetching evidence; retry against a fresh snapshot.")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ValueError("OPENROUTER_API_KEY is required.")
    try:
        decisions, inference = classify(state, key, args.threshold)
    except EvidenceBudgetError as exc:
        if not require_review:
            raise
        return {**base_report, "status": "blocked_evidence", "reason": str(exc)}
    current = {label["name"] for label in pr["labels"]}
    # Only the dedicated bot in Actions owns labels. Interactive runs never remove labels.
    actor = "github-actions[bot]" if os.environ.get("GITHUB_ACTIONS") == "true" else None
    owned = github.owned_labels(args.pr, actor) if actor else set()
    additions, removals = plan_labels(decisions, current, owned)
    if inference.get("lossy"):
        # Hierarchical evidence can support additions, never deletion of an
        # existing conclusion using only a lossy reduction of the raw patches.
        removals = []
        for category in ("type", "size"):
            if any(name.casefold().startswith(category + ": ") for name in current):
                additions = [name for name in additions if not name.startswith(category + ": ")]
    report = {"repository": args.repo, "pull_request": args.pr, "head_sha": pr["head"]["sha"],
              "mode": "apply" if args.apply else "dry-run", "add": additions, "remove": removals,
              "review_check_id": None if review is None else review["id"],
              "decisions": decisions, "model": inference.get("model"), "usage": inference.get("usage"),
              "evidence": provenance, "inference": inference}
    if args.apply:
        if not unchanged():
            raise RuntimeError("PR changed during classification; no labels changed. Retry.")
        if args.ensure_labels:
            github.ensure_labels(LABELS)
        # Preflight the schema so a typo/missing label cannot partially apply.
        available = {label["name"].casefold() for label in github.pages("/labels")}
        if {label.casefold() for label in additions} - available:
            raise ValueError("Repository labels are missing. Rerun with --ensure-labels.")
        if not unchanged():
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
