# Phase 3 Option F G0 Review Bundle v1

This directory contains the small, reviewable manifests produced by the
non-GPU G0 preparation on 2026-11-06 at Git HEAD
`efe8a4dea95043fa5890e6d2ad6e36bb4fb0afea`.

## Result

- status: `READY_FOR_M1_G0_REVIEW`
- execution authorized: `false`
- Noise Calibration plan: 30 A0 runs
- Main Campaign plan: 240 six-arm runs
- total new-run budget: 270
- GPU runs performed by preparation: 0

The generated configuration tree and its evidence archive are intentionally
not committed. The complete archive is retained externally as
`phase3-option-f-g0-v1-evidence.tar.gz` with SHA-256:

`0bec268c1e392e9387bf5656b35a97fd6c6b5618580ab33efcee22ca72bb0c77`

The complete generated-tree manifest has SHA-256:

`62623b2b2e964291e41c1af64a81889239ae5d3231bbf7e10bcc8a25f2cde588`

## Principal bindings

| Artifact | SHA-256 |
|---|---|
| G0 freeze candidate | `7fed871d272184ae96228a92b21d9b89b1500a9959ec6d4b2607677bc946e7d3` |
| G0 freeze manifest | `e8e3f13bdca381d3f70f9d6a7ea3bfe44cfac6cbee16263a49b0a45ba0506560` |
| Calibration classification | `82b23d68a0af0fa715dca6886250aee395f308ce1882a0416096f4ebfc029ec6` |
| Noise run plan | `8d7dfc84c0e8edbe798f0c682ce3dd03668f06811a625cdfd8f92d101950d7be` |
| Main run plan | `5828ce55dbc23ca14aa5c0074ae8c795f51ecb301bd01de003eb8c7045e27f21` |
| Input bundle manifest | `879d004e243edaec90cd2d5411597fe98b55013f83cdeff66905a1b3ca869391` |
| Noise input manifest | `50c36e180601edcca4df8e1f6009e3aa037025a36ffc600a6bc633434b2514e7` |
| Main input manifest | `55d967230c41de3c2229a2b4b91bcb61048ff67cafc612c8e532663a2a3b7022` |

The absolute server paths in the generated candidate are immutable provenance
from the preparation environment. They are not portable execution paths.
Execution remains locked pending M1 G0 review; these files do not constitute
authorization.

## Validation

- archive transfer and tar validation: PASS
- generated manifest consistency: PASS
- all generated plans and inputs have `execution_authorized=false`
- full CPU regression at the merged PR head: `1902 passed, 15 skipped`
- post-conflict NEC/Option F targeted regression: `139 passed, 7 skipped`
- targeted Ruff: PASS
- `git diff --check`: PASS

