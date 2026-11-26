#!/usr/bin/env python3
"""Execute the single authorized Phase 5E Part A Native run.

This entry point performs no implicit mock construction and never retries.  A
reviewed production integration factory must be supplied explicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from kvopt.continuum.clock import SystemMonotonicClock
from kvopt.workload.phase5_gpu_conformance import build_phase5e_review_candidate
from kvopt.workload.phase5e_native_runner import (
    Phase5ENativeRunnerError,
    claim_native_execution_once,
    create_pinned_asyncllm,
    install_production_native_stack,
    load_integration_factory,
    run_phase5e_native_pipeline,
    validate_native_execution_authorization,
    validate_reviewed_plan_identity,
)


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Phase5ENativeRunnerError(f"{path.name} is not a JSON object")
    return value


def _prepare(arguments: argparse.Namespace) -> tuple[object, ...]:
    repository = arguments.repository.resolve()
    freeze_root = arguments.freeze_root.resolve()
    authorization = validate_native_execution_authorization(
        freeze_root=freeze_root,
        authorization_path=arguments.authorization.resolve(),
        repository=repository,
    )
    plan = build_phase5e_review_candidate(authorization.git_sha)
    validate_reviewed_plan_identity(
        frozen_plan=_load_json(freeze_root / "plan.json"),
        rebuilt_plan=plan.to_dict(),
    )
    explicit_inputs = _load_json(freeze_root / "explicit-inputs.json")
    factory = load_integration_factory(arguments.integration_factory)

    # Consumption occurs immediately before the first action that can initialize
    # CUDA.  A failed attempt remains consumed and cannot be silently retried.
    claim_native_execution_once(freeze_root=freeze_root, authorization=authorization)
    engine = create_pinned_asyncllm(plan)
    return authorization, plan, explicit_inputs, factory, engine


async def _run(
    arguments: argparse.Namespace, prepared: tuple[object, ...]
) -> dict[str, object]:
    authorization, plan, explicit_inputs, factory, engine = prepared
    clock = SystemMonotonicClock()
    run_epoch = time.monotonic()
    try:
        evidence, _report, adapter = install_production_native_stack(
            engine=engine,
            plan=plan,
            integration_factory=factory,
            clock=clock,
            run_epoch_monotonic=run_epoch,
        )
    except BaseException:
        shutdown = getattr(engine, "shutdown", None)
        if callable(shutdown):
            shutdown()
        raise
    return await run_phase5e_native_pipeline(
        plan=plan,
        authorization=authorization,
        explicit_inputs=explicit_inputs,
        engine=engine,
        evidence_source=evidence,
        output_root=arguments.output_root.resolve(),
        archive_path=arguments.archive.resolve(),
        run_epoch_monotonic=run_epoch,
        prepared_adapter=adapter,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--freeze-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument(
        "--integration-factory",
        default=(
            "kvopt.workload.phase5e_production_integration:build_phase5e_production_integration"
        ),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    arguments = parser.parse_args()
    # Pinned AsyncLLM eagerly starts its output handler when constructed inside
    # a running loop.  Prepare synchronously so the lifecycle proxy can be
    # installed before the first request starts that handler.
    prepared = _prepare(arguments)
    result = asyncio.run(_run(arguments, prepared))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
