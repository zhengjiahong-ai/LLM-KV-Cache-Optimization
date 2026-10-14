"""Validate the Phase 2E 36-draw freeze candidate without executing outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from .phase2 import load_phase2_trace


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_phase2e_campaign(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "phase2e.campaign_materialization.v1":
        raise ValueError("unsupported Phase 2E campaign manifest")
    scenarios = manifest.get("scenarios")
    runs = manifest.get("runs")
    if not isinstance(scenarios, list) or not isinstance(runs, list):
        raise TypeError("campaign manifest lacks scenarios/runs")
    ids = [str(row["scenario_id"]) for row in scenarios]
    if len(ids) != 36 or len(set(ids)) != 36:
        raise ValueError("scenario identities must be 36 unique values")
    family_counts = Counter(str(row["family"]) for row in scenarios)
    if family_counts != Counter({family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")}):
        raise ValueError("campaign must contain six draws per family")
    by_scenario: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in runs:
        by_scenario[str(row["scenario_id"])].append(row)
    checks: dict[str, dict[str, bool]] = {}
    root = manifest_path.parent
    for scenario in scenarios:
        scenario_id = str(scenario["scenario_id"])
        trace_path = root / str(scenario["trace"])
        if _sha(trace_path) != scenario.get("trace_sha256"):
            raise ValueError(f"trace hash mismatch: {scenario_id}")
        trace = load_phase2_trace(trace_path)
        rows = by_scenario[scenario_id]
        if len(rows) != 4:
            raise ValueError(f"scenario must have four paired runs: {scenario_id}")
        pair_shape = Counter((str(row["baseline"]), int(row["repeat"])) for row in rows)
        expected_shape = Counter(
            (baseline, repeat)
            for baseline in ("native-lru", "continuum-baseline")
            for repeat in (1, 2)
        )
        if pair_shape != expected_shape:
            raise ValueError(f"invalid pair/repeat shape: {scenario_id}")
        configs = []
        for row in rows:
            config_path = root / str(row["config"])
            if _sha(config_path) != row.get("config_sha256"):
                raise ValueError(f"config hash mismatch: {row['run_id']}")
            configs.append(json.loads(config_path.read_text(encoding="utf-8")))
        reference = configs[0]
        stable_fields = ("model", "tokenizer", "generation", "batching", "cache", "backend_options", "trace")
        paired_equal = all(
            all(config.get(field) == reference.get(field) for field in stable_fields)
            for config in configs[1:]
        )
        family = str(scenario["family"])
        request_segments = reference["backend_options"]["prefix_segments_by_request"]
        sizes = {
            sum(int(segment[1]) for segment in segments)
            for segments in request_segments.values()
        }
        offsets = [request.planned_arrival_offset_seconds for request in trace.requests]
        family_semantics = {
            "F1": any(request.tool_gap_seconds is not None for request in trace.requests),
            "F2": len(set(Counter(request.program_id for request in trace.requests).values())) > 1,
            "F3": len(sizes) >= 3,
            "F4": (
                bool(scenario["shared_prefix_control"])
                or len(
                    {
                        str(segments[0][0])
                        for segments in request_segments.values()
                    }
                ) < len({request.program_id for request in trace.requests})
            ),
            "F5": len(trace.pressure_stages) >= 2 and len(sizes) >= 2,
            "F6": reference["batching"]["max_concurrent_requests"] > 1
            and len(offsets) != len(set(offsets)),
        }[family]
        checks[scenario_id] = {
            "paired_inputs_equal": paired_equal,
            "request_ids_unique": len(trace.requests)
            == len({request.request_id for request in trace.requests}),
            "tool_lifecycle_present": any(
                request.tool_gap_seconds is not None for request in trace.requests
            ),
            "pressure_present": bool(trace.pressure_stages),
            "family_semantics_materialized": family_semantics,
        }
        if not all(checks[scenario_id].values()):
            raise ValueError(f"scenario fidelity validation failed: {scenario_id}")
    return {
        "schema_version": "phase2e.campaign_validation.v1",
        "status": "PASS",
        "manifest_sha256": _sha(manifest_path),
        "scenario_count": len(scenarios),
        "run_count": len(runs),
        "family_counts": dict(sorted(family_counts.items())),
        "scenario_checks": checks,
        "joint_freeze_complete": False,
        "measured_campaign_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = validate_phase2e_campaign(args.manifest)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"validated Phase 2E freeze candidate: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
