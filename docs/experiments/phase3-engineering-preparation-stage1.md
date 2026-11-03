# Phase 3 Engineering Preparation — Stage 1

Status: **CLOSED / MERGED — PR #93.** At Stage 1 closeout, acquisition and GPU execution were not authorized; current M1 authorization is recorded in [the Phase 3 Data Readiness Decision](phase3-data-readiness-decision.md).

Baseline: main merge `67e5e29b93d547040500f1205c5a2aeb8f469d6e`.
Protocol authority: M4 Final Evaluation Protocol v3, reviewed HEAD
`3a8c3882ad248715b2f5ea90e34baa3875ea0226`.

## Delivered scope

### Six-arm cell materializer

`phase3_materialize.materialize_six_arm_cell()` expands one immutable base cell
into N0/A0/A1/A2/A3/E0 configurations. It:

- preserves the common trace, Explicit Token IDs, pressure inputs and replay
  boundaries;
- copies the real frozen Trace into the cell directory, rewrites every config
  to that local path and binds its SHA-256 in the manifest;
- freezes the complete Pressure Request identity/attempt sequence with
  `stop_on_forced_release=false`, so all arms submit the same requests
  regardless of policy outcomes;
- changes only the frozen Entry/Block policy fields and run identity;
- gives all arms one canonical `shared_input_sha256`;
- always writes `execution_authorized=false`;
- rejects an input that attempts to grant execution authority.

It is deliberately a cell expander, not a Cohort acquisition tool. M6's
Final Evaluation Data Readiness Confirmation supplies the qualified 40-task
inputs. The final task/group/request/replay manifest is frozen as part of
pre-run preparation; no separate Stage 3 Cohort Seal engineering milestone is
required.

### E0

E0 composes the reviewed A3 live evidence classifier and applies the only
permitted policy difference to a fully scorable S2A decision:

`(deadline, identity)`

S2B returns the A3-classified frozen-A1 fallback unchanged. S2C returns the
frozen-A1 delegated decision unchanged. The A3 default strategy and event
schema are not changed. E0 reuses A3's classifier only to determine whether the
evidence is scorable and thereby keep S2B aligned; E0 does not use the Cost
Score to choose an S2A candidate. Native E0 emits
`E0_DEADLINE_RELEASE_DECISION` with the same live content/depth verification
boundary used by A3.

### N0

N0 retains the Pressure invocation and its active Boundary/Stage/Request
context, but executes the pressure selection in Native mode. It therefore:

- performs Native LRU/APC pressure work;
- does not call project-side forced Entry Release;
- does not increment the forced-release counter;
- emits `N0_NO_FORCED_RELEASE` with status `NO_FORCED_RELEASE`;
- does not create a `FORCED_RELEASE_DECISION` event.

The implementation does not remove pressure stages or alter Native ownership.

## Fail-closed boundaries

- E0 and N0 are accepted only for exact campaign kind
  `phase3_final_evaluation`.
- Similar campaign names are rejected by the existing exact allowlists.
- A3/E0 still require live content/depth/event evidence.
- Materialization cannot authorize execution.
- Unknown arms and pre-existing output directories are rejected.

## CPU/Mock evidence

Targeted regression covers:

- six-arm mapping and shared input identity;
- N0/A0 multi-attempt Pressure Request count, identity and Boundary equality;
- real Trace path resolution and Trace SHA equality across all six configs;
- N0 pressure execution with zero forced releases;
- E0 S2A deadline ordering independent of cost ordering;
- E0/A3 S2B identity;
- E0/frozen-A1 S2C identity;
- E0 Native live-evidence coordinator construction;
- exact Phase 3 campaign allowlisting and near-name rejection;
- existing A3 Native binding and physical-attribution regressions.

Targeted result: `82 passed`.

Repository-wide result excluding the Phase 2E clean-worktree authorization
test module: `1712 passed, 8 skipped`. The excluded module intentionally
rejects any dirty Git worktree and does not exercise Phase 3 behavior. A full
clean-tree run is required after commit.
