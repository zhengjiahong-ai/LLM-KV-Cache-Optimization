"""Validate non-holdout H1 compiler runs against their evidence contracts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .datasets import build_decision_tables
from .ingestion import load_run_artifacts
from .runtime_evidence import build_request_runtime_evidence_table


def _baseline_replay_is_ordered(candidates: tuple[object, ...]) -> bool:
    by_decision: dict[int, list[object]] = {}
    for row in candidates:
        by_decision.setdefault(row.decision_event_index, []).append(row)
    for rows in by_decision.values():
        selected = sorted(
            (row for row in rows if row.selected),
            key=lambda row: row.release_order,
        )
        expected = sorted(
            rows,
            key=lambda row: (
                row.retention_deadline_timestamp,
                row.program_id,
                row.prefix_id,
            ),
        )[: len(selected)]
        if [row.program_id for row in selected] != [row.program_id for row in expected]:
            return False
    return True


def build_fidelity_report(campaign_path: Path, run_root: Path) -> dict[str, object]:
    campaign_path = campaign_path.resolve()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign.get("campaign_kind") != "NON_HOLDOUT_FIDELITY_VALIDATION":
        raise ValueError("unsupported H1 fidelity campaign")
    results = []
    for fixture in campaign["fixtures"]:
        run_id = fixture["scenario_id"]
        contract_path = campaign_path.parent / f"{run_id}.evidence-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        artifacts = load_run_artifacts(run_root.resolve() / run_id)
        tables = build_decision_tables((artifacts,))
        runtime_rows = build_request_runtime_evidence_table((artifacts,))
        expected_stages = contract["pressure_contract"]["stage_count"]
        expected_programs = {item["program_id"] for item in contract["candidate_contracts"]}
        observed_programs = {row.program_id for row in tables.candidates}
        baseline_replay = _baseline_replay_is_ordered(tables.candidates)
        native_rows_available = all(
            row.availability == "AVAILABLE" for row in runtime_rows if row.kind == "turn"
        )
        checks = {
            "forced_release_decisions_present": len(tables.decisions) >= expected_stages,
            "all_compiled_candidates_observed": expected_programs <= observed_programs,
            "baseline_replay_uses_earliest_deadline": baseline_replay,
            "native_request_evidence_available": native_rows_available,
            "level_a_metric_unchanged": contract["primary_metric"]
            == "planned_return_weighted_prefill_proxy",
            "no_challenger_policy_switch": contract["challenger_runtime_policy_switch_authorized"]
            is False,
        }
        results.append(
            {
                "fixture_id": run_id,
                "decision_count": len(tables.decisions),
                "candidate_program_count": len(observed_programs),
                "checks": checks,
                "outcome": "PASS" if all(checks.values()) else "FAIL",
            }
        )
    return {
        "schema_version": "phase2a.h1_compiler_fidelity_report.v1",
        "formal_h1_outcome_execution_authorized": False,
        "challenger_runtime_policy_switch_authorized": False,
        "overall_outcome": "PASS" if all(item["outcome"] == "PASS" for item in results) else "FAIL",
        "fixture_results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = build_fidelity_report(arguments.campaign, arguments.run_root)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{report['overall_outcome']}: {arguments.output.resolve()}")
    return 0 if report["overall_outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
