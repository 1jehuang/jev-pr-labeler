# Validation record

Observed on 2026-09-19 using OpenRouter `typesafe/jev-1.13-20260917`.
These observations are integration checks, not an accuracy benchmark.

## Offline and hosted tests

`python3 -m unittest discover -s tests -v`: 62 tests pass locally.
GitHub Actions runs the same suite on Python 3.11 and 3.14.

Coverage includes the 26-label taxonomy, exact choice schemas, probability
validation, abstention, preservation of human choices, case-insensitive GitHub
label identity, ownership rechecks, stale PRs, pagination, missing/truncated
patches, zero-line binary changes, response limits, non-redirecting transport,
credential-safe errors, concurrent label creation, dry-run, and write/readback.

An independent review identified and prompted regression fixes for ownership
changes during classification, binary evidence, case-insensitive names, and
concurrent label creation. A residual race remains between the final ownership
check and GitHub DELETE because the API has no atomic conditional label delete.

## Real pull request

Ran the full CLI against [Jcode PR #1305](https://github.com/1jehuang/jcode/pull/1305):

- First dry-run correctly identified `area: ci` but abstained on type and size.
- Refined instructions to prioritize the actual diff over descriptions of an
  external dependency's entire capabilities. No confidence threshold reduction.
- The apply run selected `type: maintenance` (1.00), `area: ci` (1.00), and
  `size: S` (0.98), then wrote and read back those labels successfully.
- That apply request used 4,321 input tokens and cost $0.000181482 as reported
  by OpenRouter. This is an example, not a cost guarantee.
- The integration PR changed one pinned workflow and was merged after automatic operation was requested.

The production `pull_request_target` workflow is now enabled and exercised on
Jcode PR #1306. PR-open, PR-update, and manual runs all passed. Its OpenRouter
repository secret is configured separately, not in source. See
[the acceptance map](ACCEPTANCE.md) for run links and observed label results.

## Synthetic live semantic checks

Two additional state fixtures exercised Jev directly, not GitHub write paths:

1. Mechanical local-variable renames across 30 independent utility files:
   selected `size: XS` with confidence 0.98, no breaking-change flag.
2. A one-line public event timestamp schema change requiring coordinated client
   migration: selected XL at only 0.39, so size correctly **abstained** rather
   than forcing a label. `breaking-change` was selected at 0.99.

The fixtures demonstrate sensitivity to conceptual impact rather than diff
volume. They do not establish general classification accuracy or calibrated
confidence. Human review remains necessary, especially for architectural scope.
