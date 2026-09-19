# Acceptance map and interpretation audit

Verified 2026-09-19. Production action code is pinned to
`07e219fcdcfd5b94463f492760e33e5f0baa99c2`. Subsequent repository commits add
operational documentation and acceptance workflows, not changes to that runtime.

## Intent audit

The requested outcome is a separate repository using **Jev** to label GitHub
PRs with the agreed taxonomy. **Size is semantic scope, not changed-line counts.**
The later operating request requires the labeling to run automatically for Jcode.

Initial uncertainty concerned locating Jev's actual API. Before implementation,
its existing Jcode integration and a real OpenRouter Decisions request established
that it is a typed classifier, not a chat/completions model. No alternate model
or heuristic line-count labeler was deployed. The earlier line-count descriptions
were replaced with semantic definitions before this implementation began.

Implementation choices inferred rather than specified by the owner:

- `jev-pr-labeler` name, public GitHub visibility, Python, MIT licensing, and
  GitHub Actions delivery. Public visibility allows a pinned action to be reused
  by Jcode without cross-repository private-action permissions.
- Reuse the existing OpenRouter credential as a repository secret, with its
  existing spending cap. No new subscription, budget increase, personal GitHub
  token in Actions, or always-on server was created.
- Confidence 0.75, conservative abstention, and manual `needs-tests` / `blocked`.
  Those two labels represent reviewer/workflow judgments not reliably inferable
  from a patch. The other 24 labels are available to the classifier.
- Initially leave the Jcode integration PR unmerged. It was enabled only after
  the owner requested that automatic operation be made to run.

The implementation matches the confirmed request. There is no residual
line-count-based sizing. Metadata line counts only detect incomplete patches.
An early internal `attention:` naming mismatch was corrected before deployment;
the public deployed taxonomy uses the exact requested unprefixed attention names.

## Explicit requirements and observed results

| Requirement | Concrete check | Observed result |
| --- | --- | --- |
| Separate repository | GitHub repository API plus clean Git status | `1jehuang/jev-pr-labeler` exists, public, default branch `main`; source committed and pushed independently of Jcode's dirty local work |
| Use Jev, not another model | Real provider response and production action log | `typesafe/jev-1.13-20260917` returned typed choices through OpenRouter Decisions; no chat-model fallback |
| Agreed labels | Compare all `taxonomy.LABELS` keys with live Jcode label names; `test_exact_taxonomy`, `test_all_type_and_size_mappings`, binary-label tests | Exactly 26 supported repository label names match; no unintended `attention:` aliases; 24 automated candidates plus two documented manual states |
| Semantic size | Live 30-file mechanical-rename fixture, one-line public-contract fixture, and real workflow PR; `test_semantic_state_has_no_line_counts` | Mechanical rename got XS at 0.98 despite many files; incompatible contract got breaking-change at 0.99 and abstained on uncertain size, not a low line-count size; real CI workflow got S at 0.98 |
| Apply labels to actual PRs | Full CLI apply/readback on Jcode #1305 | Previously unlabeled integration PR gained `type: maintenance`, `area: ci`, `size: S`, with `verified: true` |
| Run automatically on new PRs | Production [PR-open run](https://github.com/1jehuang/jcode/actions/runs/35412019372) for #1306 | Successful `pull_request_target` run added `type: docs` and `size: XS`; issue events confirm the actor was `github-actions[bot]` |
| Run on PR updates | Push a second documentation-only commit to #1306; [update run](https://github.com/1jehuang/jcode/actions/runs/35412058760) | Successful `pull_request_target` run after synchronization, `add: []`, `remove: []`, `verified: true` |
| Operator can run it on demand | Execute documented `gh workflow run label-pr.yml ... -f pull-request=1306`; [manual run](https://github.com/1jehuang/jcode/actions/runs/35412057552) | Successful `workflow_dispatch` run against the existing open PR, no duplicate changes, readback verified |

The observed improvement is operational, not just inspection: before deployment,
new PRs had no automatic semantic labeling. After deployment, a PR opened through
the GitHub API acquired the expected labels without a local classification command,
and a subsequent push triggered another successful run. No local process stayed
running. Both temporary acceptance PRs (#1306 in Jcode and #1 here) were closed
without merging their fixture changes.

## Changed public interfaces and safety properties

| Interface / property | Check | Observed result |
| --- | --- | --- |
| Composite `action.yml`, scoped token, secret input | [Hosted action smoke](https://github.com/1jehuang/jev-pr-labeler/actions/runs/35411924837) on this repository's #1 | The pinned published action ran on Ubuntu with `GITHUB_TOKEN`, provisioned missing labels, applied docs/XS, and verified them |
| Hosted rerun | [Second smoke](https://github.com/1jehuang/jev-pr-labeler/actions/runs/35411980422) | Same labels retained, zero additions/removals, successful readback |
| `python -m jev_labeler`, JSON report | Real dry-run and apply on #1305; CLI regression tests | Dry-run wrote nothing; apply wrote intended labels; report exposed choices, confidence, model, usage, changes, and verification |
| `pip install .` / `jev-pr-labeler` entry point | Built and installed wheel in a fresh scratch virtual environment, ran installed `--help` | `jev_pr_labeler-0.1.0-py3-none-any.whl` built and installed, installed entry point exited successfully |
| Type and size exclusivity, manual preservation | `test_human_choices_win`, `test_case_insensitive_human_group`, `test_type_and_size_are_exclusive`, `test_human_reapply_prevents_removal` | Human categories win, bot categories replace only owned alternatives, case variants do not create conflicting categories, last-minute ownership changes abort deletion |
| Missing label bootstrap | Actual hosted smoke plus `test_label_provision_race_refetches_existing` and `test_unrelated_provision_failure_not_hidden` | New repository taxonomy created; concurrent existing-label conflicts recovered; unrelated failures are not hidden |
| Strict API output and uncertainty | Classifier numeric/schema/unknown tests; live small-contract fixture | Invalid or injected names are rejected before writes; unknown or low confidence abstains; manual workflow states are never proposed |
| Incomplete evidence | Snapshot missing/truncated/binary/size-budget tests | Refuses partial classification, including binary changes reporting zero text lines; oversized changes are not automatically called XL |
| Stale PR and case handling | CLI stale-snapshot, invalid-response, case-insensitive schema tests | No label writes on stale snapshots or invalid responses; actual case variants are handled consistently |
| Network/credential boundaries | No-redirect and sanitized/bounded-error tests; independent review; live hosted runs | Fixed GitHub/OpenRouter destinations, no credential-bearing redirects, no raw HTTP body logging, no PR checkout/execution |
| Production workflow and permissions | Read back default-branch workflow after merging #1305; actual PR-open/update/manual runs | Only one workflow added to Jcode; reviewed action SHA pinned; contents read, PR/issues write; no admin merge bypass used |
| Runtime portability | [Pinned-revision CI](https://github.com/1jehuang/jev-pr-labeler/actions/runs/35411826892) | All 62 tests and CLI help pass on Python 3.11 and 3.14 |
| Operator documentation and example | Run documented manual command, compare installed workflow to example with SHA substitution | Manual path works; automatic events and secret names match deployed configuration |

## Limits, not hidden guarantees

These checks do not establish model accuracy on arbitrary PRs or calibrated
confidence. The semantic contrast fixtures are synthetic. Live GitHub acceptance
used same-repository PRs, not a fork-origin PR; fork support relies on the trusted
`pull_request_target` event design and has not had a separate fork-origin smoke.
Large/binary/unavailable patches can require manual classification.

Human-label preservation is best-effort: GitHub provides no atomic conditional
label delete, so a narrow race remains after the last ownership check. Labels
must never grant merge/deploy/security permissions. `needs-tests` and `blocked`
stay manual. All model requests incur usage, including dry-runs. The OpenRouter
key budget is shared with other uses of that existing key.
