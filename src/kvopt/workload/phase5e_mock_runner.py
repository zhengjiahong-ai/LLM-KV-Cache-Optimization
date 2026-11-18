"""End-to-end CPU/Mock runner for the Phase 5E Part A evidence path."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from .phase5_archive import (
    create_phase5_evidence_archive,
    validate_phase5_evidence_archive,
)
from .phase5_gpu_conformance import Phase5GPUConformancePlan
from .phase5_replay import canonical_sha256
from .phase5e_part_a import (
    PartAAdapter,
    PartARequestInput,
    execute_phase5e_part_a,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def run_phase5e_part_a_mock_pipeline(
    *,
    plan: Phase5GPUConformancePlan,
    run_id: str,
    requests: Mapping[str, PartARequestInput],
    adapter: PartAAdapter,
    candidate_exposure_evaluator: Callable[[], Mapping[str, object]],
    run_epoch_monotonic: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
    output_root: Path,
    archive_path: Path,
) -> dict[str, object]:
    """Exercise execute → gates → archive without claiming GPU Conformance."""

    if output_root.exists():
        raise FileExistsError(output_root)
    if archive_path.exists():
        raise FileExistsError(archive_path)
    output_root.mkdir(parents=True)
    result = await execute_phase5e_part_a(
        plan=plan,
        run_id=run_id,
        requests=requests,
        adapter=adapter,
        candidate_exposure_evaluator=candidate_exposure_evaluator,
        run_epoch_monotonic=run_epoch_monotonic,
        monotonic=monotonic,
        sleep=sleep,
    )
    result_payload = result.to_dict()
    metadata = {
        "schema_version": "phase5e.part_a_mock_run.v1",
        "run_id": run_id,
        "execution_mode": "CPU_MOCK",
        "gpu_conformance_claim": "NOT_ESTABLISHED",
        "plan_sha256": plan.sha256,
        "result_sha256": canonical_sha256(result_payload),
        "status": result.status,
    }
    _write_json(output_root / "plan.json", plan.to_dict())
    _write_json(output_root / "controller-result.json", result_payload)
    _write_json(output_root / "run.json", metadata)
    archive = create_phase5_evidence_archive(
        source_root=output_root,
        archive_path=archive_path,
        required_relative_paths=("plan.json", "controller-result.json", "run.json"),
    )
    validation = validate_phase5_evidence_archive(archive_path)
    if validation["status"] != "PASS":
        raise RuntimeError("Phase 5E Mock archive failed independent validation")
    return {
        "schema_version": "phase5e.part_a_mock_pipeline_result.v1",
        "status": result.status,
        "run_id": run_id,
        "execution_mode": "CPU_MOCK",
        "gpu_conformance_claim": "NOT_ESTABLISHED",
        "archive": archive,
        "archive_validation": validation,
    }
