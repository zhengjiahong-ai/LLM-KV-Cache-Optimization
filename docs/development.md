# Development Guide

## Main branch

`main` must remain runnable. Do not push directly to `main`; use reviewed pull requests.

## Branch naming

Use `feature/scheduler-xxx`, `feature/baseline-xxx`, `feature/optimization-xxx`, `feature/workload-xxx`, `feature/evaluation-xxx`, `fix/xxx`, or `docs/xxx`.

## Pull Requests

Every PR should state its purpose, main changes, test result, and affected modules. Keep PRs small and focused.

## Ownership

For current Phase 2 work packages, [team-responsibilities.md](team-responsibilities.md) and the [canonical research-status ledger](research-status.md) supersede early generic ownership labels.

- Member 1: architecture, integration, experimental authorization and evidence adjudication.
- Member 3: frozen baseline maintenance and validation-backed fixes.
- Member 4: A1/A2 algorithm analysis, simple-rule/Sufficient-first comparison and mechanism interpretation.
- Member 5: shared workload/benchmark runner substrate and concrete interface support.
- Member 6: current W0/W1 Agent acquisition, replay, Native execution, profiling, missingness and evaluation.

Avoid direct dependencies on another module's private implementation. Use the public interfaces under `src/kvopt`.
