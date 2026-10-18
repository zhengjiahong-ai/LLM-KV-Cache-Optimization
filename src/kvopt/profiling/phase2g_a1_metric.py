"""Frozen token-metric semantics for the Phase 2G A1 Gate 2 evaluation.

Why this module exists
----------------------
The Gate 2 evaluator computed ``recomputed_tokens`` as ``N - C`` and then reported
that same sum under two different names: ``aggregate_recomputed_tokens`` and
``aggregate_actual_prefill_tokens``. Per the frozen Level-B semantics those are
**different** quantities:

```text
N  native_prompt_tokens
E  eligible_prefix_tokens      (derived from hash provenance, arm-invariant)
C  native_cached_prefix_tokens (observed cache occupancy, arm-dependent)

W  actual_prefill_tokens = N - C
R  observed_recomputed    = E - C          <- the frozen recomputation metric
S  new_suffix_tokens      = N - E
invariant: W = R + S                       (enforced by derive_level_b_token_semantics)
```

So the old code labelled ``W`` as ``R`` and never computed ``R`` at all.

Does that invalidate the paired comparison? Not by itself. The paired delta obeys

```text
W = R + S   =>   ΔW = ΔR + ΔS   (Δ = A1 - A0, per matched request)
```

so ``ΔW = ΔR`` exactly when ``ΔS = 0``, i.e. when every request has the same
``(N, E)`` in both arms. ``E`` is derived from the request's own block hashes
against prior recorded hashes and is capped by ``(N - 1) // block_size``, so it is
arm-invariant *provided both arms observe the same, equally complete request set*.
That condition is exactly what request completeness has to establish, which is why
this module reports it separately instead of assuming it.

This module therefore does three things:

1. derives every quantity through the frozen
   :func:`~kvopt.profiling.runtime_evidence.derive_level_b_token_semantics`, so
   nothing is re-derived locally;
2. reports ``ΔW`` and ``ΔR`` side by side, with the measured ``ΔS``;
3. states explicitly whether the two deltas coincide, rather than picking one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .runtime_evidence import RawRunArtifacts, build_request_runtime_evidence_table

#: Evidence levels a pairing may reach. Kept as strings so they serialise directly.
PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class RequestTokenFacts:
    """One request's token facts, all four derived from the frozen semantics."""

    request_id: str
    program_id: str
    prompt_tokens: int
    eligible_prefix_tokens: int
    cached_prefix_tokens: int
    actual_prefill_tokens: int
    recomputed_tokens: int
    new_suffix_tokens: int


@dataclass(frozen=True, slots=True)
class ArmTokenTotals:
    """Summed token facts for one arm, over the same request population."""

    request_count: int
    actual_prefill_tokens: int
    recomputed_tokens: int
    new_suffix_tokens: int


@dataclass(frozen=True, slots=True)
class PairMetricVerdict:
    """Both candidate metrics plus the measured reason they may or may not agree."""

    #: Per-request agreement of ``(N, E)`` between arms, i.e. ``ΔS = 0`` everywhere.
    new_suffix_identical: bool
    #: Request ids present in exactly one arm.
    unpaired_request_ids: tuple[str, ...]
    #: ``Δ`` of the frozen recomputation metric.
    delta_recomputed_tokens: int
    #: ``Δ`` of actual prefill, which is what Gate 2 previously reported.
    delta_actual_prefill_tokens: int
    #: ``Δ`` of the new suffix; zero when the two deltas coincide.
    delta_new_suffix_tokens: int
    #: How the two deltas relate, stated rather than assumed.
    equivalence: str
    #: Why the equivalence verdict came out as it did.
    reason: str

    @property
    def deltas_coincide(self) -> bool:
        return self.delta_recomputed_tokens == self.delta_actual_prefill_tokens


def request_token_facts(
    runs: Iterable[RawRunArtifacts],
) -> dict[str, RequestTokenFacts]:
    """Frozen token facts per request id.

    Raises whatever the frozen derivation raises on a Level-B invariant violation,
    so a malformed run fails closed instead of contributing a partial total.
    """
    facts: dict[str, RequestTokenFacts] = {}
    for row in build_request_runtime_evidence_table(runs):
        if row.observed_recomputed_tokens is None:
            # No usable prefix provenance: refuse to guess, and let the caller
            # classify the run rather than silently dropping the request.
            raise ValueError(
                f"request {row.request_id} has no frozen recomputation metric "
                f"(availability={row.availability}, "
                f"reason={row.unavailable_reason})"
            )
        facts[row.request_id] = RequestTokenFacts(
            request_id=row.request_id,
            program_id=row.program_id,
            prompt_tokens=int(row.native_prompt_tokens or 0),
            eligible_prefix_tokens=int(row.eligible_prefix_tokens or 0),
            cached_prefix_tokens=int(row.native_cached_prefix_tokens or 0),
            actual_prefill_tokens=int(row.actual_prefill_tokens or 0),
            recomputed_tokens=int(row.observed_recomputed_tokens),
            new_suffix_tokens=(
                int(row.native_prompt_tokens or 0) - int(row.eligible_prefix_tokens or 0)
            ),
        )
    return facts


def totals(
    facts: dict[str, RequestTokenFacts], request_ids: Sequence[str]
) -> ArmTokenTotals:
    """Sum a named request population, so both arms use the same denominator."""
    selected = [facts[request_id] for request_id in request_ids]
    return ArmTokenTotals(
        request_count=len(selected),
        actual_prefill_tokens=sum(row.actual_prefill_tokens for row in selected),
        recomputed_tokens=sum(row.recomputed_tokens for row in selected),
        new_suffix_tokens=sum(row.new_suffix_tokens for row in selected),
    )


def pair_verdict(
    a0: dict[str, RequestTokenFacts],
    a1: dict[str, RequestTokenFacts],
    request_ids: Sequence[str],
) -> PairMetricVerdict:
    """Compare the two candidate metrics on one request population.

    Reports the frozen recomputation delta and the actual-prefill delta together
    with the measured new-suffix delta, and classifies their relationship. No
    choice between the two is made here: the caller reports both, and the
    equivalence verdict says whether reporting only one would have been wrong.
    """
    unpaired = tuple(
        sorted(
            {rid for rid in request_ids if rid not in a0}
            | {rid for rid in request_ids if rid not in a1}
        )
    )
    paired = [rid for rid in request_ids if rid in a0 and rid in a1]
    new_suffix_identical = all(
        a0[rid].new_suffix_tokens == a1[rid].new_suffix_tokens for rid in paired
    )

    t0 = totals(a0, paired)
    t1 = totals(a1, paired)
    delta_r = t1.recomputed_tokens - t0.recomputed_tokens
    delta_w = t1.actual_prefill_tokens - t0.actual_prefill_tokens
    delta_s = t1.new_suffix_tokens - t0.new_suffix_tokens

    if unpaired:
        equivalence = "NOT_COMPUTABLE"
        reason = (
            f"{len(unpaired)} request(s) observed in only one arm; "
            "a paired delta over different populations is not a pairing"
        )
    elif not new_suffix_identical:
        equivalence = "NOT_EQUIVALENT"
        reason = (
            "per-request new-suffix tokens differ between arms, so "
            "delta(actual_prefill) differs from delta(recomputed); "
            "the two metrics give different answers and both must be reported"
        )
    else:
        equivalence = "EXACT"
        reason = (
            "every paired request has identical (N, E), so delta(new_suffix) = 0 "
            "and delta(actual_prefill) = delta(recomputed) exactly"
        )

    # The identity must hold arithmetically whenever the populations are paired.
    if not unpaired and delta_w != delta_r + delta_s:
        raise AssertionError(
            "token identity violated: "
            f"delta_actual_prefill={delta_w} != "
            f"delta_recomputed({delta_r}) + delta_new_suffix({delta_s})"
        )

    return PairMetricVerdict(
        new_suffix_identical=new_suffix_identical,
        unpaired_request_ids=unpaired,
        delta_recomputed_tokens=delta_r,
        delta_actual_prefill_tokens=delta_w,
        delta_new_suffix_tokens=delta_s,
        equivalence=equivalence,
        reason=reason,
    )
