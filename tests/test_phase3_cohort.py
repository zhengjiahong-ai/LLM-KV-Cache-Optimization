from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from kvopt.workload.continuum_w1a_runner import (
    load_acquisition_config,
    validate_instance_id,
)
from kvopt.workload.phase3_acquisition import pending_candidates
from kvopt.workload.phase3_cohort import (
    build_candidate_plan,
    select_reserve_promotions,
    validate_candidate_plan,
)


def _freeze() -> dict[str, object]:
    repositories = {
        "owner/repo-a": 30,
        "owner/repo-b": 15,
        "owner/repo-c": 10,
        "owner/repo-d": 8,
        "owner/repo-e": 5,
        "owner/repo-f": 4,
        "owner/repo-g": 3,
        "owner/repo-h": 2,
        "owner/repo-i": 2,
        "owner/repo-j": 1,
    }
    tasks: list[dict[str, object]] = []
    for repo_index, (repository, count) in enumerate(repositories.items()):
        for task_index in range(count):
            tasks.append(
                {
                    "instance_id": f"repo{repo_index}__task-{task_index}",
                    "repository": repository,
                    "base_commit": f"base-{repo_index}-{task_index}",
                    "created_at": "2026-01-01T00:00:00Z",
                    "difficulty": "unknown",
                    "problem_statement_char_count": 100 + task_index,
                    "problem_statement_word_count": 10 + task_index,
                    "problem_statement_sha256": f"{repo_index:02x}{task_index:02x}".ljust(64, "0"),
                    "pilot_selected": False,
                }
            )
    for index in range(20):
        tasks.append(
            {
                **tasks[index],
                "instance_id": f"pilot__task-{index}",
                "pilot_selected": True,
            }
        )
    return {
        "schema_version": "continuum.w1c_stratified_sample_freeze.v1",
        "dataset": {"revision": "frozen-revision"},
        "selected_tasks": tasks,
        "pilot_instance_ids": [f"pilot__task-{index}" for index in range(20)],
    }


def test_candidate_plan_is_deterministic_and_meets_frozen_counts() -> None:
    source = _freeze()
    first = build_candidate_plan(source, source_sha256="a" * 64)
    second = build_candidate_plan(source, source_sha256="a" * 64)

    assert first == second
    assert first["primary_count"] == 40
    assert first["reserve_count"] == 24
    assert len(first["candidates"]) == 64
    primary = [row for row in first["candidates"] if row["role"] == "PRIMARY"]
    assert len({row["repository"] for row in primary}) == 10
    assert not (
        {row["instance_id"] for row in first["candidates"]}
        & set(first["historical_pilot_ids_excluded"])
    )
    assert validate_candidate_plan(
        source, first, source_sha256="a" * 64
    ) == []


def test_candidate_plan_validation_rejects_role_tampering() -> None:
    source = _freeze()
    plan = build_candidate_plan(source, source_sha256="a" * 64)
    tampered = deepcopy(plan)
    tampered["candidates"][0]["role"] = "RESERVE"

    problems = validate_candidate_plan(
        source, tampered, source_sha256="a" * 64
    )

    assert "candidate plan does not deterministically regenerate" in problems
    assert "candidate plan role counts are invalid" in problems


def test_candidate_plan_rejects_non_eighty_candidate_frame() -> None:
    source = _freeze()
    source["selected_tasks"].pop(0)

    try:
        build_candidate_plan(source, source_sha256="a" * 64)
    except ValueError as error:
        assert "exactly 80" in str(error)
    else:
        raise AssertionError("an incomplete candidate frame must fail closed")


def _write_phase3_acquisition_fixture(root: Path) -> tuple[Path, dict[str, object]]:
    plan = build_candidate_plan(_freeze(), source_sha256="a" * 64)
    plan_path = root / "candidate-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    config = {
        "schema_version": "phase3.agent_acquisition_config.v1",
        "scope": "PHASE3_FROZEN_COHORT_AGENT_ACQUISITION_NO_NATIVE_CAMPAIGN",
        "sample_manifest": plan_path.name,
        "candidate_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "dataset": {"revision": "frozen-revision"},
        "author_runner": {"effective_step_limit": 100},
        "execution_budget": {
            "agent_acquisition_authorized": True,
            "formal_native_campaign_authorized": False,
        },
    }
    config_path = root / "acquisition.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path, plan


def test_phase3_acquisition_config_binds_candidate_plan(tmp_path: Path) -> None:
    config_path, plan = _write_phase3_acquisition_fixture(tmp_path)

    config, loaded = load_acquisition_config(config_path, repository=tmp_path)

    assert config["schema_version"] == "phase3.agent_acquisition_config.v1"
    assert loaded == plan
    validate_instance_id(str(plan["candidates"][0]["instance_id"]), loaded)
    with pytest.raises(ValueError, match="frozen acquisition sample"):
        validate_instance_id("unregistered__task-1", loaded)


def test_phase3_acquisition_config_rejects_plan_hash_drift(tmp_path: Path) -> None:
    config_path, _plan = _write_phase3_acquisition_fixture(tmp_path)
    plan_path = tmp_path / "candidate-plan.json"
    plan_path.write_text(plan_path.read_text() + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="candidate-plan SHA-256 mismatch"):
        load_acquisition_config(config_path, repository=tmp_path)


def test_phase3_pending_candidates_preserve_rank_and_attempts(tmp_path: Path) -> None:
    plan = build_candidate_plan(_freeze(), source_sha256="a" * 64)
    candidates = plan["candidates"]
    first_id = str(candidates[0]["instance_id"])
    attempted = tmp_path / first_id
    attempted.mkdir()
    (attempted / "run.json").write_text('{"status":"failed"}', encoding="utf-8")

    pending = pending_candidates(plan, runs_root=tmp_path)

    assert len(pending) == 39
    assert pending[0]["acquisition_rank"] == 2
    assert all(row["role"] == "PRIMARY" for row in pending)


def test_phase3_pending_candidates_fail_on_incomplete_attempt(tmp_path: Path) -> None:
    plan = build_candidate_plan(_freeze(), source_sha256="a" * 64)
    first_id = str(plan["candidates"][0]["instance_id"])
    (tmp_path / first_id).mkdir()

    with pytest.raises(ValueError, match="lacks run.json"):
        pending_candidates(plan, runs_root=tmp_path)


def test_phase3_reserve_promotions_are_same_repository_first() -> None:
    plan = build_candidate_plan(_freeze(), source_sha256="a" * 64)
    primary = [row for row in plan["candidates"] if row["role"] == "PRIMARY"]
    failed = [
        next(row for row in primary if row["repository"] == "owner/repo-a"),
        next(row for row in primary if row["repository"] == "owner/repo-b"),
    ]

    promoted = select_reserve_promotions(
        plan, [str(row["instance_id"]) for row in failed]
    )

    assert [row["repository"] for row in promoted] == [
        "owner/repo-a",
        "owner/repo-b",
    ]
    assert [row["replaces_primary_instance_id"] for row in promoted] == [
        row["instance_id"] for row in failed
    ]


def test_phase3_explicit_reserve_selection_is_exact(tmp_path: Path) -> None:
    plan = build_candidate_plan(_freeze(), source_sha256="a" * 64)
    reserve = next(row for row in plan["candidates"] if row["role"] == "RESERVE")

    pending = pending_candidates(
        plan,
        runs_root=tmp_path,
        roles=("RESERVE",),
        instance_ids=(str(reserve["instance_id"]),),
    )

    assert [row["instance_id"] for row in pending] == [reserve["instance_id"]]
    with pytest.raises(ValueError, match="does not match the selected role"):
        pending_candidates(
            plan,
            runs_root=tmp_path,
            roles=("PRIMARY",),
            instance_ids=(str(reserve["instance_id"]),),
        )
