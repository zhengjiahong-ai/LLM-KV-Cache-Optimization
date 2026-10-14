"""Fail-closed Gate C validation for one Phase 2E measured native run."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .ingestion import load_run_artifacts
from .phase2e_fidelity import _materialized_digests, _runtime_mode
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
    checks = {
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
        "evictions_have_pre_eviction_identity": all(
            isinstance(row.get("payload"), dict)
            and row["payload"].get("native_cache_key_before")
            and row["payload"].get("native_hash_process_id")
            for row in run.events
            if row.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
        ),
    }
    reasons.extend(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "phase2e.gate_c_run.v1",
        "run_id": run.run_id,
        "scenario_id": stage.get("scenario_id"),
        "family": stage.get("family"),
        "baseline": baseline,
        "repeat": stage.get("repeat"),
        "status": "VALID" if not reasons else "INVALID",
        "checks": checks,
        "reasons": reasons,
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
