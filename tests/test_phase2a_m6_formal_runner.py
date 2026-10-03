import json
from pathlib import Path

import pytest

from kvopt.workload.phase2_formal import materialize_formal_campaign
from kvopt.workload.phase2_formal_runner import execute_formal_campaign

BASE_CONFIG = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "profiling"
    / "p3-a128-b512-a-early.json"
)


def test_formal_runner_executes_once_and_resumes_without_replacement(
    tmp_path: Path,
) -> None:
    campaign = materialize_formal_campaign(BASE_CONFIG, tmp_path / "campaign")
    output_root = tmp_path / "runs"
    calls: list[dict[str, object]] = []

    def fake_executor(
        config_path: Path,
        *,
        output_root: Path,
        run_id: str,
    ) -> Path:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        calls.append(config)
        run_dir = output_root / run_id
        run_dir.mkdir()
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "success",
                    "failure_reason": None,
                }
            ),
            encoding="utf-8",
        )
        return run_dir

    filters = {
        "scenario_ids": ("f1-two-homogeneous-shallow",),
        "seeds": (101,),
    }
    first, first_path = execute_formal_campaign(
        campaign,
        output_root,
        run_executor=fake_executor,
        **filters,
    )
    second, second_path = execute_formal_campaign(
        campaign,
        output_root,
        resume=True,
        run_executor=fake_executor,
        **filters,
    )

    assert first.executed_run_count == 1
    assert first.successful_run_count == 1
    assert second.executed_run_count == 0
    assert second.skipped_run_count == 1
    assert len(calls) == 1
    assert calls[0]["seed"] == 101
    assert calls[0]["profiling_scenario_family"] == "F1"
    assert Path(calls[0]["trace"]).is_absolute()
    assert first_path != second_path
    assert first_path.is_file() and second_path.is_file()


def test_formal_runner_refuses_existing_run_without_resume(
    tmp_path: Path,
) -> None:
    campaign = materialize_formal_campaign(BASE_CONFIG, tmp_path / "campaign")
    output_root = tmp_path / "runs"
    existing = output_root / "f1-two-homogeneous-shallow-seed-101"
    existing.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="formal run output already exists"):
        execute_formal_campaign(
            campaign,
            output_root,
            scenario_ids=("f1-two-homogeneous-shallow",),
            seeds=(101,),
        )


def test_formal_runner_resume_preserves_failed_run(tmp_path: Path) -> None:
    campaign = materialize_formal_campaign(BASE_CONFIG, tmp_path / "campaign")
    output_root = tmp_path / "runs"
    calls = 0

    def failing_executor(
        config_path: Path,
        *,
        output_root: Path,
        run_id: str,
    ) -> Path:
        nonlocal calls
        calls += 1
        assert config_path.is_file()
        run_dir = output_root / run_id
        run_dir.mkdir()
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "failed",
                    "failure_reason": "synthetic failure",
                }
            ),
            encoding="utf-8",
        )
        return run_dir

    filters = {
        "scenario_ids": ("f1-two-homogeneous-shallow",),
        "seeds": (101,),
    }
    first, _ = execute_formal_campaign(
        campaign,
        output_root,
        run_executor=failing_executor,
        **filters,
    )
    second, _ = execute_formal_campaign(
        campaign,
        output_root,
        resume=True,
        run_executor=failing_executor,
        **filters,
    )

    assert first.failed_run_count == 1
    assert second.failed_run_count == 1
    assert second.skipped_run_count == 1
    assert calls == 1
