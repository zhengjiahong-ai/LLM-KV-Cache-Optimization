"""Fail-closed contracts for Phase 5 BFCL Web Search acquisition."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .phase5_dataset_processing import file_sha256
from .phase5_replay import canonical_sha256


class BFCLAcquisitionError(ValueError):
    """Raised when the pinned BFCL acquisition identity is not satisfied."""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BFCLAcquisitionError(f"expected JSON object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise BFCLAcquisitionError(
                f"invalid JSONL at {path}:{line_number}"
            ) from error
        if not isinstance(value, dict):
            raise BFCLAcquisitionError(
                f"expected object at {path}:{line_number}"
            )
        values.append(value)
    return values


def validate_bfcl_sampling_frame(
    *, frame_path: Path, source_path: Path, observed_revision: str
) -> dict[str, object]:
    """Validate the pinned source and all 200 ordered acquisition identities."""

    frame = _load_json(frame_path)
    source = frame["source"]
    configuration = frame["configuration"]
    if observed_revision != source["revision"]:
        raise BFCLAcquisitionError(
            f"BFCL revision mismatch: {observed_revision} != {source['revision']}"
        )
    observed_sha = file_sha256(source_path)
    if observed_sha != source["raw_file_sha256"]:
        raise BFCLAcquisitionError("BFCL source SHA-256 mismatch")
    if source_path.stat().st_size != source["raw_file_bytes"]:
        raise BFCLAcquisitionError("BFCL source byte length mismatch")

    rows = _load_jsonl(source_path)
    if len(rows) != source["source_case_count"]:
        raise BFCLAcquisitionError("BFCL source case count mismatch")
    expected_source_ids = [f"web_search_{index}" for index in range(len(rows))]
    observed_source_ids = [str(row.get("id")) for row in rows]
    if observed_source_ids != expected_source_ids:
        raise BFCLAcquisitionError("BFCL source IDs are not complete and ordered")
    if any(row.get("involved_classes") != ["WebSearchAPI"] for row in rows):
        raise BFCLAcquisitionError("BFCL source contains a non-WebSearchAPI case")

    expected_cases = []
    for mode, suffix, show_snippet in (
        ("SNIPPET", "snippet", True),
        ("NO_SNIPPET", "no_snippet", False),
    ):
        for source_id in expected_source_ids:
            expected_cases.append((source_id, mode, suffix, show_snippet))
    cases = frame["cases"]
    if len(cases) != configuration["formal_case_count"]:
        raise BFCLAcquisitionError("BFCL formal case count mismatch")
    if len({case["case_id"] for case in cases}) != len(cases):
        raise BFCLAcquisitionError("BFCL case IDs are not unique")
    for index, (case, expected) in enumerate(
        zip(cases, expected_cases, strict=True), start=1
    ):
        source_id, mode, suffix, show_snippet = expected
        if case["phase5_case_index"] != index:
            raise BFCLAcquisitionError("BFCL phase5_case_index is not contiguous")
        if case["source_case_id"] != source_id:
            raise BFCLAcquisitionError("BFCL source pairing/order mismatch")
        if case["case_id"] != f"bfcl_{source_id}:{suffix}":
            raise BFCLAcquisitionError("BFCL case identity mismatch")
        if case["search_mode"] != mode or case["show_snippet"] is not show_snippet:
            raise BFCLAcquisitionError("BFCL search mode mismatch")
        content_sha = case.get("content_sha256")
        if not isinstance(content_sha, str) or len(content_sha) != 64:
            raise BFCLAcquisitionError("BFCL content identity is missing")

    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_source_validation.v1",
        "status": "PASS",
        "observed_revision": observed_revision,
        "source_file_sha256": observed_sha,
        "source_case_count": len(rows),
        "formal_case_count": len(cases),
        "snippet_case_count": sum(
            case["search_mode"] == "SNIPPET" for case in cases
        ),
        "no_snippet_case_count": sum(
            case["search_mode"] == "NO_SNIPPET" for case in cases
        ),
        "frame_sha256": file_sha256(frame_path),
    }
    return {**payload, "validation_sha256": canonical_sha256(payload)}


def build_bfcl_preflight_report(
    *,
    source_validation: Mapping[str, object],
    protocol_sha256: str,
    qualification_contract_sha256: str,
    expected_model: str,
    expected_model_revision: str,
    endpoint_models: Sequence[str] | None,
    serpapi_key_present: bool,
    model_endpoint_configured: bool,
) -> dict[str, object]:
    """Build a credential-safe acquisition readiness report."""

    checks = {
        "SOURCE_IDENTITY": source_validation.get("status") == "PASS",
        "SERPAPI_KEY_PRESENT": serpapi_key_present,
        "MODEL_ENDPOINT_CONFIGURED": model_endpoint_configured,
        "EXPECTED_MODEL_SERVED": (
            endpoint_models is not None and expected_model in endpoint_models
        ),
        "MODEL_REVISION_PINNED": len(expected_model_revision) == 40,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_acquisition_preflight.v1",
        "status": "READY" if not blockers else "FAIL_CLOSED",
        "checks": checks,
        "blockers": blockers,
        "protocol_sha256": protocol_sha256,
        "qualification_contract_sha256": qualification_contract_sha256,
        "expected_model": expected_model,
        "expected_model_revision": expected_model_revision,
        "endpoint_model_ids": sorted(endpoint_models or []),
        "credentials_recorded": False,
        "live_search_for_formal_replay": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
        "source_validation_sha256": source_validation["validation_sha256"],
    }
    return {**payload, "preflight_sha256": canonical_sha256(payload)}
