#!/usr/bin/env python3
"""Prepare the independently reviewable BFCL derived cohort candidate pool."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from kvopt.workload.phase5_bfcl_derived_cohort import (
    build_bfcl_derived_cohort_proposal,
    validate_bfcl_derived_cohort_lineage,
    validate_bfcl_derived_cohort_proposal,
)
from kvopt.workload.phase5_dataset_processing import file_sha256


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived-evidence-root", type=Path, required=True)
    parser.add_argument("--protocol-appendix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.derived_evidence_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite cohort preparation: {output}")

    summary = _load(root / "collection-summary.json")
    exclusions = _load(root / "context-budget-exclusions.json")
    parent_seal = _load(root / "bfcl-derived-workload-seal.json")
    parent_manifest = _load(root / "sha256-manifest.json")
    appendix = _load(args.protocol_appendix)
    context_exclusions_file_sha256 = file_sha256(root / "context-budget-exclusions.json")
    appendix_file_sha256 = file_sha256(args.protocol_appendix)
    lineage = validate_bfcl_derived_cohort_lineage(
        parent_workload_seal=parent_seal,
        parent_evidence_manifest=parent_manifest,
        parent_workload_seal_file_sha256=file_sha256(root / "bfcl-derived-workload-seal.json"),
        parent_evidence_manifest_file_sha256=file_sha256(root / "sha256-manifest.json"),
        context_budget_exclusions=exclusions,
        context_budget_exclusions_file_sha256=context_exclusions_file_sha256,
        protocol_appendix=appendix,
        protocol_appendix_file_sha256=appendix_file_sha256,
    )
    if (
        summary.get("status") != "READY_WITH_CONTEXT_EXCLUSIONS"
        or summary.get("formal_q1_q9_status") != "NOT_EVALUATED"
        or summary.get("derived_q4d_status") != "PASS"
        or summary.get("derived_q5d_status") != "PASS"
        or summary.get("formal_cohort_selected") is not False
        or summary.get("gpu_execution_authorized") is not False
    ):
        raise ValueError("derived collection is not accepted for Cohort preparation")
    if (
        exclusions.get("excluded_session_count") != 40
        or exclusions.get("formal_eligible_session_count") != 159
    ):
        raise ValueError("derived context partition differs from accepted asset")
    session_identities = parent_seal.get("session_identities")
    if not isinstance(session_identities, dict):
        raise TypeError("parent derived workload Seal lacks Session identities")
    eligible_ids = exclusions["formal_eligible_archive_record_ids"]
    if not isinstance(eligible_ids, list):
        raise TypeError("context exclusion report lacks eligible identities")
    eligible_identity_map = {}
    for record_id in eligible_ids:
        matches = [
            (case_id, value)
            for case_id, value in session_identities.items()
            if isinstance(value, dict) and value.get("archive_record_id") == record_id
        ]
        if len(matches) != 1:
            raise ValueError(f"parent Seal lacks identity for {record_id}")
        case_id, identity = matches[0]
        eligible_identity_map[str(record_id)] = {
            **identity,
            "phase5_case_id": case_id,
        }

    membership, seal = build_bfcl_derived_cohort_proposal(
        accepted_archive_record_ids=parent_seal["accepted_archive_record_ids"],
        context_excluded_archive_record_ids=exclusions["excluded_archive_record_ids"],
        session_identity_by_archive_record_id=eligible_identity_map,
        parent_workload_seal_content_sha256=str(parent_seal["seal_content_sha256"]),
        context_budget_exclusions_file_sha256=context_exclusions_file_sha256,
        protocol_appendix_canonical_sha256=str(appendix["protocol_appendix_sha256"]),
        protocol_appendix_file_sha256=appendix_file_sha256,
        context_budget_exclusions_canonical_sha256=str(
            lineage["context_budget_exclusions_canonical_sha256"]
        ),
        lineage_validation_sha256=str(lineage["lineage_validation_sha256"]),
    )
    validate_bfcl_derived_cohort_proposal(membership, seal)
    output.mkdir(parents=True)
    _write(output / "bfcl-derived-cohort-membership-proposal.json", membership)
    _write(output / "bfcl-derived-cohort-preparation-seal.json", seal)
    _write(output / "bfcl-derived-cohort-lineage-validation.json", lineage)
    lineage_root = output / "lineage"
    lineage_root.mkdir()
    shutil.copyfile(
        root / "bfcl-derived-workload-seal.json",
        lineage_root / "parent-bfcl-derived-workload-seal.json",
    )
    shutil.copyfile(
        root / "context-budget-exclusions.json",
        lineage_root / "parent-context-budget-exclusions.json",
    )
    shutil.copyfile(
        root / "sha256-manifest.json",
        lineage_root / "parent-sha256-manifest.json",
    )
    shutil.copyfile(
        args.protocol_appendix,
        lineage_root / "phase5-bfcl-derived-protocol-appendix-v1.json",
    )
    manifest = {
        str(path.relative_to(output)): file_sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "sha256-manifest.json"
    }
    _write(output / "sha256-manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": membership["status"],
                "derived_eligible_sessions": membership["derived_eligible_session_count"],
                "independent_source_question_programs": membership[
                    "independent_source_question_program_count"
                ],
                "maximum_disjoint_four_program_groups": membership[
                    "maximum_disjoint_four_program_group_count"
                ],
                "formal_cohort_selected": False,
                "gpu_execution_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
