#!/usr/bin/env python3
"""Materialize the M1-frozen BFCL derived candidate-Group inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase5_bfcl_derived_cohort import (
    validate_bfcl_derived_cohort_proposal,
)
from kvopt.workload.phase5_bfcl_derived_groups import (
    build_bfcl_derived_candidate_groups,
    validate_bfcl_derived_candidate_groups,
)
from kvopt.workload.phase5_dataset_processing import file_sha256
from kvopt.workload.phase5_replay import canonical_sha256


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
    parser.add_argument("--cohort-data-root", type=Path, required=True)
    parser.add_argument("--derived-evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cohort_root = args.cohort_data_root.resolve()
    evidence_root = args.derived_evidence_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite Group preparation: {output}")

    membership = _load(cohort_root / "bfcl-derived-cohort-membership-proposal.json")
    cohort_seal = _load(cohort_root / "bfcl-derived-cohort-preparation-seal.json")
    validate_bfcl_derived_cohort_proposal(membership, cohort_seal)
    if cohort_seal.get("lineage_validation_status") != "PASS":
        raise ValueError("Cohort candidate pool lineage is not closed")

    request_counts = {}
    for row in membership["session_membership"]:
        record_id = row["archive_record_id"]
        session_path = evidence_root / "sessions" / record_id / "derived-session.json"
        session = _load(session_path)
        if canonical_sha256(session) != row["derived_session_sha256"]:
            raise ValueError(f"derived Session identity mismatch: {record_id}")
        requests = session.get("requests")
        if not isinstance(requests, list):
            raise TypeError(f"derived Session requests missing: {record_id}")
        request_counts[record_id] = len(requests)

    group_manifest, paired_ledger, audit, summary = build_bfcl_derived_candidate_groups(
        membership=membership,
        session_request_count=request_counts,
    )
    validate_bfcl_derived_candidate_groups(group_manifest, paired_ledger, audit, summary)
    package_seal_payload = {
        "schema_version": "phase5.bfcl_derived_group_preparation_seal.v1",
        "status": "READY_FOR_M4_GROUP_REVIEW",
        "cohort_membership_content_sha256": membership["membership_content_sha256"],
        "cohort_preparation_seal_content_sha256": cohort_seal["seal_content_sha256"],
        "lineage_validation_sha256": cohort_seal["lineage_validation_sha256"],
        "group_manifest_content_sha256": group_manifest["group_manifest_content_sha256"],
        "paired_ledger_content_sha256": paired_ledger["paired_ledger_content_sha256"],
        "outcome_blind_audit_content_sha256": audit["audit_content_sha256"],
        "statistics_summary_content_sha256": summary["summary_content_sha256"],
        "formal_q1_q9_status": "NOT_EVALUATED",
        "calibration_groups_assigned": False,
        "formal_groups_assigned": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    package_seal = {
        **package_seal_payload,
        "seal_content_sha256": canonical_sha256(package_seal_payload),
    }
    output.mkdir(parents=True)
    files = {
        "bfcl-derived-candidate-group-manifest.json": group_manifest,
        "bfcl-derived-paired-mode-ledger.json": paired_ledger,
        "bfcl-derived-group-outcome-blind-audit.json": audit,
        "bfcl-derived-group-statistics-summary.json": summary,
        "bfcl-derived-group-preparation-seal.json": package_seal,
    }
    for name, value in files.items():
        _write(output / name, value)
    manifest = {
        path.name: file_sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "sha256-manifest.json"
    }
    _write(output / "sha256-manifest.json", manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
