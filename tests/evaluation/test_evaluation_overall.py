from __future__ import annotations

import math
from copy import deepcopy

from app.evaluation.evaluator import evaluate_simulation
from app.evaluation.models import EvaluationConfig, EvaluationTargets
from tests.evaluation.helpers import (
    STATUS_CATALOG,
    completed_entity,
    entity,
    ev,
    failed_repaired_entity,
    make_process,
    make_reliability,
    make_result,
    sample,
)


def _extract_warning_codes(evaluation) -> set[str]:
    return {warning.code for warning in evaluation.warnings}


def test_all_entities_complete_good_and_no_failure() -> None:
    process = make_process(
        status_catalog=STATUS_CATALOG, status_on_enter="operational"
    )
    reliability = make_reliability(process, lam=0.1)
    entities = [
        completed_entity("e1", seq_base=0),
        completed_entity("e2", seq_base=20),
    ]
    samples = [
        sample("e1", lam=0.1, exposure=1.0),
        sample("e2", lam=0.1, exposure=1.0),
    ]
    evaluation = evaluate_simulation(
        process, reliability, make_result(process, reliability, entities, samples)
    )
    overall = evaluation.overall
    assert overall.overall_reliability == 1.0
    assert overall.ever_failed_entity_count == 0
    assert overall.good_end_count == 2
    assert overall.bad_end_count == 0
    assert overall.unknown_end_count == 0
    assert overall.availability_evaluable is True
    assert overall.end_availability == 1.0
    assert overall.observed_good_end_fraction == 1.0
    assert overall.total_failure_count == 0
    assert overall.failure_counter_consistent is True
    assert evaluation.target_status == "not_configured"


def test_one_failure_with_repair_keeps_ever_failed_but_restores_availability() -> None:
    process = make_process(
        status_catalog=STATUS_CATALOG, status_on_enter="operational"
    )
    reliability = make_reliability(process, lam=0.1)
    entities = [
        failed_repaired_entity("e1", seq_base=0),
        completed_entity("e2", seq_base=30),
    ]
    samples = [
        sample("e1", lam=0.1, exposure=1.0, failure=True, random_value=0.9),
        sample("e2", lam=0.1, exposure=1.0),
    ]
    evaluation = evaluate_simulation(
        process, reliability, make_result(process, reliability, entities, samples)
    )
    overall = evaluation.overall
    assert overall.overall_reliability == 0.5
    assert overall.ever_failed_entity_count == 1
    assert overall.good_end_count == 2
    assert overall.end_availability == 1.0
    assert overall.currently_failed_entity_count == 0
    assert overall.total_repair_count == 1
    assert overall.repair_completed_count == 1
    assert overall.repair_in_progress_count == 0
    failed = next(item for item in evaluation.entities if item.entity_id == "e1")
    assert failed.ever_failed is True
    assert failed.failure_count == 1
    assert failed.repair_count == 1
    work = next(item for item in evaluation.nodes if item.node_id == "work")
    assert work.failure_count == 1
    assert work.sample_count == 2
    assert work.empirical_failure_frequency == 0.5


def test_multiple_failures_on_one_entity_count_once_in_r_e() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    history_entity = entity(
        "e1",
        final_node_id="work",
        status="operational",
        currently_failed=True,
        completed=False,
        failure_count=2,
        ever_failed=True,
        node_visits={"start": 1, "work": 2},
        history=[
            ev(0, 0, "node_entered", "e1", "start"),
            ev(1, 0, "node_completed", "e1", "start", {"elapsed": 0}),
            ev(2, 0, "node_entered", "e1", "work"),
            ev(3, 1, "reliability_sample", "e1", "work", {"exposure_time": 1.0, "failure_occurred": True}),
            ev(4, 1, "reliability_failure", "e1", "work"),
            ev(5, 1, "node_entered", "e1", "work"),
            ev(6, 2, "reliability_sample", "e1", "work", {"exposure_time": 1.0, "failure_occurred": True}),
            ev(7, 2, "reliability_failure", "e1", "work"),
        ],
        node_elapsed_time=1.0,
    )
    samples = [
        sample("e1", exposure=1.0, failure=True),
        sample("e1", exposure=1.0, failure=True),
    ]
    evaluation = evaluate_simulation(
        process, reliability, make_result(process, reliability, [history_entity], samples)
    )
    assert evaluation.overall.overall_reliability == 0.0
    assert evaluation.overall.ever_failed_entity_count == 1
    assert evaluation.overall.total_failure_count == 2
    assert evaluation.overall.mean_failure_count_per_entity == 2.0
    assert evaluation.overall.end_availability is not None


def test_good_bad_unknown_classification_and_null_end_availability() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.0)
    entities = [
        completed_entity("e1", seq_base=0, status="operational"),
        completed_entity("e2", seq_base=20, status="retired"),
        completed_entity("e3", seq_base=40, status=None),
    ]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, entities, []),
        targets=EvaluationTargets(end_availability_min=0.9),
    )
    overall = evaluation.overall
    assert overall.good_end_count == 1
    assert overall.bad_end_count == 1
    assert overall.unknown_end_count == 1
    assert overall.availability_evaluable is False
    assert overall.end_availability is None
    assert overall.observed_good_end_fraction == 1 / 3
    assert overall.good_end_count + overall.bad_end_count + overall.unknown_end_count == 3
    assert "unknown_end_state" in _extract_warning_codes(evaluation)
    availability_target = next(
        item for item in evaluation.targets if item.metric == "end_availability"
    )
    assert availability_target.status == "unevaluable"
    assert availability_target.actual is None


def test_failure_counter_mismatch_keeps_sample_metric_and_warns() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    failed = failed_repaired_entity("e1", seq_base=0)
    failed.failure_count = 3
    samples = [sample("e1", lam=0.1, exposure=1.0, failure=True)]
    evaluation = evaluate_simulation(
        process, reliability, make_result(process, reliability, [failed], samples)
    )
    assert evaluation.overall.total_failure_count == 1
    assert evaluation.overall.runtime_failure_counter_total == 3
    assert evaluation.overall.failure_counter_consistent is False
    assert "failure_counter_mismatch" in _extract_warning_codes(evaluation)


def test_repair_counter_mismatch_and_repeated_repair_started() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    repair_entity = entity(
        "e1",
        final_node_id="repair",
        status="under_repair",
        currently_failed=True,
        completed=False,
        failure_count=1,
        repair_count=2,
        ever_failed=True,
        node_visits={"start": 1, "work": 1, "repair": 2},
        history=[
            ev(0, 0, "repair_started", "e1", "repair"),
            ev(1, 0, "repair_started", "e1", "repair"),
        ],
        node_elapsed_time=0.2,
    )
    evaluation = evaluate_simulation(
        process, reliability, make_result(process, reliability, [repair_entity], [])
    )
    overall = evaluation.overall
    assert overall.repair_in_progress_count == 1
    assert overall.repair_pending_count == 1
    assert overall.repair_completed_count == 0
    assert overall.total_repair_count == 2
    assert "repair_cycle_overlap" in _extract_warning_codes(evaluation)
    assert "repair_counter_mismatch" in _extract_warning_codes(evaluation)


def test_multiple_repair_cycles_count_active_device_once() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    repair_entity = entity(
        "e1",
        final_node_id="repair",
        status="under_repair",
        currently_failed=True,
        completed=False,
        failure_count=2,
        repair_count=1,
        ever_failed=True,
        node_visits={"work": 2, "repair": 2},
        history=[
            ev(0, 0, "repair_started", "e1", "repair"),
            ev(1, 1, "repair_completed", "e1", "repair"),
            ev(2, 1, "repair_started", "e1", "repair"),
        ],
        node_elapsed_time=0.2,
    )
    evaluation = evaluate_simulation(
        process, reliability, make_result(process, reliability, [repair_entity], [])
    )
    assert evaluation.overall.repair_completed_count == 1
    assert evaluation.overall.total_repair_count == 1
    assert evaluation.overall.repair_in_progress_count == 1
    assert evaluation.overall.repair_pending_count == 1
    assert "repair_cycle_overlap" not in {
        warning.code for warning in evaluation.warnings
    }


def test_non_participating_node_is_not_in_node_metrics() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, participates=False)
    entity_one = completed_entity("e1", seq_base=0)
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [entity_one], []),
    )
    assert evaluation.nodes == []
    assert evaluation.overall.total_failure_count == 0


def test_targets_achieved_not_achieved_and_unevaluable_precedence() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.0)

    good_entity = completed_entity("e1", seq_base=0, status="operational")
    achieved = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [good_entity], []),
        targets=EvaluationTargets(
            overall_reliability_min=0.9, end_availability_min=0.9
        ),
    )
    assert achieved.target_status == "achieved"

    failed_entity = completed_entity("e1", seq_base=0, status="operational")
    failed_entity.ever_failed = True
    failed_entity.failure_count = 1
    not_achieved = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [failed_entity], []),
        targets=EvaluationTargets(
            overall_reliability_min=0.9, end_availability_min=0.9
        ),
    )
    assert not_achieved.target_status == "not_achieved"
    assert not_achieved.overall.end_availability == 1.0

    unknown_entity = completed_entity("e1", seq_base=0, status=None)
    unevaluable = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [unknown_entity], []),
        targets=EvaluationTargets(
            overall_reliability_min=0.9, end_availability_min=0.9
        ),
    )
    assert unevaluable.target_status == "unevaluable"
    assert unevaluable.overall.end_availability is None

    failed_and_unknown = completed_entity("e1", seq_base=0, status=None)
    failed_and_unknown.ever_failed = True
    failed_and_unknown.failure_count = 1
    mixed = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [failed_and_unknown], []),
        targets=EvaluationTargets(
            overall_reliability_min=0.9, end_availability_min=0.9
        ),
    )
    assert mixed.target_status == "not_achieved"


def test_small_sample_does_not_change_metrics() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.0)
    entity_one = completed_entity("e1", seq_base=0)
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [entity_one], []),
        evaluation_config=EvaluationConfig(small_sample_threshold=30),
    )
    assert evaluation.is_small_sample is True
    assert evaluation.overall.overall_reliability == 1.0
    assert evaluation.overall.end_availability == 1.0
    assert "small_sample" in _extract_warning_codes(evaluation)


def test_evaluation_is_pure_and_deterministic() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    entities = [completed_entity("e1", seq_base=0)]
    samples = [sample("e1", lam=0.1, exposure=1.0)]
    result = make_result(process, reliability, entities, samples)
    before_process = process.model_dump(mode="json") if hasattr(process, "model_dump") else None
    before_reliability = reliability.model_dump(mode="json")
    before_result = result.model_dump(mode="json")

    first = evaluate_simulation(process, reliability, result)
    second = evaluate_simulation(process, reliability, result)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    if before_process is not None:
        assert process.model_dump(mode="json") == before_process
    assert reliability.model_dump(mode="json") == before_reliability
    assert result.model_dump(mode="json") == before_result
