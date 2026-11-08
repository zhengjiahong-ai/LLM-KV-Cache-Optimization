from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from kvopt.workload.phase3_option_f import (
    NOISE_GROUPS,
    build_g0_freeze_candidate,
    classify_calibration_reports,
    evaluate_noise,
    evaluate_option_f_results,
    finalize_g0_freeze_candidate,
    main_campaign_plan,
    materialize_option_f_run_inputs,
    select_noise_groups,
)

RESPONSIVE = {"g03", "g04", "g05", "g09", "g10", "g12", "g16", "g18", "g19"}
WEAK = {"g02", "g06", "g07", "g08", "g11", "g13", "g15", "g17"}
FLAT = {"g01", "g14", "g20"}


def _reports() -> list[dict[str, object]]:
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
            band = (0.05, 0.15) if load == "L_LOW" else (0.25, 0.45)
            reports.append(
                {
                    "schema_version": "phase3.load_calibration_run_report.v1",
                    "status": (
                        "PASS" if band[0] <= rho <= band[1] else "TARGET_MISSED_FAIL_CLOSED"
                    ),
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
    return reports


def _calibration_manifest(tmp_path: Path, cohort_sha: str | None = None) -> Path:
    calibration_root = tmp_path / "calibration"
    calibration_root.mkdir()
    runs = []
    for index in range(1, 21):
        group = f"g{index:02d}"
        for load, blocks in (("L_LOW", 256), ("L_HIGH", 1024)):
            cell = calibration_root / f"{group}-{load.lower()}"
            cell.mkdir()
            trace = cell / "trace.json"
            trace.write_text("{}", encoding="utf-8")
            profile = cell / "profile.json"
            profile.write_text("{}", encoding="utf-8")
            stage = f"pressure-{group}-{load.lower()}"
            config = {
                "schema_version": "phase2.config.v1",
                "execution_authorized": True,
                "trace": trace.name,
                "pressure": {"required_blocks": blocks},
                "backend_options": {
                    "controlled_pressure_stages_by_boundary": {
                        f"pressure:{group}:{load}": {
                            "stage_id": stage,
                            "max_requests": 1,
                            "stop_on_forced_release": False,
                        }
                    }
                },
            }
            config_path = cell / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
            freeze = cell / "freeze-record.json"
            freeze.write_text(
                json.dumps(
                    {
                        "config_sha256": config_sha,
                        "trace": trace.name,
                        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                        "profile": profile.name,
                        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            runs.append(
                {
                    "group_id": group,
                    "load_level": load,
                    "run_id": f"phase3-load-calibration-{group}-{load.lower().replace('_', '-')}-a0",
                    "directory": cell.name,
                    "config": str(config_path.relative_to(calibration_root)),
                    "config_sha256": config_sha,
                    "freeze_sha256": hashlib.sha256(freeze.read_bytes()).hexdigest(),
                }
            )
    manifest = calibration_root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "phase3.load_calibration_manifest.v1",
                "cohort_seal_sha256": cohort_sha,
                "runs": runs,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _execution_evidence(tmp_path: Path) -> dict[str, Path]:
    summary = tmp_path / "execution-summary.json"
    summary.write_text(
        json.dumps(
            {
                "planned_run_count": 40,
                "completed_run_count": 40,
                "failed_run_count": 0,
            }
        ),
        encoding="utf-8",
    )
    calibration = json.loads((tmp_path / "calibration/manifest.json").read_text())
    mappings = []
    for index, row in enumerate(calibration["runs"]):
        native_id = f"phase2-{index:012x}"
        directory = tmp_path / "native" / native_id
        directory.mkdir(parents=True)
        run_json = directory / "run.json"
        run_json.write_text(
            json.dumps(
                {
                    "schema_version": "phase2.run.v1",
                    "run_id": native_id,
                    "status": "success",
                }
            ),
            encoding="utf-8",
        )
        events = directory / "events.jsonl"
        events.write_text("{}\n", encoding="utf-8")
        mappings.append(
            {
                "group_id": row["group_id"],
                "load_level": row["load_level"],
                "run_id": row["run_id"],
                "native_run_directory": str(directory),
                "run_json_path": str(run_json),
                "events_path": str(events),
            }
        )
    run_map = tmp_path / "formal-to-native-run-map.json"
    run_map.write_text(json.dumps(mappings), encoding="utf-8")
    native = tmp_path / "native-evidence.tar.gz"
    native.write_bytes(b"native evidence")
    analysis = tmp_path / "analysis-evidence.tar.gz"
    analysis.write_bytes(b"analysis evidence")
    return {
        "execution_summary": summary,
        "formal_to_native_run_map": run_map,
        "native_evidence_archive": native,
        "analysis_archive": analysis,
    }


def test_classification_freezes_option_f_populations() -> None:
    result = classify_calibration_reports(_reports())

    assert result["manipulation_check"]["cells_total"] == 40
    assert len(result["paired_primary_groups"]) == 18
    assert set(result["paired_primary_groups"]) == {f"g{index:02d}" for index in range(1, 21)} - {
        "g09",
        "g18",
    }
    assert len(result["headroom_qualified_cells"]) == 38
    assert set(result["strata"]["RESPONSIVE"]) == RESPONSIVE
    assert set(result["strata"]["WEAK"]) == WEAK
    assert set(result["strata"]["FLAT"]) == FLAT


def test_band_attainment_never_excludes_a_headroom_cell() -> None:
    reports = _reports()
    for report in reports:
        report["observed_recompute_ratio"] = 0.50
        report["arm"]["aggregate_recomputed_tokens"] = 5_000
    # Restore distinct, valid strata while keeping every value out of band.
    for report in reports:
        group = str(report["group_id"])
        base = 0.50
        if group == "g09":
            base = 0.04
        elif group == "g18":
            base = 0.0
        if report["load_level"] == "L_LOW":
            rho = base
        else:
            delta = 0.15 if group in RESPONSIVE else (0.05 if group in WEAK else 0.005)
            rho = base + delta
        report["observed_recompute_ratio"] = rho
        report["arm"]["aggregate_recomputed_tokens"] = int(rho * 10_000)
    result = classify_calibration_reports(reports)
    assert result["manipulation_check"]["cells_in_band"] == 0
    assert len(result["headroom_qualified_cells"]) == 38


def test_negative_delta_rho_is_flat() -> None:
    reports = _reports()
    for report in reports:
        if report["group_id"] == "g01" and report["load_level"] == "L_HIGH":
            report["observed_recompute_ratio"] = 0.19
            report["arm"]["aggregate_recomputed_tokens"] = 1_900
            report["status"] = "TARGET_MISSED_FAIL_CLOSED"
    result = classify_calibration_reports(reports)
    g01 = next(row for row in result["groups"] if row["group_id"] == "g01")
    assert g01["delta_rho"] == pytest.approx(-0.01)
    assert g01["pressure_response_stratum"] == "FLAT"


def test_noise_selection_is_frozen_and_has_exactly_thirty_runs() -> None:
    result = select_noise_groups(classify_calibration_reports(_reports()))
    assert tuple(result["selected_groups"]) == NOISE_GROUPS
    assert result["selected_by_stratum"] == {
        "RESPONSIVE": ["g04", "g10"],
        "WEAK": ["g07", "g06"],
        "FLAT": ["g01"],
    }
    assert result["planned_run_count"] == len(result["runs"]) == 30
    assert {row["arm"] for row in result["runs"]} == {"A0"}


def test_main_plan_is_full_20_by_2_by_6_grid() -> None:
    result = main_campaign_plan()
    assert result["execution_authorized"] is False
    assert result["planned_run_count"] == len(result["runs"]) == 240
    assert len({row["run_id"] for row in result["runs"]}) == 240


def test_materializes_unauthorized_noise_and_main_inputs(tmp_path: Path) -> None:
    manifest = _calibration_manifest(tmp_path)
    classification = tmp_path / "classification.json"
    classification.write_text(
        json.dumps(classify_calibration_reports(_reports())), encoding="utf-8"
    )

    result = materialize_option_f_run_inputs(
        calibration_manifest_path=manifest,
        classification_path=classification,
        output_dir=tmp_path / "inputs",
    )

    assert result["execution_authorized"] is False
    assert result["new_run_budget"] == 270
    main = json.loads((tmp_path / "inputs/main-input-manifest.json").read_text())
    noise = json.loads((tmp_path / "inputs/noise-input-manifest.json").read_text())
    assert main["planned_run_count"] == 240
    assert len(main["cells"]) == 40
    assert noise["planned_run_count"] == len(noise["runs"]) == 30
    assert all(
        not json.loads((tmp_path / "inputs" / row["config"]).read_text())["execution_authorized"]
        for row in noise["runs"]
    )


def test_final_g0_manifest_binds_protocol_and_unauthorized_inputs(
    tmp_path: Path,
) -> None:
    g0 = tmp_path / "g0"
    inputs = tmp_path / "inputs"
    g0.mkdir()
    inputs.mkdir()
    classification = {"schema_version": "phase3.option_f_calibration_classification.v1"}
    (g0 / "calibration-classification.json").write_text(
        json.dumps(classification), encoding="utf-8"
    )
    for name in ("noise-run-plan.json", "main-run-plan.json"):
        (g0 / name).write_text("{}", encoding="utf-8")
    (g0 / "g0-freeze-candidate.json").write_text(
        json.dumps(
            {
                "status": "READY_FOR_M1_G0_REVIEW",
                "execution_authorized": False,
            }
        ),
        encoding="utf-8",
    )
    classification_sha = hashlib.sha256(
        (g0 / "calibration-classification.json").read_bytes()
    ).hexdigest()
    (inputs / "manifest.json").write_text(
        json.dumps(
            {
                "execution_authorized": False,
                "classification_sha256": classification_sha,
            }
        ),
        encoding="utf-8",
    )
    protocol = tmp_path / "protocol.md"
    protocol.write_text("v4", encoding="utf-8")
    authorization = tmp_path / "authorization.md"
    authorization.write_text("M1", encoding="utf-8")

    result = finalize_g0_freeze_candidate(
        g0_directory=g0,
        input_directory=inputs,
        protocol_path=protocol,
        authorization_path=authorization,
    )

    assert result["execution_authorized"] is False
    assert result["status"] == "READY_FOR_M1_G0_REVIEW"
    assert result["new_run_budget"] == 270
    assert (g0 / "g0-freeze-manifest.json").is_file()


def test_noise_estimator_uses_frozen_df_and_formula() -> None:
    plan = select_noise_groups(classify_calibration_reports(_reports()))
    rows = [
        {**run, "aggregate_recomputed_tokens": (99, 100, 101)[run["repeat"] - 1]}
        for run in plan["runs"]
    ]
    result = evaluate_noise(rows, plan)
    assert result["df"] == 20
    assert result["sigma_run"] == 1.0
    assert result["sigma_delta"] == pytest.approx(math.sqrt(2))
    assert result["tied_threshold"] == pytest.approx(2 * math.sqrt(2))
    assert result["stratum_status"] == "DIAGNOSTIC_ONLY"
    assert set(result["stratum_sigma_run"]) == {"FLAT", "WEAK", "RESPONSIVE"}
    assert result["stratum_sigma_max_min_ratio"] == pytest.approx(1.0)
    assert result["stratum_sigma_max_min_ratio_status"] == "DEFINED"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows[0].update(repeat=2), "identity differs"),
        (lambda rows: rows[0].update(run_id=rows[1]["run_id"]), "identity differs|unique"),
        (lambda rows: rows[0].pop("stratum"), "identity differs"),
    ],
)
def test_noise_evaluator_rejects_repeat_run_id_and_stratum_drift(mutation, message: str) -> None:
    plan = select_noise_groups(classify_calibration_reports(_reports()))
    rows = [{**run, "aggregate_recomputed_tokens": 100} for run in plan["runs"]]
    mutation(rows)
    with pytest.raises(ValueError, match=message):
        evaluate_noise(rows, plan)


def test_noise_evaluator_reports_zero_sigma_ratio_status() -> None:
    plan = select_noise_groups(classify_calibration_reports(_reports()))
    rows = [{**run, "aggregate_recomputed_tokens": 100} for run in plan["runs"]]
    result = evaluate_noise(rows, plan)
    assert result["stratum_sigma_max_min_ratio"] is None
    assert result["stratum_sigma_max_min_ratio_status"] == ("UNDEFINED_ALL_STRATUM_SIGMAS_ZERO")


def test_noise_evaluator_reports_zero_minimum_stratum_sigma() -> None:
    plan = select_noise_groups(classify_calibration_reports(_reports()))
    rows = []
    for run in plan["runs"]:
        value = 100 if run["stratum"] == "FLAT" else 100 + run["repeat"]
        rows.append({**run, "aggregate_recomputed_tokens": value})
    result = evaluate_noise(rows, plan)
    assert result["stratum_sigma_max_min_ratio"] is None
    assert result["stratum_sigma_max_min_ratio_status"] == (
        "UNDEFINED_ZERO_MINIMUM_STRATUM_SIGMA"
    )


def test_noise_evaluator_requires_frozen_strata_and_repeats() -> None:
    plan = select_noise_groups(classify_calibration_reports(_reports()))
    rows = [{**run, "aggregate_recomputed_tokens": 100} for run in plan["runs"]]

    missing_strata = dict(plan)
    missing_strata.pop("strata_by_group")
    with pytest.raises(ValueError, match="lacks the selected-group strata"):
        evaluate_noise(rows, missing_strata)

    invalid_repeats = {**plan, "runs": [dict(run) for run in plan["runs"]]}
    invalid_repeats["runs"][0]["repeat"] = 2
    with pytest.raises(ValueError, match="repeats|run IDs"):
        evaluate_noise(rows, invalid_repeats)


def test_option_f_statistics_keep_groups_as_units() -> None:
    classification = classify_calibration_reports(_reports())
    rows = []
    arm_offset = {"N0": -10, "A0": 0, "A1": 1, "A2": 2, "A3": 3, "E0": 4}
    for index in range(1, 21):
        group = f"g{index:02d}"
        for condition in ("C1", "C2"):
            for arm, offset in arm_offset.items():
                rows.append(
                    {
                        "group_id": group,
                        "condition": condition,
                        "arm": arm,
                        "aggregate_recomputed_tokens": 1_000 + offset,
                    }
                )
    result = evaluate_option_f_results(rows, classification)
    assert result["primary"]["A3"] == {
        "N_analyzed": 18,
        "group_weight": 1 / 18,
        "mean_delta": 3,
    }
    assert result["per_condition_descriptive"]["A3"]["C1"]["N_analyzed"] == 18
    assert result["per_condition_descriptive"]["A3"]["C2"]["N_analyzed"] == 20
    assert result["H3_0"]["group_count"] == 20
    assert result["H3_0"]["cell_count"] == 38
    assert result["H3_R"]["group_count"] == 9
    assert result["H3_R"]["cell_count"] == 16
    assert result["interactions"]["A3"]["Interaction_B"]["verdict_allowed"] is False
    assert result["stratified_effects"]["A3"]["FLAT"]["N_analyzed"] == 3
    assert result["stratified_effects"]["A3"]["WEAK"]["N_analyzed"] == 8
    assert result["stratified_effects"]["A3"]["RESPONSIVE"]["N_analyzed"] == 7
    assert result["stratified_effects"]["A3"]["FLAT"]["cell_count"] == 6
    assert result["stratified_effects"]["A3"]["WEAK"]["cell_count"] == 16
    assert result["stratified_effects"]["A3"]["RESPONSIVE"]["cell_count"] == 14
    assert result["interactions"]["A3"]["Interaction_B"]["N_analyzed"] == 7
    assert all(
        row["within_group_conditions_averaged_first"]
        for row in result["stratified_effects"]["A3"].values()
    )


def test_main_evaluator_rejects_group_substitution_and_duplicate_cells() -> None:
    classification = classify_calibration_reports(_reports())
    rows = [
        {
            "group_id": f"g{index:02d}",
            "condition": condition,
            "arm": arm,
            "aggregate_recomputed_tokens": 1_000,
        }
        for index in range(1, 21)
        for condition in ("C1", "C2")
        for arm in ("N0", "A0", "A1", "A2", "A3", "E0")
    ]
    rows[0]["group_id"] = "g21"
    with pytest.raises(ValueError, match="duplicate or invalid"):
        evaluate_option_f_results(rows, classification)


def test_main_evaluator_rejects_tampered_paired_population() -> None:
    classification = classify_calibration_reports(_reports())
    rows = [
        {
            "group_id": f"g{index:02d}",
            "condition": condition,
            "arm": arm,
            "aggregate_recomputed_tokens": 1_000,
        }
        for index in range(1, 21)
        for condition in ("C1", "C2")
        for arm in ("N0", "A0", "A1", "A2", "A3", "E0")
    ]
    paired = list(classification["paired_primary_groups"])
    assert "g09" not in paired
    classification["paired_primary_groups"] = [*paired[1:], "g09"]

    with pytest.raises(ValueError, match="paired primary population"):
        evaluate_option_f_results(rows, classification)
    rows[0]["group_id"] = "g01"
    rows[1] = dict(rows[0])
    with pytest.raises(ValueError, match="duplicate or invalid"):
        evaluate_option_f_results(rows, classification)


def _g0_inputs(tmp_path: Path) -> tuple[Path, Path, list[Path], dict[str, Path]]:
    groups = []
    repos = [f"repo{index:02d}" for index in range(1, 21)]
    for index in range(1, 21):
        groups.append(
            {
                "group_id": f"g{index:02d}",
                "sessions": [
                    {"instance_id": f"{repos[index - 1]}__task-a"},
                    {"instance_id": f"{repos[index % 20]}__task-b"},
                ],
            }
        )
    seal = tmp_path / "seal.json"
    seal.write_text(
        json.dumps({"schema_version": "phase3.cohort_seal.v1", "groups": groups}),
        encoding="utf-8",
    )
    seal_sha = hashlib.sha256(seal.read_bytes()).hexdigest()
    manifest = _calibration_manifest(tmp_path, seal_sha)
    paths = []
    for index, report in enumerate(_reports()):
        path = tmp_path / f"report-{index:02d}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        paths.append(path)
    return seal, manifest, paths, _execution_evidence(tmp_path)


def test_g0_candidate_binds_seal_manifest_and_reports(tmp_path: Path) -> None:
    seal, manifest, paths, evidence = _g0_inputs(tmp_path)

    result = build_g0_freeze_candidate(
        cohort_seal_path=seal,
        calibration_manifest_path=manifest,
        report_paths=paths,
        evidence_bindings=evidence,
        output_dir=tmp_path / "g0",
    )
    assert result["status"] == "READY_FOR_M1_G0_REVIEW"
    assert result["execution_authorized"] is False
    assert result["gates"]["G4"] == "PASS_HEADROOM_38_OF_40"
    assert json.loads((tmp_path / "g0/noise-run-plan.json").read_text())["planned_run_count"] == 30


@pytest.mark.parametrize("corruption", ["duplicate", "substitute"])
def test_g0_rejects_cohort_group_ids_that_differ_from_manifest(
    tmp_path: Path, corruption: str
) -> None:
    seal, manifest, paths, evidence = _g0_inputs(tmp_path)
    seal_document = json.loads(seal.read_text())
    seal_document["groups"][1]["group_id"] = (
        seal_document["groups"][0]["group_id"] if corruption == "duplicate" else "g99"
    )
    seal.write_text(json.dumps(seal_document), encoding="utf-8")
    manifest_document = json.loads(manifest.read_text())
    manifest_document["cohort_seal_sha256"] = hashlib.sha256(seal.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(manifest_document), encoding="utf-8")

    with pytest.raises(ValueError, match="group IDs"):
        build_g0_freeze_candidate(
            cohort_seal_path=seal,
            calibration_manifest_path=manifest,
            report_paths=paths,
            evidence_bindings=evidence,
            output_dir=tmp_path / "g0",
        )


@pytest.mark.parametrize("corruption", ["duplicate_formal", "duplicate_native"])
def test_g0_rejects_non_bijective_formal_native_mapping(tmp_path: Path, corruption: str) -> None:
    seal, manifest, paths, evidence = _g0_inputs(tmp_path)
    mapping_path = evidence["formal_to_native_run_map"]
    mappings = json.loads(mapping_path.read_text())
    if corruption == "duplicate_formal":
        mappings[1]["run_id"] = mappings[0]["run_id"]
    else:
        for key in ("native_run_directory", "run_json_path", "events_path"):
            mappings[1][key] = mappings[0][key]
    mapping_path.write_text(json.dumps(mappings), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate|differs"):
        build_g0_freeze_candidate(
            cohort_seal_path=seal,
            calibration_manifest_path=manifest,
            report_paths=paths,
            evidence_bindings=evidence,
            output_dir=tmp_path / "g0",
        )


@pytest.mark.parametrize("corruption", ["schema", "status", "identity"])
def test_g0_rejects_invalid_calibration_report_contract(tmp_path: Path, corruption: str) -> None:
    seal, manifest, paths, evidence = _g0_inputs(tmp_path)
    report = json.loads(paths[0].read_text())
    if corruption == "schema":
        report["schema_version"] = "unknown"
    elif corruption == "status":
        report["status"] = "PASS"
    else:
        report["group_id"] = "g99"
    paths[0].write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="schema|status|duplicated|outside"):
        build_g0_freeze_candidate(
            cohort_seal_path=seal,
            calibration_manifest_path=manifest,
            report_paths=paths,
            evidence_bindings=evidence,
            output_dir=tmp_path / "g0",
        )


def test_g0_fails_on_wrong_cohort_binding(tmp_path: Path) -> None:
    seal = tmp_path / "seal.json"
    seal.write_text(json.dumps({"schema_version": "phase3.cohort_seal.v1", "groups": []}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "phase3.load_calibration_manifest.v1",
                "cohort_seal_sha256": "0" * 64,
                "runs": [],
            }
        )
    )
    with pytest.raises(ValueError, match="20-group"):
        build_g0_freeze_candidate(
            cohort_seal_path=seal,
            calibration_manifest_path=manifest,
            report_paths=[],
            evidence_bindings={},
            output_dir=tmp_path / "g0",
        )
