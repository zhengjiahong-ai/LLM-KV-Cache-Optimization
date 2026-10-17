"""Materialize the authorized Phase 2G A1 native Gate 1 campaign."""

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
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != "phase2g.a1_native_gate1_fixture.v1":
        raise ValueError("unsupported Phase 2G A1 Gate 1 fixture")
    if fixture.get("execution_authorized") is not True:
        raise ValueError("Phase 2G A1 Gate 1 is not authorized")
    if fixture.get("policies") != ["A0", "A1"]:
        raise ValueError("Gate 1 must compare A0 and A1")
    if fixture.get("runtime_repeats") != 2:
        raise ValueError("Gate 1 requires exactly two runtime repeats")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not 2 <= len(cases) <= 4:
        raise ValueError("Gate 1 requires two to four controlled cases")
    return fixture


def materialize_gate1(*, fixture_path: Path, output_dir: Path) -> Path:
    fixture_path = fixture_path.resolve()
    fixture = _load_fixture(fixture_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    block_size = int(fixture["block_size_tokens"])
    pressure_tokens = int(fixture["pressure_prompt_tokens"])
    shortage = int(fixture["initial_shortage_blocks"])
    pressure_blocks = pressure_tokens // block_size
    runs: list[dict[str, object]] = []
    for case in fixture["cases"]:
        case_id = str(case["case_id"])
        prefixes = {
            str(key): int(value)
            for key, value in case["program_prefix_tokens"].items()
        }
        if set(prefixes) != {"gate1-a", "gate1-b"}:
            raise ValueError("Gate 1 cases must define gate1-a and gate1-b")
        if any(value % block_size for value in prefixes.values()):
            raise ValueError("Gate 1 prefix sizes must align to the block size")
        block_override = (
            sum(value // block_size for value in prefixes.values())
            + pressure_blocks
            + 1
            - shortage
        )
        requests = [
            {
                "program_id": program,
                "request_id": f"{program}:1",
                "turn_index": 1,
                "planned_arrival_offset_seconds": offset,
                "prompt": f"Phase 2G Gate 1 {case_id} {program}:1",
                "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                "is_terminal": False,
                "next_tool_type": "phase2g-gate1",
                "tool_gap_seconds": 1.0,
            }
            for program, offset in (("gate1-a", 0.0), ("gate1-b", 0.5))
        ]
        requests.extend(
            {
                "program_id": program,
                "request_id": f"{program}:2",
                "turn_index": 2,
                "planned_arrival_offset_seconds": offset,
                "prompt": f"Phase 2G Gate 1 {case_id} {program}:2",
                "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                "is_terminal": True,
                "next_tool_type": None,
                "tool_gap_seconds": None,
            }
            for program, offset in (("gate1-a", 2.0), ("gate1-b", 3.0))
        )
        segments = {
            str(row["request_id"]): [
                [f"phase2g:{case_id}:{row['program_id']}", prefixes[str(row["program_id"])]]
            ]
            for row in requests
        }
        trace = {
            "schema_version": "phase2.trace.v1",
            "trace_id": f"phase2g-{case_id}",
            "requests": requests,
            "pressure_stages": [
                {
                    "stage_id": "phase2g-gate1-pressure",
                    "planned_arrival_offset_seconds": 1.0,
                    "prompt": "Phase 2G A1 Gate 1 native pressure",
                    "max_requests": 1,
                    "stop_on_forced_release": True,
                }
            ],
        }
        trace_name = f"{case_id}.trace.json"
        trace_path = output_dir / trace_name
        _write_json(trace_path, trace)
        for repeat in (1, 2):
            for policy in ("A0", "A1"):
                run_id = f"{case_id}-{policy.lower()}-repeat-{repeat}"
                config_name = f"{run_id}.config.json"
                config = {
                    "schema_version": "phase2.config.v1",
                    "runtime_mode": "vllm-metal-observability",
                    "backend_factory": fixture["runtime"]["backend_factory"],
                    "backend_revision": "phase2g-a1-native-gate1-v1",
                    "campaign_kind": "phase2g_a1_native_gate1",
                    "policy": f"continuum-{policy.lower()}",
                    "seed": 20261101 + repeat,
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
                        "block_override": block_override,
                    },
                    "pressure": {
                        "initial_shortage_blocks": shortage,
                        "required_blocks": pressure_blocks,
                        "safety_ceiling": 1,
                    },
                    "backend_options": {
                        "execute_planned_timing": False,
                        "executor_mode": "submit_collect",
                        "gpu_memory_utilization": fixture["runtime"]["gpu_memory_utilization"],
                        "phase2c_native_pilot_mode": True,
                        "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                        "phase2g_release_policy": policy,
                        "phase2g_a1_lambda": fixture["a1"]["lambda"],
                        "phase2g_a1_tau_seconds": fixture["a1"]["tau_seconds"],
                        "prefix_segments_by_request": segments,
                        "program_prefix_tokens": prefixes,
                        "pressure_prompt_tokens": pressure_tokens,
                        "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
                    },
                    "trace": trace_name,
                    "phase2g_stage": {
                        "stage": "A1_GATE1",
                        "case_id": case_id,
                        "policy": policy,
                        "repeat": repeat,
                        "expected_selection_relation": case[
                            "expected_selection_relation"
                        ],
                    },
                }
                config_path = output_dir / config_name
                _write_json(config_path, config)
                runs.append(
                    {
                        "run_id": run_id,
                        "case_id": case_id,
                        "policy": policy,
                        "repeat": repeat,
                        "config": config_name,
                        "config_sha256": _sha256(config_path),
                        "trace": trace_name,
                        "trace_sha256": _sha256(trace_path),
                    }
                )
    manifest = {
        "schema_version": "phase2g.a1_native_gate1_materialization.v1",
        "scope": "NATIVE_MECHANISM_VALIDATION",
        "fixture_sha256": _sha256(fixture_path),
        "planned_run_count": len(runs),
        "case_count": len(fixture["cases"]),
        "policies": ["A0", "A1"],
        "runtime_repeats": 2,
        "runs": runs,
        "execution_started": False,
        "gate2_execution_started": False,
    }
    path = output_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    path = materialize_gate1(fixture_path=args.fixture, output_dir=args.output_dir)
    print(f"wrote Phase 2G A1 Gate 1 campaign: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
