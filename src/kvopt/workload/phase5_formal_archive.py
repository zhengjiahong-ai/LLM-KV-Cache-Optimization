"""Whole-campaign Phase 5 archive assembly and independent integrity checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from .phase5_archive import (
    create_phase5_evidence_archive,
    validate_phase5_evidence_archive,
)
from .phase5_formal_manifests import (
    FORMAL_EVIDENCE_NAMES,
    manifest_sha256,
    validate_run_result_manifest,
)
from .phase5_formal_orchestrator import validate_campaign_plan_identity
from .phase5_replay import canonical_sha256


class FormalArchiveError(RuntimeError):
    """Raised when a campaign archive is incomplete or identity-inconsistent."""


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise FormalArchiveError(f"JSON document must be an object: {path}")
    return value


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_file(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise FormalArchiveError(f"{label} must be a non-empty relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise FormalArchiveError(f"{label} escapes the campaign evidence root")
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file():
        raise FormalArchiveError(f"{label} does not resolve to a regular file")
    return path


def create_formal_campaign_archive(
    *, source_root: Path, archive_path: Path
) -> dict[str, object]:
    """Validate every frozen Run and build one deterministic evidence archive."""

    root = source_root.resolve()
    plan = _read_json(root / "campaign-plan.json")
    validate_campaign_plan_identity(plan)
    phase = plan.get("phase")
    expected_run_counts = {
        "CALIBRATION": {72},
        "FORMAL": set(range(96, 193, 12)),
    }
    if phase not in expected_run_counts or plan.get("run_count") not in expected_run_counts[phase]:
        raise FormalArchiveError("campaign run count is outside the frozen design")
    plan_rows = plan.get("runs")
    assert isinstance(plan_rows, list)
    expected_run_ids = {
        row.get("run_id") for row in plan_rows if isinstance(row, Mapping)
    }
    if None in expected_run_ids or len(expected_run_ids) != len(plan_rows):
        raise FormalArchiveError("campaign plan run identities are incomplete")

    run_index = _read_json(root / "run-index.json")
    index_rows = run_index.get("runs")
    if not isinstance(index_rows, list):
        raise FormalArchiveError("run index rows are absent")
    indexed_ids = [
        row.get("run_id") for row in index_rows if isinstance(row, Mapping)
    ]
    if len(indexed_ids) != len(index_rows) or set(indexed_ids) != expected_run_ids:
        raise FormalArchiveError("run index differs from the Campaign Plan")
    if len(indexed_ids) != len(set(indexed_ids)):
        raise FormalArchiveError("run index contains duplicate run IDs")

    required = {
        "campaign-plan.json",
        "protocol-bundle.json",
        "gate-ledger.json",
        "analysis.json",
        "run-index.json",
    }
    expected_evidence_names = FORMAL_EVIDENCE_NAMES
    status_counts: dict[str, int] = {}
    for raw_row in index_rows:
        assert isinstance(raw_row, Mapping)
        run_id = raw_row["run_id"]
        input_path = _resolve_file(root, raw_row.get("input_manifest"), "input manifest")
        result_path = _resolve_file(root, raw_row.get("result_manifest"), "result manifest")
        evidence_paths = raw_row.get("evidence")
        if not isinstance(evidence_paths, Mapping) or set(evidence_paths) != expected_evidence_names:
            raise FormalArchiveError("run evidence path set is incomplete")
        input_manifest = _read_json(input_path)
        result_manifest = _read_json(result_path)
        if input_manifest.get("run_id") != run_id:
            raise FormalArchiveError("run input identity differs from the index")
        validate_run_result_manifest(
            result_manifest, run_input_manifest=input_manifest
        )
        if result_manifest.get("run_id") != run_id:
            raise FormalArchiveError("run result identity differs from the index")
        for name, relative_path in evidence_paths.items():
            evidence_path = _resolve_file(root, relative_path, f"{name} evidence")
            if _sha256_path(evidence_path) != result_manifest["evidence_sha256"][name]:
                raise FormalArchiveError(f"{name} evidence SHA-256 mismatch")
            required.add(evidence_path.relative_to(root).as_posix())
        metrics_relative = raw_row.get("derived_metrics")
        metrics_digest = result_manifest.get("derived_metrics_sha256")
        metrics_path = None
        if metrics_digest is None:
            if metrics_relative is not None:
                raise FormalArchiveError(
                    "failed Run has an unbound derived metrics path"
                )
        else:
            metrics_path = _resolve_file(root, metrics_relative, "derived metrics")
            if _sha256_path(metrics_path) != metrics_digest:
                raise FormalArchiveError("derived metrics SHA-256 mismatch")
        required.update(
            {
                input_path.relative_to(root).as_posix(),
                result_path.relative_to(root).as_posix(),
            }
        )
        if metrics_path is not None:
            required.add(metrics_path.relative_to(root).as_posix())
        status = str(result_manifest.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    archive = create_phase5_evidence_archive(
        source_root=root,
        archive_path=archive_path,
        required_relative_paths=sorted(required),
    )
    validation = validate_phase5_evidence_archive(archive_path)
    payload = {
        "schema_version": "phase5.formal_campaign_archive_envelope.v1",
        "status": "PASS",
        "phase": phase,
        "plan_sha256": plan["plan_sha256"],
        "run_index_sha256": manifest_sha256(run_index),
        "run_count": len(index_rows),
        "run_status_counts": dict(sorted(status_counts.items())),
        "archive_sha256": archive["archive_sha256"],
        "archive_member_manifest_sha256": validation["internal_manifest_sha256"],
        "source_file_count": archive["source_file_count"],
        "archive_validation_status": validation["status"],
        "archive_envelope_external": True,
        "execution_authorization_effect": "NONE",
    }
    return {**payload, "envelope_sha256": canonical_sha256(payload)}
