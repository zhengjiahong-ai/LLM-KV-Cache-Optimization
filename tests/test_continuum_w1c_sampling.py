import hashlib
import json
from pathlib import Path

import pytest

from kvopt.profiling.continuum_w1c_report import (
    _canonical_sha256,
    _classify,
    _validate_context_limit_sidecar,
    build_report,
)
from kvopt.workload.continuum_w1a_runner import (
    load_acquisition_config,
    validate_instance_id,
)
from kvopt.workload.continuum_w1c_runner import _existing_run_problems, _inputs
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


def test_w1c_lifecycle_classification_distinguishes_limits() -> None:
    base = {
        "agent_outcome": "INCOMPLETE",
        "agent_exit_status": "LimitsExceeded",
        "effective_step_limit": 50,
        "cost_limit": 3.0,
    }
    assert _classify(
        base,
        {"info": {"model_stats": {"api_calls": 50, "instance_cost": 0.0}}},
    ) == "RIGHT_CENSORED_STEP_LIMIT"
    assert _classify(
        base,
        {"info": {"model_stats": {"api_calls": 12, "instance_cost": 3.0}}},
    ) == "RIGHT_CENSORED_COST_LIMIT"
    assert _classify(
        {**base, "agent_exit_status": "JobTimeoutError"},
        {"info": {"model_stats": {"api_calls": 12, "instance_cost": 0.0}}},
    ) == "FAILED_JOB_TIMEOUT"


def test_w1c_resume_rejects_incomplete_or_stale_manifest() -> None:
    repository = Path(__file__).parents[1]
    config_path = repository / "configs/phase2/continuum-w1c-pilot-s50-v1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = {
        "status": "running",
        "instance_id": "astropy__astropy-8872",
        "condition": "S50",
        "config_sha256": "wrong",
        "repository_git_sha": "execution-sha",
        "author_repository_git_sha": config["author_runner"]["commit"],
        "effective_step_limit": 50,
        "cost_limit": 3.0,
        "max_model_len": 32768,
        "dataset": config["dataset"],
        "model": config["model"],
        "server_runtime": config["server_runtime"],
        "environment": config["environment"],
    }

    problems = _existing_run_problems(
        manifest,
        instance_id="astropy__astropy-8872",
        condition="S50",
        config=config,
        config_path=config_path,
        authorization={"repository_git_sha": "execution-sha"},
    )

    assert "existing run status binding mismatch" in problems
    assert "existing run config_sha256 binding mismatch" in problems
    assert "existing run lacks a completed terminal Agent outcome" in problems


def test_w1c_pair_rejects_policy_independent_config_drift(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    s50_source = repository / "configs/phase2/continuum-w1c-pilot-s50-v1.json"
    s100_source = repository / "configs/phase2/continuum-w1c-pilot-s100-v1.json"
    s50 = tmp_path / "s50.json"
    s100 = tmp_path / "s100.json"
    s50.write_bytes(s50_source.read_bytes())
    payload = json.loads(s100_source.read_text(encoding="utf-8"))
    payload["model"]["max_completion_tokens"] = 256
    s100.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="policy-independent configuration drift"):
        _inputs(repository, s50, s100)


def test_w1c_report_requires_authorized_bindings_for_existing_runs(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).parents[1]
    freeze = repository / "configs/phase2/continuum-w1c-stratified-sample-v1.json"
    (tmp_path / "S50" / "unexpected").mkdir(parents=True)

    with pytest.raises(ValueError, match="requires configs and authorization"):
        build_report(freeze, tmp_path)


def test_w1c_context_limit_validation_rejects_tampered_final_tokens(
    tmp_path: Path,
) -> None:
    instance_id = "owner__task-1"
    trajectory = {
        "messages": [
            {"role": "user", "content": "fix"},
            {"role": "assistant", "content": "done", "extra": None},
            {"role": "user", "content": "maximum context length exceeded"},
        ],
        "info": {"exit_status": "ContextLengthExceeded"},
    }
    trajectory_path = tmp_path / "task.traj.json"
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")

    def tokenize(messages):
        rendered = f"rendered:{len(messages)}"
        return rendered, list(range(len(messages) + 1))

    first_messages = trajectory["messages"][:1]
    first_rendered, first_tokens = tokenize(first_messages)
    failed_messages = trajectory["messages"][:-1]
    final_rendered, _final_tokens = tokenize(failed_messages)
    sidecar = {
        "schema_version": "continuum.w1a_acquisition_sidecar.v1",
        "program_id": instance_id,
        "trajectory_sha256": hashlib.sha256(trajectory_path.read_bytes()).hexdigest(),
        "observation_boundaries": {},
        "tool_calls": [],
        "model_calls": [
            {
                "request_id": f"{instance_id}:turn:1",
                "status": "SUCCESS",
                "messages": first_messages,
                "messages_sha256": _canonical_sha256(first_messages),
                "response_sha256": _canonical_sha256(
                    {"content": "done", "extra": None}
                ),
                "model_submit_monotonic_seconds": 1.0,
                "model_completion_monotonic_seconds": 2.0,
                "rendered_prompt": first_rendered,
                "rendered_prompt_sha256": hashlib.sha256(
                    first_rendered.encode()
                ).hexdigest(),
                "submitted_token_ids": first_tokens,
                "token_observation_status": "PINNED_LOCAL_TOKENIZATION",
            },
            {
                "request_id": f"{instance_id}:turn:2",
                "status": "FAILED",
                "messages": failed_messages,
                "messages_sha256": _canonical_sha256(failed_messages),
                "model_submit_monotonic_seconds": 3.0,
                "model_completion_monotonic_seconds": 4.0,
                "rendered_prompt": final_rendered,
                "submitted_token_ids": [999],
                "error": "maximum context length exceeded",
            },
        ],
    }

    with pytest.raises(ValueError, match="token IDs mismatch"):
        _validate_context_limit_sidecar(
            sidecar,
            trajectory=trajectory,
            trajectory_path=trajectory_path,
            instance_id=instance_id,
            tokenize_messages=tokenize,
        )
