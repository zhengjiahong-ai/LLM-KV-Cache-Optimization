"""Fail-closed Gate D2 evaluation for the bounded shared-retention fixture."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .phase2d_shared_retention import audit_shared_retention


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON must be an object: {path}")
    return value


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def evaluate_e2(runs_root: Path) -> dict[str, Any]:
    audit = audit_shared_retention(runs_root)
    decisions = {row["run_id"]: row for row in audit["decisions"]}
    results: list[dict[str, Any]] = []
    for run_path in sorted(runs_root.glob("*/run.json")):
        run_dir = run_path.parent
        run = _json(run_path)
        config = _json(run_dir / "config.json")
        trace = _json(run_dir / "trace.json")
        stage = config.get("phase2d_stage")
        if not isinstance(stage, dict):
            raise TypeError("E2 run config lacks phase2d_stage")
        events = _events(run_dir / "events.jsonl")
        run_id = str(run["run_id"])
        expected_request_ids = {str(row["request_id"]) for row in trace.get("requests", [])}
        materialized_ids = {
            str(row.get("request_id"))
            for row in events
            if row.get("event_type") == "BACKEND_INPUT_MATERIALIZED"
            and row.get("request_id") in expected_request_ids
        }
        native_by_request = {
            str(row.get("request_id")): row
            for row in events
            if row.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
            and row.get("request_id") in expected_request_ids
        }
        reasons: list[str] = []
        if run.get("execution_status") != "success":
            reasons.append("execution did not succeed")
        if materialized_ids != expected_request_ids:
            reasons.append("not every expected request has materialized-input evidence")
        if set(native_by_request) != expected_request_ids:
            reasons.append("not every expected request has native APC evidence")
        block_size = int(config["cache"]["block_size"])
        for request_id, event in native_by_request.items():
            payload = event.get("payload", {})
            cached = payload.get("native_cached_prefix_tokens")
            prompt = payload.get("native_prompt_tokens")
            if (
                not isinstance(cached, int)
                or cached < 0
                or cached % block_size
                or not isinstance(prompt, int)
                or cached > prompt
            ):
                reasons.append(f"invalid cached-token evidence for {request_id}")
        decision = decisions.get(run_id)
        expected_shared = int(stage["expected_shared_protected_blocks"])
        actual_shared: int | None = None
        relief_counts: list[int] = []
        if decision is None:
            reasons.append("exactly one forced-release decision was not observed")
        else:
            if decision["candidate_count"] != 2:
                reasons.append("decision does not contain exactly two legal candidates")
            if decision["owner_mapping_status"] != "OBSERVABLE":
                reasons.append("decision-time owner mapping is not observable")
            actual_shared = len(decision["shared_protected_blocks"])
            if actual_shared != expected_shared:
                reasons.append("observed shared protected block count differs from fixture")
            relief_counts = [int(value) for value in decision["marginal_relief_counts"]]
            for mapping in decision["candidate_mappings"]:
                owner_blocks = {
                    (mapping["native_hash_process_id"], block["block_id"], block["native_hash"])
                    for block in mapping["blocks"]
                }
                shared_blocks = {
                    (
                        row["native_hash_process_id"],
                        row["block_id"],
                        row["native_hash"],
                    )
                    for row in decision["shared_protected_blocks"]
                }
                expected_relief = len(owner_blocks - shared_blocks)
                if mapping["initially_reclaimable_block_count"] != expected_relief:
                    reasons.append("marginal relief differs from owner-minus-shared blocks")
        results.append(
            {
                "run_id": run_id,
                "case_id": stage.get("case_id"),
                "status": "PASS" if not reasons else "FAIL",
                "reasons": reasons,
                "expected_request_count": len(expected_request_ids),
                "observed_materialized_request_count": len(materialized_ids),
                "observed_native_request_count": len(native_by_request),
                "expected_shared_protected_blocks": expected_shared,
                "observed_shared_protected_blocks": actual_shared,
                "marginal_relief_counts": relief_counts,
                "decision_event_index": (
                    None if decision is None else decision["decision_event_index"]
                ),
            }
        )
    expected_run_ids = {
        f"{case}-repeat-{repeat}"
        for case in ("e2-shared-root", "e2-distinct-root-control")
        for repeat in (1, 2)
    }
    observed_run_ids = {row["run_id"] for row in results}
    all_pass = observed_run_ids == expected_run_ids and all(
        row["status"] == "PASS" for row in results
    )
    return {
        "schema_version": "phase2d.e2_gate.v1",
        "gate": "D2",
        "status": "PASS" if all_pass else "FAIL",
        "expected_run_ids": sorted(expected_run_ids),
        "observed_run_ids": sorted(observed_run_ids),
        "runs": results,
        "shared_retention_audit": audit,
        "forced_victim_used": False,
        "formal_claim": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = evaluate_e2(arguments.runs_root)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Gate D2 {result['status']}: {arguments.output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
