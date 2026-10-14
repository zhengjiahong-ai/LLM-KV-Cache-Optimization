"""Materialize the authorized two-arm Phase 2D E4 concurrency fixture."""

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


def materialize_e4(*, fixture_path: Path, output_dir: Path) -> Path:
    fixture_path = fixture_path.resolve()
    fixture: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != "phase2d.e4_fixture.v1":
        raise ValueError("unsupported E4 fixture schema")
    if fixture.get("run_kind") != "NON_HOLDOUT_RESEARCH_PILOT":
        raise ValueError("E4 must remain a non-holdout research pilot")
    if fixture.get("execution_authorized") is not True:
        raise ValueError("E4 execution is not authorized")
    if fixture.get("formal_campaign") is not False or fixture.get("cost_aware_policy") is not False:
        raise ValueError("E4 cannot be formal or Cost-Aware")
    output_dir.mkdir(parents=True, exist_ok=False)
    block_size = int(fixture["block_size_tokens"])
    pressure_tokens = int(fixture["pressure_prompt_tokens"])
    program_prefix_tokens = {"e4-a": 192, "e4-b": 192}
    pressure_blocks = pressure_tokens // block_size
    protected_blocks = sum(value // block_size for value in program_prefix_tokens.values())
    block_override = protected_blocks + pressure_blocks + 1 - int(fixture["initial_shortage_blocks"])
    segments = {
        "e4-a": [["e4-shared-root", 128], ["e4-branch-a", 64]],
        "e4-b": [["e4-shared-root", 128], ["e4-branch-b", 64]],
    }
    runs: list[dict[str, Any]] = []
    for release_program in program_prefix_tokens:
        arm = f"release-{release_program[-1]}"
        run_id = f"e4-concurrent-shared-{arm}-repeat-1"
        config_name = f"{run_id}.config.json"
        trace_name = f"{run_id}.trace.json"
        requests = [
            {
                "program_id": program,
                "request_id": f"{program}:1",
                "turn_index": 1,
                "planned_arrival_offset_seconds": 0.0,
                "prompt": f"Phase 2D E4 {program}:1",
                "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                "is_terminal": False,
                "next_tool_type": "phase2d-e4",
                "tool_gap_seconds": 1.0,
            }
            for program in ("e4-a", "e4-b")
        ]
        requests.extend(
            {
                "program_id": program,
                "request_id": f"{program}:2",
                "turn_index": 2,
                "planned_arrival_offset_seconds": 3.0,
                "prompt": f"Phase 2D E4 {program}:2",
                "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                "is_terminal": True,
                "next_tool_type": None,
                "tool_gap_seconds": None,
            }
            for program in ("e4-a", "e4-b")
        )
        request_segments = {
            str(row["request_id"]): segments[str(row["program_id"])] for row in requests
        }
        trace = {
            "schema_version": "phase2.trace.v1",
            "trace_id": f"phase2d-{run_id}",
            "requests": requests,
            "pressure_stages": [
                {
                    "stage_id": "phase2d-e4-pressure",
                    "planned_arrival_offset_seconds": 2.0,
                    "prompt": "Phase 2D E4 controlled native allocation pressure",
                    "max_requests": 1,
                    "stop_on_forced_release": True,
                }
            ],
        }
        config = {
            "schema_version": "phase2.config.v1",
            "runtime_mode": "vllm-metal-observability",
            "backend_factory": fixture["runtime"]["backend_factory"],
            "backend_revision": "phase2d-e4-concurrency-v1",
            "campaign_kind": "phase2d_non_holdout_research_pilot",
            "policy": "continuum-baseline",
            "seed": 20261041,
            "observe": True,
            "model": fixture["model"],
            "tokenizer": fixture["model"],
            "generation": {
                "max_new_tokens": fixture["runtime"]["max_new_tokens"],
                "temperature": fixture["runtime"]["temperature"],
            },
            "batching": {"max_concurrent_requests": 2},
            "cache": {"block_size": block_size, "block_override": block_override},
            "pressure": {
                "initial_shortage_blocks": fixture["initial_shortage_blocks"],
                "required_blocks": pressure_blocks,
                "safety_ceiling": 1,
            },
            "backend_options": {
                "execute_planned_timing": False,
                "executor_mode": "submit_collect",
                "gpu_memory_utilization": fixture["runtime"]["gpu_memory_utilization"],
                "phase2c_native_pilot_mode": True,
                "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                "phase2d_diagnostic_first_release_program_id": release_program,
                "prefix_segments_by_request": request_segments,
                "program_prefix_tokens": program_prefix_tokens,
                "pressure_prompt_tokens": pressure_tokens,
                "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
            },
            "trace": trace_name,
            "phase2d_stage": {
                "stage": "E4",
                "case_id": "e4-concurrent-shared",
                "arm": arm,
                "repeat": 1,
                "forced_first_logical_release_program_id": release_program,
                "expected_peak_inflight": 2,
            },
        }
        config_path = output_dir / config_name
        trace_path = output_dir / trace_name
        _write_json(config_path, config)
        _write_json(trace_path, trace)
        runs.append(
            {
                "run_id": run_id,
                "arm": arm,
                "config": config_name,
                "config_sha256": _sha256(config_path),
                "trace": trace_name,
                "trace_sha256": _sha256(trace_path),
            }
        )
    manifest = {
        "schema_version": "phase2d.e4_materialization.v1",
        "run_kind": "NON_HOLDOUT_RESEARCH_PILOT",
        "fixture_sha256": _sha256(fixture_path),
        "planned_run_count": len(runs),
        "runs": runs,
        "execution_started": False,
        "true_overlap_required": True,
        "native_physical_victim_forced": False,
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
    path = materialize_e4(fixture_path=arguments.fixture, output_dir=arguments.output_dir)
    print(f"wrote Phase 2D E4 fixture: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
