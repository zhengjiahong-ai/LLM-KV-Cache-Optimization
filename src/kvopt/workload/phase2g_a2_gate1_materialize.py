"""Materialize the authorized Phase 2G A2 Native Gate 1 campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kvopt.costaware.a2_contract import BlockDecisionInput, DecisionRequest, decide
from kvopt.costaware.a2_geometry import Membership

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
    if fixture.get("schema_version") != "phase2g.a2_native_gate1_fixture.v1":
        raise ValueError("unsupported Phase 2G A2 Gate 1 fixture")
    if fixture.get("execution_authorized") is not True:
        raise ValueError("Phase 2G A2 Gate 1 is not authorized")
    if fixture.get("policies") != ["A0", "A2"]:
        raise ValueError("A2 Gate 1 must compare A0 and A2")
    if fixture.get("runtime_repeats") != 2:
        raise ValueError("A2 Gate 1 requires exactly two runtime repeats")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or len(cases) != 6:
        raise ValueError("A2 Gate 1 requires the six frozen controlled cases")
    return fixture


def _segments(case: Mapping[str, object]) -> dict[str, list[list[object]]]:
    raw = case.get("segments")
    if not isinstance(raw, Mapping) or set(raw) != {"gate1-a", "gate1-b"}:
        raise ValueError("each case must define gate1-a and gate1-b segments")
    result: dict[str, list[list[object]]] = {}
    for program, values in raw.items():
        if not isinstance(values, list) or not values:
            raise ValueError("program segments must be a non-empty list")
        result[str(program)] = [[str(key), int(tokens)] for key, tokens in values]
    return result


def _mechanism_preflight() -> dict[str, object]:
    """Prove the frozen selector can diverge before Native outcomes are read."""
    blocks: list[BlockDecisionInput] = []
    for rank, depth in enumerate(range(12, 0, -1)):
        blocks.append(
            BlockDecisionInput(
                rank + 1,
                rank,
                True,
                (Membership("chain-b", depth, f"b-{depth}"),),
            )
        )
    for offset, depth in enumerate(range(12, 0, -1), start=12):
        blocks.append(
            BlockDecisionInput(
                offset + 1,
                offset,
                True,
                (Membership("chain-a", depth, f"a-{depth}"),),
            )
        )
    request = DecisionRequest(
        required_blocks=12,
        timestamp=1.0,
        blocks=tuple(blocks),
        chain_length={"chain-a": 12, "chain-b": 12},
        reuse_weight={"chain-a": 0.4, "chain-b": 0.6},
    )
    outcome = decide(request)
    native = tuple(block.block_id for block in request.blocks[:12])
    selected = tuple(outcome.selection.blocks)
    return {
        "contract": "frozen_a2_decide",
        "native_lru_victims": native,
        "cost_aware_victims": selected,
        "victim_set_differs": set(native) != set(selected),
        "claim_boundary": "abstract preflight only; Native realization is measured",
    }


def materialize_gate1(*, fixture_path: Path, output_dir: Path) -> Path:
    fixture_path = fixture_path.resolve()
    fixture = _load_fixture(fixture_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    block_size = int(fixture["block_size_tokens"])
    runs: list[dict[str, object]] = []

    for case in fixture["cases"]:
        case_id = str(case["case_id"])
        base_segments = _segments(case)
        pressure_tokens = int(
            case.get("pressure_prompt_tokens", fixture["pressure_prompt_tokens"])
        )
        pressure_blocks = pressure_tokens // block_size
        shortage = int(
            case.get("initial_shortage_blocks", fixture["initial_shortage_blocks"])
        )
        prefixes = {
            program: sum(int(row[1]) for row in rows)
            for program, rows in base_segments.items()
        }
        if any(tokens % block_size for tokens in prefixes.values()):
            raise ValueError("all segment totals must align to the Native block size")
        unique_segments: dict[str, int] = {}
        for rows in base_segments.values():
            for key, tokens in rows:
                previous = unique_segments.setdefault(str(key), int(tokens))
                if previous != int(tokens):
                    raise ValueError("a shared content key must have one frozen length")
        unique_protected_blocks = sum(unique_segments.values()) // block_size
        block_override = unique_protected_blocks + pressure_blocks + 1 - shortage

        requests = [
            {
                "program_id": program,
                "request_id": f"{program}:1",
                "turn_index": 1,
                "planned_arrival_offset_seconds": offset,
                "prompt": f"Phase 2G A2 Gate 1 {case_id} {program}:1",
                "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                "is_terminal": False,
                "next_tool_type": "phase2g-a2-gate1",
                "tool_gap_seconds": 1.0,
            }
            for program, offset in (("gate1-a", 0.0), ("gate1-b", 0.5))
        ]
        program_segments = dict(base_segments)
        refresh_source = case.get("refresh_content_from_program")
        if refresh_source is not None:
            if refresh_source not in base_segments:
                raise ValueError("refresh content source must name a candidate program")
            program_segments["gate1-refresh"] = base_segments[str(refresh_source)]
            prefixes["gate1-refresh"] = prefixes[str(refresh_source)]
            requests.append(
                {
                    "program_id": "gate1-refresh",
                    "request_id": "gate1-refresh:1",
                    "turn_index": 1,
                    "planned_arrival_offset_seconds": 0.75,
                    "prompt": f"Phase 2G A2 Gate 1 {case_id} refresh",
                    "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                    "is_terminal": True,
                    "next_tool_type": None,
                    "tool_gap_seconds": None,
                }
            )
        requests.extend(
            {
                "program_id": program,
                "request_id": f"{program}:2",
                "turn_index": 2,
                "planned_arrival_offset_seconds": offset,
                "prompt": f"Phase 2G A2 Gate 1 {case_id} {program}:2",
                "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                "is_terminal": True,
                "next_tool_type": None,
                "tool_gap_seconds": None,
            }
            for program, offset in (("gate1-a", 2.0), ("gate1-b", 3.0))
        )
        request_segments = {
            str(request["request_id"]): program_segments[str(request["program_id"])]
            for request in requests
        }
        trace = {
            "schema_version": "phase2.trace.v1",
            "trace_id": f"phase2g-{case_id}",
            "requests": requests,
            "pressure_stages": [
                {
                    "stage_id": "phase2g-a2-gate1-pressure",
                    "planned_arrival_offset_seconds": 1.0,
                    "prompt": "Phase 2G A2 Gate 1 Native pressure",
                    "max_requests": 1,
                    "stop_on_forced_release": True,
                }
            ],
        }
        trace_name = f"{case_id}.trace.json"
        trace_path = output_dir / trace_name
        _write_json(trace_path, trace)

        for repeat in (1, 2):
            for policy in ("A0", "A2"):
                run_id = f"{case_id}-{policy.lower()}-repeat-{repeat}"
                config_name = f"{run_id}.config.json"
                config = {
                    "schema_version": "phase2.config.v1",
                    "runtime_mode": "vllm-metal-observability",
                    "backend_factory": fixture["runtime"]["backend_factory"],
                    "backend_revision": "phase2g-a2-native-gate1-v1",
                    "campaign_kind": "phase2g_a2_native_gate1",
                    "policy": f"continuum-{policy.lower()}",
                    "seed": 20261120 + repeat,
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
                        "phase2g_release_policy": "A0",
                        "phase2g_block_policy": policy,
                        "phase2g_a2_tau_seconds": fixture["a2"]["tau_seconds"],
                        "phase2g_a2_identity_mode": (
                            case["identity_mode"] if policy == "A2" else "normal"
                        ),
                        "phase2g_unique_protected_blocks": unique_protected_blocks,
                        "prefix_segments_by_request": request_segments,
                        "program_prefix_tokens": prefixes,
                        "pressure_prompt_tokens": pressure_tokens,
                        "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
                    },
                    "trace": trace_name,
                    "phase2g_stage": {
                        "stage": "A2_GATE1",
                        "case_id": case_id,
                        "expected_relation": case["expected_relation"],
                        "identity_mode": case["identity_mode"],
                        "refresh_content_from_program": refresh_source,
                        "policy": policy,
                        "repeat": repeat,
                    },
                }
                config_path = output_dir / config_name
                _write_json(config_path, config)
                runs.append(
                    {
                        "run_id": run_id,
                        "case_id": case_id,
                        "expected_relation": case["expected_relation"],
                        "identity_mode": case["identity_mode"],
                        "policy": policy,
                        "repeat": repeat,
                        "config": config_name,
                        "config_sha256": _sha256(config_path),
                        "trace": trace_name,
                        "trace_sha256": _sha256(trace_path),
                    }
                )

    manifest = {
        "schema_version": "phase2g.a2_native_gate1_materialization.v1",
        "scope": "NATIVE_BLOCK_MECHANISM_VALIDATION",
        "fixture_sha256": _sha256(fixture_path),
        "planned_run_count": len(runs),
        "case_count": len(fixture["cases"]),
        "policies": ["A0", "A2"],
        "runtime_repeats": 2,
        "mechanism_preflight": _mechanism_preflight(),
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
    print(f"wrote Phase 2G A2 Gate 1 campaign: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
