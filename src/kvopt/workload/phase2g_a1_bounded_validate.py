"""Validate the execution-locked Phase 2G A1 bounded campaign."""

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


def _shared_segment_keys(
    segments: dict[str, list[list[object]]],
) -> set[str]:
    owners: dict[str, set[str]] = defaultdict(set)
    for request_id, request_segments in segments.items():
        program, _ = str(request_id).rsplit(":", 1)
        for segment in request_segments:
            owners[str(segment[0])].add(program)
    return {key for key, programs in owners.items() if len(programs) > 1}


def _family_semantics(
    family: str,
    scenario: dict[str, object],
    config: dict[str, object],
) -> dict[str, bool]:
    backend = config["backend_options"]
    segments = backend["prefix_segments_by_request"]
    by_program: dict[str, list[tuple[int, list[list[object]]]]] = defaultdict(list)
    for request_id, request_segments in segments.items():
        program, turn = str(request_id).rsplit(":", 1)
        by_program[program].append((int(turn), request_segments))
    shared = _shared_segment_keys(segments)
    prefix_sizes = {
        program: max(
            sum(int(segment[1]) for segment in request_segments) for _, request_segments in turns
        )
        for program, turns in by_program.items()
    }
    parameters = scenario["family_parameters"]
    checks = {
        "entry_count_realized": len(by_program) == int(scenario["entry_count"]),
        "prefix_size_variation_realized": len(set(prefix_sizes.values())) >= 2,
    }
    if family == "F1":
        checks.update(
            shared_root_realized=bool(shared),
            unequal_private_tails_realized=len(set(prefix_sizes.values())) >= 2,
        )
    elif family == "F2":
        root_owners: dict[str, set[str]] = defaultdict(set)
        for program, turns in by_program.items():
            for segment in turns[0][1]:
                if "group-" in str(segment[0]):
                    root_owners[str(segment[0])].add(program)
        checks.update(
            multi_entry_shared_groups_realized=bool(root_owners)
            and max(map(len, root_owners.values())) >= 2,
            more_than_one_entry_realized=len(by_program) >= 3,
        )
    elif family == "F3":
        gaps = parameters["declared_return_gap_seconds"]
        checks.update(
            heterogeneous_tool_gaps_realized=len(set(gaps)) == len(gaps),
            private_content_realized=not shared,
        )
    elif family == "F4":
        turn_counts = [len(turns) for turns in by_program.values()]
        growth = all(
            len(
                {
                    sum(int(segment[1]) for segment in request_segments)
                    for _, request_segments in turns
                }
            )
            >= 2
            for turns in by_program.values()
        )
        checks.update(
            multi_turn_growth_realized=min(turn_counts) >= 3 and growth,
            repeated_pressure_declared=int(scenario["pressure_count"]) >= 2,
            shared_root_realized=bool(shared),
        )
    elif family == "F5":
        checks.update(
            no_shared_prefix_realized=not shared,
            negative_control_recorded="negative control" in str(parameters["focus"]),
        )
    elif family == "F6":
        mode = str(parameters["return_realization"])
        turn_counts = [len(turns) for turns in by_program.values()]
        checks.update(
            adverse_return_mode_recorded=mode.startswith("omit-") or mode == "reverse",
            return_mismatch_realized=(
                min(turn_counts) == 1 if mode.startswith("omit-") else mode == "reverse"
            ),
            private_content_realized=not shared,
        )
    else:
        raise ValueError(f"unsupported family: {family}")
    return checks


def validate_bounded_campaign(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "phase2g.a1_bounded_materialization.v1":
        raise ValueError("unsupported Phase 2G A1 bounded manifest")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("validation requires an execution-locked manifest")
    scenarios = manifest.get("scenarios")
    runs = manifest.get("runs")
    if not isinstance(scenarios, list) or not isinstance(runs, list):
        raise TypeError("bounded manifest lacks scenarios/runs")
    if len(scenarios) != 36 or len(runs) != 144:
        raise ValueError("bounded campaign cardinality mismatch")
    family_counts = Counter(str(row["family"]) for row in scenarios)
    expected_families = Counter({family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")})
    if family_counts != expected_families:
        raise ValueError("bounded campaign must contain six scenarios per family")
    root = manifest_path.parent
    by_scenario: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in runs:
        by_scenario[str(row["scenario_id"])].append(row)
    scenario_checks: dict[str, dict[str, bool]] = {}
    order_counts: Counter[tuple[str, int]] = Counter()
    for scenario in scenarios:
        scenario_id = str(scenario["scenario_id"])
        trace_path = root / str(scenario["trace"])
        if _sha(trace_path) != scenario.get("trace_sha256"):
            raise ValueError(f"trace hash mismatch: {scenario_id}")
        trace = load_phase2_trace(trace_path)
        rows = by_scenario[scenario_id]
        shape = Counter((str(row["policy"]), int(row["repeat"])) for row in rows)
        expected_shape = Counter((policy, repeat) for policy in ("A0", "A1") for repeat in (1, 2))
        if shape != expected_shape:
            raise ValueError(f"invalid policy/repeat shape: {scenario_id}")
        configs: list[dict[str, object]] = []
        for row in rows:
            config_path = root / str(row["config"])
            if _sha(config_path) != row.get("config_sha256"):
                raise ValueError(f"config hash mismatch: {row['run_id']}")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            stage = config.get("phase2g_stage", {})
            if (
                stage.get("scenario_id") != scenario_id
                or stage.get("policy") != row["policy"]
                or stage.get("repeat") != row["repeat"]
                or config.get("policy") != f"continuum-{str(row['policy']).lower()}"
                or config.get("trace") != row["trace"]
            ):
                raise ValueError(f"manifest/config identity mismatch: {row['run_id']}")
            order_counts[(str(row["policy"]), int(row["execution_order"]))] += 1
            configs.append(config)
        reference = configs[0]
        stable_fields = ("model", "tokenizer", "generation", "batching", "cache", "seed", "trace")
        paired_inputs_equal = all(
            all(config[field] == reference[field] for field in stable_fields)
            and config["backend_options"]["prefix_segments_by_request"]
            == reference["backend_options"]["prefix_segments_by_request"]
            and config["backend_options"]["program_prefix_tokens"]
            == reference["backend_options"]["program_prefix_tokens"]
            and config["backend_options"]["pressure_prompt_tokens"]
            == reference["backend_options"]["pressure_prompt_tokens"]
            for config in configs[1:]
        )
        semantics = _family_semantics(str(scenario["family"]), scenario, reference)
        checks = {
            "four_paired_runs": len(rows) == 4,
            "paired_inputs_equal": paired_inputs_equal,
            "request_ids_unique": len(trace.requests)
            == len({request.request_id for request in trace.requests}),
            "pressure_count_matches": len(trace.pressure_stages) == int(scenario["pressure_count"]),
            "family_parameters_recorded": bool(scenario.get("family_parameters")),
            **semantics,
        }
        if not all(checks.values()):
            raise ValueError(f"scenario fidelity validation failed: {scenario_id}")
        scenario_checks[scenario_id] = checks
    balanced_order = order_counts == Counter(
        {(policy, order): 36 for policy in ("A0", "A1") for order in (1, 2)}
    )
    if not balanced_order:
        raise ValueError("policy execution order is not balanced")
    return {
        "schema_version": "phase2g.a1_bounded_validation.v1",
        "status": "PASS",
        "manifest_sha256": _sha(manifest_path),
        "scenario_count": len(scenarios),
        "run_count": len(runs),
        "family_counts": dict(sorted(family_counts.items())),
        "execution_order_counts": {
            f"{policy}_position_{order}": count
            for (policy, order), count in sorted(order_counts.items())
        },
        "scenario_checks": scenario_checks,
        "execution_authorized": False,
        "outcomes_inspected": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = validate_bounded_campaign(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"validated Phase 2G A1 bounded campaign: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
