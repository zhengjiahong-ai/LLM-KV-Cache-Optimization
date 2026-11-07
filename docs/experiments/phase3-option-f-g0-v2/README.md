# Phase 3 Option F G0 Review Bundle v2

This directory contains the small, reviewable manifests regenerated on the
real evidence server after the PR #99 concentrated review fixes, at Git HEAD
`1e210f681ae257858a33f295b2e7ef118e218e62`.

## Result

- status: `READY_FOR_M1_G0_REVIEW`
- execution authorized: `false`
- Noise Calibration plan: 30 A0 runs
- Main Campaign plan: 240 six-arm runs
- total new-run budget: 270
- GPU runs performed by regeneration: 0

The generated configuration tree and its evidence archive are intentionally
not committed. The complete archive is retained externally as
`phase3-option-f-g0-v2-evidence.tar.gz` with SHA-256:

`ea1a49037543c850471b1e94b1b0cf4b3a67935de097c908fd2552026f53b47a`

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

The v2 generation independently validated the Formal/Native Run-ID bijection,
the complete 20×2 A0 calibration mapping, Native run schema/identity/success,
and calibration report schema/status/identity. The Noise plan binds exact
repeats `{1,2,3}`, unique Run IDs, and all three frozen strata. All generated
plans and inputs remain unauthorized.

## Validation

- local clean-HEAD full CPU regression: `1915 passed, 15 skipped`
- targeted Option F and related regression: `158 passed, 7 skipped`
- targeted Ruff: PASS
- `git diff --check`: PASS
- server G0 preparation and validation: PASS
- archive transfer, SHA-256, and tar validation: PASS
- complete generated manifest verification: PASS

The historical v1 bundle remains available for provenance but is superseded
for PR #99 review by this v2 bundle.
