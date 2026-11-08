# Phase 3 Cohort Candidate Plan

Status: **PREREGISTERED — ACQUISITION NOT YET STARTED**

This is the first ordered Phase 3 dataset deliverable. It freezes candidate
identity and qualification-independent acquisition order before any new Agent
trace or Native policy outcome is observed.

## Source binding

- Source: `configs/phase2/continuum-w1c-stratified-sample-v1.json`
- Source SHA-256:
  `a1fd9554d55c934590c30fd55768c617c8283a7203ece316121a057b1db3985f`
- Candidate frame: exactly 80 previously unacquired W1-C tasks.
- Historical Pilot tasks excluded: 20/20.
- Source repositories represented by the remaining frame: 10.

## Frozen assignment

- Manifest: `configs/phase3/phase3-cohort-candidate-plan-v1.json`
- Manifest SHA-256:
  `5acf735d7b94a0d77222194e325abdeea9ea86f4e15ac8b23fe468df02f06290`
- Candidate-assignment canonical SHA-256:
  `4b44ddcb5e5dd342efb9f456f614115bb002600e76f13b7abddc210d16e23ef6`
- Primary: 40 tasks across all 10 available repositories.
- Reserve: 24 tasks.

The ordered IDs, repositories, source revisions, static issue features, roles,
role ranks, and acquisition ranks are recorded directly in the manifest.

## Deterministic selection

The plan uses seed `20261103`. It allocates at least one Primary slot to every
repository and distributes the remaining Primary capacity proportionally.
Within each repository it stratifies tasks by problem-statement length
quartile and ranks each stratum by a seeded SHA-256 key. Acquisition order is
Primary before Reserve and repository round-robin within each role.

No Agent result, Native execution result, cache-policy outcome, solution-patch
feature, or task success label participates in selection.

## Qualification and promotion

Qualification requires complete full-payload trace, lifecycle/tool and
failure/right-censoring evidence, Explicit Token IDs, hash-bound sidecar,
valid Profile provenance, Native replay executability, and frozen
model/tokenizer/context/runtime compatibility.

A failed Primary may be replaced only using the preregistered Reserve order:
the lowest-ranked qualified unused Reserve from the same repository first,
otherwise the lowest-ranked qualified unused Reserve. Promotion uses only the
pre-Native qualification record. It never reads policy outcomes.

If promotion cannot produce 40 qualified tasks, 20 different-repository
groups, and at least 10 repositories, processing stops. The candidate pool is
not expanded and the requirements are not weakened.

## Current execution boundary

No Agent acquisition was started while producing this plan. The local model
endpoint at `127.0.0.1:8100` and Docker daemon were not running during the
static freeze, so no candidate has been assigned a qualification result. The
next action is to commit this preregistration, start the pinned acquisition
environment, and execute candidates strictly in manifest acquisition order.
