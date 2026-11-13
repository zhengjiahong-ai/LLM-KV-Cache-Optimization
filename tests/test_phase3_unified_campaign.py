from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kvopt.workload.phase3_materialize import ARMS
from kvopt.workload.phase3_option_f import (
    classify_calibration_reports,
    main_campaign_plan,
    select_noise_groups,
)
from kvopt.workload.phase3_unified_campaign import (
    RunSpec,
    UnifiedCampaignController,
    ValidatedCampaign,
    _validate_cohort_binding,
)

RESPONSIVE = {"g03", "g04", "g05", "g09", "g10", "g12", "g16", "g18", "g19"}
WEAK = {"g02", "g06", "g07", "g08", "g11", "g13", "g15", "g17"}


def _classification() -> dict[str, object]:
    reports = []
    for index in range(1, 21):
        group = f"g{index:02d}"
        if group in RESPONSIVE:
            c1, c2 = 0.20, 0.35
        elif group in WEAK:
            c1, c2 = 0.20, 0.25
        else:
            c1, c2 = 0.20, 0.205
        if group == "g09":
            c1, c2 = 0.04, 0.30
        if group == "g18":
            c1, c2 = 0.0, 0.30
        for load, rho in (("L_LOW", c1), ("L_HIGH", c2)):
            reports.append(
                {
                    "group_id": group,
                    "load_level": load,
                    "observed_recompute_ratio": rho,
                    "arm": {
                        "arm": "A0",
                        "aggregate_recomputed_tokens": int(rho * 10_000),
                        "aggregate_actual_prefill_tokens": 10_000,
                    },
                }
            )
    return classify_calibration_reports(reports)


def _campaign(tmp_path: Path) -> ValidatedCampaign:
    classification = _classification()
    noise_plan = select_noise_groups(classification)
    noise = tuple(
        RunSpec(
            stage="NOISE",
            run_id=str(row["run_id"]),
            group_id=str(row["group_id"]),
            condition=str(row["condition"]),
            arm="A0",
            repeat=int(row["repeat"]),
            stratum=str(row["stratum"]),
            config_path=tmp_path / f"{row['run_id']}.json",
            config_sha256="0" * 64,
        )
        for row in noise_plan["runs"]
    )
    main_plan = main_campaign_plan()
    main = tuple(
        RunSpec(
            stage="MAIN",
            run_id=str(row["run_id"]),
            group_id=str(row["group_id"]),
            condition=str(row["condition"]),
            arm=str(row["arm"]),
            repeat=1,
            config_path=tmp_path / f"{row['run_id']}.json",
            config_sha256="0" * 64,
        )
        for row in main_plan["runs"]
    )
    return ValidatedCampaign(
        git_sha="git-sha",
        g0={},
        classification=classification,
        noise_plan=noise_plan,
        main_plan=main_plan,
        cohort={},
        authorization={},
        noise_runs=noise,
        main_runs=main,
    )


def _executor(spec: RunSpec, root: Path, _timeout: int) -> Path:
    result = root / spec.run_id
    result.mkdir()
    return result


def _evaluator(
    spec: RunSpec, run_directory: Path, _cohort: object
) -> dict[str, object]:
    return {
        "run_id": spec.run_id,
        "group_id": spec.group_id,
        "condition": spec.condition,
        "arm": spec.arm,
        "repeat": spec.repeat,
        "stratum": spec.stratum,
        "aggregate_recomputed_tokens": 1000 + spec.repeat,
        "native_run_directory": str(run_directory),
    }


def test_unified_pipeline_transitions_only_after_noise_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = UnifiedCampaignController(
        campaign=_campaign(tmp_path),
        output_root=tmp_path / "output",
        executor=_executor,
        run_evaluator=_evaluator,
    )
    monkeypatch.setattr(controller, "_evaluate_main_cells", lambda: [{}] * 40)
    result = controller.run()

    assert result["status"] == "COMPLETE"
    assert len(result["completed_noise_run_ids"]) == 30
    assert len(result["completed_main_run_ids"]) == 240
    transition = (tmp_path / "output/stage-transition.json").read_text()
    assert "MAIN_AUTHORIZED_BY_PIPELINE" in transition
    assert (tmp_path / "output/noise-report.json").is_file()
    assert (tmp_path / "output/main-report.json").is_file()


def test_noise_failure_never_starts_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executed: list[str] = []

    def executor(spec: RunSpec, root: Path, timeout: int) -> Path:
        executed.append(spec.stage)
        return _executor(spec, root, timeout)

    controller = UnifiedCampaignController(
        campaign=_campaign(tmp_path),
        output_root=tmp_path / "output",
        executor=executor,
        run_evaluator=_evaluator,
    )
    monkeypatch.setattr(
        "kvopt.workload.phase3_unified_campaign.evaluate_noise",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid pooled estimator")),
    )
    with pytest.raises(ValueError, match="invalid pooled estimator"):
        controller.run()

    assert executed == ["NOISE"] * 30
    state = (tmp_path / "output/pipeline-state.json").read_text()
    assert "FAIL_CLOSED" in state
    assert "LOCKED_PENDING_AUTOMATED_NOISE_GATE" in state
    assert not (tmp_path / "output/stage-transition.json").exists()


def test_resume_does_not_repeat_committed_noise_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign = _campaign(tmp_path)
    calls: list[str] = []

    def first_executor(spec: RunSpec, root: Path, timeout: int) -> Path:
        calls.append(spec.run_id)
        if len(calls) == 3:
            raise RuntimeError("interrupted")
        return _executor(spec, root, timeout)

    first = UnifiedCampaignController(
        campaign=campaign,
        output_root=tmp_path / "output",
        executor=first_executor,
        run_evaluator=_evaluator,
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        first.run()
    assert len(calls) == 3

    second_calls: list[str] = []

    def second_executor(spec: RunSpec, root: Path, timeout: int) -> Path:
        second_calls.append(spec.run_id)
        return _executor(spec, root, timeout)

    second = UnifiedCampaignController(
        campaign=campaign,
        output_root=tmp_path / "output",
        executor=second_executor,
        run_evaluator=_evaluator,
    )
    monkeypatch.setattr(second, "_evaluate_main_cells", lambda: [{}] * 40)
    result = second.run()
    assert result["status"] == "COMPLETE"
    assert not set(calls[:2]) & set(second_calls)
    assert len(second_calls) == 28 + 240


def test_main_inventory_is_exact_twenty_by_two_by_six(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path)
    assert len(campaign.main_runs) == 240
    assert {
        (spec.group_id, spec.condition, spec.arm) for spec in campaign.main_runs
    } == {
        (f"g{index:02d}", condition, arm)
        for index in range(1, 21)
        for condition in ("C1", "C2")
        for arm in ARMS
    }


def test_cohort_seal_must_match_g0_candidate_hash(tmp_path: Path) -> None:
    seal = tmp_path / "cohort-seal.json"
    seal.write_text('{"schema_version":"phase3.cohort_seal.v1"}\n')
    expected = hashlib.sha256(seal.read_bytes()).hexdigest()
    assert _validate_cohort_binding(
        {"cohort_seal": {"sha256": expected}}, seal
    ) == expected

    seal.write_text('{"schema_version":"phase3.cohort_seal.v1","changed":true}\n')
    with pytest.raises(ValueError, match="differs from G0 freeze"):
        _validate_cohort_binding({"cohort_seal": {"sha256": expected}}, seal)


def test_cohort_seal_binding_cannot_be_omitted(tmp_path: Path) -> None:
    seal = tmp_path / "cohort-seal.json"
    seal.write_text("{}\n")
    with pytest.raises(TypeError, match="lacks Cohort Seal binding"):
        _validate_cohort_binding({}, seal)
