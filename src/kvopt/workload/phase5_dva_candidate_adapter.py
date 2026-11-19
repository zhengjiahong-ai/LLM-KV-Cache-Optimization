"""Adapter from the Phase 5 Candidate contract to the real DVA-ER v1 policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from kvopt.costaware.dva_er import (
    DVAERDecisionInput,
    DVAERStrategy,
    FollowupGapSource,
    FollowupObservation,
    NativeBlock,
    NativePoolSnapshot,
)

from .phase5_candidate_evaluation import CandidateDecision, CandidateDecisionSnapshot

_FORBIDDEN_FUTURE_FIELDS = {
    "future_turn_content",
    "future_reuse_outcome",
    "future_victim_set_label",
    "oracle_future_use",
}


def _reject_future_fields(value: object) -> None:
    if isinstance(value, Mapping):
        if _FORBIDDEN_FUTURE_FIELDS & set(value):
            raise ValueError("DVA-ER feature payload contains forbidden future evidence")
        for nested in value.values():
            _reject_future_fields(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            _reject_future_fields(nested)


def _candidate_key(value: object, label: str) -> tuple[str, str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
        or not all(isinstance(part, str) and part for part in value)
    ):
        raise ValueError(f"{label} must be a two-part candidate identity")
    return value[0], value[1]


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    return float(value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


class DVAERCandidateAdapter:
    """Evaluate one immutable decision-time snapshot using DVA-ER v1."""

    candidate_id = "DVA_ER_V1"
    correctness_gate_status = "PASS"
    candidate_status = "PROVISIONAL_NOT_FROZEN"
    native_conformance_status = "NOT_RUN"

    def __init__(
        self,
        *,
        cpu_gate: Mapping[str, object],
        strategy: DVAERStrategy | None = None,
    ) -> None:
        if cpu_gate.get("status") != "PASS_CORRECTNESS_ONLY":
            raise ValueError("DVA-ER CPU correctness gate is not PASS")
        if cpu_gate.get("candidate") != self.candidate_id:
            raise ValueError("DVA-ER CPU gate candidate identity differs")
        if cpu_gate.get("candidate_status") != self.candidate_status:
            raise ValueError("DVA-ER candidate freeze status differs")
        if cpu_gate.get("gpu_executed") is not False:
            raise ValueError("DVA-ER CPU gate cannot claim GPU execution")
        if cpu_gate.get("implementation") != "src/kvopt/costaware/dva_er.py":
            raise ValueError("DVA-ER CPU gate implementation path differs")
        if cpu_gate.get("test_module") != "tests/test_dva_er.py":
            raise ValueError("DVA-ER CPU gate test module differs")
        tests_passed = cpu_gate.get("tests_passed")
        if (
            isinstance(tests_passed, bool)
            or not isinstance(tests_passed, int)
            or tests_passed < 28
        ):
            raise ValueError("DVA-ER CPU gate test count is incomplete")
        checks = cpu_gate.get("checks")
        required_checks = {
            "FULL_NATIVE_LRU_SEQUENCE_ORDER",
            "NO_FUTURE_FIELDS_IN_INPUT_CONTRACT",
            "OBSERVATION_NOT_AFTER_DECISION",
            "FUTURE_TRACE_ARRIVAL_SOURCE_REJECTED",
        }
        if not isinstance(checks, list) or not required_checks <= set(checks):
            raise ValueError("DVA-ER CPU gate required checks are incomplete")
        self._strategy = strategy or DVAERStrategy()

    def evaluate(self, snapshot: CandidateDecisionSnapshot) -> CandidateDecision:
        features = _mapping(
            snapshot.candidate_features_by_algorithm[self.candidate_id],
            "DVA-ER features",
        )
        _reject_future_fields(features)
        key_rows = _mapping(features.get("candidate_key_by_id"), "candidate_key_by_id")
        if set(key_rows) != set(snapshot.legal_candidate_ids):
            raise ValueError("DVA-ER candidate identity map differs from the legal set")
        keys = {
            candidate_id: _candidate_key(value, f"candidate key {candidate_id}")
            for candidate_id, value in key_rows.items()
        }
        if len(set(keys.values())) != len(keys):
            raise ValueError("DVA-ER candidate keys are not unique")
        reverse_keys = {value: key for key, value in keys.items()}

        block_rows = features.get("blocks")
        if not isinstance(block_rows, list) or not block_rows:
            raise ValueError("DVA-ER blocks must be a non-empty array")
        blocks = []
        for ordinal, raw_block in enumerate(block_rows):
            block = _mapping(raw_block, f"block {ordinal}")
            owners = frozenset(
                keys[str(candidate_id)]
                for candidate_id in block.get("owner_candidate_ids", [])
            )
            protected = frozenset(
                keys[str(candidate_id)]
                for candidate_id in block.get("protected_candidate_ids", [])
            )
            blocks.append(
                NativeBlock(
                    block_id=_integer(block.get("block_id"), "block_id"),
                    has_hash=block.get("has_hash"),
                    refcount=_integer(block.get("refcount"), "refcount"),
                    native_lru_rank=_integer(
                        block.get("native_lru_rank"), "native_lru_rank"
                    ),
                    owners=owners,
                    protected_owners=protected,
                )
            )

        followup_rows = _mapping(features.get("followups"), "followups")
        if set(followup_rows) != set(snapshot.legal_candidate_ids):
            raise ValueError("DVA-ER follow-up set differs from the legal set")
        followups = {}
        for candidate_id, raw_followup in followup_rows.items():
            followup = _mapping(raw_followup, f"follow-up {candidate_id}")
            source = followup.get("pending_tool_gap_source")
            followups[keys[candidate_id]] = FollowupObservation(
                candidate_key=keys[candidate_id],
                chain_id=str(followup.get("chain_id", "")),
                active=followup.get("active"),
                pending_tool_gap_seconds=(
                    None
                    if followup.get("pending_tool_gap_seconds") is None
                    else _number(
                        followup["pending_tool_gap_seconds"],
                        "pending_tool_gap_seconds",
                    )
                ),
                observed_at_timestamp=_number(
                    followup.get("observed_at_timestamp"),
                    "observed_at_timestamp",
                ),
                chain_established_at_timestamp=_number(
                    followup.get("chain_established_at_timestamp"),
                    "chain_established_at_timestamp",
                ),
                pending_tool_gap_source=(
                    None if source is None else FollowupGapSource(str(source))
                ),
            )

        free_queue = features.get("free_queue_order")
        a0_order = features.get("a0_order")
        if not isinstance(free_queue, list) or not isinstance(a0_order, list):
            raise TypeError("DVA-ER free queue and A0 order must be arrays")
        input_row = DVAERDecisionInput(
            decision_id=snapshot.decision_id,
            timestamp=_number(features.get("decision_timestamp"), "decision_timestamp"),
            required_blocks=_integer(features.get("required_blocks"), "required_blocks"),
            pool=NativePoolSnapshot(
                blocks=tuple(blocks),
                free_queue_order=tuple(
                    _integer(value, "free queue block ID") for value in free_queue
                ),
                candidate_keys=tuple(
                    keys[candidate_id]
                    for candidate_id in snapshot.legal_candidate_ids
                ),
            ),
            followups=followups,
            a0_order=tuple(keys[str(candidate_id)] for candidate_id in a0_order),
            h_seconds=_number(features.get("h_seconds"), "h_seconds"),
        )
        decision = self._strategy.choose(input_row)
        loss_by_id = {
            reverse_keys[row.candidate_key]: float(row.loss)
            for row in decision.candidate_losses
        }
        a0_rank = {
            str(candidate_id): index for index, candidate_id in enumerate(a0_order)
        }
        ordered_ids = tuple(
            sorted(
                snapshot.legal_candidate_ids,
                key=lambda candidate_id: (
                    loss_by_id[candidate_id],
                    a0_rank[candidate_id],
                    candidate_id,
                ),
            )
        )
        selected_id = reverse_keys[decision.selected]
        selected_loss = next(
            row
            for row in decision.candidate_losses
            if row.candidate_key == decision.selected
        )
        return CandidateDecision(
            candidate_id=self.candidate_id,
            snapshot_sha256=snapshot.sha256,
            selected_candidate_id=selected_id,
            scores=loss_by_id,
            ordered_candidate_ids=ordered_ids,
            simulated_native_victim_block_ids=(
                selected_loss.physical_victim_block_ids
            ),
            branch="DVA_ER_V1_NATIVE_VICTIM_LOSS",
            fell_back=False,
            fallback_reason=None,
        )
