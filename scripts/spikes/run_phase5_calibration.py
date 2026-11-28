#!/usr/bin/env python3
"""Execute exactly one frozen SWE Calibration run without automatic retry."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from importlib.metadata import entry_points
from pathlib import Path

from kvopt.workload.phase5_calibration_archive import (
    finalize_calibration_run_archive,
    normalize_calibration_native_evidence,
    validate_calibration_native_evidence,
)
from kvopt.workload.phase5_calibration_run_contract import (
    CalibrationRunContractError,
    claim_calibration_run_once,
    materialize_calibration_run_contract,
)
from kvopt.workload.phase5_calibration_runner import (
    build_calibration_request_inputs,
    create_calibration_asyncllm,
    execute_calibration_replay,
    install_official_calibration_runtime,
    install_project_calibration_runtime,
    official_timer_sink,
    project_timer_sink,
)
from kvopt.workload.phase5e_engine_core_bridge import (
    validate_engine_core_plugin_registration,
)


def _current_head(repository: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_clean_authorized_head(repository: Path, contract: dict[str, object]) -> str:
    head = _current_head(repository)
    if head != contract.get("git_sha"):
        raise CalibrationRunContractError("runtime HEAD differs from Calibration freeze")
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise CalibrationRunContractError("Calibration execution requires a clean worktree")
    return head


def _validate_official_plugin() -> None:
    matches = [
        point
        for point in entry_points(group="vllm.general_plugins")
        if point.name == "kvopt_phase5_official_observer"
    ]
    expected = (
        "kvopt.workload.phase5_official_engine_core_plugin:"
        "register_phase5_official_observer"
    )
    if len(matches) != 1 or matches[0].value != expected:
        raise CalibrationRunContractError("Official observer plugin is not installed")


def _prepare(arguments: argparse.Namespace) -> tuple[object, ...]:
    repository = arguments.repository.resolve()
    contract = materialize_calibration_run_contract(
        execution_manifest_path=arguments.execution_manifest.resolve(),
        run_id=arguments.run_id,
        path_replacements=dict(arguments.path_map),
    )
    git_sha = _validate_clean_authorized_head(repository, contract)
    if contract["system_id"] == "CONTINUUM_OFFICIAL":
        _validate_official_plugin()
    else:
        validate_engine_core_plugin_registration()
    claim = claim_calibration_run_once(
        state_root=arguments.state_root.resolve(),
        run_contract=contract,
        git_sha=git_sha,
    )
    try:
        engine = create_calibration_asyncllm(contract)
    except BaseException as error:
        consumption = json.loads(claim.read_text(encoding="utf-8"))
        finalize_calibration_run_archive(
            output_root=arguments.output_root.resolve(),
            archive_path=arguments.archive.resolve(),
            run_contract=contract,
            consumption_record=consumption,
            preflight={"status": "FAIL_CLOSED_BEFORE_ENGINE_INITIALIZATION"},
            controller_result=None,
            native_evidence=(),
            engine_cleanup={"status": "NOT_STARTED"},
            failure=error,
        )
        raise
    return contract, claim, engine


async def _shutdown_engine(engine: object) -> dict[str, object]:
    shutdown = getattr(engine, "shutdown", None)
    if not callable(shutdown):
        return {"status": "FAIL_CLOSED", "reason": "shutdown unavailable"}
    shutdown()
    output = getattr(engine, "output_handler", None)
    if isinstance(output, asyncio.Task) and not output.done():
        await asyncio.gather(output, return_exceptions=True)
    return {
        "schema_version": "phase5.swe_calibration_engine_cleanup.v1",
        "status": "PASS",
        "output_handler_done": output is None or output.done(),
    }


async def _run(arguments: argparse.Namespace, prepared: tuple[object, ...]) -> dict[str, object]:
    contract, claim_path, engine = prepared
    assert isinstance(contract, dict)
    assert isinstance(claim_path, Path)
    epoch = time.monotonic()
    runtime = None
    controller_result = None
    native_evidence: list[dict[str, object]] = []
    cleanup: dict[str, object] = {"status": "NOT_RUN"}
    failure: BaseException | None = None
    preflight: dict[str, object] = {}
    try:
        if contract["system_id"] == "CONTINUUM_OFFICIAL":
            runtime = await install_official_calibration_runtime(
                engine=engine,
                run_contract=contract,
                run_epoch_monotonic=epoch,
                clock=time.monotonic,
            )
            timer_sink = official_timer_sink()
        else:
            runtime = await install_project_calibration_runtime(
                engine=engine,
                run_contract=contract,
                run_epoch_monotonic=epoch,
                clock=time.monotonic,
            )
            timer_sink = project_timer_sink(runtime)
        preflight = {
            "schema_version": "phase5.swe_calibration_native_preflight.v1",
            "status": "PASS",
            "run_id": contract["run_id"],
            "git_sha": contract["git_sha"],
            "run_contract_sha256": contract["run_contract_sha256"],
            "runtime_installation": dict(runtime.installation_report),
            "preheat_performed": False,
            "empty_cache_preflight_passed": True,
        }
        from vllm.sampling_params import SamplingParams  # type: ignore[import-not-found]

        sampling = SamplingParams(
            temperature=0.0,
            top_p=1.0,
            top_k=0,
            seed=20261201,
            max_tokens=128,
            ignore_eos=False,
        )
        requests = build_calibration_request_inputs(
            run_contract=contract, sampling_params=sampling
        )
        controller_result = await execute_calibration_replay(
            run_id=str(contract["run_id"]),
            expected_enqueue_order=contract["expected_native_enqueue_order"],
            requests=requests,
            adapter=runtime.adapter,
            timer_sink=timer_sink,
            run_epoch_monotonic=epoch,
            completion_timeout_seconds=600.0,
            monotonic=time.monotonic,
        )
        if contract["system_id"] == "CONTINUUM_OFFICIAL":
            exported = await runtime.export_evidence()
            events = exported.get("events")
            if not isinstance(events, list):
                raise RuntimeError("Official evidence lacks events")
            native_evidence = [dict(row) for row in events if isinstance(row, dict)]
        else:
            await runtime.evidence.refresh()
            native_evidence = [dict(row) for row in runtime.evidence.raw_evidence()]
        native_evidence = normalize_calibration_native_evidence(native_evidence)
        evidence_validation = validate_calibration_native_evidence(
            run_contract=contract, native_evidence=native_evidence
        )
        if evidence_validation["status"] != "PASS":
            raise RuntimeError(
                "Calibration Native APC evidence is incomplete: "
                + ",".join(evidence_validation["failure_reasons"])
            )
    except BaseException as error:  # noqa: BLE001 - preserve the failed run
        failure = error
    finally:
        try:
            cleanup = await _shutdown_engine(engine)
        except BaseException as error:  # noqa: BLE001 - archive cleanup failure
            cleanup = {"status": "FAIL_CLOSED", "failure_reason": repr(error)}
            if failure is None:
                failure = error
    consumption = json.loads(claim_path.read_text(encoding="utf-8"))
    archive = finalize_calibration_run_archive(
        output_root=arguments.output_root.resolve(),
        archive_path=arguments.archive.resolve(),
        run_contract=contract,
        consumption_record=consumption,
        preflight=preflight or {"status": "FAIL_CLOSED_BEFORE_INSTALL"},
        controller_result=controller_result,
        native_evidence=native_evidence,
        engine_cleanup=cleanup,
        failure=failure,
    )
    if failure is not None:
        raise failure
    return archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--execution-manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument(
        "--path-map",
        action="append",
        default=[],
        type=lambda value: tuple(value.split("=", 1)),
        metavar="SOURCE=TARGET",
    )
    arguments = parser.parse_args()
    if any(len(value) != 2 or not value[0] or not value[1] for value in arguments.path_map):
        parser.error("--path-map must use SOURCE=TARGET")
    prepared = _prepare(arguments)
    result = asyncio.run(_run(arguments, prepared))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
