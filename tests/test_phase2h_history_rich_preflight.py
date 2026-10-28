from __future__ import annotations

import json
from pathlib import Path

from kvopt.workload.phase2h_history_rich_materialize import materialize
from kvopt.workload.phase2h_history_rich_preflight import (
    ARMS,
    PRESSURE_ROUNDS,
    SCENARIOS,
    _pressure_token_ids,
    build_preflight,
)


def test_pressure_inputs_are_boundary_distinct_and_arm_independent() -> None:
    for scenario_id, spec in SCENARIOS.items():
        hashes = []
        for round_index in PRESSURE_ROUNDS:
            seed = f"phase2h:{scenario_id}:after-round-{round_index}:pressure-v1"
            values = _pressure_token_ids(seed, int(spec["pressure_tokens"]))
            assert len(values) == spec["pressure_tokens"]
            assert len(values) % 16 == 0
            hashes.append(hash(values))
        assert len(set(hashes)) == len(PRESSURE_ROUNDS)
    assert ARMS == ("A0", "A1", "A2")


def test_real_w1c_preflight_when_evidence_is_available() -> None:
    root = Path("artifacts/continuum-w1c-pilot-runs-v1/S100")
    if not root.is_dir():
        return
    result = build_preflight(root)
    assert result["status"] == "PASS_STATIC_PREFLIGHT"
    assert result["planned_run_count"] == 6
    for scenario in result["scenarios"]:
        assert scenario["request_count"] == 180
        assert scenario["boundary_count"] == 363
        assert scenario["global_gap_count_before_first_pressure"] == 117
        arm_rows = [
            row
            for row in result["runs"]
            if row["scenario_id"] == scenario["scenario_id"]
        ]
        assert len(arm_rows) == 3
        assert {row["timeline_sha256"] for row in arm_rows} == {
            scenario["timeline_sha256"]
        }
        assert {row["pressure_input_sha256"] for row in arm_rows} == {
            scenario["pressure_input_sha256"]
        }


def test_preflight_result_is_json_serializable() -> None:
    root = Path("artifacts/continuum-w1c-pilot-runs-v1/S100")
    if root.is_dir():
        json.dumps(build_preflight(root), allow_nan=False)


def test_materialized_configs_bind_identical_pressure_and_timeline_across_arms(
    tmp_path: Path,
) -> None:
    root = Path("artifacts/continuum-w1c-pilot-runs-v1/S100")
    if not root.is_dir():
        return
    profile = tmp_path / "profile.json"
    profile.write_text("{}\n", encoding="utf-8")
    manifest = materialize(
        source_root=root,
        profile_path=profile,
        output_dir=tmp_path / "materialized",
    )
    assert manifest["execution_authorized"] is False
    assert manifest["planned_run_count"] == 6
    for scenario_id in SCENARIOS:
        rows = [row for row in manifest["runs"] if row["scenario_id"] == scenario_id]
        assert len(rows) == 3
        assert len({row["timeline_sha256"] for row in rows}) == 1
        assert len({row["pressure_input_sha256"] for row in rows}) == 1
