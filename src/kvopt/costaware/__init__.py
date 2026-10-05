"""M4 offline Cost-Aware method design for Phase 2A.

This package is *offline analysis only*. It ranks decision-time candidate
snapshots to study whether a simple rule can recover canonical proxy headroom.
It contains no runtime policy, no vLLM coupling, and no future-derived feature.

Authority:

- ``docs/phase2a-m4-method-design-input.md`` authorizes method design and
  offline evaluation, and explicitly does not yet authorize a final runtime
  implementation.
"""

from .offline_eval import (
    BaselineReproduction,
    DegeneracyAuditRow,
    RuleAggregate,
    RuleDecisionOutcome,
    RuleEvaluation,
    evaluate_rules,
    reproduce_executed_baseline,
)
from .rules import (
    CANDIDATE_RULES,
    DECISION_TIME_FEATURES,
    FORBIDDEN_FEATURES,
    CandidateRule,
    rule_by_id,
)

__all__ = [
    "CANDIDATE_RULES",
    "DECISION_TIME_FEATURES",
    "FORBIDDEN_FEATURES",
    "BaselineReproduction",
    "CandidateRule",
    "DegeneracyAuditRow",
    "RuleAggregate",
    "RuleDecisionOutcome",
    "RuleEvaluation",
    "evaluate_rules",
    "reproduce_executed_baseline",
    "rule_by_id",
]
