"""Orchestration between the simulation runtime and the evaluation layer.

This module does not implement simulation or evaluation algorithms. It only
connects the existing Runtime and Evaluation components.
"""

from __future__ import annotations

from app.domain.process_ir import ProcessDocument
from app.domain.reliability_ir import ReliabilityDocument
from app.evaluation.evaluator import evaluate_simulation
from app.evaluation.explanations import build_explanation
from app.evaluation.models import (
    EvaluationConfig,
    EvaluationResult,
    EvaluationTargets,
)
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from app.simulation.models import SimulationResult


def simulate_and_evaluate(
    process: ProcessDocument,
    reliability: ReliabilityDocument,
    simulation_config: SimulationConfig,
    *,
    evaluation_targets: EvaluationTargets | None = None,
    evaluation_config: EvaluationConfig | None = None,
) -> tuple[SimulationResult, EvaluationResult, str]:
    """Run a real simulation, evaluate it, and build the explanation text."""

    simulation_result = run_simulation(process, reliability, simulation_config)
    evaluation_result = evaluate_simulation(
        process,
        reliability,
        simulation_result,
        targets=evaluation_targets,
        evaluation_config=evaluation_config,
    )
    explanation = build_explanation(evaluation_result)
    return simulation_result, evaluation_result, explanation


__all__ = ["simulate_and_evaluate"]
