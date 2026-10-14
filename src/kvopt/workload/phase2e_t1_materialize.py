"""Materialize the paired, non-measured Phase 2E T1 fidelity smoke."""

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


def materialize_t1(*, fixture_path: Path, output_dir: Path) -> Path:
    fixture_path = fixture_path.resolve()
    fixture: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != "phase2e.t1_smoke_fixture.v1":
        raise ValueError("unsupported Phase 2E T1 fixture schema")
    if fixture.get("run_kind") != "NON_HOLDOUT_RESEARCH_DISCOVERY":
        raise ValueError("T1 must remain non-holdout research discovery")
    if fixture.get("execution_authorized") is not True:
        raise ValueError("T1 execution is not authorized")
    if fixture.get("measured_campaign") is not False:
        raise ValueError("T1 smoke cannot be a measured campaign")
    if fixture.get("cost_aware_policy") is not False:
        raise ValueError("T1 cannot enable a Cost-Aware policy")
    if fixture.get("baselines") != ["native-lru", "continuum-baseline"]:
        raise ValueError("T1 requires exactly the two authorized baselines")
    output_dir.mkdir(parents=True, exist_ok=False)

    block_size = int(fixture["block_size_tokens"])
    initial_tokens = int(fixture["initial_prefix_tokens"])
    grown_tokens = int(fixture["grown_prefix_tokens"])
    pressure_tokens = int(fixture["pressure_prompt_tokens"])
    growth_tokens = grown_tokens - initial_tokens
    if min(initial_tokens, grown_tokens, pressure_tokens) % block_size:
        raise ValueError("T1 token sizes must align to the native block size")
    if growth_tokens <= 0:
        raise ValueError("T1 must contain real positive context growth")

    initial_segments = {
        "t1-a": [["t1-shared-root", 128], ["t1-branch-a", 64]],
        "t1-b": [["t1-shared-root", 128], ["t1-branch-b", 64]],
    }
    grown_segments = {
        program: [*segments, [f"{program}-turn-2-growth", growth_tokens]]
        for program, segments in initial_segments.items()
    }
    requests = [
        {
            "program_id": program,
            "request_id": f"{program}:1",
            "turn_index": 1,
            "planned_arrival_offset_seconds": 0.0,
            "prompt": f"Phase 2E T1 {program} initial turn",
            "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
            "is_terminal": False,
            "next_tool_type": "phase2e-t1-idle",
            "tool_gap_seconds": 1.0
        }
        for program in ("t1-a", "t1-b")
    ]
    requests.extend(
        {
            "program_id": program,
            "request_id": f"{program}:2",
            "turn_index": 2,
            "planned_arrival_offset_seconds": 2.0,
            "prompt": f"Phase 2E T1 {program} grown return",
            "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
            "is_terminal": True,
            "next_tool_type": None,
            "tool_gap_seconds": None,
        }
        for program in ("t1-a", "t1-b")
    )
    request_segments = {
        "t1-a:1": initial_segments["t1-a"],
        "t1-b:1": initial_segments["t1-b"],
        "t1-a:2": grown_segments["t1-a"],
        "t1-b:2": grown_segments["t1-b"],
    }
    trace = {
        "schema_version": "phase2.trace.v1",
        "trace_id": "phase2e-t1-native-fidelity-smoke",
        "requests": requests,
        "pressure_stages": [
            {
                "stage_id": "phase2e-t1-pressure",
                "planned_arrival_offset_seconds": 1.0,
                "prompt": "Phase 2E T1 controlled native allocation pressure",
                "max_requests": 1,
                "stop_on_forced_release": False,
            }
        ],
    }
    program_sizes = {"t1-a": grown_tokens, "t1-b": grown_tokens}
    pressure_blocks = pressure_tokens // block_size
    protected_blocks = sum(value // block_size for value in program_sizes.values())
    block_override = (
        protected_blocks
        + pressure_blocks
        + 1
        - int(fixture["initial_shortage_blocks"])
    )
    entries: list[dict[str, Any]] = []
    for baseline in fixture["baselines"]:
        run_id = f"t1-shared-growth-concurrency-{baseline}"
        config_name = f"{run_id}.config.json"
        trace_name = f"{run_id}.trace.json"
        config = {
            "schema_version": "phase2.config.v1",
            "runtime_mode": "vllm-metal-observability",
            "backend_factory": fixture["runtime"]["backend_factory"],
            "backend_revision": "phase2e-t1-native-fidelity-smoke-v1",
            "campaign_kind": "phase2e_non_holdout_research_discovery",
            "policy": baseline,
            "seed": 20261051,
            "observe": True,
            "model": fixture["model"],
            "tokenizer": fixture["model"],
            "generation": {
                "max_new_tokens": fixture["runtime"]["max_new_tokens"],
                "temperature": fixture["runtime"]["temperature"],
            },
            "batching": {
                "max_concurrent_requests": fixture["runtime"]["max_concurrent_requests"]
            },
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
                "prefix_segments_by_request": request_segments,
                "program_prefix_tokens": program_sizes,
                "pressure_prompt_tokens": pressure_tokens,
                "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
            },
            "trace": trace_name,
            "phase2e_stage": {
                "stage": "T1",
                "smoke_id": "t1-shared-growth-concurrency",
                "baseline": baseline,
                "measured": False,
                "expected_peak_inflight": 2,
                "expected_initial_prefix_tokens": initial_tokens,
                "expected_grown_prefix_tokens": grown_tokens,
            },
        }
        config_path = output_dir / config_name
        trace_path = output_dir / trace_name
        _write_json(config_path, config)
        _write_json(trace_path, trace)
        entries.append(
            {
                "run_id": run_id,
                "baseline": baseline,
                "config": config_name,
                "config_sha256": _sha256(config_path),
                "trace": trace_name,
                "trace_sha256": _sha256(trace_path),
            }
        )
    manifest = {
        "schema_version": "phase2e.t1_materialization.v1",
        "run_kind": fixture["run_kind"],
        "fixture_sha256": _sha256(fixture_path),
        "planned_run_count": 2,
        "runs": entries,
        "measured_campaign": False,
        "joint_freeze_complete": False,
    }
    path = output_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    path = materialize_t1(fixture_path=arguments.fixture, output_dir=arguments.output_dir)
    print(f"wrote Phase 2E T1 smoke: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
