"""Phase 3 Protocol v4 Option F freeze, planning, and evaluation helpers.

This module is deliberately non-executing.  It converts the already measured
A0 calibration evidence into the G0 freeze candidate, creates deterministic
Noise/Main run plans, and evaluates the pre-registered estimands without
granting execution authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .phase3_materialize import ARMS, arm_binding, materialize_six_arm_cell

CONDITIONS = {
    "C1": {"source_load_level": "L_LOW", "required_blocks": 256, "band": (0.05, 0.15)},
    "C2": {"source_load_level": "L_HIGH", "required_blocks": 1024, "band": (0.25, 0.45)},
}
LOAD_TO_CONDITION = {
    value["source_load_level"]: condition for condition, value in CONDITIONS.items()
}
NOISE_SALT = "phase3-noise-selection-v1"
NOISE_ALLOCATION = {"RESPONSIVE": 2, "WEAK": 2, "FLAT": 1}
NOISE_GROUPS = ("g01", "g04", "g06", "g07", "g10")
NOISE_REPEATS = 3
HEADROOM_RATIO = 0.05
HEADROOM_TOKENS = 512


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _validate_calibration_inventory(
    manifest_path: Path, manifest: Mapping[str, object]
) -> list[dict[str, object]]:
    runs = manifest.get("runs")
    if not isinstance(runs, list) or len(runs) != 40:
        raise ValueError("A0 calibration manifest must bind 40 runs")
    bindings = []
    identities = set()
    for row in runs:
        if not isinstance(row, Mapping):
            raise TypeError("calibration manifest run must be an object")
        group = str(row["group_id"])
        load = str(row["load_level"])
        if load not in LOAD_TO_CONDITION:
            raise ValueError(f"unsupported source load label: {load}")
        identity = (group, load)
        if identity in identities:
            raise ValueError(f"duplicate calibration run: {identity}")
        identities.add(identity)
        config_path = manifest_path.parent / str(row["config"])
        directory = row.get("directory")
        if not isinstance(directory, str):
            raise TypeError("calibration run lacks its frozen directory")
        freeze_path = manifest_path.parent / directory / "freeze-record.json"
        if not config_path.is_file() or _sha256(config_path) != row.get("config_sha256"):
            raise ValueError(f"source config binding failed: {group}/{load}")
        if not freeze_path.is_file() or _sha256(freeze_path) != row.get("freeze_sha256"):
            raise ValueError(f"source freeze binding failed: {group}/{load}")
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if freeze.get("config_sha256") != row.get("config_sha256"):
            raise ValueError(f"freeze/config mismatch: {group}/{load}")
        trace_path = freeze_path.parent / str(freeze["trace"])
        profile_path = freeze_path.parent / str(freeze["profile"])
        if not trace_path.is_file() or _sha256(trace_path) != freeze.get("trace_sha256"):
            raise ValueError(f"trace binding failed: {group}/{load}")
        if not profile_path.is_file() or _sha256(profile_path) != freeze.get("profile_sha256"):
            raise ValueError(f"profile binding failed: {group}/{load}")
        bindings.append(
            {
                "group_id": group,
                "load_level": load,
                "config": str(config_path),
                "config_sha256": _sha256(config_path),
                "freeze": str(freeze_path),
                "freeze_sha256": _sha256(freeze_path),
                "trace_sha256": _sha256(trace_path),
                "profile_sha256": _sha256(profile_path),
            }
        )
    expected = {(f"g{index:02d}", load) for index in range(1, 21) for load in LOAD_TO_CONDITION}
    if identities != expected:
        raise ValueError("A0 calibration inventory does not cover the 20x2 grid")
    return bindings


def _stratum(delta_rho: float) -> str:
    if delta_rho < 0:
        raise ValueError("C2 rho0 must not be below C1 rho0")
    if delta_rho < 0.01:
        return "FLAT"
    if delta_rho < 0.10:
        return "WEAK"
    return "RESPONSIVE"


@dataclass(frozen=True, slots=True)
class CalibrationCell:
    group_id: str
    condition: str
    source_load_level: str
    required_blocks: int
    rho0: float
    r0: int
    w0: int
    in_designed_band: bool
    headroom_eligible: bool
    report_sha256: str | None = None


def classify_calibration_reports(
    reports: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Classify all 40 measured A0 cells for Option F.

    Band attainment is a manipulation check only.  Headroom remains the cell
    eligibility gate used by the registered populations.
    """

    if len(reports) != 40:
        raise ValueError("Option F requires exactly 40 A0 calibration reports")
    cells: dict[tuple[str, str], CalibrationCell] = {}
    for report in reports:
        group_id = report.get("group_id")
        load = report.get("load_level")
        if not isinstance(group_id, str) or not isinstance(load, str):
            raise TypeError("calibration report lacks group/load identity")
        try:
            condition = LOAD_TO_CONDITION[load]
        except KeyError as error:
            raise ValueError(f"unsupported source load label: {load}") from error
        arm = report.get("arm")
        if not isinstance(arm, Mapping) or arm.get("arm") != "A0":
            raise ValueError(f"{group_id}/{load} is not an A0 report")
        rho0 = _number(report.get("observed_recompute_ratio"), "rho0")
        r0 = int(_number(arm.get("aggregate_recomputed_tokens"), "R0"))
        w0 = int(_number(arm.get("aggregate_actual_prefill_tokens"), "W0"))
        if w0 <= 0 or abs(rho0 - r0 / w0) > 1e-12:
            raise ValueError(f"{group_id}/{load} has inconsistent rho0/R0/W0")
        geometry = CONDITIONS[condition]
        lower, upper = geometry["band"]
        cell = CalibrationCell(
            group_id=group_id,
            condition=condition,
            source_load_level=load,
            required_blocks=int(geometry["required_blocks"]),
            rho0=rho0,
            r0=r0,
            w0=w0,
            in_designed_band=float(lower) <= rho0 <= float(upper),
            headroom_eligible=rho0 >= HEADROOM_RATIO and r0 >= HEADROOM_TOKENS,
            report_sha256=(
                None if report.get("report_sha256") is None else str(report["report_sha256"])
            ),
        )
        key = (group_id, condition)
        if key in cells:
            raise ValueError(f"duplicate calibration cell: {key}")
        cells[key] = cell

    expected = {(f"g{index:02d}", condition) for index in range(1, 21) for condition in CONDITIONS}
    if set(cells) != expected:
        raise ValueError("calibration reports do not cover the frozen 20x2 grid")

    groups = []
    strata: dict[str, list[str]] = defaultdict(list)
    for group_id in (f"g{index:02d}" for index in range(1, 21)):
        c1, c2 = cells[(group_id, "C1")], cells[(group_id, "C2")]
        delta = c2.rho0 - c1.rho0
        stratum = _stratum(delta)
        strata[stratum].append(group_id)
        groups.append(
            {
                "group_id": group_id,
                "C1": vars_cell(c1),
                "C2": vars_cell(c2),
                "delta_rho": delta,
                "pressure_response_stratum": stratum,
                "paired_headroom": c1.headroom_eligible and c2.headroom_eligible,
            }
        )

    paired = [row["group_id"] for row in groups if row["paired_headroom"]]
    headroom_cells = [
        f"{group_id}/{condition}"
        for (group_id, condition), cell in cells.items()
        if cell.headroom_eligible
    ]
    if len(paired) != 18 or len(headroom_cells) != 38:
        raise ValueError("measured Headroom population differs from Option F freeze")
    if {name: len(strata[name]) for name in ("FLAT", "WEAK", "RESPONSIVE")} != {
        "FLAT": 3,
        "WEAK": 8,
        "RESPONSIVE": 9,
    }:
        raise ValueError("measured pressure-response strata differ from Option F freeze")

    return {
        "schema_version": "phase3.option_f_calibration_classification.v1",
        "conditions": CONDITIONS,
        "band_attainment_role": "NON_GATING_MANIPULATION_CHECK",
        "headroom_role": "ELIGIBILITY_GATE",
        "groups": groups,
        "strata": {key: sorted(value) for key, value in sorted(strata.items())},
        "paired_primary_groups": paired,
        "headroom_qualified_cells": sorted(headroom_cells),
        "manipulation_check": {
            "cells_in_band": sum(cell.in_designed_band for cell in cells.values()),
            "cells_total": 40,
            "groups_both_in_band": [
                row["group_id"]
                for row in groups
                if row["C1"]["in_designed_band"] and row["C2"]["in_designed_band"]
            ],
        },
    }


def vars_cell(cell: CalibrationCell) -> dict[str, object]:
    return {
        "source_load_level": cell.source_load_level,
        "required_blocks": cell.required_blocks,
        "rho0": cell.rho0,
        "R0": cell.r0,
        "W0": cell.w0,
        "in_designed_band": cell.in_designed_band,
        "headroom_eligible": cell.headroom_eligible,
        "report_sha256": cell.report_sha256,
    }


def select_noise_groups(classification: Mapping[str, object]) -> dict[str, object]:
    """Apply the G0-frozen deterministic stratified selection."""

    paired = set(classification["paired_primary_groups"])
    strata = classification["strata"]
    selected_by: dict[str, list[str]] = {}
    for stratum, count in NOISE_ALLOCATION.items():
        candidates = [group for group in strata[stratum] if group in paired]
        ranked = sorted(
            candidates,
            key=lambda group: hashlib.sha256(f"{NOISE_SALT}:{group}".encode()).hexdigest(),
        )
        selected_by[stratum] = ranked[:count]
    selected = sorted(group for values in selected_by.values() for group in values)
    if tuple(selected) != NOISE_GROUPS:
        raise ValueError(f"noise draw differs from freeze: {selected}")
    runs = [
        {
            "group_id": group,
            "condition": condition,
            "arm": "A0",
            "repeat": repeat,
            "run_id": f"phase3-noise-{group}-{condition.lower()}-a0-r{repeat}",
        }
        for group in selected
        for condition in CONDITIONS
        for repeat in range(1, NOISE_REPEATS + 1)
    ]
    return {
        "schema_version": "phase3.option_f_noise_plan.v1",
        "execution_authorized": False,
        "salt": NOISE_SALT,
        "candidate_groups": sorted(paired),
        "allocation": NOISE_ALLOCATION,
        "selected_by_stratum": selected_by,
        "selected_groups": selected,
        "planned_run_count": 30,
        "runs": runs,
    }


def main_campaign_plan() -> dict[str, object]:
    runs = [
        {
            "group_id": f"g{index:02d}",
            "condition": condition,
            "arm": arm,
            "repeat": 1,
            "run_id": f"phase3-main-g{index:02d}-{condition.lower()}-r1-{arm.lower()}",
        }
        for index in range(1, 21)
        for condition in CONDITIONS
        for arm in ARMS
    ]
    return {
        "schema_version": "phase3.option_f_main_plan.v1",
        "execution_authorized": False,
        "conditions": CONDITIONS,
        "arms": list(ARMS),
        "planned_run_count": 240,
        "runs": runs,
    }


def materialize_option_f_run_inputs(
    *,
    calibration_manifest_path: Path,
    classification_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Create the unauthorized 30-run and 240-run Option F input sets.

    The source of every condition is its measured iteration-1 A0 calibration
    config.  Only run identity, arm binding, and repeat identity differ; the
    request, trace, pressure tokens, clock, pool, model, and profile remain
    inherited from the frozen source cell.
    """

    if output_dir.exists():
        raise FileExistsError(output_dir)
    calibration = json.loads(calibration_manifest_path.read_text(encoding="utf-8"))
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    if calibration.get("schema_version") != "phase3.load_calibration_manifest.v1":
        raise ValueError("unsupported A0 calibration manifest")
    if classification.get("schema_version") != "phase3.option_f_calibration_classification.v1":
        raise ValueError("unsupported Option F classification")
    inventory = _validate_calibration_inventory(calibration_manifest_path, calibration)
    source_runs = calibration["runs"]
    sources: dict[tuple[str, str], tuple[Path, dict[str, object]]] = {}
    for row in source_runs:
        if not isinstance(row, Mapping):
            raise TypeError("calibration manifest run must be an object")
        group = str(row["group_id"])
        load = str(row["load_level"])
        try:
            condition = LOAD_TO_CONDITION[load]
        except KeyError as error:
            raise ValueError(f"unsupported source load label: {load}") from error
        config_path = calibration_manifest_path.parent / str(row["config"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if int(config["pressure"]["required_blocks"]) != int(
            CONDITIONS[condition]["required_blocks"]
        ):
            raise ValueError(f"source pressure differs from {condition} freeze")
        key = (group, condition)
        if key in sources:
            raise ValueError(f"duplicate source cell: {key}")
        sources[key] = (config_path, config)
    if len(sources) != 40:
        raise ValueError("source calibration grid is incomplete")

    output_dir.mkdir(parents=True)
    main_root = output_dir / "main"
    noise_root = output_dir / "noise"
    main_root.mkdir()
    noise_root.mkdir()
    main_cells = []
    for (group, condition), (config_path, config) in sorted(sources.items()):
        base = json.loads(json.dumps(config))
        base["execution_authorized"] = False
        base["phase3_condition"] = condition
        base["phase3_source_load_level"] = CONDITIONS[condition]["source_load_level"]
        base["phase3_option_f"] = True
        trace_path = config_path.parent / str(base["trace"])
        cell_id = f"phase3-main-{group}-{condition.lower()}-r1"
        cell_dir = main_root / f"{group}-{condition.lower()}"
        cell_manifest = materialize_six_arm_cell(
            base_config=base,
            trace_path=trace_path,
            cell_id=cell_id,
            output_dir=cell_dir,
        )
        main_cells.append(
            {
                "group_id": group,
                "condition": condition,
                "directory": str(cell_dir.relative_to(output_dir)),
                "manifest_sha256": _sha256(cell_dir / "manifest.json"),
                "source_config_sha256": _sha256(config_path),
                "shared_input_sha256": cell_manifest["shared_input_sha256"],
            }
        )

    noise_plan = select_noise_groups(classification)
    noise_runs = []
    for planned in noise_plan["runs"]:
        group = str(planned["group_id"])
        condition = str(planned["condition"])
        repeat = int(planned["repeat"])
        config_path, source = sources[(group, condition)]
        config = json.loads(json.dumps(source))
        config["execution_authorized"] = False
        config["run_id"] = str(planned["run_id"])
        config["phase3_condition"] = condition
        config["phase3_source_load_level"] = CONDITIONS[condition]["source_load_level"]
        config["phase3_option_f"] = True
        config["phase3_noise_repeat"] = repeat
        binding = arm_binding("A0")
        config["policy"] = binding.label
        options = config["backend_options"]
        options["phase2g_release_policy"] = binding.release_policy
        options["phase2g_block_policy"] = binding.block_policy
        options["phase3_arm"] = "A0"
        run_dir = noise_root / f"{group}-{condition.lower()}-r{repeat}"
        run_dir.mkdir()
        trace_source = config_path.parent / str(source["trace"])
        trace_target = run_dir / f"{group}-{condition.lower()}.trace.json"
        shutil.copyfile(trace_source, trace_target)
        config["trace"] = trace_target.name
        config_target = run_dir / f"{planned['run_id']}.config.json"
        _write(config_target, config)
        noise_runs.append(
            {
                **planned,
                "config": str(config_target.relative_to(output_dir)),
                "config_sha256": _sha256(config_target),
                "trace_sha256": _sha256(trace_target),
                "source_config_sha256": _sha256(config_path),
            }
        )

    main_manifest = {
        "schema_version": "phase3.option_f_main_input_manifest.v1",
        "execution_authorized": False,
        "planned_run_count": 240,
        "cell_count": 40,
        "arms": list(ARMS),
        "cells": main_cells,
    }
    noise_manifest = {
        "schema_version": "phase3.option_f_noise_input_manifest.v1",
        "execution_authorized": False,
        "planned_run_count": 30,
        "runs": noise_runs,
    }
    _write(output_dir / "main-input-manifest.json", main_manifest)
    _write(output_dir / "noise-input-manifest.json", noise_manifest)
    top = {
        "schema_version": "phase3.option_f_input_bundle.v1",
        "execution_authorized": False,
        "calibration_manifest_sha256": _sha256(calibration_manifest_path),
        "classification_sha256": _sha256(classification_path),
        "source_inventory_sha256": _canonical_sha(inventory),
        "noise_input_manifest_sha256": _sha256(output_dir / "noise-input-manifest.json"),
        "main_input_manifest_sha256": _sha256(output_dir / "main-input-manifest.json"),
        "new_run_budget": 270,
    }
    _write(output_dir / "manifest.json", top)
    return top


def evaluate_noise(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Freeze the single pooled noise estimator after exactly 30 A0 runs."""

    if len(results) != 30:
        raise ValueError("noise evaluation requires exactly 30 runs")
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    strata_by_group: dict[str, str] = {}
    for row in results:
        group = str(row["group_id"])
        condition = str(row["condition"])
        if group not in NOISE_GROUPS or condition not in CONDITIONS or row.get("arm") != "A0":
            raise ValueError("noise result is outside the frozen plan")
        values[(group, condition)].append(
            _number(row.get("aggregate_recomputed_tokens"), "noise tokens")
        )
        if row.get("stratum") is not None:
            strata_by_group[group] = str(row["stratum"])
    if len(values) != 10 or any(len(samples) != 3 for samples in values.values()):
        raise ValueError("noise results must contain three repeats for ten cells")
    sum_squares = sum(
        sum((value - statistics.mean(samples)) ** 2 for value in samples)
        for samples in values.values()
    )
    df = 20
    sigma_run = math.sqrt(sum_squares / df)
    by_stratum: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for (group, _condition), samples in values.items():
        stratum = strata_by_group.get(group)
        if stratum is not None:
            mean = statistics.mean(samples)
            by_stratum[stratum].append(
                (sum((value - mean) ** 2 for value in samples), len(samples) - 1)
            )
    diagnostic = {}
    for stratum, parts in by_stratum.items():
        diagnostic[stratum] = math.sqrt(
            sum(part[0] for part in parts) / sum(part[1] for part in parts)
        )
    return {
        "schema_version": "phase3.option_f_noise_report.v1",
        "status": "PASS",
        "cell_count": 10,
        "run_count": 30,
        "df": df,
        "sigma_run": sigma_run,
        "sigma_delta": math.sqrt(2) * sigma_run,
        "tied_threshold": 2 * math.sqrt(2) * sigma_run,
        "stratum_sigma_run": diagnostic,
        "stratum_status": "DIAGNOSTIC_ONLY",
        "estimator_frozen": True,
    }


def build_g0_freeze_candidate(
    *,
    cohort_seal_path: Path,
    calibration_manifest_path: Path,
    report_paths: Sequence[Path],
    evidence_bindings: Mapping[str, Path],
    output_dir: Path,
) -> dict[str, object]:
    """Bind the seal, existing A0 evidence, and both unauthorized run plans."""

    if output_dir.exists():
        raise FileExistsError(output_dir)
    seal = json.loads(cohort_seal_path.read_text(encoding="utf-8"))
    manifest = json.loads(calibration_manifest_path.read_text(encoding="utf-8"))
    if seal.get("schema_version") != "phase3.cohort_seal.v1":
        raise ValueError("unsupported Cohort Seal")
    groups = seal.get("groups")
    if not isinstance(groups, list) or len(groups) != 20:
        raise ValueError("Option F requires the frozen 20-group Cohort Seal")
    tasks: list[str] = []
    repositories: set[str] = set()
    for group in groups:
        sessions = group.get("sessions")
        if not isinstance(sessions, list) or len(sessions) != 2:
            raise ValueError("each Cohort group must have two sessions")
        ids = [str(session["instance_id"]) for session in sessions]
        repos = [value.split("__", 1)[0] for value in ids]
        if len(set(repos)) != 2:
            raise ValueError("each Cohort group must pair different repositories")
        tasks.extend(ids)
        repositories.update(repos)
    if len(tasks) != 40 or len(set(tasks)) != 40 or len(repositories) < 10:
        raise ValueError("Cohort does not satisfy 40-task/10-repository freeze")
    if manifest.get("schema_version") != "phase3.load_calibration_manifest.v1":
        raise ValueError("unsupported A0 calibration manifest")
    if manifest.get("cohort_seal_sha256") != _sha256(cohort_seal_path):
        raise ValueError("A0 calibration manifest is not bound to this Cohort Seal")
    inventory = _validate_calibration_inventory(calibration_manifest_path, manifest)
    required_evidence = {
        "execution_summary",
        "formal_to_native_run_map",
        "native_evidence_archive",
        "analysis_archive",
    }
    if set(evidence_bindings) != required_evidence:
        raise ValueError(
            "G0 requires exact execution-summary, run-map, native-evidence, and "
            "analysis-archive bindings"
        )
    evidence = {}
    for name, path in sorted(evidence_bindings.items()):
        if not path.is_file():
            raise FileNotFoundError(path)
        evidence[name] = {"path": str(path), "sha256": _sha256(path)}
    execution_summary = json.loads(
        evidence_bindings["execution_summary"].read_text(encoding="utf-8")
    )
    if (
        execution_summary.get("planned_run_count") != 40
        or execution_summary.get("completed_run_count") != 40
        or execution_summary.get("failed_run_count") != 0
    ):
        raise ValueError("A0 execution summary is not a successful 40-run execution")
    run_map = json.loads(evidence_bindings["formal_to_native_run_map"].read_text(encoding="utf-8"))
    if not isinstance(run_map, list) or len(run_map) != 40:
        raise ValueError("formal-to-native run map must contain exactly 40 entries")
    reports = []
    report_bindings = []
    for path in report_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise TypeError("calibration report must be an object")
        copy = dict(document)
        copy["report_sha256"] = _sha256(path)
        reports.append(copy)
        report_bindings.append({"path": str(path), "sha256": _sha256(path)})
    classification = classify_calibration_reports(reports)
    noise = select_noise_groups(classification)
    main = main_campaign_plan()
    output_dir.mkdir(parents=True)
    _write(output_dir / "calibration-classification.json", classification)
    _write(output_dir / "noise-run-plan.json", noise)
    _write(output_dir / "main-run-plan.json", main)
    candidate = {
        "schema_version": "phase3.option_f_g0_freeze_candidate.v1",
        "status": "READY_FOR_M1_G0_REVIEW",
        "execution_authorized": False,
        "protocol": "PHASE3_FINAL_EVALUATION_PROTOCOL_V4_OPTION_F",
        "cohort_seal": {
            "path": str(cohort_seal_path),
            "sha256": _sha256(cohort_seal_path),
            "task_count": 40,
            "group_count": 20,
            "repository_count": len(repositories),
        },
        "a0_calibration_manifest": {
            "path": str(calibration_manifest_path),
            "sha256": _sha256(calibration_manifest_path),
            "run_count": 40,
            "inventory_sha256": _canonical_sha(inventory),
        },
        "a0_reports": report_bindings,
        "a0_execution_evidence": evidence,
        "classification_sha256": _sha256(output_dir / "calibration-classification.json"),
        "noise_plan_sha256": _sha256(output_dir / "noise-run-plan.json"),
        "main_plan_sha256": _sha256(output_dir / "main-run-plan.json"),
        "gates": {
            "G0": "FREEZE_CANDIDATE",
            "G4": "PASS_HEADROOM_38_OF_40",
            "G4_M": "REPORTED_NON_GATING_8_OF_40_IN_BAND",
            "noise": "LOCKED_PENDING_G0_REVIEW",
            "main": "LOCKED_PENDING_NOISE_AND_OTHER_GATES",
        },
        "prohibitions": [
            "NO_C1_C2_LOW_HIGH_RELABEL",
            "NO_CELL_LEVEL_PSEUDOREPLICATION",
            "NO_POST_HOC_SUBGROUP_SELECTION",
            "NO_DELTA_RHO_ARM_INTERACTION_INFERENCE",
        ],
    }
    _write(output_dir / "g0-freeze-candidate.json", candidate)
    candidate["g0_freeze_candidate_sha256"] = _sha256(output_dir / "g0-freeze-candidate.json")
    return candidate


def finalize_g0_freeze_candidate(
    *,
    g0_directory: Path,
    input_directory: Path,
    protocol_path: Path,
    authorization_path: Path,
) -> dict[str, object]:
    """Bind the draft G0 evidence to the materialized unauthorized inputs."""

    candidate_path = g0_directory / "g0-freeze-candidate.json"
    classification_path = g0_directory / "calibration-classification.json"
    noise_plan_path = g0_directory / "noise-run-plan.json"
    main_plan_path = g0_directory / "main-run-plan.json"
    input_manifest_path = input_directory / "manifest.json"
    required = (
        candidate_path,
        classification_path,
        noise_plan_path,
        main_plan_path,
        input_manifest_path,
        protocol_path,
        authorization_path,
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    inputs = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    if candidate.get("status") != "READY_FOR_M1_G0_REVIEW":
        raise ValueError("G0 draft is not review-ready")
    if inputs.get("execution_authorized") is not False:
        raise ValueError("G0 may bind only unauthorized inputs")
    if inputs.get("classification_sha256") != _sha256(classification_path):
        raise ValueError("input/classification binding mismatch")
    freeze = {
        "schema_version": "phase3.option_f_g0_freeze_manifest.v1",
        "status": "READY_FOR_M1_G0_REVIEW",
        "execution_authorized": False,
        "candidate_sha256": _sha256(candidate_path),
        "classification_sha256": _sha256(classification_path),
        "noise_plan_sha256": _sha256(noise_plan_path),
        "main_plan_sha256": _sha256(main_plan_path),
        "input_bundle_sha256": _sha256(input_manifest_path),
        "protocol_v4_sha256": _sha256(protocol_path),
        "m1_authorization_record_sha256": _sha256(authorization_path),
        "new_run_budget": 270,
        "noise_execution_status": "LOCKED_PENDING_M1_G0_REVIEW",
        "main_execution_status": "LOCKED_PENDING_NOISE_AND_GATES",
    }
    path = g0_directory / "g0-freeze-manifest.json"
    if path.exists():
        raise FileExistsError(path)
    _write(path, freeze)
    freeze["sha256"] = _sha256(path)
    return freeze


def evaluate_option_f_results(
    results: Sequence[Mapping[str, object]],
    classification: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate registered Option F estimands from 240 persisted run results."""

    if len(results) != 240:
        raise ValueError("Option F main evaluation requires exactly 240 results")
    values: dict[tuple[str, str, str], float] = {}
    for row in results:
        key = (str(row["group_id"]), str(row["condition"]), str(row["arm"]))
        if key in values or key[1] not in CONDITIONS or key[2] not in ARMS:
            raise ValueError("duplicate or invalid Option F result")
        values[key] = _number(row.get("aggregate_recomputed_tokens"), "result tokens")
    if len(values) != 240:
        raise ValueError("Option F result grid is incomplete")
    paired = list(classification["paired_primary_groups"])
    groups = {row["group_id"]: row for row in classification["groups"]}

    per_condition = {}
    primary = {}
    interactions = {}
    for arm in ARMS:
        if arm == "A0":
            continue
        per_condition[arm] = {}
        for condition in CONDITIONS:
            eligible = [
                group
                for group, metadata in groups.items()
                if metadata[condition]["headroom_eligible"]
            ]
            deltas = [
                values[(group, condition, arm)] - values[(group, condition, "A0")]
                for group in eligible
            ]
            per_condition[arm][condition] = {
                "N_analyzed": len(deltas),
                "mean_delta": statistics.mean(deltas),
            }
        group_deltas = [
            statistics.mean(
                values[(group, condition, arm)] - values[(group, condition, "A0")]
                for condition in CONDITIONS
            )
            for group in paired
        ]
        primary[arm] = {
            "N_analyzed": 18,
            "group_weight": 1 / 18,
            "mean_delta": statistics.mean(group_deltas),
        }
        interaction_a = [
            (values[(group, "C2", arm)] - values[(group, "C2", "A0")])
            - (values[(group, "C1", arm)] - values[(group, "C1", "A0")])
            for group in paired
        ]
        responsive_pairs = [
            group for group in paired if groups[group]["pressure_response_stratum"] == "RESPONSIVE"
        ]
        interaction_b = [
            (values[(group, "C2", arm)] - values[(group, "C2", "A0")])
            - (values[(group, "C1", arm)] - values[(group, "C1", "A0")])
            for group in responsive_pairs
        ]
        interactions[arm] = {
            "Interaction_A": {
                "N_analyzed": 18,
                "mean": statistics.mean(interaction_a),
                "verdict_allowed": True,
            },
            "Interaction_B": {
                "N_analyzed": 7,
                "mean": statistics.mean(interaction_b),
                "verdict_allowed": False,
                "status": "DIAGNOSTIC_ONLY_BELOW_MINIMUM_8",
            },
        }

    def h3(population: Sequence[str]) -> dict[str, object]:
        group_values = []
        cell_count = 0
        for group in population:
            eligible = [
                condition
                for condition in CONDITIONS
                if groups[group][condition]["headroom_eligible"]
            ]
            cell_count += len(eligible)
            group_values.append(
                statistics.mean(
                    values[(group, condition, "A0")] - values[(group, condition, "N0")]
                    for condition in eligible
                )
            )
        return {
            "group_count": len(population),
            "cell_count": cell_count,
            "mean_A0_minus_N0": statistics.mean(group_values),
        }

    responsive = [
        group for group in groups if groups[group]["pressure_response_stratum"] == "RESPONSIVE"
    ]
    return {
        "schema_version": "phase3.option_f_results.v1",
        "status": "PASS",
        "primary": primary,
        "per_condition_descriptive": per_condition,
        "H3_0": h3(list(groups)),
        "H3_R": h3(responsive),
        "interactions": interactions,
        "statistical_unit": "GROUP",
        "S10": "ENFORCED",
    }
