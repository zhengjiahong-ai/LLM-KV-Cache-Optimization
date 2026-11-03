from __future__ import annotations

from copy import deepcopy

from kvopt.workload.phase3_cohort import (
    build_candidate_plan,
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
