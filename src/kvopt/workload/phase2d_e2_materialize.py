"""Materialize the authorized four-run Phase 2D E2 fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .phase2c_native_pilot import PILOT_PREFIX_GENERATOR_VERSION


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_fixture(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("E2 fixture must be an object")
    if value.get("schema_version") != "phase2d.e2_fixture.v1":
        raise ValueError("unsupported E2 fixture schema")
    if value.get("run_kind") != "NON_HOLDOUT_RESEARCH_PILOT":
        raise ValueError("E2 must remain a non-holdout research pilot")
    if value.get("execution_authorized") is not True:
        raise ValueError("E2 execution is not authorized")
    if value.get("forced_victim_authorized_in_e2") is not False:
        raise ValueError("E2 must not force a victim")
    if value.get("formal_campaign") is not False or value.get("cost_aware_policy") is not False:
        raise ValueError("E2 cannot be formal or Cost-Aware")
    if value.get("controlled_repeats") != 2:
        raise ValueError("E2 repeat count must remain two")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise ValueError("E2 requires one shared case and one negative control")
    return value


def materialize_e2(*, fixture_path: Path, output_dir: Path) -> Path:
    fixture_path = fixture_path.resolve()
    fixture = _load_fixture(fixture_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    block_size = int(fixture["block_size_tokens"])
    pressure_tokens = int(fixture["pressure_prompt_tokens"])
    initial_shortage = int(fixture["initial_shortage_blocks"])
    program_prefix_tokens = {"e2-a": 192, "e2-b": 192}
    protected_blocks = sum(value // block_size for value in program_prefix_tokens.values())
    pressure_blocks = pressure_tokens // block_size
    block_override = protected_blocks + pressure_blocks + 1 - initial_shortage
    runs: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        for repeat in range(1, 3):
            run_id = f"{case['case_id']}-repeat-{repeat}"
            config_name = f"{run_id}.config.json"
            trace_name = f"{run_id}.trace.json"
            request_segments = {
                "e2-a:1": case["program_a_segments"],
                "e2-b:1": case["program_b_segments"],
                "e2-a:2": case["program_a_segments"],
                "e2-b:2": case["program_b_segments"],
            }
            requests = [
                {
                    "program_id": program,
                    "request_id": request_id,
                    "turn_index": turn,
                    "planned_arrival_offset_seconds": offset,
                    "prompt": f"Phase 2D E2 {case['case_id']} {request_id}",
                    "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                    "is_terminal": turn == 2,
                    "next_tool_type": None if turn == 2 else "phase2d-e2",
                    "tool_gap_seconds": None if turn == 2 else 1.0,
                }
                for program, request_id, turn, offset in (
                    ("e2-a", "e2-a:1", 1, 0.0),
                    ("e2-b", "e2-b:1", 1, 1.0),
                    ("e2-a", "e2-a:2", 2, 3.0),
                    ("e2-b", "e2-b:2", 2, 4.0),
                )
            ]
            trace = {
                "schema_version": "phase2.trace.v1",
                "trace_id": f"phase2d-e2-{run_id}",
                "requests": requests,
                "pressure_stages": [
                    {
                        "stage_id": "phase2d-e2-pressure",
                        "planned_arrival_offset_seconds": 2.0,
                        "prompt": "Phase 2D E2 controlled native allocation pressure",
                        "max_requests": 1,
                        "stop_on_forced_release": True,
                    }
                ],
            }
            config = {
                "schema_version": "phase2.config.v1",
                "runtime_mode": "vllm-metal-observability",
                "backend_factory": fixture["runtime"]["backend_factory"],
                "backend_revision": "phase2d-e2-shared-retention-v1",
                "campaign_kind": "phase2d_non_holdout_research_pilot",
                "policy": "continuum-baseline",
                "seed": 20261020 + repeat,
                "observe": True,
                "model": fixture["model"],
                "tokenizer": fixture["model"],
                "generation": {
                    "max_new_tokens": fixture["runtime"]["max_new_tokens"],
                    "temperature": fixture["runtime"]["temperature"],
                },
                "batching": {"max_concurrent_requests": 1},
                "cache": {"block_size": block_size, "block_override": block_override},
                "pressure": {
                    "initial_shortage_blocks": initial_shortage,
                    "required_blocks": pressure_blocks,
                    "safety_ceiling": 1,
                },
                "backend_options": {
                    "execute_planned_timing": False,
                    "executor_mode": "submit_collect",
                    "gpu_memory_utilization": fixture["runtime"]["gpu_memory_utilization"],
                    "phase2c_native_pilot_mode": True,
                    "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                    "prefix_segments_by_request": request_segments,
                    "program_prefix_tokens": program_prefix_tokens,
                    "pressure_prompt_tokens": pressure_tokens,
                    "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
                },
                "trace": trace_name,
                "phase2d_stage": {
                    "stage": "E2",
                    "case_id": case["case_id"],
                    "repeat": repeat,
                    "expected_shared_protected_blocks": case["expected_shared_protected_blocks"],
                    "forced_victim": None,
                },
            }
            config_path = output_dir / config_name
            trace_path = output_dir / trace_name
            _write_json(config_path, config)
            _write_json(trace_path, trace)
            runs.append(
                {
                    "run_id": run_id,
                    "case_id": case["case_id"],
                    "repeat": repeat,
                    "config": config_name,
                    "config_sha256": _sha256(config_path),
                    "trace": trace_name,
                    "trace_sha256": _sha256(trace_path),
                }
            )
    manifest = {
        "schema_version": "phase2d.e2_materialization.v1",
        "run_kind": "NON_HOLDOUT_RESEARCH_PILOT",
        "fixture_sha256": _sha256(fixture_path),
        "planned_run_count": len(runs),
        "runs": runs,
        "execution_started": False,
        "forced_victim": False,
        "formal_campaign": False,
    }
    path = output_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    path = materialize_e2(fixture_path=arguments.fixture, output_dir=arguments.output_dir)
    print(f"wrote Phase 2D E2 fixture: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
