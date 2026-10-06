"""M4 offline Cost-Aware method design for Phase 2A.

This package is *offline analysis only*. It ranks decision-time candidate
snapshots to study whether a simple rule can recover canonical proxy headroom.
It contains no runtime policy, no vLLM coupling, and no future-derived feature.

Authority:

- ``docs/phase2a-m4-method-design-input.md`` authorizes method design and
  offline evaluation, and explicitly does not yet authorize a final runtime
  implementation.
"""

from .feasible_oracle import (
    MAX_EXACT_CANDIDATES,
    FeasibleOracleRow,
    PressureFeasibleRegretRow,
    build_feasible_oracle,
    pressure_feasible_regret,
)
from .offline_eval import (
    ABLATION_PAIRS,
    AblationRow,
    BehaviourBreakdown,
    DegeneracyAuditRow,
    DenominatorDiagnosticRow,
    PressureFeasibleAggregate,
    ReleaseBurdenRow,
    RuleAggregate,
    RuleDecisionOutcome,
    RuleEvaluation,
    ablation_table,
    behaviour_breakdown,
    denominator_diagnostic,
    evaluate_rules,
)
from .replay import (
    DecisionSnapshot,
    ExecutedP1BStrategy,
    QueueBlock,
    ReleaseStrategy,
    ReplayFidelity,
    ReplayOutcome,
    ReplayState,
    RuleStrategy,
    all_rule_strategies,
    candidate_key,
    load_decision_snapshots,
    replay_decision,
    validate_replay_fidelity,
)
from .rules import (
    CANDIDATE_RULES,
    DECISION_TIME_FEATURES,
    FORBIDDEN_FEATURES,
    CandidateRule,
    fallback_key,
    rule_by_id,
)

__all__ = [
    "ABLATION_PAIRS",
    "CANDIDATE_RULES",
    "DECISION_TIME_FEATURES",
    "FORBIDDEN_FEATURES",
    "MAX_EXACT_CANDIDATES",
    "AblationRow",
    "BehaviourBreakdown",
    "CandidateRule",
    "DecisionSnapshot",
    "DegeneracyAuditRow",
    "DenominatorDiagnosticRow",
    "ExecutedP1BStrategy",
    "FeasibleOracleRow",
    "PressureFeasibleAggregate",
    "PressureFeasibleRegretRow",
    "QueueBlock",
    "ReleaseBurdenRow",
    "ReleaseStrategy",
    "ReplayFidelity",
    "ReplayOutcome",
    "ReplayState",
    "RuleAggregate",
    "RuleDecisionOutcome",
    "RuleEvaluation",
    "RuleStrategy",
    "ablation_table",
    "all_rule_strategies",
    "behaviour_breakdown",
    "build_feasible_oracle",
    "candidate_key",
    "denominator_diagnostic",
    "evaluate_rules",
    "fallback_key",
    "load_decision_snapshots",
    "pressure_feasible_regret",
    "replay_decision",
    "rule_by_id",
    "validate_replay_fidelity",
]
