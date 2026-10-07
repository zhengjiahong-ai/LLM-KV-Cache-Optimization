# Phase 2A M6 H1 Independent Campaign Design

Status: **AWAITING M1 REVIEW — HOLDOUT MATERIALIZATION IS NOT AUTHORIZED**

This document specifies the H1 independent campaign before any sealed scenario
or outcome is materialized. The machine-readable companion is
`configs/phase2/h1-independent-campaign-design.json`.

## 1. Statistical design

The campaign contains **42 independent scenario draws**, split evenly across
F1–F6 with **7 draws per family**. Each scenario is repeated under three seeds
(`101`, `211`, `307`) only to estimate runtime noise and reproducibility.
Seeds, decision rows, candidates, and decision positions are not independent
statistical samples.

The planned run count after authorization is 126, but the acceptance protocol
first collapses seed repetitions and decision positions to one value per
scenario draw.

| Family | Draws | Primary conditioning axes |
| --- | ---: | --- |
| F1 | 7 | candidate count; homogeneous versus heterogeneous candidates |
| F2 | 7 | prefix size and recompute-cost spread |
| F3 | 7 | return behavior and tool/lifecycle pattern |
| F4 | 7 | pressure depth, multi-release, repeated pressure |
| F5 | 7 | concurrency, queue delay, eta |
| F6 | 7 | shared ownership, prefix evolution, block-slot reuse |

Family membership conditions the sampling distribution; it does not select a
copied scenario template. All non-focus axes continue to vary.

## 2. Predeclared variation

The design manifest freezes finite supports and integer sampling weights for:

- candidate counts from 2 through 7;
- prefix sizes from 16 through 512 tokens, including the required
  16/32/128/256/512 points and intermediate sizes;
- early, near-horizon, outside-horizon, and no-return behavior;
- eta values on both sides of 1 and queue delay from zero to 2 seconds;
- tool/lifecycle and serialized, overlapping, burst, or sustained-queue states;
- shallow, deep multi-release, and repeated pressure;
- exclusive and shared-prefix ownership.

Eta and queue delay are sampled per candidate so the campaign can contain
within-decision variation. Minimum corner-case quotas prevent low-weight cases
from disappearing by chance. Every materialized scenario must be structurally
unique.

## 3. Seal and custody

Materialization is a separate future operation. This revision intentionally
contains no scenario list, sampler seed, trace, config, runtime observation, or
outcome. M6 keeps custody of the eventual holdout; M4 must not receive outcome
artifacts before the rule and acceptance inputs are frozen.

After M1 approves the distribution, M6 may use a committed sampler seed to
generate a private scenario manifest without executing it. Before any outcome
is produced, a freeze record must contain SHA-256 commitments for:

1. this distribution manifest;
2. the generated scenario manifest;
3. the rule implementation;
4. the acceptance protocol;
5. the baseline-derived `epsilon_latency` calibration.

Scenario generation requires M1 design approval. Outcome execution is a
separate authorization and requires all of the following gates:

- Issue #34 feature-missingness coverage is merged;
- the Level-B raw observation seam is ready;
- baseline repeats have frozen `epsilon_latency`;
- the rule and acceptance protocol are hashed;
- M1 approves the campaign design.

Only then may the 42 sealed scenarios be executed. Scenario generation and
outcome execution are separate steps; creating a scenario manifest must not run
the workload or expose any outcome to M4.

## 4. Capability dependencies

The current v4 campaign generator cannot express all of this design. The H1
materializer must be added only after review and must demonstrate that it can
encode per-candidate eta/queue delay, no-return branches, shared ownership, and
the declared concurrency/pressure patterns. Unsupported fields must fail
materialization rather than silently fall back to old defaults.

Direct runtime evidence also remains a hard dependency. Native cached-prefix
amount, actual recomputed/prefill tokens, and request-level serving timing must
come from the runtime observation seam, never from prefix identity, planned
return, or logical release.

## 5. Review boundary

This task package asks M1 to review the distribution, family conditioning,
corner-case quotas, capability gates, and sealing procedure. It does **not** ask
for permission to execute the final holdout. Any requested distribution change
must be made before the materialization authorization and recorded in the next
design version.
