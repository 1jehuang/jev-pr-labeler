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

## Deployed and observed

Jcode PR [#1308](https://github.com/1jehuang/jcode/pull/1308) deployed the reviewed
workflow, pinned to `e0f57f97afccad77134025434e1eb83f24c0f554`. All 82 tests pass on
Python 3.11 and 3.14 in [the pinned-revision CI run](https://github.com/1jehuang/jev-pr-labeler/actions/runs/35413301370).

Concrete production checks:

| Requirement | Check and observed result |
| --- | --- |
| Wait without a completed review | [Manual run on #1276](https://github.com/1jehuang/jcode/actions/runs/35413332261) returned `waiting_for_greptile` and made no label changes |
| Do not label before Greptile | Fixture #1309 had no labels while Greptile was in progress; its exact current-head review completed at `2026-09-19T01:44:00Z` |
| Real completion triggers Jev | Native [check-suite run](https://github.com/1jehuang/jcode/actions/runs/35413551259) used review check `105817133276`, applied `type: docs` and `size: XS`, and verified readback |
| Enforce ordering, not just eventual labels | GitHub issue events show both labels applied by `github-actions[bot]` at `01:44:12Z`, twelve seconds AFTER review completion |
| Duplicate completion is safe | Native [check-run run](https://github.com/1jehuang/jcode/actions/runs/35413551470) succeeded with `add: []`, `remove: []`, `verified: true` |
| Review completion is not merge approval | The fixture never received `ready-to-merge`; the label is absent from all model questions and remains manual |
| Clean acceptance side effects | Fixture #1309 was closed without merging; no contributor PR branches were changed by the backlog pass |

Independent review identified and prompted fixes for GitHub's suite-rerequest
window and workflow-level concurrency allowing unrelated app events to displace
pending Greptile runs. The deployed concurrency is job-scoped after the trusted-app
condition and also includes app identity in its group. The complete supported
workflow is verified; universal model accuracy and successful labeling of the
blocked historical backlog are not claimed.

## Public-interface backfill acceptance recheck

The backlog was subsequently tested through the **installed package**, not a direct
call to an internal dispatcher or a copied source harness. A fresh virtualenv's
`site-packages/jev_labeler` was confirmed as the imported module, with working
directory outside the source tree. Actual command:

```bash
python -m jev_labeler.after_review --repo 1jehuang/jcode --all-open --apply
```

| Acceptance path | Observed result |
| --- | --- |
| Complete real open-PR inventory | CLI returned exactly one outcome for each of the 25 open PRs independently enumerated through GitHub's API |
| Historical backlog classification | 20 `blocked_evidence`, 5 `waiting_for_greptile`, zero newly labeled PRs; process exited 0 because these are explicit deferred outcomes, not transport errors |
| No unintended changes | Independent GitHub label snapshots before and after were identical for every open PR |
| Deployed oversized-PR path | [Hosted run on actual #1295](https://github.com/1jehuang/jcode/actions/runs/35413827819) returned `blocked_evidence` after validating its completed review, with no model guesses or label writes |
| Deployed missing-review path | [Hosted run on actual #1276](https://github.com/1jehuang/jcode/actions/runs/35413332261) returned `waiting_for_greptile` |
| Real empty repository backlog | Installed CLI against this repository, whose acceptance PRs are closed, returned zero targets/results and success |
| Closed PR by number | Installed CLI on closed #1309 returned `skipped_closed` |
| Closed PR by historical head | Installed CLI using #1309's exact head SHA returned zero matching open PRs |
| Invalid selector | Installed CLI with a non-SHA path-like selector exited 1 with a sanitized error |
| Exact public taxonomy | Fresh GitHub API comparison found all 27 names; all three manual labels are absent from the model question schema |

The historical backfill has **not** achieved automatic label coverage: the observed
result remains 0/25. This is not a GitHub connectivity or credential failure. It
combines real input diffs far beyond the model's supported complete-evidence
context with an implementation policy that does not summarize/truncate them, plus
missing third-party reviews. Increasing a small byte limit alone would not make
those repository-wide code diffs fit the model context. Multi-stage large-PR
classification or repairing/recreating those branches is additional work, not an
outcome delivered here. Contributor branches have not been rewritten.

The original labeler goal, in contrast, has direct positive outcome evidence:
a real eligible PR acquired correct semantic labels automatically twelve seconds
after actual Greptile completion, with no manual labeling command. The package,
CLI reports, taxonomy, deployed action, secrets boundary, event routing, readiness
exclusion, and deferred outcomes each have a concrete check above or in the
historical acceptance map. Test counts alone are not the basis for completion.
