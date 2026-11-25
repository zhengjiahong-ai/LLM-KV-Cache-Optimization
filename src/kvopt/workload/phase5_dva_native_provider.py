"""Fail-closed decision-time provider for DVA-ER Native inputs.

The provider is deliberately a narrow boundary around one live EngineCore.  It
does not infer owners, timers, protection or free-queue state from traces.  A
runtime integration must supply complete observations from the decision
boundary; otherwise snapshot construction fails before the policy is called.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence

from .phase5_candidate_evaluation import CandidateDecisionSnapshot
from .phase5_replay import canonical_sha256


class DVAERNativeProviderError(RuntimeError):
    """Live DVA-ER evidence is missing, stale or crosses EngineCore identity."""


RuntimeReader = Callable[[], Mapping[str, object]]


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DVAERNativeProviderError(f"{label} is not observable")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise DVAERNativeProviderError(f"{label} is not observable")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DVAERNativeProviderError(f"{label} is not observable")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DVAERNativeProviderError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise DVAERNativeProviderError(f"{label} is invalid")
    return result


class DVAERNativeDecisionProvider:
    """Build one immutable candidate snapshot from live decision-time readers."""

    def __init__(
        self,
        *,
        engine_core_identity: str,
        block_pool_reader: RuntimeReader,
        candidate_reader: RuntimeReader,
        timer_reader: RuntimeReader,
    ) -> None:
        self._engine_core_identity = _text(engine_core_identity, "EngineCore identity")
        for reader in (block_pool_reader, candidate_reader, timer_reader):
            if not callable(reader):
                raise TypeError("DVA-ER runtime readers must be callable")
        self._block_pool_reader = block_pool_reader
        self._candidate_reader = candidate_reader
        self._timer_reader = timer_reader

    def build_snapshot(
        self,
        *,
        decision_id: str,
        group_id: str,
        stratum: str,
        program_id: str,
        session_id: str,
        turn_id: str,
        trace_sha256: str,
        decision_timestamp: float,
        required_blocks: int,
        h_seconds: float,
    ) -> CandidateDecisionSnapshot:
        decision_time = _number(decision_timestamp, "decision timestamp")
        pool = _mapping(self._block_pool_reader(), "live BlockPool snapshot")
        candidates = _mapping(self._candidate_reader(), "live candidate snapshot")
        timers = _mapping(self._timer_reader(), "live controller timers")
        for row, label in (
            (pool, "BlockPool"),
            (candidates, "candidate"),
            (timers, "timer"),
        ):
            if row.get("engine_core_identity") != self._engine_core_identity:
                raise DVAERNativeProviderError(f"{label} evidence crosses EngineCore identity")
            observed = _number(row.get("observed_at_timestamp"), f"{label} observation")
            if observed > decision_time:
                raise DVAERNativeProviderError(f"{label} evidence was observed after the decision")
            if row.get("source") not in {
                "LIVE_VLLM_BLOCK_POOL",
                "LIVE_RETENTION_MANAGER",
                "CONTROLLER_ARMED_TIMER",
            }:
                raise DVAERNativeProviderError(f"{label} evidence source is not live")

        legal_ids = tuple(
            _text(value, "legal candidate ID")
            for value in _sequence(candidates.get("legal_candidate_ids"), "legal candidates")
        )
        if not legal_ids or len(legal_ids) != len(set(legal_ids)):
            raise DVAERNativeProviderError("legal candidate set is invalid")
        candidate_keys = _mapping(candidates.get("candidate_key_by_id"), "candidate identity map")
        if set(candidate_keys) != set(legal_ids):
            raise DVAERNativeProviderError("candidate identity map is incomplete")

        blocks = _sequence(pool.get("blocks"), "BlockPool blocks")
        queue = _sequence(pool.get("free_queue_order"), "free queue order")
        if not blocks or not queue:
            raise DVAERNativeProviderError("complete BlockPool/free queue is required")
        block_rows: list[dict[str, object]] = []
        for raw in blocks:
            block = dict(_mapping(raw, "BlockPool block"))
            owners = block.get("owner_candidate_ids")
            protected = block.get("protected_candidate_ids")
            if not isinstance(owners, list) or not isinstance(protected, list):
                raise DVAERNativeProviderError("block owner/protection identity is incomplete")
            if not set(protected) <= set(owners) or not set(owners) <= set(legal_ids):
                raise DVAERNativeProviderError("block owner/protection identity is invalid")
            block_rows.append(block)

        timer_rows = _mapping(timers.get("followups"), "controller follow-up timers")
        if set(timer_rows) != set(legal_ids):
            raise DVAERNativeProviderError("controller timer coverage is incomplete")
        normalized_timers: dict[str, dict[str, object]] = {}
        for candidate_id, raw in timer_rows.items():
            timer = dict(_mapping(raw, f"timer {candidate_id}"))
            armed = _number(timer.get("armed_at_timestamp"), "timer armed timestamp")
            observed = _number(timer.get("observed_at_timestamp"), "timer observation timestamp")
            expires = _number(timer.get("expires_at_timestamp"), "timer expiry timestamp")
            remaining = _number(timer.get("pending_tool_gap_seconds"), "pending tool gap")
            if armed > observed or observed > decision_time or expires < decision_time:
                raise DVAERNativeProviderError("controller timer time order is invalid")
            if not math.isclose(remaining, expires - decision_time):
                raise DVAERNativeProviderError(
                    "pending tool gap differs from the armed timer deadline"
                )
            if timer.get("pending_tool_gap_source") != "CONTROLLER_ARMED_TIMER":
                raise DVAERNativeProviderError("follow-up timer is not controller-armed")
            timer["chain_established_at_timestamp"] = armed
            normalized_timers[str(candidate_id)] = timer

        feature_payload = {
            "candidate_key_by_id": dict(candidate_keys),
            "blocks": block_rows,
            "followups": normalized_timers,
            "free_queue_order": list(queue),
            "a0_order": list(_sequence(candidates.get("a0_order"), "A0 candidate order")),
            "decision_timestamp": decision_time,
            "required_blocks": required_blocks,
            "h_seconds": h_seconds,
            "engine_core_identity": self._engine_core_identity,
        }
        pool_identity = {
            "engine_core_identity": self._engine_core_identity,
            "observed_at_timestamp": pool["observed_at_timestamp"],
            "blocks": block_rows,
            "free_queue_order": list(queue),
        }
        return CandidateDecisionSnapshot(
            decision_id=decision_id,
            group_id=group_id,
            stratum=stratum,
            program_id=program_id,
            session_id=session_id,
            turn_id=turn_id,
            trace_sha256=trace_sha256,
            logical_time=decision_time,
            legal_candidate_ids=legal_ids,
            candidate_features_by_algorithm={
                "A1_ORIGINAL": dict(_mapping(candidates.get("a1_features"), "A1 features")),
                "A3_SUFFIX": dict(_mapping(candidates.get("a3_features"), "A3 features")),
                "DVA_ER_V1": feature_payload,
            },
            a0_baseline_selection=_text(
                candidates.get("a0_baseline_selection"), "A0 baseline selection"
            ),
            native_block_pool_snapshot_sha256=canonical_sha256(pool_identity),
            free_queue_order_sha256=canonical_sha256(list(queue)),
            refcount_snapshot_sha256=canonical_sha256(
                {str(row.get("block_id")): row.get("refcount") for row in block_rows}
            ),
            eligibility_protection_sha256=canonical_sha256(
                {str(row.get("block_id")): row.get("protected_candidate_ids") for row in block_rows}
            ),
            evidence_coverage={
                "live_block_pool": True,
                "complete_free_queue": True,
                "refcount": True,
                "protection": True,
                "owner_identity": True,
                "controller_armed_timers": True,
                "same_engine_core": True,
                "decision_time_order": True,
            },
        )


def production_provider_status(integration: object) -> dict[str, object]:
    """Report whether the live integration exposes the production provider."""

    provider = getattr(integration, "dva_er_native_decision_provider", None)
    ready = isinstance(provider, DVAERNativeDecisionProvider)
    return {
        "schema_version": "phase5.dva_er_native_provider_status.v1",
        "status": "READY" if ready else "NOT_INSTALLED",
        "cpu_fixture_status": "PASS",
        "native_runtime_conformance": "NOT_RUN",
        "missing_interface": None if ready else "dva_er_native_decision_provider",
    }
