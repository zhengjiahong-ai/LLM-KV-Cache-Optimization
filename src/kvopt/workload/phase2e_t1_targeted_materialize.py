"""Materialize the Phase 2E T1 RC4 forced-release targeted smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .phase2c_native_pilot import PILOT_PREFIX_GENERATOR_VERSION


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_targeted_t1(*, fixture_path: Path, output_dir: Path) -> Path:
    fixture: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != "phase2e.t1_targeted_fixture.v1":
        raise ValueError("unsupported Phase 2E targeted fixture schema")
    if fixture.get("execution_authorized") is not True:
        raise ValueError("targeted smoke is not authorized")
    if fixture.get("measured_campaign") is not False:
        raise ValueError("targeted smoke cannot be measured")
    if fixture.get("joint_freeze_complete") is not False:
        raise ValueError("joint freeze must remain pending")
    if fixture.get("cost_aware_policy") is not False:
        raise ValueError("targeted smoke cannot enable Cost-Aware policy")
    output_dir.mkdir(parents=True, exist_ok=False)
    block_size = int(fixture["block_size_tokens"])
    prefix_tokens = int(fixture["prefix_tokens"])
    pressure_tokens = int(fixture["pressure_prompt_tokens"])
    initial_shortage = int(fixture["initial_shortage_blocks"])
    if prefix_tokens % block_size or pressure_tokens % block_size:
        raise ValueError("targeted smoke token counts must be block aligned")
    segments = {
        "rc4-a": [["rc4-shared-root", 128], ["rc4-branch-a", 64]],
        "rc4-b": [["rc4-shared-root", 128], ["rc4-branch-b", 64]],
    }
    requests = [
        {
            "program_id": program,
            "request_id": f"{program}:1",
            "turn_index": 1,
            "planned_arrival_offset_seconds": offset,
            "prompt": f"Phase 2E RC4 {program} initial",
            "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
            "is_terminal": False,
            "next_tool_type": "phase2e-rc4",
            "tool_gap_seconds": 1.0,
        }
        for program, offset in (("rc4-a", 0.0), ("rc4-b", 1.0))
    ]
    requests.extend(
        {
            "program_id": program,
            "request_id": f"{program}:2",
            "turn_index": 2,
            "planned_arrival_offset_seconds": offset,
            "prompt": f"Phase 2E RC4 {program} return",
            "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
            "is_terminal": True,
            "next_tool_type": None,
            "tool_gap_seconds": None,
        }
        for program, offset in (("rc4-a", 3.0), ("rc4-b", 4.0))
    )
    run_id = "t1-rc4-forced-release-continuum"
    trace_name = f"{run_id}.trace.json"
    config_name = f"{run_id}.config.json"
    trace = {
        "schema_version": "phase2.trace.v1",
        "trace_id": "phase2e-t1-rc4-forced-release",
        "requests": requests,
        "pressure_stages": [
            {
                "stage_id": "phase2e-t1-rc4-pressure",
                "planned_arrival_offset_seconds": 2.0,
                "prompt": "Phase 2E RC4 controlled allocation pressure",
                "max_requests": 1,
                "stop_on_forced_release": True,
            }
        ],
    }
    protected_blocks = 2 * (prefix_tokens // block_size)
    pressure_blocks = pressure_tokens // block_size
    config = {
        "schema_version": "phase2.config.v1",
        "runtime_mode": "vllm-metal-observability",
        "backend_factory": fixture["runtime"]["backend_factory"],
        "backend_revision": "phase2e-t1-targeted-forced-release-v1",
        "campaign_kind": "phase2e_non_holdout_research_discovery",
        "policy": "continuum-baseline",
        "seed": 20261052,
        "observe": True,
        "model": fixture["model"],
        "tokenizer": fixture["model"],
        "generation": {
            "max_new_tokens": fixture["runtime"]["max_new_tokens"],
            "temperature": fixture["runtime"]["temperature"],
        },
        "batching": {"max_concurrent_requests": 1},
        "cache": {
            "block_size": block_size,
            "block_override": protected_blocks + pressure_blocks + 1 - initial_shortage,
        },
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
            "prefix_segments_by_request": {
                str(row["request_id"]): segments[str(row["program_id"])]
                for row in requests
            },
            "program_prefix_tokens": {"rc4-a": prefix_tokens, "rc4-b": prefix_tokens},
            "pressure_prompt_tokens": pressure_tokens,
            "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
        },
        "trace": trace_name,
        "phase2e_stage": {
            "stage": "T1",
            "smoke_id": "t1-rc4-forced-release",
            "baseline": "continuum-baseline",
            "measured": False,
            "targeted_capability": "forced_release_decision_chain",
        },
    }
    trace_path = output_dir / trace_name
    config_path = output_dir / config_name
    _write(trace_path, trace)
    _write(config_path, config)
    manifest = {
        "schema_version": "phase2e.t1_targeted_materialization.v1",
        "run_kind": "NON_HOLDOUT_RESEARCH_DISCOVERY",
        "fixture_sha256": _sha(fixture_path),
        "planned_run_count": 1,
        "measured_campaign": False,
        "joint_freeze_complete": False,
        "run": {
            "run_id": run_id,
            "config": config_name,
            "config_sha256": _sha(config_path),
            "trace": trace_name,
            "trace_sha256": _sha(trace_path),
        },
    }
    path = output_dir / "manifest.json"
    _write(path, manifest)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    path = materialize_targeted_t1(
        fixture_path=arguments.fixture,
        output_dir=arguments.output_dir,
    )
    print(f"wrote Phase 2E T1 targeted smoke: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
