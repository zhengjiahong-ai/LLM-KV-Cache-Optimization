import copy
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

_V5_CAPABILITIES = (
    "runtime_identity",
    "logical_lifecycle",
    "prefix_block_mapping",
    "forced_release_snapshot",
    "native_block_eviction",
    "native_block_content_identity",
    "native_block_logical_owners",
    "native_block_lru_position",
    "generated_token_count",
    "native_apc_hit_miss",
    "recomputed_prefill_tokens",
    "native_first_token_timestamp",
    "native_scheduler_admission_timestamp",
    "hardware_counters",
)


def _mark_manifest_v5_capability_complete(manifest: dict[str, object]) -> None:
    manifest["observation_capability_contract"] = {
        "schema_version": "phase2.observation_capabilities.v1",
        "required": list(_V5_CAPABILITIES),
        "complete": True,
    }
    manifest["observation_availability"] = {
        name: {
            "status": "AVAILABLE"
            if name in {
                "runtime_identity",
                "logical_lifecycle",
                "prefix_block_mapping",
                "forced_release_snapshot",
            }
            else "UNAVAILABLE",
            "reason": None
            if name in {
                "runtime_identity",
                "logical_lifecycle",
                "prefix_block_mapping",
                "forced_release_snapshot",
            }
            else "test fixture capability unavailable",
        }
        for name in _V5_CAPABILITIES
    }


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
    _mark_manifest_v5_capability_complete(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return load_run_artifacts(run_dir)


def _load_mixed_validity_smoke_run(tmp_path: Path):
    artifacts = _load_current_schema_smoke_run(tmp_path)
    events_path = artifacts.run_dir / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    first_decision = events[14]
    second_candidate = copy.deepcopy(first_decision["payload"]["candidates"][0])
    second_candidate.update(
        program_id="agent-b",
        prefix_id="prefix-agent-b",
        block_ids=[20],
        initially_reclaimable_block_ids=[20],
    )
    first_decision["payload"]["candidates"].append(second_candidate)

    untraceable_decision = copy.deepcopy(first_decision)
    untraceable_decision["event_index"] = 20
    untraceable_decision["timestamp"] = 9.0
    events.append(untraceable_decision)
    events_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    manifest_path = artifacts.run_dir / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["event_count"] = 21
    manifest["persisted_forced_release_event_count"] = 2
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return load_run_artifacts(artifacts.run_dir)


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
            "request_runtime_evidence",
            "decision_outcomes",
        )
    ) == (1, 1, 1, 1, 0, 4, 4, 1)
    validity = bundle.run_validity[0]
    assert not validity.valid_for_candidate_analysis
    assert validity.invalid_reasons == ("no_multi_candidate_decision",)
    assert bundle.decision_validity[0].invalid_reasons == (
        "fewer_than_two_candidates",
    )
    assert len(bundle.candidate_loss_evidence) == 4
    assert len(bundle.loss_view_availability) == 4
    assert len(bundle.horizon_sensitivity) == 1
    assert bundle.horizon_sensitivity_summary[0].candidate_count == 1
    assert bundle.decision_regret == ()
    assert len(bundle.candidate_feature_spreads) == 8
    assert bundle.candidate_heterogeneity_summary == ()
    assert bundle.regret_summary == ()
    assert bundle.loss_heterogeneity_summary == ()
    assert bundle.signal_evaluation.status == "INSUFFICIENT_COVERAGE"
    assert bundle.run_prevalence[0].decision_count == 1
    assert bundle.prevalence_summary[0].run_count == 1
    assert bundle.empirical_gap_report.overall_outcome == "INSUFFICIENT-EVENTS"

    output_dir = tmp_path / "derived"
    write_derived_dataset_bundle(bundle, output_dir)
    manifest = json.loads(
        (output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "phase2a.derived.v4"
    assert manifest["analysis_provenance"]["entry_point"] == (
        "kvopt.profiling.cli"
    )
    assert "git_sha" in manifest["analysis_provenance"]
    assert "git_dirty" in manifest["analysis_provenance"]
    assert manifest["row_counts"]["request_outcomes"] == 4
    assert manifest["row_counts"]["request_runtime_evidence"] == 4
    assert manifest["analysis_parameters"]["bootstrap_seed"] == 0
    assert manifest["analysis_parameters"]["canonical_loss_view"] == (
        "planned_return_weighted_prefill_proxy"
    )
    assert not manifest["analysis_parameters"][
        "observed_sensitivity_gate_eligible"
    ]
    pack = json.loads(
        (output_dir / "method_support_pack.json").read_text(encoding="utf-8")
    )
    assert pack["schema_version"] == "phase2a.method-support.v3"
    assert manifest["row_counts"]["signal_feature_coverage"] == 0
    assert len(tuple(output_dir.glob("*.jsonl"))) == 28
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


def test_pipeline_statistics_exclude_invalid_decision_within_valid_run(
    tmp_path: Path,
) -> None:
    bundle = build_derived_dataset_bundle(
        (_load_mixed_validity_smoke_run(tmp_path),)
    )

    assert [
        row.valid_for_candidate_analysis for row in bundle.decision_validity
    ] == [True, False]
    assert bundle.run_validity[0].valid_for_candidate_analysis
    assert all(
        row.decision_count == 1
        for row in bundle.candidate_heterogeneity_summary
    )
    assert all(row.decision_count == 1 for row in bundle.regret_summary)


def test_legacy_pre_v5_manifest_is_diagnostic_but_gate_invalid(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "legacy-run"
    shutil.copytree(SMOKE_RUN, run_dir)
    manifest_path = run_dir / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["persisted_forced_release_event_count"] = 1
    manifest.pop("observation_capability_contract", None)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bundle = build_derived_dataset_bundle(
        (load_run_artifacts(run_dir),),
        formal_campaign=True,
    )

    assert bundle.empirical_gap_report.overall_outcome == "DATA-INVALID"
    integrity = next(
        row
        for row in bundle.empirical_gap_report.checks
        if row.gate == "data_integrity"
    )
    assert integrity.status == "FAIL"
