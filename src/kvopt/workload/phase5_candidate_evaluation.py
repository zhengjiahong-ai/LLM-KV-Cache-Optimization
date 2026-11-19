"""Candidate-family adapter boundary for the frozen Phase 5 evaluation contract."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Protocol

from .phase5_replay import canonical_sha256

CANDIDATE_IDS = ("A1_ORIGINAL", "A3_SUFFIX", "DVA_ER_V1")
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class CandidateDecisionSnapshot:
    decision_id: str
    group_id: str
    stratum: str
    program_id: str
    session_id: str
    turn_id: str
    trace_sha256: str
    logical_time: float
    legal_candidate_ids: tuple[str, ...]
    candidate_features_by_algorithm: Mapping[str, Mapping[str, object]]
    a0_baseline_selection: str
    native_block_pool_snapshot_sha256: str
    free_queue_order_sha256: str
    refcount_snapshot_sha256: str
    eligibility_protection_sha256: str
    evidence_coverage: Mapping[str, bool]

    def __post_init__(self) -> None:
        for value in (
            self.decision_id,
            self.group_id,
            self.stratum,
            self.program_id,
            self.session_id,
            self.turn_id,
        ):
            if not value:
                raise ValueError("candidate snapshot identities must be non-empty")
        for value in (
            self.trace_sha256,
            self.native_block_pool_snapshot_sha256,
            self.free_queue_order_sha256,
            self.refcount_snapshot_sha256,
            self.eligibility_protection_sha256,
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError("candidate snapshot hashes must be SHA-256")
        if not math.isfinite(self.logical_time) or self.logical_time < 0:
            raise ValueError("candidate snapshot logical time is invalid")
        if not self.legal_candidate_ids or len(set(self.legal_candidate_ids)) != len(
            self.legal_candidate_ids
        ):
            raise ValueError("legal candidate identities must be non-empty and unique")
        if self.a0_baseline_selection not in self.legal_candidate_ids:
            raise ValueError("A0 baseline selection is outside the legal set")
        if set(self.candidate_features_by_algorithm) != set(CANDIDATE_IDS):
            raise ValueError("snapshot must expose features for all three candidates")
        if not self.evidence_coverage or not all(self.evidence_coverage.values()):
            raise ValueError("candidate snapshot evidence is incomplete")
        forbidden = {
            "future_turn_content",
            "future_reuse_outcome",
            "future_victim_set_label",
            "oracle_future_use",
        }
        if any(
            forbidden & set(features)
            for features in self.candidate_features_by_algorithm.values()
        ):
            raise ValueError("candidate snapshot contains forbidden future information")

    @property
    def sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: str
    snapshot_sha256: str
    selected_candidate_id: str
    scores: Mapping[str, float]
    ordered_candidate_ids: tuple[str, ...]
    simulated_native_victim_block_ids: tuple[int, ...]
    branch: str
    fell_back: bool
    fallback_reason: str | None

    def __post_init__(self) -> None:
        if self.candidate_id not in CANDIDATE_IDS:
            raise ValueError("unknown Cost-Aware candidate identity")
        if _SHA256.fullmatch(self.snapshot_sha256) is None:
            raise ValueError("candidate decision snapshot hash is invalid")
        if not self.branch:
            raise ValueError("candidate decision branch must be explicit")
        if self.fell_back != (self.fallback_reason is not None):
            raise ValueError("candidate fallback reason is inconsistent")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in self.scores.values()
        ):
            raise ValueError("candidate decision scores must be finite")


class CandidateAlgorithmAdapter(Protocol):
    candidate_id: str
    correctness_gate_status: str

    def evaluate(self, snapshot: CandidateDecisionSnapshot) -> CandidateDecision: ...


def evaluate_candidate_family(
    *,
    snapshot: CandidateDecisionSnapshot,
    adapters: Sequence[CandidateAlgorithmAdapter],
) -> dict[str, object]:
    """Evaluate A1/A3/DVA on exactly one immutable decision snapshot."""

    by_id = {adapter.candidate_id: adapter for adapter in adapters}
    if len(by_id) != len(adapters) or tuple(by_id) != CANDIDATE_IDS:
        raise ValueError("candidate adapters must be exact ordered A1/A3/DVA")
    if by_id["DVA_ER_V1"].correctness_gate_status != "PASS":
        raise ValueError("DVA-ER CPU correctness gate has not passed")
    decisions: dict[str, CandidateDecision] = {}
    for candidate_id in CANDIDATE_IDS:
        decision = by_id[candidate_id].evaluate(snapshot)
        if decision.candidate_id != candidate_id:
            raise ValueError("candidate adapter changed its identity")
        if decision.snapshot_sha256 != snapshot.sha256:
            raise ValueError("candidate decision used a different snapshot")
        if set(decision.scores) != set(snapshot.legal_candidate_ids):
            raise ValueError("candidate decision score set differs from legal candidates")
        if (
            len(decision.ordered_candidate_ids) != len(snapshot.legal_candidate_ids)
            or set(decision.ordered_candidate_ids) != set(snapshot.legal_candidate_ids)
        ):
            raise ValueError("candidate ranking differs from the legal candidate set")
        ordered_scores = [
            float(decision.scores[row]) for row in decision.ordered_candidate_ids
        ]
        if any(
            left_score > right_score
            for left_score, right_score in pairwise(ordered_scores)
        ):
            raise ValueError("candidate ranking is inconsistent with its scores")
        if decision.selected_candidate_id != decision.ordered_candidate_ids[0]:
            raise ValueError("candidate selection differs from its frozen ranking")
        if len(set(decision.simulated_native_victim_block_ids)) != len(
            decision.simulated_native_victim_block_ids
        ):
            raise ValueError("simulated Native victim sequence contains duplicates")
        decisions[candidate_id] = decision
    pairs = (("A1_ORIGINAL", "A3_SUFFIX"), ("A1_ORIGINAL", "DVA_ER_V1"), ("A3_SUFFIX", "DVA_ER_V1"))
    payload = {
        "schema_version": "phase5.candidate_family_evaluation.v1",
        "status": "PASS",
        "decision_id": snapshot.decision_id,
        "snapshot_sha256": snapshot.sha256,
        "legal_candidate_count": len(snapshot.legal_candidate_ids),
        "multi_candidate": len(snapshot.legal_candidate_ids) >= 2,
        "decisions": {
            candidate_id: asdict(decisions[candidate_id])
            for candidate_id in CANDIDATE_IDS
        },
        "pairwise_selection_divergence": {
            f"{left}_vs_{right}": (
                decisions[left].selected_candidate_id
                != decisions[right].selected_candidate_id
            )
            for left, right in pairs
        },
        "pairwise_victim_set_divergence": {
            f"{left}_vs_{right}": (
                decisions[left].simulated_native_victim_block_ids
                != decisions[right].simulated_native_victim_block_ids
            )
            for left, right in pairs
        },
        "algorithmic_benefit_claim": "NOT_ESTABLISHED",
    }
    return {**payload, "evaluation_sha256": canonical_sha256(payload)}
