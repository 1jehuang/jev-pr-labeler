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

Deployment, installed-package acceptance, and actual label readback are recorded
below once performed. These initial observations are not a claim of completed
backfill coverage.
