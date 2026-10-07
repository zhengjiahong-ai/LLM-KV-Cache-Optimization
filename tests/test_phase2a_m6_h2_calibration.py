import json
from pathlib import Path

import pytest

from kvopt.profiling.h2_calibration import _dispersion
from kvopt.workload.phase2 import load_phase2_trace
from kvopt.workload.phase2_h2_calibration import (
    materialize_h2_calibration_pilot,
)
from kvopt.workload.phase2_h2_calibration_runner import (
    execute_h2_calibration_pilot,
)

ROOT = Path(__file__).parents[1]
DESIGN = ROOT / "configs" / "phase2" / "h2-measurement-design.json"
BASE_CONFIG = ROOT / "configs" / "phase2" / "metal-observability-config.json"


def test_h2_pilot_materializes_frozen_grid_without_verdict(
    tmp_path: Path,
) -> None:
    manifest_path = materialize_h2_calibration_pilot(
        DESIGN,
        BASE_CONFIG,
        tmp_path / "pilot",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["campaign_kind"] == "calibration_pilot"
    assert not manifest["formal_measurement"]
    assert not manifest["formal_verdict"]
    assert not manifest["b1_authorized"]
    assert manifest["planned_run_count"] == 17 * 7
    assert [point["prefix_tokens"] for point in manifest["points"]][-4:] == [
        24576,
        26624,
        28672,
        30720,
    ]


def test_h2_pilot_configs_fit_each_requested_context(tmp_path: Path) -> None:
    manifest_path = materialize_h2_calibration_pilot(
        DESIGN,
        BASE_CONFIG,
        tmp_path / "pilot",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for point in manifest["points"]:
        config_path = manifest_path.parent / point["config"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        trace = load_phase2_trace(manifest_path.parent / config["trace"])
        capacity = config["cache"]["block_override"] * 16
        assert capacity >= max(528, point["prefix_tokens"] + 1)
        assert not config["backend_options"][
            "capture_terminal_prefix_snapshot"
        ]
        assert len(trace.requests) == 1
        assert not trace.pressure_stages


def test_h2_runner_filters_and_resumes_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = materialize_h2_calibration_pilot(
        DESIGN,
        BASE_CONFIG,
        tmp_path / "pilot",
    )
    output = tmp_path / "runs"

    def fake_run(_config: Path, output_root: Path, run_id: str) -> Path:
        run_dir = output_root / run_id
        run_dir.mkdir(parents=True)
        run_dir.joinpath("run.json").write_text(
            json.dumps({"status": "success", "failure_reason": None}),
            encoding="utf-8",
        )
        return run_dir

    monkeypatch.setattr(
        "kvopt.workload.phase2_h2_calibration_runner._run_isolated",
        fake_run,
    )
    first, _ = execute_h2_calibration_pilot(
        campaign,
        output,
        prefix_tokens=(16,),
        roles=("warmup",),
    )
    second, _ = execute_h2_calibration_pilot(
        campaign,
        output,
        resume=True,
        prefix_tokens=(16,),
        roles=("warmup",),
    )

    assert first["successful_run_count"] == 2
    assert second["skipped_run_count"] == 2


def test_calibration_dispersion_uses_median_center() -> None:
    summary = _dispersion([1.0, 1.1, 1.2, 1.3, 4.0])

    assert summary["median_seconds"] == pytest.approx(1.2)
    assert summary["median_absolute_deviation_seconds"] == pytest.approx(0.1)
    assert summary["maximum_absolute_deviation_seconds"] == pytest.approx(2.8)
