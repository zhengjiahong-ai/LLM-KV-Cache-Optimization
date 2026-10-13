"""Materialize the frozen bounded Phase 2C native pilot without executing it."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .phase2c_native_pilot import (
    PILOT_PREFIX_GENERATOR_VERSION,
    load_and_validate_pilot,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_pilot(
    *,
    authorization_path: Path,
    contract_path: Path,
    cases_path: Path,
    output_dir: Path,
) -> Path:
    authorization, contract, document = load_and_validate_pilot(
        authorization_path=authorization_path,
        contract_path=contract_path,
        cases_path=cases_path,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, Any]] = []
    for case in document["cases"]:
        for repeat in range(1, int(document["controlled_repeats"]) + 1):
            run_id = f"{case['case_id']}-repeat-{repeat}"
            config_name = f"{run_id}.config.json"
            trace_name = f"{run_id}.trace.json"
            requests = case["requests"]
            prefix_segments = {request["request_id"]: request["segments"] for request in requests}
            program_sizes: dict[str, int] = {}
            for request in requests:
                tokens = sum(segment[1] for segment in request["segments"])
                program = request["program_id"]
                program_sizes[program] = max(program_sizes.get(program, 0), tokens)

            planned_requests: list[dict[str, Any]] = []
            program_request_counts: dict[str, int] = {}
            for request in requests:
                program = request["program_id"]
                program_request_counts[program] = program_request_counts.get(program, 0) + 1
            seen: dict[str, int] = {}
            for index, request in enumerate(requests):
                program = request["program_id"]
                seen[program] = seen.get(program, 0) + 1
                terminal = seen[program] == program_request_counts[program]
                planned_requests.append(
                    {
                        "program_id": program,
                        "request_id": request["request_id"],
                        "turn_index": seen[program],
                        "planned_arrival_offset_seconds": float(index),
                        "prompt": f"Phase 2C {case['case_id']} {request['request_id']}",
                        "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                        "is_terminal": terminal,
                        "next_tool_type": None if terminal else "phase2c-pilot",
                        "tool_gap_seconds": None if terminal else 1.0,
                    }
                )

            pressure_enabled = case["pressure"] == "controlled_native_allocation"
            pressure_stages = (
                [
                    {
                        "stage_id": "phase2c-native-pressure",
                        "planned_arrival_offset_seconds": 0.5,
                        "prompt": "Phase 2C controlled native allocation pressure",
                        "max_requests": 2,
                        "stop_on_forced_release": True,
                    }
                ]
                if pressure_enabled
                else []
            )
            trace = {
                "schema_version": "phase2.trace.v1",
                "trace_id": f"phase2c-native-pilot-{run_id}",
                "requests": planned_requests,
                "pressure_stages": pressure_stages,
            }
            pressure_tokens = int(case.get("pressure_prompt_tokens", 512))
            pressure_blocks = pressure_tokens // int(document["block_size_tokens"])
            initial_shortage_blocks = 8 if pressure_enabled else 1
            protected_prefix_blocks = sum(
                tokens // int(document["block_size_tokens"]) for tokens in program_sizes.values()
            )
            block_override = protected_prefix_blocks + pressure_blocks + 1 - initial_shortage_blocks
            config = {
                "schema_version": "phase2.config.v1",
                "runtime_mode": "vllm-metal-observability",
                "backend_factory": document["runtime"]["backend_factory"],
                "backend_revision": "phase2c-segmented-native-pilot-v1",
                "campaign_kind": "phase2c_bounded_native_pilot",
                "policy": "continuum-baseline",
                "seed": 20261013 + repeat,
                "observe": True,
                "model": document["model"],
                "tokenizer": document["model"],
                "generation": {
                    "max_new_tokens": document["runtime"]["max_new_tokens"],
                    "temperature": document["runtime"]["temperature"],
                },
                "batching": {"max_concurrent_requests": 1},
                "cache": {
                    "block_size": document["block_size_tokens"],
                    "block_override": block_override,
                },
                "pressure": {
                    "initial_shortage_blocks": initial_shortage_blocks,
                    "required_blocks": pressure_blocks,
                    "safety_ceiling": 2,
                },
                "backend_options": {
                    "execute_planned_timing": False,
                    "executor_mode": "submit_collect",
                    "gpu_memory_utilization": document["runtime"]["gpu_memory_utilization"],
                    "phase2c_native_pilot_mode": True,
                    "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                    "prefix_segments_by_request": prefix_segments,
                    "program_prefix_tokens": program_sizes,
                    "pressure_prompt_tokens": pressure_tokens,
                    "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
                },
                "trace": trace_name,
                "phase2c_pilot": {
                    "case_id": case["case_id"],
                    "topology": case["topology"],
                    "repeat": repeat,
                    "pressure": case["pressure"],
                    "expected_requests": requests,
                },
            }
            config_path = output_dir / config_name
            trace_path = output_dir / trace_name
            _write_json(config_path, config)
            _write_json(trace_path, trace)
            entries.append(
                {
                    "run_id": run_id,
                    "case_id": case["case_id"],
                    "topology": case["topology"],
                    "repeat": repeat,
                    "config": config_name,
                    "config_sha256": _sha256(config_path),
                    "trace": trace_name,
                    "trace_sha256": _sha256(trace_path),
                }
            )

    manifest = {
        "schema_version": "phase2c.native_pilot_materialization.v1",
        "run_kind": "NON_HOLDOUT_NATIVE_PILOT",
        "pilot_id": document["pilot_id"],
        "authorization_sha256": _sha256(authorization_path),
        "contract_sha256": _sha256(contract_path),
        "cases_sha256": _sha256(cases_path),
        "authorization_status": authorization["authorization_status"],
        "controlled_repeats": contract["controlled_repeats"],
        "planned_run_count": len(entries),
        "runs": entries,
        "execution_started": False,
        "formal_campaign_authorized": False,
        "cost_aware_policy_authorized": False,
    }
    manifest_path = output_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    manifest = materialize_pilot(
        authorization_path=arguments.authorization,
        contract_path=arguments.contract,
        cases_path=arguments.cases,
        output_dir=arguments.output_dir,
    )
    print(f"wrote Phase 2C bounded native pilot: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
