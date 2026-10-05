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
    ABLATION_PAIRS,
    AblationRow,
    BaselineReproduction,
    BehaviourBreakdown,
    DegeneracyAuditRow,
    DenominatorDiagnosticRow,
    RuleAggregate,
    RuleDecisionOutcome,
    RuleEvaluation,
    ablation_table,
    behaviour_breakdown,
    denominator_diagnostic,
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
    "ABLATION_PAIRS",
    "CANDIDATE_RULES",
    "DECISION_TIME_FEATURES",
    "FORBIDDEN_FEATURES",
    "AblationRow",
    "BaselineReproduction",
    "BehaviourBreakdown",
    "CandidateRule",
    "DegeneracyAuditRow",
    "DenominatorDiagnosticRow",
    "RuleAggregate",
    "RuleDecisionOutcome",
    "RuleEvaluation",
    "ablation_table",
    "behaviour_breakdown",
    "denominator_diagnostic",
    "evaluate_rules",
    "reproduce_executed_baseline",
    "rule_by_id",
]
