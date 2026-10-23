from pathlib import Path

from kvopt.profiling.continuum_w1c_report import _classify, build_report
from kvopt.workload.continuum_w1a_runner import (
    load_acquisition_config,
    validate_instance_id,
)
from kvopt.workload.continuum_w1c_sampling import (
    build_candidate_snapshot,
    freeze_sampling,
    validate_freeze,
)


def _rows() -> list[dict[str, object]]:
    rows = []
    for repo_index in range(12):
        for task_index in range(42):
            index = repo_index * 42 + task_index
            if index >= 500:
                break
            rows.append(
                {
                    "instance_id": f"repo{repo_index}__task-{task_index}",
                    "repo": f"owner/repo{repo_index}",
                    "base_commit": f"sha-{index}",
                    "problem_statement": "word " * (task_index + 1),
                    "created_at": "2026-01-01",
                    "difficulty": "unknown",
                }
            )
    return rows


def test_sampling_freeze_is_deterministic_and_covers_repositories() -> None:
    snapshot = build_candidate_snapshot(_rows())
    freeze = freeze_sampling(
        snapshot,
        snapshot_sha256="a" * 64,
        w1a_instance_ids=("repo0__task-0",),
    )

    assert freeze["sample_count"] == 100
    assert freeze["pilot_count"] == 20
    assert len(freeze["sample_repository_quotas"]) == 12
    assert len(freeze["pilot_repository_quotas"]) == 12
    assert "repo0__task-0" not in {
        row["instance_id"] for row in freeze["selected_tasks"]
    }
    assert validate_freeze(snapshot, freeze, snapshot_sha256="a" * 64) == []


def test_sampling_validation_rejects_snapshot_drift() -> None:
    snapshot = build_candidate_snapshot(_rows())
    freeze = freeze_sampling(
        snapshot,
        snapshot_sha256="a" * 64,
        w1a_instance_ids=(),
    )

    problems = validate_freeze(snapshot, freeze, snapshot_sha256="b" * 64)

    assert "candidate snapshot SHA-256 mismatch" in problems


def test_w1c_paired_configs_bind_same_frozen_pilot() -> None:
    repository = Path(__file__).parents[1]
    s50, sample50 = load_acquisition_config(
        repository / "configs/phase2/continuum-w1c-pilot-s50-v1.json",
        repository=repository,
    )
    s100, sample100 = load_acquisition_config(
        repository / "configs/phase2/continuum-w1c-pilot-s100-v1.json",
        repository=repository,
    )

    assert sample50 == sample100
    assert s50["author_runner"]["effective_step_limit"] == 50
    assert s100["author_runner"]["effective_step_limit"] == 100
    assert len(sample50["pilot_instance_ids"]) == 20
    validate_instance_id(sample50["pilot_instance_ids"][0], sample50)


def test_w1c_report_fails_closed_on_missing_frozen_runs(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    freeze = repository / "configs/phase2/continuum-w1c-stratified-sample-v1.json"

    report = build_report(freeze, tmp_path)

    assert report["observed_expected_run_count"] == 0
    assert len(report["missing_run_keys"]) == 40
    assert report["valid_pair_count"] == 0
    assert report["recommendation"] == "NO_GO_CURRENT_ACQUISITION_CONFIGURATION"
    audit = report["decision_opportunity_audit"]
    assert audit["decision_time_candidate_count"] == (
        "NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY"
    )


def test_w1c_context_limit_is_not_classified_as_step_censoring() -> None:
    assert _classify(
        {
            "agent_outcome": "INCOMPLETE",
            "agent_exit_status": "ContextLengthExceeded",
        }
    ) == "FAILED_CONTEXT_LIMIT"
