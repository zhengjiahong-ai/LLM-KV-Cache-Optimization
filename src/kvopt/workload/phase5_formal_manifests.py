"""Two-layer manifests for the Phase 5 Formal Campaign.

``RunInputManifest`` freezes all execution inputs before a run.  The
``RunResultManifest`` binds immutable outputs after execution but deliberately
does not contain an archive digest.  The archive digest is recorded in a small
external ``ArchiveEnvelope`` so an archive never needs to contain its own hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from kvopt.workload.phase5_formal_protocol_validator import (
    ProtocolBundle,
    require_execution_ready,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SYSTEM_IDS = {
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
}
_STRATA = {"SWE_BENCH", "BFCL_WEB_SEARCH"}
_RESULT_STATUSES = {"PASS", "FAIL_CLOSED", "INCOMPLETE", "UNDERPOWERED"}
FORMAL_EVIDENCE_NAMES = {
    "planned_events",
    "native_events",
    "terminal_events",
    "exposure_events",
    "decision_physical_events",
    "downstream_observations",
}


class Phase5ManifestError(ValueError):
    """Raised when a formal manifest is incomplete or identity-inconsistent."""


def canonical_bytes(document: Mapping[str, Any]) -> bytes:
    """Return the single canonical serialization used by manifest identities."""

    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def manifest_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Phase5ManifestError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Phase5ManifestError(f"{label} must be a non-empty string")
    return value


def build_run_input_manifest(
    *,
    bundle: ProtocolBundle,
    run_id: str,
    group_id: str,
    stratum: str,
    repeat_index: int,
    system_id: str,
    system_revision: str,
    workload_seal_sha256: str,
    arrival_realization_sha256: str,
    expected_enqueue_sequence_sha256: str,
    model_revision: str,
    tokenizer_revision: str,
    sampling_parameters_sha256: str,
    engine_configuration_sha256: str,
    generation_config_sha256: str,
    execution_order_index: int,
    engine_instance_id: str,
    isolation_preflight: Mapping[str, object],
    preheat_mode: str,
    runner_version: str,
    evaluator_version: str,
) -> dict[str, Any]:
    """Build a frozen run input only from an executable M1-frozen protocol."""

    require_execution_ready(bundle)
    _require_nonempty(run_id, "run_id")
    _require_nonempty(group_id, "group_id")
    if stratum not in _STRATA:
        raise Phase5ManifestError(f"unknown workload stratum: {stratum}")
    if not isinstance(repeat_index, int) or isinstance(repeat_index, bool) or repeat_index < 0:
        raise Phase5ManifestError("repeat_index must be a non-negative integer")
    if system_id not in _SYSTEM_IDS:
        raise Phase5ManifestError(f"unknown system_id: {system_id}")

    contract_hashes = dict(bundle.sha256)
    protocol_sha = contract_hashes.pop("protocol")
    if set(contract_hashes) != {
        "metrics",
        "workload_qualification",
        "calibration_sample_size",
        "cost_aware_candidate_family",
        "candidate_evaluation",
    }:
        raise Phase5ManifestError("protocol contract hash binding is incomplete")
    for name, digest in contract_hashes.items():
        _require_sha256(digest, f"contract_sha256.{name}")

    manifest = {
        "schema_version": "phase5.run_input_manifest.v1",
        "protocol_id": bundle.protocol["protocol_id"],
        "protocol_sha256": _require_sha256(protocol_sha, "protocol_sha256"),
        "contract_sha256": contract_hashes,
        "run_id": run_id,
        "group_id": group_id,
        "stratum": stratum,
        "repeat_index": repeat_index,
        "system_id": system_id,
        "system_revision": _require_nonempty(system_revision, "system_revision"),
        "workload_seal_sha256": _require_sha256(
            workload_seal_sha256, "workload_seal_sha256"
        ),
        "arrival_realization_sha256": _require_sha256(
            arrival_realization_sha256, "arrival_realization_sha256"
        ),
        "expected_enqueue_sequence_sha256": _require_sha256(
            expected_enqueue_sequence_sha256, "expected_enqueue_sequence_sha256"
        ),
        "model_revision": _require_nonempty(model_revision, "model_revision"),
        "tokenizer_revision": _require_nonempty(
            tokenizer_revision, "tokenizer_revision"
        ),
        "sampling_parameters_sha256": _require_sha256(
            sampling_parameters_sha256, "sampling_parameters_sha256"
        ),
        "engine_configuration_sha256": _require_sha256(
            engine_configuration_sha256, "engine_configuration_sha256"
        ),
        "generation_config_sha256": _require_sha256(
            generation_config_sha256, "generation_config_sha256"
        ),
        "execution_order_index": execution_order_index,
        "engine_instance_id": _require_nonempty(engine_instance_id, "engine_instance_id"),
        "isolation_preflight": dict(isolation_preflight),
        "preheat_mode": preheat_mode,
        "runner_version": _require_nonempty(runner_version, "runner_version"),
        "evaluator_version": _require_nonempty(evaluator_version, "evaluator_version"),
        "execution_authorized": True,
    }
    validate_run_input_manifest(manifest, bundle=bundle)
    return manifest


def validate_run_input_manifest(
    manifest: Mapping[str, Any], *, bundle: ProtocolBundle
) -> None:
    require_execution_ready(bundle)
    required = {
        "schema_version",
        "protocol_id",
        "protocol_sha256",
        "contract_sha256",
        "run_id",
        "group_id",
        "stratum",
        "repeat_index",
        "system_id",
        "system_revision",
        "workload_seal_sha256",
        "arrival_realization_sha256",
        "expected_enqueue_sequence_sha256",
        "model_revision",
        "tokenizer_revision",
        "sampling_parameters_sha256",
        "engine_configuration_sha256",
        "generation_config_sha256",
        "execution_order_index",
        "engine_instance_id",
        "isolation_preflight",
        "preheat_mode",
        "runner_version",
        "evaluator_version",
        "execution_authorized",
    }
    if set(manifest) != required:
        raise Phase5ManifestError("run input manifest fields are not exact")
    if manifest["schema_version"] != "phase5.run_input_manifest.v1":
        raise Phase5ManifestError("unsupported run input manifest schema")
    if manifest["execution_authorized"] is not True:
        raise Phase5ManifestError("run input manifest is not execution-authorized")
    if manifest["protocol_id"] != bundle.protocol["protocol_id"]:
        raise Phase5ManifestError("run input protocol_id mismatch")
    if manifest["protocol_sha256"] != bundle.protocol_sha256:
        raise Phase5ManifestError("run input protocol_sha256 mismatch")
    expected_contracts = dict(bundle.sha256)
    expected_contracts.pop("protocol")
    if manifest["contract_sha256"] != expected_contracts:
        raise Phase5ManifestError("run input contract hashes mismatch")
    if manifest["system_id"] not in _SYSTEM_IDS:
        raise Phase5ManifestError("run input contains an unknown system")
    if manifest["stratum"] not in _STRATA:
        raise Phase5ManifestError("run input contains an unknown stratum")
    if (
        isinstance(manifest["execution_order_index"], bool)
        or not isinstance(manifest["execution_order_index"], int)
        or manifest["execution_order_index"] < 0
    ):
        raise Phase5ManifestError("execution_order_index must be non-negative int")
    if manifest["preheat_mode"] != "NONE":
        raise Phase5ManifestError("formal run preheat mode must be NONE")
    if manifest["isolation_preflight"] != {
        "new_process": True,
        "new_engine": True,
        "cross_run_apc_reuse": False,
        "empty_cache_verified": True,
    }:
        raise Phase5ManifestError("run isolation preflight is not exact")
    for key in (
        "protocol_sha256",
        "workload_seal_sha256",
        "arrival_realization_sha256",
        "expected_enqueue_sequence_sha256",
        "sampling_parameters_sha256",
        "engine_configuration_sha256",
        "generation_config_sha256",
    ):
        _require_sha256(manifest[key], key)


def build_run_result_manifest(
    *,
    run_input_manifest: Mapping[str, Any],
    status: str,
    actual_enqueue_sequence_sha256: str | None,
    evidence_sha256: Mapping[str, str],
    derived_metrics_sha256: str | None,
    started_at: str,
    ended_at: str,
    failure_reason: str | None,
) -> dict[str, Any]:
    """Bind post-run evidence without introducing an archive hash cycle."""

    if status not in _RESULT_STATUSES:
        raise Phase5ManifestError(f"unsupported result status: {status}")
    if status == "PASS" and (
        actual_enqueue_sequence_sha256 is None or derived_metrics_sha256 is None
    ):
        raise Phase5ManifestError("PASS result requires enqueue and derived metric evidence")
    if status != "PASS" and not failure_reason:
        raise Phase5ManifestError("non-PASS result requires a failure reason")
    if set(evidence_sha256) != FORMAL_EVIDENCE_NAMES:
        raise Phase5ManifestError("result evidence hash set is incomplete")
    for name, digest in evidence_sha256.items():
        _require_sha256(digest, f"evidence_sha256.{name}")

    result = {
        "schema_version": "phase5.run_result_manifest.v1",
        "run_id": run_input_manifest.get("run_id"),
        "run_input_manifest_sha256": manifest_sha256(run_input_manifest),
        "status": status,
        "actual_enqueue_sequence_sha256": (
            None
            if actual_enqueue_sequence_sha256 is None
            else _require_sha256(
                actual_enqueue_sequence_sha256, "actual_enqueue_sequence_sha256"
            )
        ),
        "evidence_sha256": dict(evidence_sha256),
        "derived_metrics_sha256": (
            None
            if derived_metrics_sha256 is None
            else _require_sha256(derived_metrics_sha256, "derived_metrics_sha256")
        ),
        "started_at": _require_nonempty(started_at, "started_at"),
        "ended_at": _require_nonempty(ended_at, "ended_at"),
        "failure_reason": failure_reason,
    }
    validate_run_result_manifest(result, run_input_manifest=run_input_manifest)
    return result


def validate_run_result_manifest(
    result: Mapping[str, Any], *, run_input_manifest: Mapping[str, Any]
) -> None:
    required = {
        "schema_version",
        "run_id",
        "run_input_manifest_sha256",
        "status",
        "actual_enqueue_sequence_sha256",
        "evidence_sha256",
        "derived_metrics_sha256",
        "started_at",
        "ended_at",
        "failure_reason",
    }
    if set(result) != required:
        raise Phase5ManifestError(
            "run result fields are not exact; archive hash belongs in the external envelope"
        )
    if result["schema_version"] != "phase5.run_result_manifest.v1":
        raise Phase5ManifestError("unsupported run result manifest schema")
    if result["run_id"] != run_input_manifest.get("run_id"):
        raise Phase5ManifestError("run result run_id mismatch")
    if result["run_input_manifest_sha256"] != manifest_sha256(run_input_manifest):
        raise Phase5ManifestError("run result input manifest hash mismatch")
    if result["status"] not in _RESULT_STATUSES:
        raise Phase5ManifestError("run result status is invalid")
    if result["status"] == "PASS" and result["failure_reason"] is not None:
        raise Phase5ManifestError("PASS result cannot contain a failure reason")
    if result["status"] != "PASS" and not result["failure_reason"]:
        raise Phase5ManifestError("non-PASS result requires a failure reason")


def build_archive_envelope(
    *,
    run_result_manifest: Mapping[str, Any],
    archive_sha256: str,
    archive_format: str,
    archive_member_manifest_sha256: str,
) -> dict[str, Any]:
    """Create the external, non-archived binding for a completed archive."""

    envelope = {
        "schema_version": "phase5.archive_envelope.v1",
        "run_id": run_result_manifest.get("run_id"),
        "run_result_manifest_sha256": manifest_sha256(run_result_manifest),
        "archive_sha256": _require_sha256(archive_sha256, "archive_sha256"),
        "archive_format": _require_nonempty(archive_format, "archive_format"),
        "archive_member_manifest_sha256": _require_sha256(
            archive_member_manifest_sha256, "archive_member_manifest_sha256"
        ),
        "envelope_is_external_to_archive": True,
    }
    validate_archive_envelope(envelope, run_result_manifest=run_result_manifest)
    return envelope


def validate_archive_envelope(
    envelope: Mapping[str, Any], *, run_result_manifest: Mapping[str, Any]
) -> None:
    required = {
        "schema_version",
        "run_id",
        "run_result_manifest_sha256",
        "archive_sha256",
        "archive_format",
        "archive_member_manifest_sha256",
        "envelope_is_external_to_archive",
    }
    if set(envelope) != required:
        raise Phase5ManifestError("archive envelope fields are not exact")
    if envelope["schema_version"] != "phase5.archive_envelope.v1":
        raise Phase5ManifestError("unsupported archive envelope schema")
    if envelope["envelope_is_external_to_archive"] is not True:
        raise Phase5ManifestError("archive envelope must remain external to the archive")
    if envelope["run_id"] != run_result_manifest.get("run_id"):
        raise Phase5ManifestError("archive envelope run_id mismatch")
    if envelope["run_result_manifest_sha256"] != manifest_sha256(
        run_result_manifest
    ):
        raise Phase5ManifestError("archive envelope result manifest hash mismatch")
    _require_sha256(envelope["archive_sha256"], "archive_sha256")
    _require_sha256(
        envelope["archive_member_manifest_sha256"],
        "archive_member_manifest_sha256",
    )

