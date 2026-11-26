from __future__ import annotations

import math

from app.evaluation.evaluator import evaluate_simulation
from app.evaluation.models import EvaluationConfig
from tests.evaluation.helpers import (
    STATUS_CATALOG,
    completed_entity,
    entity,
    ev,
    failed_repaired_entity,
    make_process,
    make_reliability,
    make_result,
    partial_entity,
    sample,
)
from tests.helpers import document_from_spec, reliability_document_from_process, spec_from


def _node(evaluation, node_id: str = "work"):
    return next(item for item in evaluation.nodes if item.node_id == node_id)


def test_hundred_devices_exact_theoretical_values() -> None:
    process = make_process(
        status_catalog=STATUS_CATALOG, status_on_enter="operational"
    )
    reliability = make_reliability(process, lam=0.1)
    entities = [
        completed_entity(f"e{index}", seq_base=index * 10)
        for index in range(100)
    ]
    samples = [
        sample(f"e{index}", lam=0.1, exposure=1.0) for index in range(100)
    ]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, entities, samples),
    )
    node = _node(evaluation)
    assert node.lambda_per_day == 0.1
    assert node.visit_count == 100
    assert node.sample_count == 100
    assert node.unique_exposed_entity_count == 100
    assert node.total_reliability_exposure_time == 100.0
    assert node.total_actual_elapsed_time == 100.0
    assert node.actual_elapsed_complete is True
    assert node.empirical_failure_frequency == 0.0
    assert math.isclose(
        node.mean_entity_theoretical_reliability,
        math.exp(-0.1),
        rel_tol=1e-12,
    )
    assert math.isclose(
        node.joint_theoretical_no_failure_probability,
        math.exp(-10),
        rel_tol=1e-12,
    )
    assert node.joint_theoretical_no_failure_probability < 0.0001
    assert node.node_is_small_sample is False


def test_different_device_exposures_use_average_and_joint_formulas() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    entity_one = completed_entity("e1", seq_base=0, duration=1.0)
    entity_two = completed_entity("e2", seq_base=20, duration=2.0)
    samples = [
        sample("e1", lam=0.1, exposure=1.0),
        sample("e2", lam=0.1, exposure=2.0),
    ]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [entity_one, entity_two], samples),
    )
    node = _node(evaluation)
    expected_mean = (math.exp(-0.1) + math.exp(-0.2)) / 2
    assert math.isclose(
        node.mean_entity_theoretical_reliability,
        expected_mean,
        rel_tol=1e-12,
    )
    assert math.isclose(
        node.joint_theoretical_no_failure_probability,
        math.exp(-0.3),
        rel_tol=1e-12,
    )
    assert node.total_reliability_exposure_time == 3.0
    assert node.unique_exposed_entity_count == 2


def test_repeated_visits_accumulate_exposure_before_reliability() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    repeated = entity(
        "e1",
        final_node_id="work",
        status="operational",
        completed=False,
        node_visits={"start": 1, "work": 2},
        node_elapsed_time=0.5,
        history=[
            ev(0, 0, "node_entered", "e1", "start"),
            ev(1, 0, "node_completed", "e1", "start", {"elapsed": 0}),
            ev(2, 0, "node_entered", "e1", "work"),
            ev(3, 1, "reliability_sample", "e1", "work", {"exposure_time": 1.0, "failure_occurred": False}),
            ev(4, 1, "node_completed", "e1", "work", {"elapsed": 1.0}),
            ev(5, 1, "node_entered", "e1", "work"),
            ev(6, 1.5, "reliability_sample", "e1", "work", {"exposure_time": 0.5, "failure_occurred": False, "partial": True}),
        ],
    )
    samples = [
        sample("e1", lam=0.1, exposure=1.0),
        sample("e1", lam=0.1, exposure=0.5, partial=True, time=1.5),
    ]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [repeated], samples),
        evaluation_config=EvaluationConfig(small_sample_threshold=30),
    )
    node = _node(evaluation)
    assert node.visit_count == 2
    assert node.sample_count == 2
    assert node.unique_exposed_entity_count == 1
    assert node.total_reliability_exposure_time == 1.5
    assert node.total_actual_elapsed_time == 1.5
    assert math.isclose(
        node.mean_entity_theoretical_reliability,
        math.exp(-0.15),
        rel_tol=1e-12,
    )
    assert math.isclose(
        node.joint_theoretical_no_failure_probability,
        math.exp(-0.15),
        rel_tol=1e-12,
    )
    assert node.node_is_small_sample is True
    assert node.per_entity_metrics[0].sample_count == 2
    assert node.per_entity_metrics[0].visit_count == 2


def test_partially_exposed_entities_exclude_zero_exposure_from_mean() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    entity_one = completed_entity("e1", seq_base=0)
    entity_two = completed_entity("e2", seq_base=20)
    entity_three = entity(
        "e3",
        status="operational",
        node_visits={"start": 1, "end": 1},
        history=[
            ev(40, 0, "node_entered", "e3", "start"),
            ev(41, 0, "node_completed", "e3", "start", {"elapsed": 0}),
            ev(42, 0, "node_entered", "e3", "end"),
            ev(43, 0, "node_completed", "e3", "end", {"elapsed": 0}),
        ],
    )
    samples = [
        sample("e1", lam=0.1, exposure=1.0),
        sample("e2", lam=0.1, exposure=1.0),
    ]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(
            process,
            reliability,
            [entity_one, entity_two, entity_three],
            samples,
        ),
    )
    node = _node(evaluation)
    assert node.sample_count == 2
    assert node.unique_exposed_entity_count == 2
    assert node.visit_count == 2
    assert math.isclose(
        node.mean_entity_theoretical_reliability,
        math.exp(-0.1),
        rel_tol=1e-12,
    )
    assert math.isclose(
        node.joint_theoretical_no_failure_probability,
        math.exp(-0.2),
        rel_tol=1e-12,
    )
    assert "no_valid_exposure" not in {warning.code for warning in evaluation.warnings}


def test_zero_exposure_node_reports_na_and_warning() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    entity_one = completed_entity("e1", seq_base=0)
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [entity_one], []),
    )
    node = _node(evaluation)
    assert node.total_reliability_exposure_time == 0.0
    assert node.sample_count == 0
    assert node.unique_exposed_entity_count == 0
    assert node.mean_entity_theoretical_reliability is None
    assert node.joint_theoretical_no_failure_probability is None
    assert node.empirical_failure_frequency is None
    assert node.node_is_small_sample is False
    assert "no_valid_exposure" in {warning.code for warning in evaluation.warnings}


def test_lambda_zero_yields_unity_theoretical_metrics() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.0)
    entity_one = completed_entity("e1", seq_base=0)
    samples = [sample("e1", lam=0.0, exposure=1.0)]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [entity_one], samples),
    )
    node = _node(evaluation)
    assert node.mean_entity_theoretical_reliability == 1.0
    assert node.joint_theoretical_no_failure_probability == 1.0
    assert node.empirical_failure_frequency == 0.0


def test_different_lambda_nodes_remain_separate() -> None:
    data = {
        "schema_version": "process-ir/1.0",
        "name": "双节点评价",
        "status_catalog": STATUS_CATALOG,
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {"id": "work1", "type": "task", "name": "节点一", "duration": 1, "status_on_enter": "operational"},
            {"id": "work2", "type": "task", "name": "节点二", "duration": 1, "status_on_enter": "operational"},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_1", "from": "start", "to": "work1", "kind": "normal"},
            {"id": "e_1_2", "from": "work1", "to": "work2", "kind": "normal"},
            {"id": "e_2_end", "from": "work2", "to": "end", "kind": "normal"},
        ],
        "guards": {"max_node_visits": 100},
    }
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "work1", "participates": True, "lambda": 0.1},
            {"node_id": "work2", "participates": True, "lambda": 0.2},
        ],
    )
    entity_one = entity(
        "e1",
        status="operational",
        node_visits={"start": 1, "work1": 1, "work2": 1, "end": 1},
        history=[
            ev(0, 0, "node_entered", "e1", "start"),
            ev(1, 0, "node_completed", "e1", "start", {"elapsed": 0}),
            ev(2, 0, "node_entered", "e1", "work1"),
            ev(3, 1, "node_completed", "e1", "work1", {"elapsed": 1}),
            ev(4, 1, "node_entered", "e1", "work2"),
            ev(5, 2, "node_completed", "e1", "work2", {"elapsed": 1}),
            ev(6, 2, "node_entered", "e1", "end"),
            ev(7, 2, "node_completed", "e1", "end", {"elapsed": 0}),
        ],
    )
    samples = [
        sample("e1", node_id="work1", lam=0.1, exposure=1.0),
        sample("e1", node_id="work2", lam=0.2, exposure=1.0),
    ]
    evaluation = evaluate_simulation(
        process, reliability, make_result(process, reliability, [entity_one], samples)
    )
    assert [node.node_id for node in evaluation.nodes] == ["work1", "work2"]
    assert evaluation.nodes[0].lambda_per_day == 0.1
    assert evaluation.nodes[1].lambda_per_day == 0.2
    assert math.isclose(
        evaluation.nodes[0].mean_entity_theoretical_reliability,
        math.exp(-0.1),
        rel_tol=1e-12,
    )
    assert math.isclose(
        evaluation.nodes[1].mean_entity_theoretical_reliability,
        math.exp(-0.2),
        rel_tol=1e-12,
    )


def test_failure_exit_actual_elapsed_comes_from_reliability_sample() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    failed = failed_repaired_entity("e1", seq_base=0)
    samples = [sample("e1", lam=0.1, exposure=1.0, failure=True)]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [failed], samples),
    )
    node = _node(evaluation)
    assert node.total_actual_elapsed_time == 1.0
    assert node.actual_elapsed_complete is True
    assert node.total_reliability_exposure_time == 1.0
    assert node.per_entity_metrics[0].actual_elapsed_time == 1.0
    assert node.per_entity_metrics[0].theoretical_reliability == math.exp(-0.1)


def test_partial_exposure_actual_elapsed_uses_final_node_elapsed() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    partial = partial_entity("e1", seq_base=0)
    samples = [sample("e1", lam=0.1, exposure=0.5, partial=True, time=0.5)]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [partial], samples),
    )
    node = _node(evaluation)
    assert node.total_actual_elapsed_time == 0.5
    assert node.total_reliability_exposure_time == 0.5
    assert node.per_entity_metrics[0].actual_elapsed_time == 0.5
    assert node.per_entity_metrics[0].actual_elapsed_complete is True


def test_partial_exposure_failure_counts_once_without_double_elapsed() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.5)
    partial = partial_entity("e1", seq_base=0, lam=0.5, exposure=0.5, failure=True)
    samples = [
        sample("e1", lam=0.5, exposure=0.5, failure=True, partial=True, time=0.5)
    ]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [partial], samples),
    )
    node = _node(evaluation)
    assert node.total_reliability_exposure_time == 0.5
    assert node.total_actual_elapsed_time == 0.5
    assert node.failure_count == 1
    assert evaluation.overall.total_failure_count == 1
    assert evaluation.overall.currently_failed_entity_count == 1
    assert evaluation.overall.end_availability == 0.0


def test_incomplete_actual_elapsed_is_null_and_not_replaced_by_exposure() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    broken = entity(
        "e1",
        final_node_id="end",
        status="operational",
        node_visits={"start": 1, "work": 1, "end": 1},
        history=[
            ev(0, 0, "node_entered", "e1", "start"),
            ev(1, 0, "node_completed", "e1", "start", {"elapsed": 0}),
            ev(2, 0, "node_entered", "e1", "work"),
            ev(3, 1, "reliability_sample", "e1", "work", {"exposure_time": 1.0, "failure_occurred": False}),
            ev(4, 1, "node_entered", "e1", "end"),
            ev(5, 1, "node_completed", "e1", "end", {"elapsed": 0}),
        ],
    )
    samples = [sample("e1", lam=0.1, exposure=1.0)]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [broken], samples),
    )
    node = _node(evaluation)
    assert node.total_reliability_exposure_time == 1.0
    assert node.total_actual_elapsed_time is None
    assert node.actual_elapsed_complete is False
    assert node.per_entity_metrics[0].actual_elapsed_time is None
    assert node.per_entity_metrics[0].actual_elapsed_complete is False
    assert "actual_elapsed_incomplete" in {
        warning.code for warning in evaluation.warnings
    }
