"""Dispatch after Greptile completion, or backfill all open PRs without guessing."""
import argparse
import copy
import json
import os
import re
import subprocess
import sys

from .__main__ import run
from .github import GitHub


def targets(github, pr=None, check_sha=None, all_open=False):
    if pr is not None:
        if pr <= 0:
            raise ValueError("PR number must be positive.")
        return [pr]
    if check_sha and not re.fullmatch(r"[0-9a-f]{40}", check_sha):
        raise ValueError("Check SHA must be 40 lowercase hexadecimal characters.")
    if not all_open and not check_sha:
        raise ValueError("A PR number, check SHA, or --all-open is required.")
    # check_run.pull_requests is frequently empty, including real Greptile events.
    # Resolve against live open PR heads instead. Stale and closed heads do not match.
    return [item["number"] for item in github.pages("/pulls?state=open")
            if all_open or item["head"]["sha"] == check_sha]


def dispatch(args):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    github = GitHub(args.repo, token)
    numbers = targets(github, args.pr, args.check_sha, args.all_open)
    reports = []
    for number in numbers:
        single = copy.copy(args)
        single.pr = number
        try:
            reports.append(run(single))
        except (ValueError, RuntimeError) as exc:
            # Exception messages are local, never raw HTTP responses or PR content.
            reports.append({"pull_request": number, "status": "error", "reason": str(exc)})
    return {"repository": args.repo, "requested_head_sha": args.check_sha,
            "matched_open_prs": len(numbers), "results": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pr", type=int)
    group.add_argument("--check-sha")
    group.add_argument("--all-open", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ensure-labels", action="store_true")
    parser.add_argument("--threshold", type=float, default=.75)
    parser.add_argument("--without-greptile", dest="require_greptile", action="store_false",
                        help="Explicit opt-out for independent deployments only, not Jcode's workflow")
    args = parser.parse_args()
    try:
        report = dispatch(args)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, subprocess.CalledProcessError):
        print("Could not resolve PRs safely. Check credentials and input parameters.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, allow_nan=False))
    return int(any(item.get("status") == "error" for item in report["results"]))


if __name__ == "__main__":
    sys.exit(main())
