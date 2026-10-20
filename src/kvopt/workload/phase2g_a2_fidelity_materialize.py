"""Materialize the authorized non-formal A2 Native evidence fidelity fixtures."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .phase2c_native_pilot import PILOT_PREFIX_GENERATOR_VERSION
from .phase2g_a2_gate1_materialize import _sha256, _write_json

_CASE_KINDS = {
    "COMPLETE_CHAIN",
    "PARTIAL_EVICTION",
    "SHARED_CONTENT",
    "PROGRAM_COMPLETION",
    "SLOT_REUSE",
    "INCOMPLETE_EVIDENCE",
}


def _load_fixture(path: Path) -> dict[str, object]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != (
        "phase2g.a2_native_evidence_fidelity_fixture.v1"
    ):
        raise ValueError("unsupported A2 Native evidence fidelity fixture")
    if fixture.get("execution_authorized") is not True:
        raise ValueError("A2 Native evidence fidelity execution is not authorized")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or len(cases) != 6:
        raise ValueError("A2 Native evidence fidelity requires six cases")
    kinds = {str(case.get("case_kind")) for case in cases if isinstance(case, Mapping)}
    if kinds != _CASE_KINDS:
        raise ValueError("A2 Native evidence fidelity case coverage is incomplete")
    boundaries = fixture.get("boundaries")
    if not isinstance(boundaries, Mapping) or boundaries.get("formal_campaign") is not False:
        raise ValueError("A2 Native evidence fidelity must remain non-formal")
    return fixture


def _segments(case: Mapping[str, object]) -> dict[str, list[list[object]]]:
    raw = case.get("segments")
    if not isinstance(raw, Mapping) or set(raw) != {"fidelity-a", "fidelity-b"}:
        raise ValueError("each fidelity case must define fidelity-a and fidelity-b")
    result: dict[str, list[list[object]]] = {}
    for program, values in raw.items():
        if not isinstance(values, list) or not values:
            raise ValueError("fidelity segments must be non-empty")
        result[str(program)] = [[str(key), int(tokens)] for key, tokens in values]
    return result


def _requests(case: Mapping[str, object]) -> list[dict[str, object]]:
    terminal_first = case.get("terminal_first_program") is True
    first = []
    for program, offset in (("fidelity-a", 0.0), ("fidelity-b", 0.25)):
        terminal = terminal_first and program == "fidelity-a"
        first.append(
            {
                "program_id": program,
                "request_id": f"{program}:1",
                "turn_index": 1,
                "planned_arrival_offset_seconds": offset,
                "prompt": f"A2 evidence fidelity {case['case_id']} {program}:1",
                "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                "is_terminal": terminal,
                "next_tool_type": None if terminal else "phase2g-a2-fidelity",
                "tool_gap_seconds": None if terminal else 1.0,
            }
        )
    returns = [
        {
            "program_id": program,
            "request_id": f"{program}:2",
            "turn_index": 2,
            "planned_arrival_offset_seconds": offset,
            "prompt": f"A2 evidence fidelity {case['case_id']} {program}:2",
            "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
            "is_terminal": True,
            "next_tool_type": None,
            "tool_gap_seconds": None,
        }
        for program, offset in (("fidelity-a", 2.0), ("fidelity-b", 2.25))
        if not (terminal_first and program == "fidelity-a")
    ]
    return first + returns


def materialize_fidelity(*, fixture_path: Path, output_dir: Path) -> Path:
    fixture_path = fixture_path.resolve()
    fixture = _load_fixture(fixture_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    block_size = int(fixture["block_size_tokens"])
    pressure_tokens = int(fixture["pressure_prompt_tokens"])
    pressure_blocks = pressure_tokens // block_size
    shortage = int(fixture["initial_shortage_blocks"])
    runs: list[dict[str, object]] = []

    for raw_case in fixture["cases"]:  # type: ignore[index]
        if not isinstance(raw_case, Mapping):
            raise TypeError("fidelity case must be an object")
        case = raw_case
        case_id = str(case["case_id"])
        segments = _segments(case)
        requests = _requests(case)
        prefixes = {
            program: sum(int(row[1]) for row in values)
            for program, values in segments.items()
        }
        if any(tokens % block_size for tokens in prefixes.values()):
            raise ValueError("fidelity prefix totals must align to block size")
        unique_segments: dict[str, int] = {}
        for values in segments.values():
            for key, tokens in values:
                previous = unique_segments.setdefault(str(key), int(tokens))
                if previous != int(tokens):
                    raise ValueError("shared fidelity content must have one length")
        unique_protected_blocks = sum(unique_segments.values()) // block_size
        block_override = unique_protected_blocks + pressure_blocks + 1 - shortage
        request_segments = {
            str(request["request_id"]): segments[str(request["program_id"])]
            for request in requests
        }
        trace = {
            "schema_version": "phase2.trace.v1",
            "trace_id": f"phase2g-{case_id}",
            "requests": requests,
            "pressure_stages": [
                {
                    "stage_id": f"{case_id}-pressure",
                    "planned_arrival_offset_seconds": 1.0,
                    "prompt": f"A2 evidence fidelity pressure {case_id}",
                    "max_requests": 1,
                    "stop_on_forced_release": True,
                }
            ],
        }
        trace_name = f"{case_id}.trace.json"
        trace_path = output_dir / trace_name
        _write_json(trace_path, trace)
        run_id = case_id
        config_name = f"{run_id}.config.json"
        config = {
            "schema_version": "phase2.config.v1",
            "runtime_mode": "vllm-metal-observability",
            "backend_factory": fixture["runtime"]["backend_factory"],  # type: ignore[index]
            "backend_revision": "phase2g-a2-native-evidence-fidelity-v1",
            "campaign_kind": "phase2g_a2_native_evidence_fidelity",
            "policy": "continuum-a2",
            "seed": 20261124,
            "observe": True,
            "model": fixture["model"],
            "tokenizer": fixture["model"],
            "generation": {
                "max_new_tokens": fixture["runtime"]["max_new_tokens"],  # type: ignore[index]
                "temperature": fixture["runtime"]["temperature"],  # type: ignore[index]
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
                "gpu_memory_utilization": fixture["runtime"]["gpu_memory_utilization"],  # type: ignore[index]
                "phase2c_native_pilot_mode": True,
                "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                "phase2g_release_policy": "A0",
                "phase2g_block_policy": "A2",
                "phase2g_a2_tau_seconds": fixture["a2"]["tau_seconds"],  # type: ignore[index]
                "phase2g_a2_identity_mode": case["identity_mode"],
                "phase2g_unique_protected_blocks": unique_protected_blocks,
                "prefix_segments_by_request": request_segments,
                "program_prefix_tokens": prefixes,
                "pressure_prompt_tokens": pressure_tokens,
                "h2_native_prefix_interventions": case.get(
                    "native_prefix_interventions", {}
                ),
                "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
            },
            "trace": trace_name,
            "phase2g_fidelity_stage": {
                "stage": "A2_FIDELITY",
                "case_id": case_id,
                "case_kind": case["case_kind"],
                "formal": False,
            },
        }
        config_path = output_dir / config_name
        _write_json(config_path, config)
        runs.append(
            {
                "run_id": run_id,
                "case_id": case_id,
                "case_kind": case["case_kind"],
                "config": config_name,
                "config_sha256": _sha256(config_path),
                "trace": trace_name,
                "trace_sha256": _sha256(trace_path),
            }
        )

    manifest = {
        "schema_version": "phase2g.a2_native_evidence_fidelity_materialization.v1",
        "scope": fixture["scope"],
        "formal": False,
        "fixture_sha256": _sha256(fixture_path),
        "planned_run_count": len(runs),
        "case_kinds": sorted(_CASE_KINDS),
        "runs": runs,
        "formal_campaign_execution_authorized": False,
    }
    path = output_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    path = materialize_fidelity(
        fixture_path=args.fixture, output_dir=args.output_dir
    )
    print(f"wrote A2 Native evidence fidelity fixtures: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
