# Phase 3 Option F G0 Review Bundle v3

This directory contains the final small, reviewable manifests regenerated on
the real evidence server after the last PR #99 review, at clean Git HEAD
`4e2f4c325c0e812d66d8a30090631b74194d4a37`.

## Result

- status: `READY_FOR_M1_G0_REVIEW`
- execution authorized: `false`
- Noise Calibration plan: 30 A0 runs
- Main Campaign plan: 240 six-arm runs
- total new-run budget: 270
- GPU runs performed by regeneration: 0

The complete generated configuration tree is retained externally as
`phase3-option-f-g0-v3-evidence.tar.gz` with SHA-256:

`7b3a78c8e582067e6a236885aa91980cf51a77bf2787d774b82733612cd94529`

The complete generated-tree manifest has SHA-256:

`6d075851d4427219e6b497b2b6d924a5327ad56b794b697b0118283fa9546016`

## Principal bindings

| Artifact | SHA-256 |
|---|---|
| G0 freeze candidate | `a5e3bfc43cc72bc44fcc8ef163d2e44d4e11cce1a89802164c050f8b59c3a1d4` |
| G0 freeze manifest | `db9ebb8a388d30f6d9bc1c58a19dd8b97b9ce0a7afdafea124987754fbcde971` |
| Calibration classification | `82b23d68a0af0fa715dca6886250aee395f308ce1882a0416096f4ebfc029ec6` |
| Noise run plan | `2107d1fc42d7e37c0528d681cb5c1ff2dc703e7e8573376e8ffadae76e6f33f5` |
| Main run plan | `5828ce55dbc23ca14aa5c0074ae8c795f51ecb301bd01de003eb8c7045e27f21` |
| Input bundle manifest | `8af98526e9b278bfea6e12e54fb089b88ffab98dee8af7a44e2073096f146a31` |
| Noise input manifest | `061b91e49abf912ec86b4d75f37b844654c39db8fd08fe9fcabff6b0bc8bb54a` |
| Main input manifest | `55d967230c41de3c2229a2b4b91bcb61048ff67cafc612c8e532663a2a3b7022` |

The core hashes equal v2 because the real Cohort Seal contains exactly the
same 20 unique Group IDs as the complete A0 calibration grid. v3 additionally
exercised the new fail-closed identity check; no frozen input or plan changed.

## Validation

- clean-HEAD full CPU regression: `1918 passed, 15 skipped`
- targeted Option F and related regression: `161 passed, 7 skipped`
- targeted Ruff: PASS
- `git diff --check`: PASS
- server G0 preparation and validation: PASS
- Cohort Seal/A0 Manifest Group-ID equality: PASS
- archive transfer, SHA-256, and tar validation: PASS
- all generated plans and inputs remain `execution_authorized=false`

The v1 and v2 bundles remain immutable historical evidence. This v3 bundle
supersedes them for final PR #99 review.
