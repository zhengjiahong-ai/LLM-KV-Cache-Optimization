import json
from pathlib import Path

import pytest

from kvopt.profiling.phase2c_workload_audit import (
    summarize_historical_rows,
    validate_content_schema,
)

SCHEMA = Path("configs/phase2/phase2c-workload-content-schema-v1.json")


def _row(
    run_id: str,
    request_id: str,
    hashes: list[str],
    *,
    outcome: str,
    cached: int,
    eligible: int,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "program_id": request_id.split(":", 1)[0],
        "request_id": request_id,
        "kind": "turn",
        "apc_outcome": outcome,
        "eligible_prefix_tokens": eligible,
        "native_cached_prefix_tokens": cached,
        "native_apc_block_hashes": hashes,
    }


def test_summarize_separates_eligibility_identity_and_realized_apc() -> None:
    rows = [
        _row("r-101", "a:1", ["a"], outcome="NO_REUSE_ELIGIBLE_PREFIX", cached=0, eligible=0),
        _row("r-101", "a:2", ["a"], outcome="FULL_HIT", cached=16, eligible=16),
        _row("r-101", "b:1", ["b"], outcome="NO_REUSE_ELIGIBLE_PREFIX", cached=0, eligible=0),
        _row("r-101", "b:2", ["b"], outcome="MISS", cached=0, eligible=16),
        _row("r-211", "a:1", ["x"], outcome="NO_REUSE_ELIGIBLE_PREFIX", cached=0, eligible=0),
        _row("r-211", "a:2", ["x"], outcome="FULL_HIT", cached=16, eligible=16),
        _row("r-211", "b:1", ["y"], outcome="NO_REUSE_ELIGIBLE_PREFIX", cached=0, eligible=0),
        _row("r-211", "b:2", ["y"], outcome="MISS", cached=0, eligible=16),
        _row("r-307", "a:1", ["m"], outcome="NO_REUSE_ELIGIBLE_PREFIX", cached=0, eligible=0),
        _row("r-307", "a:2", ["m"], outcome="FULL_HIT", cached=16, eligible=16),
        _row("r-307", "b:1", ["n"], outcome="NO_REUSE_ELIGIBLE_PREFIX", cached=0, eligible=0),
        _row("r-307", "b:2", ["n"], outcome="MISS", cached=0, eligible=16),
    ]
    runs = [
        {"run_id": run_id, "status": "success", "scenario_id": "s", "scenario_family_id": "F1"}
        for run_id in ("r-101", "r-211", "r-307")
    ]

    result = summarize_historical_rows(rows, runs)

    assert result["eligible_turn_rows"] == 6
    assert result["eligible_apc_outcomes"] == {"FULL_HIT": 3, "MISS": 3}
    assert result["same_program_first_to_all_later_hash_chain"] == {
        "identical": 6,
        "compared": 6,
    }
    assert result["different_program_first_hash_chain"] == {
        "equal": 0,
        "compared": 3,
    }
    assert result["three_seed_outcome_and_cached_tokens"] == {
        "identical": 2,
        "compared": 2,
    }


def test_content_schema_is_block_aligned_and_keeps_experiment_locked() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    validate_content_schema(schema)


def test_content_schema_rejects_hit_rate_target() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["sampling_contract"]["target_hit_rate_permitted"] = True

    with pytest.raises(ValueError, match="target hit-rate"):
        validate_content_schema(schema)
