# Development Guide

## Main branch

`main` must remain runnable. Do not push directly to `main`; use reviewed pull requests.

## Branch naming

Use `feature/scheduler-xxx`, `feature/baseline-xxx`, `feature/optimization-xxx`, `feature/workload-xxx`, `feature/evaluation-xxx`, `fix/xxx`, or `docs/xxx`.

## Pull Requests

Every PR should state its purpose, main changes, test result, and affected modules. Keep PRs small and focused.

## Ownership

- Member 1: architecture, scheduler, integration.
- Member 3: baseline policies.
- Member 4: optimized policies.
- Member 5: workloads and benchmarks.
- Member 6: metrics, profiling, visualization, and evaluation.

Avoid direct dependencies on another module's private implementation. Use the public interfaces under `src/kvopt`.
