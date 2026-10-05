"""Decision-time-only candidate ranking rules for the M4 offline study.

Every rule reads only fields that exist at the forced-release decision
boundary. Rules express *release priority*: a candidate whose key sorts first
is released first, so a smaller key means "cheaper to sacrifice".

Authority and boundaries:

- ``docs/phase2a-m4-method-design-input.md`` section 4 defines the online
  information boundary and forbids future-derived inputs.
- ``docs/phase2a-m4-method-design-input.md`` section 8 defines the M0-M3 rule
  families this module implements.
- The allowed field set is enforced below; nothing outside
  :data:`DECISION_TIME_FEATURES` may be read by a rule.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kvopt.profiling.datasets import DecisionCandidateRow

#: Fields a rule may read. These are exactly the decision-time facts persisted
#: by ``FORCED_RELEASE_DECISION`` on the candidate rows.
DECISION_TIME_FEATURES = (
    "block_count",
    "initially_reclaimable_block_count",
    "decision_native_lru_position",
    "retention_deadline_timestamp",
    "elapsed_since_ttl_decision_seconds",
    "prefill_reload_seconds",
    "eta",
    "queue_delay_t_seconds",
    "waiting_followup",
    "next_tool_type",
)

#: Fields that must never enter an online rule. Mirrors the forbidden list in
#: ``docs/phase2a-m4-method-design-input.md`` section 4.
FORBIDDEN_FEATURES = (
    "returned_after_decision",
    "observed_time_to_return_seconds",
    "planned_time_to_return_seconds",
    "physical_eviction_count",
    "observed_recomputed_tokens",
    "serving_impact",
    "hindsight_best_candidate",
    "absolute_regret",
    "normalized_regret",
)

_UNKNOWN_LRU_POSITION = 2**31 - 1


def _identity(candidate: DecisionCandidateRow) -> tuple[str, str]:
    """Deterministic tie-break, matching the canonical regret ordering."""
    return (candidate.program_id, candidate.prefix_id)


def _lru_position(candidate: DecisionCandidateRow) -> int:
    position = candidate.decision_native_lru_position
    return _UNKNOWN_LRU_POSITION if position is None else int(position)


def _min_max_normalizer(
    field: str,
) -> Callable[[Sequence[DecisionCandidateRow], DecisionCandidateRow], float]:
    def normalize(
        candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
    ) -> float:
        values = [float(getattr(item, field)) for item in candidates]
        low = min(values)
        high = max(values)
        if high <= low:
            return 0.0
        return (float(getattr(candidate, field)) - low) / (high - low)

    return normalize


@dataclass(frozen=True, slots=True)
class CandidateRule:
    """One interpretable, hand-auditable release-priority rule."""

    rule_id: str
    family: str
    description: str
    features: tuple[str, ...]
    key: Callable[[Sequence[DecisionCandidateRow], DecisionCandidateRow], tuple[object, ...]]

    def __post_init__(self) -> None:
        if not self.rule_id or not self.rule_id.strip():
            raise ValueError("rule_id must be non-empty")
        if not self.description.strip():
            raise ValueError("description must be non-empty")
        forbidden = sorted(set(self.features).intersection(FORBIDDEN_FEATURES))
        if forbidden:
            raise ValueError(f"rule reads forbidden future-derived features: {forbidden}")
        unknown = sorted(set(self.features) - set(DECISION_TIME_FEATURES))
        if unknown:
            raise ValueError(f"rule reads undeclared features: {unknown}")

    def order(
        self, candidates: Sequence[DecisionCandidateRow]
    ) -> tuple[DecisionCandidateRow, ...]:
        """Return candidates in release order; the first one is released first."""
        if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
            raise TypeError("candidates must be an ordered sequence")
        materialized = tuple(candidates)
        if not materialized:
            return ()
        return tuple(
            sorted(
                materialized,
                key=lambda candidate: (
                    self.key(materialized, candidate),
                    _identity(candidate),
                ),
            )
        )

    def selection(
        self, candidates: Sequence[DecisionCandidateRow], count: int
    ) -> tuple[tuple[str, str], ...]:
        """Return the identities this rule would release for ``count`` slots."""
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("count must be int")
        if count < 0:
            raise ValueError("count must be non-negative")
        ordered = self.order(candidates)
        return tuple(_identity(candidate) for candidate in ordered[:count])


def _p1b_deadline_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    """Frozen Phase 1B ordering: earliest deadline, then native LRU position."""
    del candidates
    return (candidate.retention_deadline_timestamp, _lru_position(candidate))


def _prefill_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    del candidates
    return (candidate.prefill_reload_seconds,)


def _block_count_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    del candidates
    return (candidate.block_count,)


def _reclaimable_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    del candidates
    return (candidate.initially_reclaimable_block_count,)


def _marginal_cost_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    """Re-test the previously rejected per-reclaimable-block cost ratio.

    ``docs/phase2a-m4-method-design-input.md`` section 10 requires this
    degeneracy to be audited rather than assumed away.
    """
    del candidates
    denominator = max(candidate.initially_reclaimable_block_count, 1)
    return (candidate.prefill_reload_seconds / denominator,)


def _non_code_first_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    del candidates
    return (1 if candidate.next_tool_type == "code" else 0,)


def _non_code_then_small_prefill_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    del candidates
    return (
        1 if candidate.next_tool_type == "code" else 0,
        candidate.prefill_reload_seconds,
    )


def _size_score_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    """Normalized additive size/recompute cluster score, tool indicator excluded."""
    prefill = _min_max_normalizer("prefill_reload_seconds")(candidates, candidate)
    blocks = _min_max_normalizer("block_count")(candidates, candidate)
    reclaimable = _min_max_normalizer("initially_reclaimable_block_count")(
        candidates, candidate
    )
    return ((prefill + blocks + reclaimable) / 3.0,)


def _non_code_then_size_score_key(
    candidates: Sequence[DecisionCandidateRow], candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    """Lexicographic tool indicator first, then the normalized size score."""
    return (
        1 if candidate.next_tool_type == "code" else 0,
        _size_score_key(candidates, candidate),
    )


CANDIDATE_RULES: tuple[CandidateRule, ...] = (
    CandidateRule(
        rule_id="M0_p1b_executed_ordering",
        family="M0",
        description=(
            "Frozen Phase 1B ordering: earliest retention deadline, then native "
            "LRU position, then stable identity. Re-derived here so the "
            "evaluator can be checked against the canonical executed result."
        ),
        features=(
            "retention_deadline_timestamp",
            "decision_native_lru_position",
        ),
        key=_p1b_deadline_key,
    ),
    CandidateRule(
        rule_id="M1_prefill_reload_ascending",
        family="M1",
        description="Release the cheapest-to-recompute candidate first.",
        features=("prefill_reload_seconds",),
        key=_prefill_key,
    ),
    CandidateRule(
        rule_id="M1_block_count_ascending",
        family="M1",
        description="Release the smallest footprint candidate first.",
        features=("block_count",),
        key=_block_count_key,
    ),
    CandidateRule(
        rule_id="M1_reclaimable_ascending",
        family="M1",
        description="Release the candidate freeing the fewest blocks first.",
        features=("initially_reclaimable_block_count",),
        key=_reclaimable_key,
    ),
    CandidateRule(
        rule_id="M1_marginal_cost_per_reclaimable",
        family="M1",
        description=(
            "Re-test of the previously rejected per-reclaimable-block cost "
            "ratio. Required degeneracy audit, not a candidate method."
        ),
        features=("prefill_reload_seconds", "initially_reclaimable_block_count"),
        key=_marginal_cost_key,
    ),
    CandidateRule(
        rule_id="M2_non_code_first",
        family="M2",
        description=(
            "Use only the supported lifecycle-semantic indicator: release "
            "non-code candidates before code candidates."
        ),
        features=("next_tool_type",),
        key=_non_code_first_key,
    ),
    CandidateRule(
        rule_id="M3_non_code_then_small_prefill",
        family="M3",
        description=(
            "Lexicographic: non-code candidates first, then ascending "
            "recomputation cost."
        ),
        features=("next_tool_type", "prefill_reload_seconds"),
        key=_non_code_then_small_prefill_key,
    ),
    CandidateRule(
        rule_id="M3_size_score_only",
        family="M3",
        description=(
            "Normalized additive score over the size/recompute cluster only, "
            "with the tool indicator excluded. Ablation partner of "
            "M3_non_code_then_size_score."
        ),
        features=(
            "prefill_reload_seconds",
            "block_count",
            "initially_reclaimable_block_count",
        ),
        key=_size_score_key,
    ),
    CandidateRule(
        rule_id="M3_non_code_then_size_score",
        family="M3",
        description=(
            "Lexicographic: non-code candidates first, then the normalized "
            "additive size/recompute score."
        ),
        features=(
            "next_tool_type",
            "prefill_reload_seconds",
            "block_count",
            "initially_reclaimable_block_count",
        ),
        key=_non_code_then_size_score_key,
    ),
)

_RULES_BY_ID = {rule.rule_id: rule for rule in CANDIDATE_RULES}


def rule_by_id(rule_id: str) -> CandidateRule:
    """Look up a registered rule by identifier."""
    try:
        return _RULES_BY_ID[rule_id]
    except KeyError as error:
        known = ", ".join(sorted(_RULES_BY_ID))
        raise KeyError(f"unknown rule_id {rule_id!r}; known rules: {known}") from error
