"""Materialize the final, non-executable Phase 5E Part A freeze package."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .phase5_gpu_conformance import (
    build_phase5e_review_candidate,
    materialize_phase5e_prompt_token_ids,
)
from .phase5_replay import canonical_sha256
from .phase5e_a3_retention import build_phase5e_cpu_mock_retention_manifest

_GIT_SHA = re.compile(r"[0-9a-f]{40}")
RUN_ID = "P5E-A-01"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: object) -> str:
    payload = _json_bytes(value)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _code_binding(repository: Path, relative_path: str) -> dict[str, str]:
    path = repository / relative_path
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": relative_path, "sha256": _sha256_path(path)}


def build_phase5e_freeze_payloads(*, repository: Path, git_sha: str) -> dict[str, Any]:
    """Build mutually consistent final-review payloads without writing files."""

    if _GIT_SHA.fullmatch(git_sha) is None:
        raise ValueError("git_sha must be a full lowercase Git commit identity")
    repository = repository.resolve()
    plan = build_phase5e_review_candidate(git_sha)
    prompt_tokens = {
        request_id: list(token_ids)
        for program in plan.programs
        for request_id, token_ids in zip(
            program.request_ids,
            (
                materialize_phase5e_prompt_token_ids(program.program_ordinal, 1),
                materialize_phase5e_prompt_token_ids(program.program_ordinal, 2),
            ),
            strict=True,
        )
    }
    token_hashes = {
        request_id: canonical_sha256(token_ids) for request_id, token_ids in prompt_tokens.items()
    }
    sealed_hashes = dict(plan.workload_seal["request_token_ids_sha256"])
    if token_hashes != sealed_hashes:
        raise ValueError("materialized Prompt Token IDs differ from Workload Seal")

    explicit_inputs = {
        "schema_version": "phase5e.part_a_explicit_inputs.v1",
        "run_id": RUN_ID,
        "prompt_token_ids": prompt_tokens,
        "prompt_token_ids_sha256": token_hashes,
        "pressure_token_ids": list(plan.pressure.pressure_prompt_token_ids),
        "pressure_token_ids_sha256": plan.pressure.pressure_prompt_token_ids_sha256,
    }
    gates = {
        "schema_version": "phase5e.part_a_gate_contract.v1",
        "run_id": RUN_ID,
        "all_required": True,
        "not_observable_is_pass": False,
        "gates": {
            "P5E-G0": "FREEZE_AND_EXECUTION_BINDINGS_EXACT",
            "P5E-G1": "FROZEN_ARRIVAL_AND_TIE_DISPATCH_EXACT",
            "P5E-G2": "ACTUAL_NATIVE_ENQUEUE_ORDER_EXACT",
            "P5E-G3": "PEAK_NATIVE_INFLIGHT_AT_LEAST_2_AND_OVERLAP_PROVEN",
            "P5E-G4": "EIGHT_DUAL_TERMINAL_NATURAL_LIFECYCLES",
            "P5E-G5": "SAME_ENGINE_BLOCKPOOL_PRESSURE_AND_PHYSICAL_EVIDENCE",
            "P5E-G6": "UNIQUE_FINITE_IDENTITY_CONSISTENT_EXPOSURE_EVIDENCE",
            "P5E-G7": "ZERO_OBSERVABLE_LIFECYCLE_OR_ENGINE_LEAKS",
            "P5E-G8": "INTERNAL_AND_OUTER_ARCHIVE_HASH_VALID",
            "P5E-G9": "RETENTION_INPUT_COMPLETE_AND_HASH_BOUND",
        },
    }
    code_bindings = [
        _code_binding(repository, path)
        for path in (
            "src/kvopt/workload/phase5_gpu_conformance.py",
            "src/kvopt/workload/phase5_replay.py",
            "src/kvopt/workload/phase5_native_async.py",
            "src/kvopt/workload/phase5_asyncllm_adapter.py",
            "src/kvopt/workload/phase5e_native_runner.py",
            "src/kvopt/workload/phase5e_native_runtime.py",
            "src/kvopt/workload/phase5e_native_evidence_source.py",
            "src/kvopt/workload/phase5e_a3_retention.py",
            "src/kvopt/workload/phase5e_freeze.py",
            "scripts/spikes/prepare_phase5e_part_a.py",
            "scripts/spikes/run_phase5e_part_a_native.py",
        )
    ]
    return {
        "plan": plan.to_dict(),
        "workload_seal": dict(plan.workload_seal),
        "explicit_inputs": explicit_inputs,
        "gates": gates,
        "retention_input_fixture": build_phase5e_cpu_mock_retention_manifest(
            plan=plan
        ),
        "code_bindings": code_bindings,
    }


def materialize_phase5e_freeze(
    *, repository: Path, git_sha: str, output_root: Path
) -> dict[str, object]:
    """Write the exclusive final-review package; never authorize execution."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    payloads = build_phase5e_freeze_payloads(repository=repository, git_sha=git_sha)
    hashes = {
        "plan.json": _write_json(output_root / "plan.json", payloads["plan"]),
        "workload-seal.json": _write_json(
            output_root / "workload-seal.json", payloads["workload_seal"]
        ),
        "explicit-inputs.json": _write_json(
            output_root / "explicit-inputs.json", payloads["explicit_inputs"]
        ),
        "gate-contract.json": _write_json(output_root / "gate-contract.json", payloads["gates"]),
        "a3-retention-input-cpu-mock.json": _write_json(
            output_root / "a3-retention-input-cpu-mock.json",
            payloads["retention_input_fixture"],
        ),
    }
    manifest = {
        "schema_version": "phase5e.part_a_execution_manifest.v1",
        "run_id": RUN_ID,
        "git_sha": git_sha,
        "part": "NATURAL_COMPLETION_CONFORMANCE",
        "single_execution_only": True,
        "automatic_retry_allowed": False,
        "timeout_seconds": 600,
        "termination_grace_seconds": 60,
        "gpu_budget_seconds": 1800,
        "target_environment": {
            "gpu": "NVIDIA GeForce RTX 4090 D",
            "minimum_vram_gib": 24,
            "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "model_revision": payloads["plan"]["model_revision"],
            "tokenizer_revision": payloads["plan"]["tokenizer_revision"],
            "vllm": "0.27.1",
            "VLLM_ENABLE_V1_MULTIPROCESSING": "0",
        },
        "input_sha256": hashes,
        "code_bindings": payloads["code_bindings"],
        "part_b_status": "NOT_READY",
        "execution_authorized": False,
        "m1_read_only_confirmation_required": True,
    }
    manifest_hash = _write_json(output_root / "execution-manifest.json", manifest)
    request = {
        "schema_version": "phase5e.part_a_confirmation_request.v1",
        "run_id": RUN_ID,
        "git_sha": git_sha,
        "execution_manifest_sha256": manifest_hash,
        "workload_seal_sha256": hashes["workload-seal.json"],
        "plan_sha256": hashes["plan.json"],
        "explicit_inputs_sha256": hashes["explicit-inputs.json"],
        "gate_contract_sha256": hashes["gate-contract.json"],
        "requested_action": "M1_READ_ONLY_CONFIRMATION_BEFORE_SINGLE_GPU_EXECUTION",
        "execution_authorized": False,
    }
    request_hash = _write_json(output_root / "confirmation-request.json", request)
    all_hashes = {
        **hashes,
        "execution-manifest.json": manifest_hash,
        "confirmation-request.json": request_hash,
    }
    lines = "".join(f"{digest}  {name}\n" for name, digest in sorted(all_hashes.items()))
    (output_root / "sha256-manifest.txt").write_text(lines, encoding="utf-8")
    return {
        "status": "READY_FOR_M1_READ_ONLY_CONFIRMATION",
        "run_id": RUN_ID,
        "git_sha": git_sha,
        "execution_manifest_sha256": manifest_hash,
        "confirmation_request_sha256": request_hash,
        "sha256_manifest_sha256": _sha256_path(output_root / "sha256-manifest.txt"),
        "execution_authorized": False,
    }
