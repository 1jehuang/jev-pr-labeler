# Jev PR Labeler

Semantic GitHub pull request labeling with [Jev](https://openrouter.ai/typesafe/jev-1.13),
TypeSafe's typed decision model, through OpenRouter's Decisions API.

**Size means conceptual scope, not lines changed.** A small protocol change can
have broader scope than a large mechanical rename.

## Labels

| Group | Labels |
| --- | --- |
| Type (one primary) | `type: bug`, `type: feature`, `type: refactor`, `type: docs`, `type: performance`, `type: maintenance` |
| Area (multiple) | `area: tui`, `area: providers`, `area: tools`, `area: swarm`, `area: config`, `area: install`, `area: ci`, `area: desktop` |
| Platform (only when specific) | `platform: windows`, `platform: macos`, `platform: linux` |
| Attention (positive evidence only) | `breaking-change`, `security` |
| Manual workflow state | `needs-tests`, `blocked`, `ready-to-merge` |

| Size | Conceptual scope |
| --- | --- |
| `size: XS` | Trivial correction without a design change |
| `size: S` | Focused change within one component |
| `size: M` | Substantive subsystem feature or coordinated changes to related components |
| `size: L` | Cross-subsystem behavior or interface change |
| `size: XL` | Architectural redesign or major migration |

The initial taxonomy matches Jcode. It lives in `jev_labeler/taxonomy.py` and can
be adapted in a fork. The model can select only these labels, never invent names.

## Run locally

Requires Python 3.11+, no runtime packages. Run from this repository:

```bash
export OPENROUTER_API_KEY='your-key'  # Prefer your secret manager, never commit it.
# Authenticate gh, or set GH_TOKEN/GITHUB_TOKEN.
python3 -m jev_labeler --repo owner/repo --pr 123
# The command above is a dry-run. Explicitly apply with:
python3 -m jev_labeler --repo owner/repo --pr 123 --apply --ensure-labels
```

`--ensure-labels` creates missing taxonomy labels without altering existing colors
or descriptions. Dry-run never writes to GitHub, but **does make a paid Jev call**.
The report includes per-question choice/confidence and provider usage/cost.
Never put tokens in command-line arguments. `.env` is ignored but not auto-loaded.
The optional package entry point is `jev-pr-labeler` after `pip install .`.

## GitHub Actions

1. Review this action and pin it to a **full commit SHA**.
2. Add an `OPENROUTER_API_KEY` repository secret. Use a dedicated, spend-capped key.
3. Copy [`examples/label-pr.yml`](examples/label-pr.yml) into the target repository's
   `.github/workflows/label-pr.yml`, replacing the action SHA placeholder.
4. Merge the workflow onto the default branch. Jev runs after Greptile completes a review of the current PR head.

The workflow uses Greptile `check_run` / `check_suite` completion events and a
manual dispatch option. It validates the official app ID and current PR head,
even when GitHub provides an empty PR association. It **never checks out PR code**, downloads PR artifacts, installs PR dependencies, or executes PR text.
The composite action executes only the reviewed pinned action's Python code.
Use a fresh hosted runner, not a self-hosted runner shared with untrusted jobs.
Only the transient GitHub token and OpenRouter key are required. No personal
GitHub token needs to be stored in Actions. The key goes only to OpenRouter;
GitHub credentials go only to GitHub. Redirects are refused.

## Operating Jcode's deployment

Jcode's deployment is review-ordered: **Greptile → Jev labels → human merge decision**.
GitHub-hosted runners start when Greptile finishes, not immediately on PR open.
Missing, pending, rerun-requested, or old-head reviews leave labeling waiting.
No local daemon, scheduled process, or server needs to remain online.

For an existing **open** PR, run on demand (replace `123`):

```bash
gh workflow run label-pr.yml -R 1jehuang/jcode -f pull-request=123
gh run list -R 1jehuang/jcode --workflow label-pr.yml --limit 10
```

You can also use **Actions → Semantic PR labels → Run workflow**. Inspect failed
run logs for missing credentials, unavailable patches, or context-budget limits.
Manual runs still require a completed current-head Greptile review. Low-confidence
categories abstain without replacing existing labels. The key is
spend-capped, and this workflow shares that key's budget with its other uses.

See [acceptance evidence](docs/ACCEPTANCE.md) for actual production runs and the
requirement-by-requirement validation, not just a test count.

## One-time backlog pass

Existing PRs do not receive a retroactive webhook just because the workflow was
installed. Run a bounded, review-gated pass from this repository:

```bash
python3 -m jev_labeler.after_review --repo owner/repo --all-open --apply --ensure-labels
```

This emits an outcome for every open PR: labeled, `waiting_for_greptile`,
`blocked_evidence`, or error. It never treats missing evidence as merge readiness.
For direct local classification with review context, use
`python3 -m jev_labeler --repo owner/repo --pr 123 --require-greptile`. The original CLI can still be used
without that flag for explicitly independent, diff-only use. The action defaults
to requiring Greptile; `require-greptile: 'false'` is an explicit independent-use
opt-out, not enabled in Jcode.

## Decision and update policy

- The base branch is resolved through its live Git ref. Evidence comes from a
  comparison of that immutable base SHA with the PR head SHA, not potentially
  stale PR `base.sha`, file counts, or file-list caches. Reports include the base,
  head, and merge-base SHAs used.
- Small diffs use one typed decision request. Larger complete diffs are partitioned
  into bounded excerpts, all classified by Jev, then reduced into semantic labels.
  This reduction is explicitly **lossy**, even though every substantive patch is
  covered. Ambiguous answers abstain, and hierarchical runs are add-only.
  Size is never calculated from bytes, files, lines, or excerpt count.
- Hierarchical primary type needs affirmative excerpt support. A semantic size
  estimate requires decisive size assessments for every excerpt and a decisive
  reducer, otherwise it abstains. Confidence cannot exceed the least-confident
  contributing size assessment. This bound is not a calibrated probability of
  global correctness. The reducer must abstain when interactions are unclear.
- All PR content and intermediate decisions remain untrusted evidence.
- Answers must match the fixed schema, allowed choices, finite probabilities,
  a normalized distribution, and a maximum-probability choice. Invalid responses
  fail before any label changes.
- The default confidence threshold is **0.75**, using the lower of confidence
  and selected-choice probability. Unknown or low-confidence answers abstain.
- Manual type/size labels win. In Actions, labels last applied by
  `github-actions[bot]` can be updated using issue label events for ownership.
  Local runs are add-only and do not replace existing type/size labels.
- Other automation using `github-actions[bot]` should not manage the same taxonomy.
  To override a bot label, remove it and apply your preferred label manually.
- `security` and `breaking-change` are never automatically removed. `needs-tests`,
  `blocked`, and `ready-to-merge` are manual, never proposed by Jev. Readiness means
  the current revision is reviewer-approved, required checks pass, and no blockers
  remain. Reviewers must remove/reassess readiness when new commits arrive.
- The head SHA, PR base ref/metadata, live base SHA, title, body, state, and labels
  are rechecked before inference and writes. A moving base aborts rather than
  labeling against an obsolete comparison.
  Ownership is rechecked before removals, but GitHub has no atomic compare-and-swap
  label API: an edit during the final API writes can still race. Human-label
  preservation is best-effort, not an absolute concurrency guarantee. Writes are incremental, not a destructive replace-all.
- HTTP errors can leave a partial label update. The command fails, rather than
  claiming success; rerunning reconciles the next fresh snapshot.
- Repeated check events for a head are serialized. A new head waits for its own
  Greptile review. Both run and suite completion are handled because a rerequest
  may reset a suite before the check run updates. Manual/check overlap is guarded
  by fresh PR/review snapshots; label writes remain best-effort and non-atomic.

## Limits and privacy

PR title, description, filenames, and patches are sent to OpenRouter/TypeSafe.
Do not enable this on private code without approving that data flow. Reports do
not echo patches, descriptions, or keys. Raw HTTP error bodies are never logged.

Lockfile/generated/vendor patches are omitted as incidental evidence while their
filenames remain visible. This is not a security audit or dependency vulnerability
scanner. For all other files, missing or truncated patches fail closed. Evidence
is bounded to 2 MB serialized source, 64 excerpts, and 40 KB of state per model
request. Reduction metadata must also fit the bounded request. The GitHub compare
API caps its complete file list at 300, so comparisons reaching that boundary are
rejected rather than assumed complete. Unsupported inputs require manual
classification, **not a fabricated XL label**. Line counts are used only to detect
patch truncation, never as model inputs or size thresholds. Binary changes and
text-free renames without patches also require manual review. API reads are bounded.

Model classifications can be wrong or influenced by malicious PR content even
with instruction isolation. Labels must not authorize merges, deployments,
security exceptions, or other privileged actions. This action is triage assistance.
The OpenRouter Decisions endpoint is currently alpha, so pin/review upgrades.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m jev_labeler --help
```

Tests run offline on Python 3.11 and 3.14. Live calls require credentials and incur
provider usage. No Rust/Jcode build is involved: this is an independent repository.

## License

MIT. See [LICENSE](LICENSE).
