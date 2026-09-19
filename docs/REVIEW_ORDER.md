# Greptile-ordered labeling and readiness

The requested sequence is **Greptile finishes → Jev classifies → reviewer decides
whether to mark ready-to-merge**. Jev receives the complete supported diff plus
verified current-review findings. Completion does not imply approval.

## Trust and freshness

- Only app ID `867647` and check name `Greptile Review` are accepted.
- Match the current PR head SHA, not just a PR number or check title.
- Resolve PRs by live open heads because actual Greptile events can have empty
  `pull_requests` arrays.
- Check both runs and suites. GitHub may queue a rerequested suite before the app
  updates its old completed run. In-progress/rerequested reviews wait.
- Order completed executions by timestamps, not merely run IDs (apps can reuse IDs).
- Trigger on both check-run and check-suite completion to avoid the transient gap
  where the run completes before its suite finishes updating.
- Include official-app summaries within that check's timestamps and current-head
  inline findings. Their text remains untrusted evidence, not executable instructions.
- Recheck review identity before label writes, in addition to PR/label snapshots.
- Never infer ready-to-merge from Greptile success or Jev confidence.

## Taxonomy update

`ready-to-merge` is green and **manual**. It means a reviewer has approved the
current revision, required checks pass, and no blockers remain. New commits require
reviewers to reassess/remove it. Alongside `needs-tests` and `blocked`, it is excluded
from all model questions. The taxonomy now has 27 labels, with 24 automated candidates.

## Backlog attempt, 2026-09-19

A real `--all-open --apply` pass accounted for all 25 existing Jcode PRs:

- 20 had completed Greptile checks, but their current diffs contain 1,200+ files
  and roughly 1,800 commits. Even minimum file metadata cannot fit the complete
  evidence budget, so they returned `blocked_evidence` without a model call.
- 5 had no completed current-head Greptile review: #1276, #1246, #1237, #1218, #1193.
  They returned `waiting_for_greptile`.
- **Zero PRs were newly labeled by that pass.** No PR was marked ready-to-merge.
  This is a blocked backfill, not a claim of complete coverage. The broad diffs
  must be reviewed/rebased/recreated appropriately; this tool does not rewrite
  contributor branches or silently classify just their titles/old summaries.

## Requirement checks

- Exact readiness name exists on GitHub; classifier tests prove it is never asked
  or proposed automatically, including attempted unknown-label output injection.
- API tests cover forged app IDs, stale heads, missing/pending/cancelled checks,
  rerequested suites, reused run IDs, bounded authentic findings, empty associations,
  and review changes before writes.
- A real completed review (#1295, check 105478293043) was fetched with one verified
  Greptile summary. The oversized PR itself was not submitted to the model.
- Backfill results are structured per PR, not hidden as generic workflow success.

Deployment and live event validation are recorded after the reviewed action is pinned.
