from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kvopt.workload import phase2h_history_rich_preflight as preflight_module
from kvopt.workload.phase2 import load_phase2_trace
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
        arm_rows = [row for row in result["runs"] if row["scenario_id"] == scenario["scenario_id"]]
        assert len(arm_rows) == 3
        assert {row["timeline_sha256"] for row in arm_rows} == {scenario["timeline_sha256"]}
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
    for row in manifest["runs"]:
        config = json.loads(
            (tmp_path / "materialized" / row["config"]).read_text(encoding="utf-8")
        )
        trace = load_phase2_trace(tmp_path / "materialized" / config["trace"])
        assert len(trace.requests) == 180


def test_source_hash_tamper_fails_closed(tmp_path: Path) -> None:
    source = Path("artifacts/continuum-w1c-pilot-runs-v1/S100")
    if not source.is_dir():
        return
    task = "django__django-13023"
    target = tmp_path / task
    shutil.copytree(source / task, target)
    with (target / "acquisition-sidecar.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="source hash"):
        preflight_module._load_calls(tmp_path, task)


def test_failed_call_inside_first_sixty_is_not_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path("artifacts/continuum-w1c-pilot-runs-v1/S100")
    if not source.is_dir():
        return
    task = "django__django-13023"
    target = tmp_path / task
    shutil.copytree(source / task, target)
    sidecar_path = target / "acquisition-sidecar.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["model_calls"][10]["status"] = "FAILED"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    run_path = target / "run.json"
    trajectory_path = target / f"{task}.traj.json"
    hashes = (
        preflight_module._sha(sidecar_path),
        preflight_module._sha(trajectory_path),
        preflight_module._sha(run_path),
    )
    monkeypatch.setitem(preflight_module.FROZEN_SOURCE_HASHES, task, hashes)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["sidecar_sha256"] = hashes[0]
    run_path.write_text(json.dumps(run), encoding="utf-8")
    hashes = (hashes[0], hashes[1], preflight_module._sha(run_path))
    monkeypatch.setitem(preflight_module.FROZEN_SOURCE_HASHES, task, hashes)
    with pytest.raises(ValueError, match="contiguous success cohort"):
        preflight_module._load_calls(tmp_path, task)
