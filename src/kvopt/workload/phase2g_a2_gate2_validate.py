"""Validate an execution-locked Phase 2G A2 Gate 2 materialization."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

from .phase2 import load_phase2_trace
from .phase2g_a1_bounded_validate import _family_semantics
from .phase2g_a2_gate2_materialize import _digest, _input_contract


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _without_arm_identity(config: dict[str, object]) -> dict[str, object]:
    value = deepcopy(config)
    value["policy"] = "<ARM>"
    backend = value["backend_options"]
    backend["phase2g_block_policy"] = "<ARM>"
    stage = value["phase2g_stage"]
    stage["policy"] = "<ARM>"
    stage["repeat"] = "<RUNTIME_REPEAT>"
    stage["execution_order"] = "<BALANCED>"
    return value


def validate_gate2_campaign(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "phase2g.a2_gate2_materialization.v1":
        raise ValueError("unsupported Phase 2G A2 Gate 2 manifest")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("execution_authorized must remain false")
    if manifest.get("formal_native_execution_authorized") is not False:
        raise ValueError("formal_native_execution_authorized must remain false")
    if manifest.get("outcomes_materialized") is not False:
        raise ValueError("pre-execution validation cannot inspect outcomes")
    if manifest.get("tested_a2_implementation_git_sha") != (
        "15a65e36604af5679987bb91d224fd20ce560e8a"
    ):
        raise ValueError("tested A2 implementation SHA mismatch")

    scenarios = manifest.get("scenarios")
    runs = manifest.get("runs")
    if not isinstance(scenarios, list) or not isinstance(runs, list):
        raise TypeError("Gate 2 manifest lacks scenarios/runs")
    if len(scenarios) != 36 or len(runs) != 144:
        raise ValueError("Gate 2 campaign cardinality mismatch")
    run_ids = [str(row["run_id"]) for row in runs]
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("duplicate run ID in Gate 2 manifest")
    pairing_keys = [
        (str(row["scenario_id"]), str(row["policy"]), int(row["repeat"]))
        for row in runs
    ]
    if len(set(pairing_keys)) != len(pairing_keys):
        raise ValueError("duplicate scenario/policy/repeat key in Gate 2 manifest")
    family_counts = Counter(str(row["family"]) for row in scenarios)
    if family_counts != Counter({family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")}):
        raise ValueError("Gate 2 campaign must contain six scenarios per family")

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
        expected = Counter((policy, repeat) for policy in ("A0", "A2") for repeat in (1, 2))
        if shape != expected:
            raise ValueError(f"invalid policy/repeat shape: {scenario_id}")

        configs: list[dict[str, object]] = []
        input_digests: set[str] = set()
        for row in rows:
            config_path = root / str(row["config"])
            if _sha(config_path) != row.get("config_sha256"):
                raise ValueError(f"config hash mismatch: {row['run_id']}")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            policy = str(row["policy"])
            backend = config.get("backend_options", {})
            stage = config.get("phase2g_stage", {})
            if (
                config.get("campaign_kind") != "phase2g_a2_gate2_bounded_evaluation"
                or backend.get("phase2g_release_policy") != "A0"
                or backend.get("phase2g_block_policy") != policy
                or float(backend.get("phase2g_a2_tau_seconds", 0.0)) != 30.0
                or stage.get("scenario_id") != scenario_id
                or stage.get("policy") != policy
                or stage.get("repeat") != row["repeat"]
                or config.get("trace") != row["trace"]
                or row.get("trace") != scenario.get("trace")
                or row.get("trace_sha256") != scenario.get("trace_sha256")
            ):
                raise ValueError(f"manifest/config identity mismatch: {row['run_id']}")
            computed_input_digest = _digest(_input_contract(config))
            if computed_input_digest != row.get("input_contract_sha256"):
                raise ValueError(f"input contract digest mismatch: {row['run_id']}")
            if computed_input_digest != scenario.get("input_contract_sha256"):
                raise ValueError(f"scenario input contract digest mismatch: {row['run_id']}")
            input_digests.add(computed_input_digest)
            order_counts[(policy, int(row["execution_order"]))] += 1
            configs.append(config)

        reference = _without_arm_identity(configs[0])
        policy_is_only_arm_difference = all(
            _without_arm_identity(config) == reference for config in configs[1:]
        )
        semantics = _family_semantics(str(scenario["family"]), scenario, configs[0])
        checks = {
            "four_paired_runs": len(rows) == 4,
            "single_input_contract_digest": len(input_digests) == 1,
            "policy_is_only_arm_difference": policy_is_only_arm_difference,
            "entry_release_frozen_a0": all(
                config["backend_options"]["phase2g_release_policy"] == "A0"
                for config in configs
            ),
            "request_ids_unique": len(trace.requests)
            == len({request.request_id for request in trace.requests}),
            "pressure_count_matches": len(trace.pressure_stages)
            == int(scenario["pressure_count"]),
            "family_parameters_recorded": bool(scenario.get("family_parameters")),
            **semantics,
        }
        if not all(checks.values()):
            raise ValueError(f"scenario fidelity validation failed: {scenario_id}")
        scenario_checks[scenario_id] = checks

    expected_order = Counter(
        {(policy, order): 36 for policy in ("A0", "A2") for order in (1, 2)}
    )
    if order_counts != expected_order:
        raise ValueError("policy execution order is not balanced")
    return {
        "schema_version": "phase2g.a2_gate2_validation.v1",
        "status": "PASS",
        "manifest_sha256": _sha(manifest_path),
        "tested_a2_implementation_git_sha": manifest["tested_a2_implementation_git_sha"],
        "scenario_count": len(scenarios),
        "planned_run_count": len(runs),
        "family_counts": dict(sorted(family_counts.items())),
        "execution_order_counts": {
            f"{policy}_position_{order}": count
            for (policy, order), count in sorted(order_counts.items())
        },
        "scenario_checks": scenario_checks,
        "execution_authorized": False,
        "formal_native_execution_authorized": False,
        "outcomes_inspected": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = validate_gate2_campaign(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"validated execution-locked Phase 2G A2 Gate 2 campaign: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
