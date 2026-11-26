"""Pure simulation evaluation layer."""

from app.evaluation.evaluator import (
    compute_reliability_hash,
    evaluate_simulation,
)
from app.evaluation.explanations import build_explanation
from app.evaluation.models import (
    EntityMetrics,
    EvaluationConfig,
    EvaluationResult,
    EvaluationTargets,
    EvaluationWarning,
    NodeMetrics,
    OverallMetrics,
    PerEntityNodeMetrics,
    TargetResult,
)

__all__ = [
    "EntityMetrics",
    "EvaluationConfig",
    "EvaluationResult",
    "EvaluationTargets",
    "EvaluationWarning",
    "NodeMetrics",
    "OverallMetrics",
    "PerEntityNodeMetrics",
    "TargetResult",
    "build_explanation",
    "compute_reliability_hash",
    "evaluate_simulation",
]
