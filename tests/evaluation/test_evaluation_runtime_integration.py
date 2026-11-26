from __future__ import annotations

from app.evaluation.evaluator import evaluate_simulation
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from tests.helpers import (
    document_from_spec,
    failure_process_dict,
    reliability_document_from_process,
    spec_from,
)


def test_evaluation_accepts_a_real_runtime_result() -> None:
    process = document_from_spec(spec_from(failure_process_dict()))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "inspect", "participates": True, "lambda": 0.5},
            {"node_id": "repair", "participates": False},
        ],
    )
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(
            entity_count=20, simulation_end=10, random_seed=2026
        ),
    )
    evaluation = evaluate_simulation(process, reliability, result)
    assert evaluation.sample_size == 20
    assert evaluation.process_binding.content_hash == process.content_hash
    assert evaluation.reliability_binding.reliability_id == reliability.reliability_id
    assert evaluation.overall.overall_reliability == (
        1
        - evaluation.overall.ever_failed_entity_count
        / evaluation.overall.entity_count
    )
    node = next(item for item in evaluation.nodes if item.node_id == "inspect")
    assert node.sample_count == len(
        [
            sample
            for sample in result.reliability_samples
            if sample.node_id == "inspect"
        ]
    )
    assert node.failure_count == len(
        [
            sample
            for sample in result.reliability_samples
            if sample.node_id == "inspect" and sample.failure_occurred
        ]
    )
    assert node.mean_entity_theoretical_reliability is not None
    assert node.joint_theoretical_no_failure_probability is not None
    assert not {
        "process_binding_mismatch",
        "reliability_binding_mismatch",
        "event_sequence_invalid",
    } & {warning.code for warning in evaluation.warnings}
