"""Produce the frozen H1 Level-A validity and acceptance result."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from kvopt.profiling.pipeline import (
    build_derived_dataset_bundle,
    discover_run_artifacts,
)

from .acceptance import AcceptanceCriteria, evaluate_acceptance
from .offline_eval import evaluate_rules, scenario_group
from .preregistrations import H1_R1_PREREGISTRATION
from .replay import (
    ExecutedP1BStrategy,
    candidate_key,
    load_decision_snapshots,
    validate_replay_fidelity,
)
from .report import EXECUTED_BASELINE_RULE_ID
from .rules import H1_R1_REVERSE_DEADLINE_ID, rule_by_id


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_scenario_validity(
    execution: Mapping[str, object],
) -> dict[str, object]:
    results = execution.get("results")
    if not isinstance(results, list):
        raise TypeError("execution results must be an array")
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("scenario_id"), str):
            raise TypeError("execution result identity is invalid")
        grouped[result["scenario_id"]].append(result)
    valid = []
    invalid = []
    for scenario_id, rows in sorted(grouped.items()):
        seeds = sorted(row.get("seed") for row in rows)
        families = {row.get("family_id") for row in rows}
        if len(families) != 1:
            raise ValueError("scenario results disagree on family")
        family = next(iter(families))
        all_success = len(rows) == 3 and all(row.get("status") == "success" for row in rows)
        item = {
            "scenario_id": scenario_id,
            "family_id": family,
            "seeds": seeds,
            "statuses": [row.get("status") for row in rows],
        }
        if all_success:
            valid.append(item)
        else:
            item["failure_reasons"] = sorted(
                {str(row.get("failure_reason")) for row in rows if row.get("status") != "success"}
            )
            invalid.append(item)
    family_counts = Counter(str(row["family_id"]) for row in valid)
    required = {"F1", "F2", "F3", "F4", "F5", "F6"}
    return {
        "valid_independent_scenario_count": len(valid),
        "invalid_independent_scenario_count": len(invalid),
        "valid_family_counts": dict(sorted(family_counts.items())),
        "families_missing": sorted(required - set(family_counts)),
        "minimum_valid_scenarios": 30,
        "adequate": len(valid) >= 30 and required <= set(family_counts),
        "valid_scenarios": valid,
        "invalid_scenarios": invalid,
    }


def build_h1_formal_result(
    *,
    artifact_root: Path,
    campaign_path: Path,
    execution_summary_path: Path,
) -> dict[str, object]:
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_summary_path.read_text(encoding="utf-8"))
    if campaign.get("campaign_id") != "phase2a-h1-independent-holdout-v2":
        raise ValueError("unexpected H1 formal campaign")
    if campaign.get("formal_h1_outcome_execution_authorized") is not True:
        raise ValueError("H1 formal execution was not authorized")
    validity = classify_scenario_validity(execution)
    valid_scenario_ids = {row["scenario_id"] for row in validity["valid_scenarios"]}
    valid_run_ids = frozenset(
        row["run_id"]
        for row in execution["results"]
        if row["status"] == "success" and row["scenario_id"] in valid_scenario_ids
    )
    raw_runs = discover_run_artifacts(artifact_root)
    bundle = build_derived_dataset_bundle(raw_runs, formal_campaign=True)
    snapshots = load_decision_snapshots(raw_runs)
    families_by_run = {row.run_id: row.scenario_family_id for row in bundle.runs}
    rules = (
        rule_by_id(EXECUTED_BASELINE_RULE_ID),
        rule_by_id(H1_R1_REVERSE_DEADLINE_ID),
    )
    evaluation = evaluate_rules(
        candidates=bundle.decision_candidates,
        evidence=bundle.candidate_loss_evidence,
        snapshots=snapshots,
        canonical_regret=bundle.decision_regret,
        families_by_run=families_by_run,
        rules=rules,
        loss_view="planned_return_weighted_prefill_proxy",
        included_runs=valid_run_ids,
    )
    verdict = evaluate_acceptance(
        preregistration=H1_R1_PREREGISTRATION,
        baseline_rule_id=EXECUTED_BASELINE_RULE_ID,
        proxy_evaluation=evaluation,
    )
    rows_by_decision: dict[tuple[str, int], dict[tuple[str, str], object]] = {}
    for row in bundle.decision_candidates:
        if row.run_id in valid_run_ids:
            rows_by_decision.setdefault((row.run_id, row.decision_event_index), {})[
                candidate_key(row)
            ] = row
    fidelity = validate_replay_fidelity(
        tuple(snapshot for snapshot in snapshots if snapshot.run_id in valid_run_ids),
        rows_by_decision,  # type: ignore[arg-type]
        ExecutedP1BStrategy(),
    )
    missingness = None if evaluation.missingness is None else asdict(evaluation.missingness)
    evaluable_scenario_ids = {
        scenario_group(row.run_id)
        for row in evaluation.outcomes
        if row.rule_id == EXECUTED_BASELINE_RULE_ID
    }
    exclusion_reasons_by_scenario: dict[str, Counter[str]] = defaultdict(Counter)
    for exclusion in evaluation.exclusions:
        exclusion_reasons_by_scenario[scenario_group(exclusion.run_id)][
            exclusion.reason
        ] += 1
    non_evaluable_scenarios = []
    for scenario_id in sorted(valid_scenario_ids - evaluable_scenario_ids):
        family_id = next(
            row["family_id"]
            for row in validity["valid_scenarios"]
            if row["scenario_id"] == scenario_id
        )
        non_evaluable_scenarios.append(
            {
                "scenario_id": scenario_id,
                "family_id": family_id,
                "eligibility_reason": (
                    "all_decisions_excluded"
                    if exclusion_reasons_by_scenario[scenario_id]
                    else "no_forced_release_decision_observed"
                ),
                "exclusion_reasons": dict(
                    sorted(exclusion_reasons_by_scenario[scenario_id].items())
                ),
            }
        )
    minimum_units = AcceptanceCriteria().minimum_scenario_draws
    evidence_eligibility = {
        "runtime_valid_independent_scenario_count": len(valid_scenario_ids),
        "paired_evaluable_independent_scenario_count": len(evaluable_scenario_ids),
        "minimum_paired_evaluable_scenarios": minimum_units,
        "adequate_for_formal_acceptance": len(evaluable_scenario_ids) >= minimum_units,
        "runtime_valid_but_not_paired_evaluable_count": len(
            non_evaluable_scenarios
        ),
        "runtime_valid_but_not_paired_evaluable_scenarios": (
            non_evaluable_scenarios
        ),
        "excluded_decisions_by_scenario": {
            scenario_id: dict(sorted(reasons.items()))
            for scenario_id, reasons in sorted(exclusion_reasons_by_scenario.items())
        },
        "interpretation": (
            "Runtime validity and paired evidence eligibility are separate. "
            "A runtime-valid scenario with no decision containing at least two "
            "candidates cannot contribute a frozen baseline/challenger pair."
        ),
    }
    return {
        "schema_version": "phase2a.h1_formal_level_a_result.v1",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": _sha(campaign_path),
        "execution_summary_sha256": _sha(execution_summary_path),
        "evidence_tier": "LEVEL_A_PROXY_FIRST",
        "primary_metric": "planned_return_weighted_prefill_proxy",
        "verdict_ceiling": "PROXY_CANDIDATE",
        "challenger_runtime_policy_switch_authorized": False,
        "validity": validity,
        "evidence_eligibility": evidence_eligibility,
        "replay_fidelity": asdict(fidelity),
        "missingness": missingness,
        "evaluation_counts": {
            "valid_run_count": len(valid_run_ids),
            "decisions_evaluated": evaluation.evaluated_decisions,
            "decisions_skipped": evaluation.skipped_decisions,
            "available_candidates": evaluation.available_candidates,
        },
        "acceptance_verdict": verdict.as_payload(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--execution-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = build_h1_formal_result(
        artifact_root=arguments.artifact_root,
        campaign_path=arguments.campaign,
        execution_summary_path=arguments.execution_summary,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verdict = result["acceptance_verdict"]
    print(f"H1 Level A candidate verdict: {verdict['level']} -> {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
