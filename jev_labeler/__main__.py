"""Dry-run by default. Apply requires explicit --apply."""
import argparse
import json
import math
import os
import subprocess
import sys

from .classifier import build_request, parse_response
from .github import GitHub, fingerprint
from .policy import plan_labels, snapshot
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
    state = snapshot(pr, github.files(args.pr))
    request = build_request(state)
    if len(json.dumps(request).encode()) > 80_000:
        raise ValueError("Request exceeds Jev context budget.")
    if fingerprint(github.pull(args.pr)) != fingerprint(pr):
        raise RuntimeError("PR changed while fetching evidence; retry against a fresh snapshot.")
    response = request_json("https://openrouter.ai/api/alpha/decisions", key, "POST", request, limit=256_000)
    decisions = parse_response(response, request, args.threshold)
    current = {label["name"] for label in pr["labels"]}
    # Only the dedicated bot in Actions owns labels. Interactive runs never remove labels.
    owned = github.owned_labels(args.pr, "github-actions[bot]") if os.environ.get("GITHUB_ACTIONS") == "true" else set()
    additions, removals = plan_labels(decisions, current, owned)
    report = {"repository": args.repo, "pull_request": args.pr, "head_sha": pr["head"]["sha"],
              "mode": "apply" if args.apply else "dry-run", "add": additions, "remove": removals,
              "decisions": decisions, "model": response.get("model"), "usage": response.get("usage")}
    if args.apply:
        if fingerprint(github.pull(args.pr)) != fingerprint(pr):
            raise RuntimeError("PR changed during classification; no labels changed. Retry.")
        if args.ensure_labels:
            github.ensure_labels(LABELS)
        # Preflight the schema so a typo/missing label cannot partially apply.
        available = {label["name"] for label in github.pages("/labels")}
        if set(additions) - available:
            raise ValueError("Repository labels are missing. Rerun with --ensure-labels.")
        github.apply(args.pr, additions, removals)
        actual = {label["name"] for label in github.pull(args.pr)["labels"]}
        if not set(additions).issubset(actual) or set(removals) & actual:
            raise RuntimeError("GitHub label readback differed. Inspect the PR before retrying.")
        report["verified"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub owner/repository")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--threshold", type=float, default=0.75)
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
