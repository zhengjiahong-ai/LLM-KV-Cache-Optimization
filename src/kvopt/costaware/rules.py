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
Fallback ladder (required by ``docs/phase2a-m4-method-design-input.md`` §13)
---------------------------------------------------------------------------

When a rule cannot separate two candidates, resolution follows a fixed,
documented ladder:

1. **Primary rule key.** The decision-time feature(s) the rule declares.
2. **Stable logical identity** ``(program_id, prefix_id)``. Always available and
   deterministic, so every rule induces a total order and no candidate is
   silently dropped or ordered by accident.
3. **For the frozen P1B rule only:** an unknown ``decision_native_lru_position``
   (``None``) sorts last. This is the conservative reading: an unknown position
   is treated as most-recently-used, therefore most expensive to release, so it
   is deferred rather than guessed at.

What the ladder explicitly does *not* do:

- it never falls back to LRU recency for a non-P1B rule. Doing so would
  silently transform every cost rule into the baseline it is being compared
  against, which would make the comparison meaningless;
- it never falls back to a future-derived label;
- it never falls back to input order, which would make results depend on how
  artifacts happened to be enumerated.

A useful consequence: the entry-level rules (M1/M2/M3) do not read
``decision_native_lru_position`` at all, so they are unaffected by that
capability being unsupported in the M6 signal analysis."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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

#: A rule key receives either the raw candidate sequence or the object returned
#: by :meth:`CandidateRule.prepare`.
RuleKeyContext = Sequence[DecisionCandidateRow] | Mapping[tuple[str, str], float]


def _identity(candidate: DecisionCandidateRow) -> tuple[str, str]:
    """Stable logical identity, used as the final deterministic tie-break."""
    return (candidate.program_id, candidate.prefix_id)


def fallback_key(candidate: DecisionCandidateRow) -> tuple[str, str]:
    """Public view of the ladder's step 2.

    Exposed so callers can reproduce the exact fallback the evaluator applies
    instead of re-deriving it.
    """
    if not isinstance(candidate, DecisionCandidateRow):
        raise TypeError("candidate must be DecisionCandidateRow")
    return _identity(candidate)


def _lru_position(candidate: DecisionCandidateRow) -> int:
    position = candidate.decision_native_lru_position
    return _UNKNOWN_LRU_POSITION if position is None else int(position)


def _prepare_size_score(
    candidates: Sequence[DecisionCandidateRow],
) -> Mapping[tuple[str, str], float]:
    """Precompute the normalized size score once per decision, in O(n).

    Two things would silently make a decision quadratic here, and both are
    avoided deliberately:

    - computing the normalization inside the sort key, which rescan every
      candidate per comparison;
    - recomputing each field's min/max per candidate inside the preparation,
      which rescans the group once per field per candidate.

    Both bounds are pinned by
    ``test_size_score_prepare_does_not_rescan_per_candidate``.
    """
    fields = (
        "prefill_reload_seconds",
        "block_count",
        "initially_reclaimable_block_count",
    )
    # One pass per field, not one pass per field per candidate.
    bounds: dict[str, tuple[float, float]] = {}
    for field in fields:
        values = [float(getattr(candidate, field)) for candidate in candidates]
        bounds[field] = (min(values), max(values))

    scores: dict[tuple[str, str], float] = {}
    for candidate in candidates:
        total = 0.0
        for field in fields:
            low, high = bounds[field]
            value = float(getattr(candidate, field))
            total += 0.0 if high <= low else (value - low) / (high - low)
        scores[_identity(candidate)] = total / len(fields)
    return scores


@dataclass(frozen=True, slots=True)
class CandidateRule:
    """One interpretable, hand-auditable release-priority rule."""

    rule_id: str
    family: str
    description: str
    features: tuple[str, ...]
    key: Callable[[RuleKeyContext, DecisionCandidateRow], tuple[object, ...]]
    prepare: Callable[[Sequence[DecisionCandidateRow]], RuleKeyContext] | None = None

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
        if self.prepare is not None and not callable(self.prepare):
            raise TypeError("prepare must be callable or None")

    def order(
        self, candidates: Sequence[DecisionCandidateRow]
    ) -> tuple[DecisionCandidateRow, ...]:
        """Return candidates in release order; the first one is released first.

        Applied ladder: primary key, then stable identity. See the module
        docstring for the full fallback contract.
        """
        if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
            raise TypeError("candidates must be an ordered sequence")
        materialized = tuple(candidates)
        if not materialized:
            return ()
        context: RuleKeyContext = (
            materialized if self.prepare is None else self.prepare(materialized)
        )
        return tuple(
            sorted(
                materialized,
                key=lambda candidate: (
                    self.key(context, candidate),
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
def _size_score_key(
    context: RuleKeyContext, candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    """Read the precomputed normalized size score from the prepared context."""
    if not isinstance(context, Mapping):
        raise TypeError("size score rule requires its prepared context")
    return (context[_identity(candidate)],)


def _non_code_then_size_score_key(
    context: RuleKeyContext, candidate: DecisionCandidateRow
) -> tuple[object, ...]:
    """Lexicographic tool indicator first, then the normalized size score."""
    return (
        1 if candidate.next_tool_type == "code" else 0,
        _size_score_key(context, candidate),
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
        prepare=_prepare_size_score,
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
        prepare=_prepare_size_score,
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
