"""Read-only final gate audit for the completed Phase 3 Option F campaign."""

from __future__ import annotations

import copy
import hashlib
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from kvopt.workload.phase3_materialize import ARMS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _member(tar: tarfile.TarFile, suffix: str) -> tarfile.TarInfo:
    matches = [row for row in tar.getmembers() if row.isfile() and row.name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"archive member is not unique: {suffix}")
    return matches[0]


def _bytes(tar: tarfile.TarFile, suffix: str) -> bytes:
    handle = tar.extractfile(_member(tar, suffix))
    if handle is None:
        raise ValueError(f"archive member cannot be read: {suffix}")
    return handle.read()


def _json(tar: tarfile.TarFile, suffix: str) -> dict[str, object]:
    value = json.loads(_bytes(tar, suffix))
    if not isinstance(value, dict):
        raise TypeError(f"archive member must contain an object: {suffix}")
    return value


def _jsonl(tar: tarfile.TarFile, suffix: str) -> list[dict[str, object]]:
    rows = []
    for line in _bytes(tar, suffix).splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"archive event must contain an object: {suffix}")
        rows.append(value)
    return rows


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _normalized_config(config: Mapping[str, object]) -> dict[str, object]:
    result = copy.deepcopy(dict(config))
    result.pop("run_id", None)
    result.pop("policy", None)
    options = result.get("backend_options")
    if not isinstance(options, dict):
        raise TypeError("Native config lacks backend_options")
    for field in ("phase2g_block_policy", "phase2g_release_policy", "phase3_arm"):
        options.pop(field, None)
    return result


def _cohort_groups(cohort: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    groups = cohort.get("groups")
    if not isinstance(groups, list) or len(groups) != 20:
        raise ValueError("Cohort Seal must contain exactly 20 groups")
    result = {}
    for row in groups:
        if not isinstance(row, Mapping) or not isinstance(row.get("group_id"), str):
            raise TypeError("Cohort group identity is invalid")
        group_id = str(row["group_id"])
        if group_id in result:
            raise ValueError("Cohort group identity is duplicated")
        result[group_id] = row
    return result


def audit_phase3_final_gates(
    *,
    execution_archive: Path,
    g0_archive: Path,
    cohort_seal: Path,
    authorization: Path,
    prelaunch: Path,
    algorithm_audit_directory: Path,
    output_directory: Path,
) -> dict[str, object]:
    """Audit immutable evidence without altering or re-running the campaign."""

    paths = [
        execution_archive,
        g0_archive,
        cohort_seal,
        authorization,
        prelaunch,
        algorithm_audit_directory / "summary.json",
    ]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
    if output_directory.exists():
        raise FileExistsError(output_directory)
    output_directory.mkdir(parents=True)
    (output_directory / "README.md").write_text(
        "# Phase 3 final gate audit data\n\n"
        "This directory is a read-only derivative of the immutable Option F "
        "execution archive. `gate-ledger.json` is the entry point; `nec-cells/` "
        "contains the 40 independent N/E/C reports. Retrospective checks do not "
        "alter historical authorization or evidence.\n",
        encoding="utf-8",
    )

    cohort = json.loads(cohort_seal.read_text(encoding="utf-8"))
    authorization_document = json.loads(authorization.read_text(encoding="utf-8"))
    prelaunch_document = json.loads(prelaunch.read_text(encoding="utf-8"))
    algorithm = json.loads(
        (algorithm_audit_directory / "summary.json").read_text(encoding="utf-8")
    )
    if not all(
        isinstance(value, dict)
        for value in (cohort, authorization_document, prelaunch_document, algorithm)
    ):
        raise TypeError("audit inputs must contain JSON objects")
    cohort_sha = _sha256(cohort_seal)
    groups = _cohort_groups(cohort)

    with tarfile.open(g0_archive) as g0, tarfile.open(execution_archive) as evidence:
        candidate = _json(g0, "g0/g0-freeze-candidate.json")
        classification = _json(g0, "g0/calibration-classification.json")
        noise_plan = _json(g0, "g0/noise-run-plan.json")
        main_plan = _json(g0, "g0/main-run-plan.json")
        state = _json(evidence, "pipeline-state.json")
        noise_report = _json(evidence, "noise-report.json")
        transition = _json(evidence, "stage-transition.json")
        main_report = _json(evidence, "main-report.json")

        frozen_cohort = candidate.get("cohort_seal")
        frozen_cohort_sha = (
            frozen_cohort.get("sha256") if isinstance(frozen_cohort, Mapping) else None
        )
        cohort_match = frozen_cohort_sha == cohort_sha

        noise_rows = noise_plan.get("runs")
        main_rows = main_plan.get("runs")
        if not isinstance(noise_rows, list) or not isinstance(main_rows, list):
            raise TypeError("frozen plans lack run inventories")
        expected_noise = {str(row["run_id"]) for row in noise_rows}
        expected_main = {str(row["run_id"]) for row in main_rows}
        completed_noise = set(state.get("completed_noise_run_ids", []))
        completed_main = set(state.get("completed_main_run_ids", []))
        result_ids = {
            PurePosixPath(row.name).stem
            for row in evidence.getmembers()
            if row.isfile() and "/results/" in row.name and row.name.endswith(".json")
        }
        native_ids = {
            PurePosixPath(row.name).parent.name
            for row in evidence.getmembers()
            if row.isfile() and "/native-runs/" in row.name and row.name.endswith("/run.json")
        }
        run_identity_exact = (
            completed_noise == expected_noise
            and completed_main == expected_main
            and result_ids == expected_noise | expected_main
            and native_ids == expected_noise | expected_main
        )

        normalized_config_cells = 0
        enqueue_checks = 0
        boundary_checks = 0
        g1_failures: list[str] = []
        for group_id in sorted(groups):
            expected_enqueue = groups[group_id].get("native_enqueue_order")
            if not isinstance(expected_enqueue, list):
                raise TypeError(f"Cohort group lacks Native enqueue order: {group_id}")
            for condition in ("c1", "c2"):
                run_ids = {
                    arm: f"phase3-main-{group_id}-{condition}-r1-{arm.lower()}"
                    for arm in ARMS
                }
                configs = {
                    arm: _json(evidence, f"native-runs/{run_id}/config.json")
                    for arm, run_id in run_ids.items()
                }
                normalized = {_canonical_sha(_normalized_config(row)) for row in configs.values()}
                if len(normalized) != 1:
                    g1_failures.append(f"CONFIG_ISOLATION:{group_id}/{condition}")
                else:
                    normalized_config_cells += 1

                boundary_sequences = {}
                for arm, run_id in run_ids.items():
                    events = _jsonl(evidence, f"native-runs/{run_id}/events.jsonl")
                    enqueue = [
                        row.get("request_id")
                        for row in events
                        if row.get("event_type") == "VLLM_REQUEST_SUBMITTED"
                        and isinstance(row.get("request_id"), str)
                        and not str(row["request_id"]).startswith("pressure:")
                    ]
                    if enqueue != expected_enqueue:
                        g1_failures.append(f"ENQUEUE_ORDER:{run_id}")
                    else:
                        enqueue_checks += 1
                    boundary_sequences[arm] = [
                        (
                            (row.get("payload") or {}).get("boundary_id"),
                            (row.get("payload") or {}).get("stage_id"),
                            (row.get("payload") or {}).get("attempt_count"),
                        )
                        for row in events
                        if row.get("event_type") == "CONTROLLED_REPLAY_PRESSURE_COMPLETED"
                    ]
                if len({_canonical_sha(row) for row in boundary_sequences.values()}) != 1:
                    g1_failures.append(f"N0_BOUNDARY:{group_id}/{condition}")
                else:
                    boundary_checks += 1

        nec_members = [
            row for row in evidence.getmembers() if row.isfile() and "/nec-cells/" in row.name
        ]
        nec_reports = [json.loads(evidence.extractfile(row).read()) for row in nec_members]
        nec_exact = len(nec_reports) == 40 and all(
            row.get("status") == "PASS" for row in nec_reports
        )

        classification_groups = classification.get("groups")
        if not isinstance(classification_groups, list):
            raise TypeError("classification lacks groups")
        headroom_cells = sum(
            bool(row.get(condition, {}).get("headroom_eligible"))
            for row in classification_groups
            for condition in ("C1", "C2")
            if isinstance(row, Mapping) and isinstance(row.get(condition), Mapping)
        )
        paired_headroom = sum(
            bool(row.get("paired_headroom"))
            for row in classification_groups
            if isinstance(row, Mapping)
        )

        core = {
            "pipeline-state.json": state,
            "noise-report.json": noise_report,
            "stage-transition.json": transition,
            "main-report.json": main_report,
        }
        for name, document in core.items():
            _write(output_directory / name, document)
        nec_output = output_directory / "nec-cells"
        nec_output.mkdir()
        for member, report in zip(nec_members, nec_reports, strict=True):
            _write(nec_output / PurePosixPath(member.name).name, report)

    g1_retrospective_pass = not g1_failures and nec_exact
    transition_recorded_gates = all(
        field in transition for field in ("g1", "g4", "cohort_seal_sha256")
    )
    process_deviation = {
        "status": "RECORDED_DEVIATION" if not transition_recorded_gates else "NONE",
        "main_started": True,
        "execution_time_gate_ledger_present": transition_recorded_gates,
        "retrospective_checks_are_not_retroactive_authorization": True,
        "description": (
            "The historical controller persisted the Noise result but did not persist "
            "the complete G1/G4/Cohort gate ledger before Main admission. Independent "
            "read-only checks are reported separately and are not relabeled as an "
            "execution-time PASS."
        ),
    }
    g2 = algorithm.get("g2", {})
    g3 = algorithm.get("g3_cm", {})
    ledger = {
        "schema_version": "phase3.option_f_final_gate_audit.v1",
        "source_execution_archive_sha256": _sha256(execution_archive),
        "source_g0_archive_sha256": _sha256(g0_archive),
        "cohort_seal": {
            "expected_sha256": frozen_cohort_sha,
            "observed_sha256": cohort_sha,
            "retrospective_status": "PASS" if cohort_match else "FAIL",
            "execution_authorization_record_bound_sha": authorization_document.get(
                "cohort_seal_sha256"
            ),
            "historical_authorization_gap": "cohort_seal_sha256"
            not in authorization_document,
        },
        "run_identity": {
            "expected_noise_count": len(expected_noise),
            "expected_main_count": len(expected_main),
            "completed_noise_count": len(completed_noise),
            "completed_main_count": len(completed_main),
            "result_count": len(result_ids),
            "native_run_count": len(native_ids),
            "retrospective_status": "PASS" if run_identity_exact else "FAIL",
        },
        "G1": {
            "retrospective_status": "PASS" if g1_retrospective_pass else "FAIL",
            "normalized_config_cells": normalized_config_cells,
            "native_enqueue_order_checks": enqueue_checks,
            "n0_boundary_equality_cells": boundary_checks,
            "nec_pass_cells": len(nec_reports) if nec_exact else 0,
            "failures": g1_failures,
            "execution_time_status": "NOT_RECORDED_BEFORE_MAIN",
        },
        "G2": g2,
        "G3_CM": g3,
        "G4": {
            "retrospective_status": (
                "PASS_HEADROOM_38_OF_40"
                if headroom_cells == 38 and paired_headroom == 18
                else "FAIL"
            ),
            "headroom_cell_count": headroom_cells,
            "paired_headroom_group_count": paired_headroom,
            "execution_time_status": "NOT_RECORDED_IN_STAGE_TRANSITION",
        },
        "automatic_transition_process": process_deviation,
        "prelaunch_status": prelaunch_document.get("status"),
        "claim_boundary": {
            "campaign_gpu_rerun_required": False,
            "physical_owner_attribution": "NOT_ESTABLISHED",
            "h2": "NOT_EVALUABLE",
        },
    }
    _write(output_directory / "gate-ledger.json", ledger)
    _write(output_directory / "authorization-record.json", authorization_document)
    _write(output_directory / "prelaunch-validation.json", prelaunch_document)

    for source in sorted(algorithm_audit_directory.iterdir()):
        if source.is_file():
            (output_directory / f"algorithm-{source.name}").write_bytes(source.read_bytes())
    manifest = []
    for path in sorted(output_directory.rglob("*")):
        if path.is_file() and path.name != "sha256-manifest.txt":
            manifest.append(f"{_sha256(path)}  {path.relative_to(output_directory)}")
    (output_directory / "sha256-manifest.txt").write_text(
        "\n".join(manifest) + "\n", encoding="utf-8"
    )
    return ledger
