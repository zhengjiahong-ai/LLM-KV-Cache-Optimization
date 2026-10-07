"""Frozen preregistration records for H1 hypotheses.

A preregistration is data, not prose, so that the frozen form can be committed,
quoted in a report, and checked by code. Each record states the exact ordering,
direction, tie-break, fallback, applicability boundary and primary metric that
were fixed **before** the final holdout existed.

Authority: M1 ruling 2026-10-07, items 3 and 4. The reverse-deadline ordering was
approved as a *post-hoc discovery hypothesis* that ``可以正式进入 H1`` but
``目前只能叫 POST-HOC DISCOVERY HYPOTHESIS，不能叫结果``, because it was found on
the canonical campaign that already existed.

Nothing here evaluates a rule or reads a label.
"""

from __future__ import annotations

from .acceptance import (
    PRIMARY_METRIC_PROXY_LOSS,
    RulePreregistration,
)
from .rules import H1_R1_REVERSE_DEADLINE_ID

#: The commit this preregistration was frozen against. A record whose anchor
#: does not match the reviewed commit is not the frozen record.
H1_FREEZE_DATE = "2026-10-07"

#: H1-R1: reverse retention-deadline ordering.
#:
#: Formula     release the candidate with the LARGEST
#:             ``retention_deadline_timestamp`` first -- the exact negation of
#:             the frozen Phase 1B primary key.
#: Tie-break   stable logical identity ``(program_id, prefix_id)``, applied by
#:             the standard rule ladder. NOTE: untested on the discovery data,
#:             where deadlines are tied in 0 of 60 decisions.
#: Fallback    the frozen baseline ordering, never a fabricated value.
H1_R1_PREREGISTRATION = RulePreregistration(
    rule_id=H1_R1_REVERSE_DEADLINE_ID,
    family="H1",
    formula=(
        "release the candidate with the LARGEST retention_deadline_timestamp "
        "first: descending on retention_deadline_timestamp, equivalently "
        "negating the frozen Phase 1B primary key"
    ),
    direction="descending on retention_deadline_timestamp",
    tie_break=(
        "stable logical identity (program_id, prefix_id) applied by the rule "
        "ladder as the final deterministic step; the deadline itself provides "
        "no tie-break because it is tied in 0 of 60 discovery decisions"
    ),
    fallback=(
        "if retention_deadline_timestamp is unavailable for any candidate in "
        "the decision, use the frozen baseline ordering; never fabricate a "
        "value (see docs/phase2a-m4-missingness-semantics.md)"
    ),
    boundary=(
        "forced-release candidate sets of two or more logical retention entries "
        "only, under the frozen TTL estimator. This is a DERIVED signal: "
        "retention_deadline_timestamp = decision_timestamp + ttl_seconds and "
        "ttl_seconds is the output of the frozen estimator, so the rule inverts "
        "the baseline's own keep decision rather than reading an independent "
        "observation. It does not apply if the TTL estimator, its history "
        "thresholds, or its inputs change; any such change requires the rule to "
        "be re-derived and re-preregistered. It was discovered on the canonical "
        "campaign, so that campaign can never serve as its holdout."
    ),
    primary_metric=PRIMARY_METRIC_PROXY_LOSS,
    frozen_at=H1_FREEZE_DATE,
    frozen_commit="72c462b",
)

#: Every frozen H1 preregistration, keyed by rule id.
PREREGISTRATIONS: dict[str, RulePreregistration] = {
    H1_R1_PREREGISTRATION.rule_id: H1_R1_PREREGISTRATION,
}


def preregistration_for(rule_id: str) -> RulePreregistration:
    """Look up a frozen preregistration, refusing an unregistered hypothesis."""
    try:
        return PREREGISTRATIONS[rule_id]
    except KeyError as error:
        known = ", ".join(sorted(PREREGISTRATIONS))
        raise KeyError(
            f"no frozen preregistration for {rule_id!r}; registered: {known}"
        ) from error
