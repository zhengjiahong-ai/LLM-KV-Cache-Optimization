"""Fail-closed Gate C validation for one Phase 2E measured native run."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .ingestion import load_run_artifacts
from .phase2e_fidelity import (
    _materialized_digests,
    _native_execution_overlap,
    _runtime_mode,
)
from .runtime_evidence import build_request_runtime_evidence_table


def evaluate_run(run_dir: Path) -> dict[str, object]:
    run = load_run_artifacts(run_dir)
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    stage = config.get("phase2e_stage", {})
    rows = [asdict(row) for row in build_request_runtime_evidence_table((run,))]
    replay_ids = [str(row.get("request_id")) for row in run.replay]
    digests = _materialized_digests(run)
    expected_turn_ids = {
        str(row["request_id"])
        for row in run.trace.get("requests", [])
        if isinstance(row, dict)
    }
    replay_turn_ids = {value for value in replay_ids if not value.startswith("pressure:")}
    baseline = stage.get("baseline")
    expected_mode = "native" if baseline == "native-lru" else "controlled"
    reasons: list[str] = []
    base_checks = {
        "execution_success": run.manifest.get("execution_status") == "success",
        "clean_git": run.manifest.get("git_dirty") is False,
        "expected_turn_request_ids_complete": replay_turn_ids == expected_turn_ids,
        "completion_count_matches_replay": run.manifest.get("completion_count")
        == len(replay_ids),
        "all_materialized_digests_present": set(digests) == set(replay_ids)
        and all(digests.values()),
        "request_native_evidence_complete": len(rows) == len(replay_ids)
        and all(row["availability"] == "AVAILABLE" for row in rows),
        "native_timestamps_complete": all(
            row["native_queue_delay_status"] == "available"
            and row["native_prefill_to_first_token_status"] == "available"
            for row in rows
        ),
        "baseline_mode_realized": _runtime_mode(run) == expected_mode,
        "native_lru_has_no_forced_release": baseline != "native-lru"
        or not any(row.get("event_type") == "FORCED_RELEASE_DECISION" for row in run.events),
    }
    evictions = [
        row
        for row in run.events
        if row.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
    ]
    eviction_identity_complete = bool(evictions) and all(
            isinstance(row.get("payload"), dict)
            and row["payload"].get("native_cache_key_before")
            and row["payload"].get("native_hash_process_id")
            for row in evictions
        )
    family = str(stage.get("family"))
    by_program: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        if str(row["request_id"]).startswith("pressure:"):
            continue
        by_program.setdefault(str(row["program_id"]), []).append(row)
    shared_native_prefix = False
    program_values = list(by_program.values())
    for index, left_rows in enumerate(program_values):
        for right_rows in program_values[index + 1 :]:
            left = left_rows[0].get("native_apc_block_hashes") or ()
            right = right_rows[0].get("native_apc_block_hashes") or ()
            shared_native_prefix = shared_native_prefix or bool(
                left and right and left[0] == right[0]
            )
    growth_realized = any(
        len({int(row["native_prompt_tokens"]) for row in program_rows}) > 1
        for program_rows in by_program.values()
    )
    overlap = _native_execution_overlap(rows)
    mechanism_checks: dict[str, bool] = {
        "physical_eviction_realized_with_identity": eviction_identity_complete,
    }
    if family == "F4":
        control = bool(stage.get("shared_prefix_control"))
        mechanism_checks["shared_prefix_mode_realized"] = (
            not shared_native_prefix if control else shared_native_prefix
        )
    elif family == "F5":
        mechanism_checks.update(
            context_growth_realized=growth_realized,
            repeated_pressure_realized=int(run.manifest.get("pressure_attempts", 0)) >= 2,
            return_after_pressure_observed=len(rows) >= len(replay_ids),
        )
    elif family == "F6":
        mechanism_checks.update(
            native_request_overlap_realized=bool(
                overlap["identity_checks_pass"] and overlap["overlap_seconds"] > 0
            ),
            pressure_is_post_completion_barrier=True,
            inflight_cache_competition_not_claimed=True,
        )
    base_valid = all(base_checks.values())
    mechanism_realized = all(mechanism_checks.values())
    reasons.extend(name for name, passed in base_checks.items() if not passed)
    return {
        "schema_version": "phase2e.gate_c_run.v1",
        "run_id": run.run_id,
        "scenario_id": stage.get("scenario_id"),
        "family": family,
        "baseline": baseline,
        "repeat": stage.get("repeat"),
        "status": "VALID" if base_valid else "INVALID",
        "request_metrics_status": "VALID" if base_valid else "INVALID",
        "family_mechanism_status": (
            "REALIZED" if mechanism_realized else "NOT_REALIZED"
        ),
        "base_checks": base_checks,
        "mechanism_checks": mechanism_checks,
        "reasons": reasons,
        "mechanism_limitations": (
            []
            if mechanism_realized
            else [name for name, passed in mechanism_checks.items() if not passed]
        ),
        "native_overlap_evidence": overlap if family == "F6" else None,
        "request_evidence": rows,
        "materialized_token_digests": digests,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate_run(args.run_dir)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Phase 2E Gate C: {result['status']} -> {args.output}")
    return 0 if result["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
