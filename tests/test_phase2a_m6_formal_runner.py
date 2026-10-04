import json
import subprocess
import sys
from pathlib import Path

import pytest

from kvopt.workload.phase2_formal import materialize_formal_campaign
from kvopt.workload.phase2_formal_runner import (
    execute_formal_campaign,
    load_formal_campaign,
    run_phase2_isolated,
)

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


def test_formal_runner_rejects_modified_scenario_config(tmp_path: Path) -> None:
    campaign = materialize_formal_campaign(BASE_CONFIG, tmp_path / "campaign")
    manifest = json.loads(campaign.read_text(encoding="utf-8"))
    config_path = campaign.parent / manifest["scenarios"][0]["config"]
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="scenario config SHA-256 mismatch"):
        load_formal_campaign(campaign)


def test_isolated_executor_launches_fresh_python_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    output_root = tmp_path / "runs"
    output_root.mkdir()

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command[:3] == [
            sys.executable,
            "-m",
            "kvopt.workload.phase2_single_runner",
        ]
        assert capture_output and not check and text
        run_dir = output_root / "isolated-run"
        run_dir.mkdir()
        (run_dir / "run.json").write_text(
            json.dumps({"status": "success"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "success\n", "runtime log\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_phase2_isolated(
        config_path,
        output_root=output_root,
        run_id="isolated-run",
    )

    assert result == output_root / "isolated-run"
    assert (result / "launcher-stdout.log").read_text(encoding="utf-8") == "success\n"
    assert (result / "launcher-stderr.log").read_text(encoding="utf-8") == "runtime log\n"


def test_isolated_executor_reports_missing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            2,
            "",
            "child failed before creating artifacts",
        ),
    )

    with pytest.raises(RuntimeError, match="without run.json"):
        run_phase2_isolated(
            tmp_path / "config.json",
            output_root=tmp_path / "runs",
            run_id="missing",
        )
