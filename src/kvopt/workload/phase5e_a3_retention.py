"""Unified Phase 5E A3 retention-input manifest and P5E-G9 gate."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .phase5_replay import canonical_sha256

SCHEMA_VERSION = "phase5e.a3_retention_input_manifest.v1"
PREFILL_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
PREFILL_REVISION = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"
PREFILL_PROFILE_PATH = (
    "configs/phase2/continuum-native-cost-aware-bounded-prefill-profile-v1.json"
)
PREFILL_PROFILE_SHA256 = (
    "d5b77e70fdf0899a4a5fa2a139112f4bc7a99d3a098189caa3e4be13a072682e"
)
PREFILL_PROTOCOL_REVISION = "bounded-cuda-1p5b-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class Phase5EG9Error(ValueError):
    """The decision-critical A3 input is incomplete or inconsistent."""


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise Phase5EG9Error(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise Phase5EG9Error(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Phase5EG9Error(f"{label} must be non-empty")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Phase5EG9Error(f"{label} must be a lowercase SHA-256")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Phase5EG9Error(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise Phase5EG9Error(f"{label} must be finite and non-negative")
    return result


def _unique_texts(value: object, label: str, *, nonempty: bool = True) -> tuple[str, ...]:
    rows = tuple(_text(row, label) for row in _sequence(value, label))
    if (nonempty and not rows) or len(rows) != len(set(rows)):
        raise Phase5EG9Error(f"{label} must contain unique identities")
    return rows


def _validate_histories(value: object) -> None:
    histories = _mapping(value, "histories")
    for name in ("server_gap", "queue_delay", "eta"):
        row = _mapping(histories.get(name), f"histories.{name}")
        provenance = _text(row.get("provenance"), f"{name} provenance")
        refs = row.get("source_event_refs", [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise Phase5EG9Error(f"{name} source_event_refs are invalid")
        if provenance == "OBSERVED":
            if not refs:
                raise Phase5EG9Error(f"observed {name} lacks source events")
        elif provenance in {"EXPLICIT_COLD_START", "APPROXIMATED"}:
            _text(row.get("reason"), f"{name} cold-start reason")
        else:
            raise Phase5EG9Error(f"unsupported {name} provenance")
    server = _mapping(histories["server_gap"], "server_gap")
    samples = _sequence(server.get("samples"), "server_gap samples")
    for sample in samples:
        _number(sample, "server_gap sample")
    queue = _mapping(histories["queue_delay"], "queue_delay")
    _number(queue.get("value"), "queue_delay value")
    eta = _mapping(histories["eta"], "eta")
    _number(eta.get("value"), "eta value")


@dataclass(frozen=True, slots=True)
class A3RetentionInputManifest:
    """Validated canonical binding for one live A3 decision boundary."""

    payload: Mapping[str, object]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> A3RetentionInputManifest:
        payload = dict(value)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise Phase5EG9Error("unsupported A3 retention manifest schema")
        _text(payload.get("run_id"), "run_id")
        _text(payload.get("decision_id"), "decision_id")
        boundary = _mapping(payload.get("decision_boundary"), "decision_boundary")
        _text(boundary.get("boundary_id"), "decision boundary ID")
        decision_timestamp = _number(boundary.get("timestamp"), "decision timestamp")
        clock_domain = _text(boundary.get("clock_domain"), "decision clock domain")
        if clock_domain != "continuum_lifecycle":
            raise Phase5EG9Error("decision boundary uses the wrong clock domain")
        engine = _mapping(payload.get("engine_core_identity"), "engine_core_identity")
        engine_identity = _text(engine.get("identity"), "EngineCore identity")
        _sha(engine.get("installation_report_sha256"), "installation report SHA-256")
        boundary_id = _text(boundary.get("boundary_id"), "decision boundary ID")

        candidates = _unique_texts(payload.get("a3_candidate_ids"), "A3 candidates")
        ttl_rows = _sequence(payload.get("ttl_inputs"), "ttl_inputs")
        ttl_by_prefix: dict[str, Mapping[str, object]] = {}
        for item in ttl_rows:
            row = _mapping(item, "ttl input row")
            _text(row.get("program_id"), "TTL program_id")
            _text(row.get("request_id"), "TTL request_id")
            if row.get("engine_core_identity") != engine_identity or row.get(
                "decision_boundary_id"
            ) != boundary_id:
                raise Phase5EG9Error("TTL evidence crosses EngineCore or decision boundary")
            prefix_id = _text(row.get("prefix_id"), "TTL prefix_id")
            if prefix_id in ttl_by_prefix:
                raise Phase5EG9Error("candidate has multiple TTL decisions")
            ttl_input = _mapping(row.get("ttl_input"), "ttl_input")
            ttl_decision = _mapping(row.get("ttl_decision"), "ttl_decision")
            if canonical_sha256(ttl_input) != _sha(
                row.get("ttl_input_sha256"), "TTL input SHA-256"
            ):
                raise Phase5EG9Error("TTL input hash mismatch")
            if canonical_sha256(ttl_decision) != _sha(
                row.get("ttl_decision_sha256"), "TTL decision SHA-256"
            ):
                raise Phase5EG9Error("TTL decision hash mismatch")
            ttl_timestamp = _number(
                ttl_input.get("decision_timestamp"), "TTL decision timestamp"
            )
            if ttl_timestamp != decision_timestamp:
                raise Phase5EG9Error("TTL decision boundary timestamp mismatch")
            ttl_seconds = _number(ttl_decision.get("ttl_seconds"), "ttl_seconds")
            deadline = _number(
                ttl_decision.get("deadline_timestamp"), "deadline_timestamp"
            )
            if not math.isclose(deadline, ttl_timestamp + ttl_seconds):
                raise Phase5EG9Error("TTL deadline is not derived from the decision")
            _unique_texts(row.get("source_event_refs"), "TTL source_event_refs")
            ttl_by_prefix[prefix_id] = row
        if set(ttl_by_prefix) != set(candidates):
            raise Phase5EG9Error("A3 candidates and TTL inputs differ")

        retention_rows = _sequence(payload.get("retention_entries"), "retention_entries")
        retention_by_prefix: dict[str, Mapping[str, object]] = {}
        for item in retention_rows:
            row = _mapping(item, "retention entry")
            _text(row.get("program_id"), "retention program_id")
            prefix_id = _text(row.get("prefix_id"), "retention prefix_id")
            if row.get("engine_core_identity") != engine_identity or row.get(
                "decision_boundary_id"
            ) != boundary_id:
                raise Phase5EG9Error(
                    "retention evidence crosses EngineCore or decision boundary"
                )
            if prefix_id in retention_by_prefix:
                raise Phase5EG9Error("candidate has multiple retention entries")
            if not isinstance(row.get("protected"), bool) or not isinstance(
                row.get("waiting_followup"), bool
            ):
                raise Phase5EG9Error("retention lifecycle flags are missing")
            block_ids = _sequence(row.get("block_ids"), "retention block_ids")
            if not block_ids or any(
                isinstance(block_id, bool) or not isinstance(block_id, int)
                for block_id in block_ids
            ) or len(block_ids) != len(set(block_ids)):
                raise Phase5EG9Error("retention block identities are invalid")
            ttl_row = ttl_by_prefix.get(prefix_id)
            if ttl_row is None or row.get("ttl_decision_sha256") != ttl_row.get(
                "ttl_decision_sha256"
            ):
                raise Phase5EG9Error("retention entry TTL binding mismatch")
            retention_by_prefix[prefix_id] = row
        if set(retention_by_prefix) != set(candidates):
            raise Phase5EG9Error("A3 candidates and retention entries differ")

        prefill = _mapping(payload.get("prefill"), "prefill")
        expected_prefill = {
            "model": PREFILL_MODEL,
            "model_revision": PREFILL_REVISION,
            "tokenizer_revision": PREFILL_REVISION,
            "profile_path": PREFILL_PROFILE_PATH,
            "profile_sha256": PREFILL_PROFILE_SHA256,
            "protocol_revision": PREFILL_PROTOCOL_REVISION,
            "provenance": "APPROXIMATED",
        }
        if any(prefill.get(key) != expected for key, expected in expected_prefill.items()):
            raise Phase5EG9Error("wrong frozen 1.5B Prefill Reload profile")
        query_tokens = prefill.get("query_token_count")
        if isinstance(query_tokens, bool) or not isinstance(query_tokens, int) or not (
            1024 <= query_tokens <= 32256
        ):
            raise Phase5EG9Error("Prefill Reload query is outside the frozen grid")
        _number(prefill.get("estimate_seconds"), "Prefill Reload estimate")
        _validate_histories(payload.get("histories"))

        chain_rows = _sequence(payload.get("prefix_chain"), "prefix_chain")
        chain_by_prefix: dict[str, Mapping[str, object]] = {}
        process_ids: set[str] = set()
        for item in chain_rows:
            row = _mapping(item, "prefix chain")
            prefix_id = _text(row.get("prefix_id"), "chain prefix_id")
            if row.get("engine_core_identity") != engine_identity or row.get(
                "decision_boundary_id"
            ) != boundary_id:
                raise Phase5EG9Error(
                    "prefix evidence crosses EngineCore or decision boundary"
                )
            if prefix_id in chain_by_prefix:
                raise Phase5EG9Error("candidate has multiple prefix chains")
            block_ids = tuple(_sequence(row.get("block_ids"), "chain block_ids"))
            hashes = tuple(_sequence(row.get("content_hashes"), "content_hashes"))
            if block_ids != tuple(retention_by_prefix.get(prefix_id, {}).get("block_ids", [])):
                raise Phase5EG9Error("prefix and retention block IDs differ")
            if len(hashes) != len(block_ids) or any(
                not isinstance(value, str) or _SHA256.fullmatch(value) is None
                for value in hashes
            ):
                raise Phase5EG9Error("prefix content hash chain is incomplete")
            process_ids.add(_text(row.get("native_hash_process_id"), "hash process ID"))
            _sha(row.get("chain_depth_proof_sha256"), "chain depth proof SHA-256")
            chain_by_prefix[prefix_id] = row
        if set(chain_by_prefix) != set(candidates) or len(process_ids) != 1:
            raise Phase5EG9Error("prefix chains do not share one Native hash process")

        lifecycle = _sequence(payload.get("lifecycle"), "lifecycle")
        indices: list[int] = []
        for item in lifecycle:
            row = _mapping(item, "lifecycle event")
            _text(row.get("event_type"), "lifecycle event_type")
            index = row.get("event_index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise Phase5EG9Error("lifecycle event index is invalid")
            indices.append(index)
            timestamp = _number(row.get("timestamp"), "lifecycle timestamp")
            if timestamp > decision_timestamp:
                raise Phase5EG9Error("future lifecycle information is forbidden")
            if row.get("clock_domain") != clock_domain:
                raise Phase5EG9Error("lifecycle clock domain differs from decision")
            _sha(row.get("source_event_sha256"), "source event SHA-256")
        if not lifecycle or indices != sorted(indices) or len(indices) != len(set(indices)):
            raise Phase5EG9Error("lifecycle evidence is missing or unordered")

        checks = _mapping(payload.get("checks"), "checks")
        required_checks = {
            "required_inputs_complete",
            "same_engine_core",
            "same_decision_boundary",
            "temporal_order_valid",
            "no_future_information",
            "prefill_profile_hash_valid",
            "prefix_block_hash_depth_consistent",
            "cold_start_explicit",
        }
        if set(checks) != required_checks or any(checks[name] is not True for name in checks):
            raise Phase5EG9Error("manifest completeness checks are not all true")
        expected_hash = canonical_sha256(
            {key: item for key, item in payload.items() if key != "manifest_sha256"}
        )
        if _sha(payload.get("manifest_sha256"), "manifest SHA-256") != expected_hash:
            raise Phase5EG9Error("manifest SHA-256 mismatch")
        return cls(payload=payload)

    @property
    def sha256(self) -> str:
        return str(self.payload["manifest_sha256"])


def evaluate_p5e_g9(value: Mapping[str, object]) -> dict[str, object]:
    """Evaluate the one unified retention-input gate without fallback."""

    try:
        manifest = A3RetentionInputManifest.from_mapping(value)
    except (Phase5EG9Error, TypeError, KeyError) as error:
        return {
            "schema_version": "phase5e.g9_evaluation.v1",
            "gate": "P5E-G9",
            "status": "FAIL_CLOSED",
            "failure_reason": str(error),
            "a3_selection": "NOT_EXECUTED",
            "native_lru_fallback": "FORBIDDEN",
            "synthetic_values_inserted": False,
        }
    return {
        "schema_version": "phase5e.g9_evaluation.v1",
        "gate": "P5E-G9",
        "status": "PASS",
        "manifest_sha256": manifest.sha256,
        "a3_selection": "AUTHORIZED_FOR_BOUND_DECISION_ONLY",
        "native_lru_fallback": "FORBIDDEN",
        "synthetic_values_inserted": False,
    }


def execute_g9_bound_selection(
    value: Mapping[str, object], select: Callable[[], object]
) -> tuple[dict[str, object], object | None]:
    """Run A3 only after G9 PASS; never invoke a fallback selector."""

    report = evaluate_p5e_g9(value)
    if report["status"] != "PASS":
        return report, None
    return report, select()


def build_phase5e_cpu_mock_retention_manifest(
    *, plan: object, installation_report_sha256: str = "a" * 64
) -> dict[str, object]:
    """Build the one CPU/Mock fixture; it is never evidence of a GPU run."""

    pressure = plan.pressure
    order = tuple(plan.frozen_native_enqueue_order)
    candidates = order[:4]
    boundary_id = str(pressure.boundary_id)
    timestamp = float(pressure.logical_trigger_offset_seconds)
    engine = "phase5e-cpu-mock-engine-core"
    ttl_rows = []
    retention_rows = []
    chain_rows = []
    for index, prefix_id in enumerate(candidates, start=1):
        program_id = prefix_id.split(":", maxsplit=1)[0]
        ttl_input = {
            "program_id": program_id,
            "request_id": prefix_id,
            "prefix_id": prefix_id,
            "decision_timestamp": timestamp,
            "next_tool_type": None,
            "global_server_gap_samples_seconds": [],
            "tool_server_gap_samples_seconds": [],
            "queue_delay_t_seconds": 0.0,
            "eta": 1.0,
            "prefill_reload_seconds": 0.01,
            "default_ttl_seconds": 1.0,
        }
        decision = {
            "ttl_seconds": 1.0,
            "deadline_timestamp": timestamp + 1.0,
            "history_mode": "COLD_START",
            "reason": "insufficient global server gap history",
        }
        decision_sha = canonical_sha256(decision)
        blocks = [index * 10, index * 10 + 1]
        shared = {
            "engine_core_identity": engine,
            "decision_boundary_id": boundary_id,
        }
        ttl_rows.append(
            {
                "program_id": program_id,
                "request_id": prefix_id,
                "prefix_id": prefix_id,
                **shared,
                "ttl_input": ttl_input,
                "ttl_input_sha256": canonical_sha256(ttl_input),
                "ttl_decision": decision,
                "ttl_decision_sha256": decision_sha,
                "source_event_refs": [f"ttl-input:{prefix_id}"],
            }
        )
        retention_rows.append(
            {
                "program_id": program_id,
                "prefix_id": prefix_id,
                **shared,
                "protected": True,
                "waiting_followup": False,
                "block_ids": blocks,
                "ttl_decision_sha256": decision_sha,
            }
        )
        chain_rows.append(
            {
                "prefix_id": prefix_id,
                **shared,
                "block_ids": blocks,
                "content_hashes": [
                    canonical_sha256([prefix_id, block_id]) for block_id in blocks
                ],
                "native_hash_process_id": "phase5e-cpu-mock-hash-process",
                "chain_depth_proof_sha256": canonical_sha256(
                    {"prefix_id": prefix_id, "blocks": blocks}
                ),
            }
        )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_scope": "CPU_MOCK_CONTRACT_ONLY_NOT_GPU_EVIDENCE",
        "run_id": "P5E-A-01",
        "decision_id": "phase5e-cpu-mock-decision-1",
        "decision_boundary": {
            "boundary_id": boundary_id,
            "timestamp": timestamp,
            "clock_domain": "continuum_lifecycle",
        },
        "engine_core_identity": {
            "identity": engine,
            "installation_report_sha256": _sha(
                installation_report_sha256, "installation report SHA-256"
            ),
        },
        "a3_candidate_ids": list(candidates),
        "ttl_inputs": ttl_rows,
        "retention_entries": retention_rows,
        "prefill": {
            "model": PREFILL_MODEL,
            "model_revision": PREFILL_REVISION,
            "tokenizer_revision": PREFILL_REVISION,
            "profile_path": PREFILL_PROFILE_PATH,
            "profile_sha256": PREFILL_PROFILE_SHA256,
            "protocol_revision": PREFILL_PROTOCOL_REVISION,
            "query_token_count": 1984,
            "estimate_seconds": 0.01,
            "provenance": "APPROXIMATED",
        },
        "histories": {
            "server_gap": {
                "samples": [],
                "provenance": "EXPLICIT_COLD_START",
                "reason": "NO_COMPLETED_TOOL_GAPS",
                "source_event_refs": [],
            },
            "queue_delay": {
                "value": 0.0,
                "provenance": "EXPLICIT_COLD_START",
                "reason": "NO_EVICTED_REQUEST_QUEUE_DELAY",
                "source_event_refs": [],
            },
            "eta": {
                "value": 1.0,
                "provenance": "APPROXIMATED",
                "reason": "FULLY_MEMORYFUL_COLD_START",
                "source_event_refs": [],
            },
        },
        "prefix_chain": chain_rows,
        "lifecycle": [
            {
                "event_type": "TURN_FINISHED",
                "event_index": index,
                "timestamp": 1.0 + index * 0.1,
                "clock_domain": "continuum_lifecycle",
                "source_event_sha256": canonical_sha256(["TURN_FINISHED", index]),
            }
            for index in range(4)
        ],
        "checks": {
            "required_inputs_complete": True,
            "same_engine_core": True,
            "same_decision_boundary": True,
            "temporal_order_valid": True,
            "no_future_information": True,
            "prefill_profile_hash_valid": True,
            "prefix_block_hash_depth_consistent": True,
            "cold_start_explicit": True,
        },
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    A3RetentionInputManifest.from_mapping(payload)
    return payload
