import json
import shutil
from pathlib import Path

import pytest

from kvopt.profiling.cli import main
from kvopt.profiling.ingestion import load_run_artifacts
from kvopt.profiling.pipeline import (
    build_derived_dataset_bundle,
    discover_run_artifacts,
    write_derived_dataset_bundle,
)

SMOKE_RUN = (
    Path(__file__).parents[1]
    / "docs"
    / "experiments"
    / "phase2-m5-smoke"
    / "synthetic-smoke-v2"
)


def _load_current_schema_smoke_run(tmp_path: Path):
    run_dir = tmp_path / "raw-run"
    shutil.copytree(SMOKE_RUN, run_dir)
    manifest_path = run_dir / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["persisted_forced_release_event_count"] = 1
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return load_run_artifacts(run_dir)


def test_pipeline_builds_and_writes_small_smoke_bundle(tmp_path: Path) -> None:
    raw_manifest_before = (SMOKE_RUN / "run.json").read_text(encoding="utf-8")
    bundle = build_derived_dataset_bundle(
        (_load_current_schema_smoke_run(tmp_path),)
    )

    assert tuple(
        len(getattr(bundle, name))
        for name in (
            "runs",
            "decisions",
            "decision_candidates",
            "logical_releases",
            "physical_evictions",
            "request_outcomes",
            "decision_outcomes",
        )
    ) == (1, 1, 1, 1, 0, 4, 1)
    validity = bundle.run_validity[0]
    assert not validity.valid_for_candidate_analysis
    assert validity.invalid_reasons == ("no_multi_candidate_decision",)

    output_dir = tmp_path / "derived"
    write_derived_dataset_bundle(bundle, output_dir)
    manifest = json.loads(
        (output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "phase2a.derived.v1"
    assert manifest["row_counts"]["request_outcomes"] == 4
    assert len(tuple(output_dir.glob("*.jsonl"))) == 9
    assert (SMOKE_RUN / "run.json").read_text(encoding="utf-8") == raw_manifest_before


def test_pipeline_refuses_to_overwrite_output_directory(tmp_path: Path) -> None:
    bundle = build_derived_dataset_bundle(
        (_load_current_schema_smoke_run(tmp_path),)
    )
    output_dir = tmp_path / "derived"

    write_derived_dataset_bundle(bundle, output_dir)

    with pytest.raises(FileExistsError):
        write_derived_dataset_bundle(bundle, output_dir)


def test_discovery_and_cli_write_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = _load_current_schema_smoke_run(tmp_path)
    output_dir = tmp_path / "derived"

    assert discover_run_artifacts(tmp_path) == (artifacts,)
    assert main(
        [str(tmp_path), "--output", str(output_dir)]
    ) == 0

    assert (output_dir / "decision_candidates.jsonl").is_file()
    assert "wrote 1 run(s)" in capsys.readouterr().out


def test_discovery_fails_when_no_runs_exist(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="no run.json files found",
    ):
        discover_run_artifacts(tmp_path)
