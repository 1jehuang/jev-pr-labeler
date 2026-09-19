# Backfill remediation

## Root cause and scope

The original backfill trusted `pulls/{number}.base.sha`, `changed_files`, and the
PR file-list endpoint. On 2026-09-19, those endpoints still described an older
base history even though the target branch had moved. For PR #1295:

- PR metadata: base `0c6056425bf36fd7e1d9584cfd12fc3d4a801041`, 1,242 files.
- Live `refs/heads/master`: `7d25a564621d3d9e88c702d5295324f58bf3abe8`.
- Immutable live-base/head comparison: **2 files**, merge base
  `0735c75317e644ecb440e0c3dddb7a6b3cd0d8bf`.

The older 0/25 blocked result was observed, but it was not a sufficient diagnosis
of what could be labeled against the current branch. Repeating that same check
could not reveal the stale-base issue. This fix resolves the target ref explicitly
and records the immutable comparison used. It does not rewrite any contributor
branch, change PR targets, merge PRs, or execute PR code.

At remediation time the live open inventory contained 20 PRs. The five previously
unreviewed PRs had closed through separate work. Their closure is not a labeler
fix or a claim that Jev reviewed them.

## Evidence handling

The compare API returns its file list only on the first commit page and caps it
at 300 files. The labeler requests page 1 with one commit, rejects the 300-file
boundary, validates complete substantive patch line counts, and ignores commit
pagination for file completeness. A diverged history is valid comparison evidence.

Every live base ref is checked before model inference and before writes, alongside
PR title/body/head/base-ref/state/labels and the completed Greptile review. Moving
inputs abort. A comparison with no changed files is reported as `skipped_no_changes`.

Larger complete diffs use bounded Jev excerpt classification and semantic reduction.
The reduction is explicitly lossy and cannot remove any existing label or replace
an existing type/size label. Missing/truncated raw evidence remains unsupported.
Semantic size is not derived from line, byte, file, commit, or excerpt counts.

## Initial real-interface observations

- Public CLI dry-run for #1295 successfully classified the current two-file diff,
  instead of returning the previous repository-wide evidence error.
- Public CLI dry-run for #1270 processed all 43 changed files through 10 bounded
  excerpts plus reduction in about 8 seconds. It proposed `type: feature`,
  `area: providers`, `area: tui`, and `security`; reported provider cost was
  $0.006049806. This was not an apply run and does not establish label readback.
- All 20 current immutable comparisons passed complete-patch validation. Their
  substantive serialized states ranged from roughly 2 KB to 275 KB, not a
  repository-wide 1,200-file change each.

## Deployment and acceptance mapping

Runtime `267b789247298b06e04fcf3cac01730694c9dcb5` passed all **112 tests** on
Python 3.11 and 3.14 in [hosted CI](https://github.com/1jehuang/jev-pr-labeler/actions/runs/35414527794).
An independent reviewer inspected the implementation and reran the suite.
[Jcode PR #1311](https://github.com/1jehuang/jcode/pull/1311) deployed the one-line
action pin as commit `3824bf931e181772083f64d4aeed4ca3be7695cf`.

| Requirement / output | Concrete check and observation |
| --- | --- |
| Correct current PR evidence | Actual #1295 resolves to two complete files via the live-ref immutable comparison, not stale 1,242-file PR metadata |
| Larger supported diffs actually classify | Installed package, run outside the source tree, classified all 20 open PRs in a public `--all-open` dry-run, with no evidence blocks or errors |
| Complete bounded excerpt coverage | Regression tests reconstruct every source patch exactly, including Unicode, oversized lines, renamed-file provenance, and file boundaries; all 20 real comparison patches pass truncation checks |
| Semantic, not numeric, sizing | Tests permit semantic synthesis from locally focused excerpts to broader global scope, prohibit mechanically counting/maxing/voting sizes in instructions, and force abstention when any excerpt is uncertain |
| No invented model support | Tests reject unsupported reducer positives/types and cap size confidence by every contributing excerpt; these are informational lossy estimates, not calibrated correctness probabilities |
| Live base/head freshness | Tests change live base at every pre-inference/write checkpoint and abort without writes; reviewer additionally tested a base-ref retarget with the same live SHA |
| Preserve existing labels | CLI regression proves hierarchical runs neither remove labels nor introduce conflicting type/size labels, including case-variant bot-owned labels |
| Bad responses remain errors | Malformed provider answers raise an error, not a successful `blocked_evidence` deferral; only local budget exhaustion uses the dedicated deferral exception |
| Real hosted small-PR writes | [Run 35414645883](https://github.com/1jehuang/jcode/actions/runs/35414645883) applied `type: refactor` on #1295, used completed Greptile check 105478293043, and returned `verified: true`; independent GitHub readback confirmed the label |
| Real hosted large-PR writes | [Run 35414646970](https://github.com/1jehuang/jcode/actions/runs/35414646970) processed #1270 using 10 excerpts after check 104635384886, applied feature/provider/TUI/Windows/security labels, and returned `verified: true`; independent readback confirmed them |
| Bounded unsupported inputs | Tests reject the compare API's 300-file boundary, binary/missing/truncated patches, exceeded source/chunk/reduction budgets, and malformed refs without label writes |
| Packaging | The built wheel imports from `site-packages`, and the real public module CLI works from outside the repository. A first no-build-isolation attempt failed because the test venv lacked setuptools; the project's declared isolated build succeeded |

The integration PR also ran unrelated Jcode-wide Rust jobs. Format and Quality
Guardrails failed on pre-existing Rust formatting (for example `src/cli/acp.rs`),
not on the one-line action pin. No Rust files were changed to conceal those
failures, no required-check override was used, and this is not a claim that the
entire Jcode build passed. The labeler's pinned Python CI and both hosted runtime
paths passed independently.

## Delivered backlog outcome

Final independent GitHub inventory and label-event readback at **2026-09-19
02:13 UTC** verified **20/20 currently open PRs have bot-managed labels**.
There are no remaining evidence-blocked or waiting-review PRs in that inventory.
All current head SHAs match the reviewed snapshots. Existing labels were preserved,
and no `ready-to-merge`, `needs-tests`, or `blocked` labels were inferred.

**Five PRs received confident semantic size labels.** The other fifteen abstained
on size, rather than guessing from volume or forcing a category. Primary type also
abstains where confidence is insufficient. Coverage of some labels on every PR is
not a claim that every category is known or that classifications are infallible.

The full installed-CLI apply pass first succeeded for all 20 with exact independent
before/after label-set verification. Its personal-token writes would count as
manual overrides in later bot runs, so the managed labels introduced by that pass
were handed over to the deployed hosted workflow. The handoff was restricted to
this session's exact new labels, required unchanged PR heads/label sets and exact
latest event IDs, and preserved every pre-existing label and every security/breaking
attention flag. All 18 additional hosted runs returned actual `verified: true`
apply reports. GitHub event readback confirms every current type/size/area/platform
label is owned by `github-actions[bot]`. Attention flags remain positive-only and
were never removed. The README now recommends hosted backfill for bot ownership.

| PR | Final labels | Verified hosted apply |
| --- | --- | --- |
| [#1295](https://github.com/1jehuang/jcode/pull/1295) | `type: refactor` | [run](https://github.com/1jehuang/jcode/actions/runs/35414645883) |
| [#1293](https://github.com/1jehuang/jcode/pull/1293) | `area: config`, `size: S`, `type: bug` | [run](https://github.com/1jehuang/jcode/actions/runs/35414910414) |
| [#1290](https://github.com/1jehuang/jcode/pull/1290) | `area: providers`, `area: tools`, `area: tui`, `breaking-change` | [run](https://github.com/1jehuang/jcode/actions/runs/35414914565) |
| [#1285](https://github.com/1jehuang/jcode/pull/1285) | `area: desktop`, `area: tui`, `type: bug` | [run](https://github.com/1jehuang/jcode/actions/runs/35414918805) |
| [#1283](https://github.com/1jehuang/jcode/pull/1283) | `area: config`, `area: providers`, `size: S`, `type: bug` | [run](https://github.com/1jehuang/jcode/actions/runs/35414924107) |
| [#1282](https://github.com/1jehuang/jcode/pull/1282) | `area: config`, `security`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414927814) |
| [#1281](https://github.com/1jehuang/jcode/pull/1281) | `area: tools`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414931670) |
| [#1280](https://github.com/1jehuang/jcode/pull/1280) | `area: config`, `security`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414935661) |
| [#1279](https://github.com/1jehuang/jcode/pull/1279) | `area: config`, `area: tools`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414940185) |
| [#1278](https://github.com/1jehuang/jcode/pull/1278) | `area: tui`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414943725) |
| [#1271](https://github.com/1jehuang/jcode/pull/1271) | `area: providers`, `security`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414946884) |
| [#1270](https://github.com/1jehuang/jcode/pull/1270) | `area: providers`, `area: tui`, `platform: windows`, `security`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414646970) |
| [#1268](https://github.com/1jehuang/jcode/pull/1268) | `area: config`, `area: tui`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414950137) |
| [#1267](https://github.com/1jehuang/jcode/pull/1267) | `area: swarm`, `size: M`, `type: bug` | [run](https://github.com/1jehuang/jcode/actions/runs/35414954392) |
| [#1265](https://github.com/1jehuang/jcode/pull/1265) | `area: swarm`, `size: S`, `type: performance` | [run](https://github.com/1jehuang/jcode/actions/runs/35414958483) |
| [#1263](https://github.com/1jehuang/jcode/pull/1263) | `area: install`, `area: providers`, `area: tui`, `security`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414963194) |
| [#1262](https://github.com/1jehuang/jcode/pull/1262) | `area: install`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414966368) |
| [#1261](https://github.com/1jehuang/jcode/pull/1261) | `area: providers`, `area: tools`, `security`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414970698) |
| [#1260](https://github.com/1jehuang/jcode/pull/1260) | `area: providers`, `type: feature` | [run](https://github.com/1jehuang/jcode/actions/runs/35414974917) |
| [#1253](https://github.com/1jehuang/jcode/pull/1253) | `size: S`, `type: bug` | [run](https://github.com/1jehuang/jcode/actions/runs/35414977900) |

Detailed local evidence artifacts:
- `jev-remediated-all-dry.json`: installed public CLI classification for every PR.
- `jev-remediated-backfill-apply.json`: full local apply reports and independent snapshots.
- `jev-bot-ownership-preflight.json`: exact event IDs restricting ownership handoff.
- `jev-bot-ownership-hosted-results.json`: each real hosted apply report and run ID.
- `jev-remediation-final-readback.json`: final independent labels and event actors.

The previously reported 0/25 result is historical, not the current outcome. Five
of those original PRs closed through other work, and all twenty still-open PRs now
have labels. No contributor branch was rewritten or merged by this remediation.
