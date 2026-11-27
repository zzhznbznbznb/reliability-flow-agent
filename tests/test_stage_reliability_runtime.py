from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.domain.process_ir import ProcessSpec
from app.domain.validation import validate_process
from app.simulation.config import ProjectParameters, SimulationConfig
from app.simulation.engine import run_simulation
from app.simulation.errors import SimulationValidationError
from tests.helpers import (
    document_from_spec,
    equipment_reliability_nodes,
    reliability_document_from_process,
)

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "examples" / "equipment_support_reliability_flow.json"


def _process():
    spec = ProcessSpec.model_validate(
        json.loads(CASE_PATH.read_text(encoding="utf-8"))
    )
    return document_from_spec(spec)


def _reliability(process, *, lambda1=0.0, lambda2=0.0, ft=1.0, unit="day"):
    return reliability_document_from_process(
        process,
        equipment_reliability_nodes(
            process,
            lambda1=lambda1,
            lambda2=lambda2,
            detection_rate=ft,
            simulation_unit=unit,
        ),
    )


def _run(
    *,
    lambda1=0.0,
    lambda2=0.0,
    ft=1.0,
    entities=1,
    horizon=120.0,
    seed=7,
    unit="day",
):
    process = _process()
    reliability = _reliability(
        process, lambda1=lambda1, lambda2=lambda2, ft=ft, unit=unit
    )
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(
            entity_count=entities,
            simulation_end=horizon,
            random_seed=seed,
            simulation_unit=unit,
        ),
    )
    return process, reliability, result


def test_reference_nested_flow_is_structure_valid() -> None:
    spec = ProcessSpec.model_validate(
        json.loads(CASE_PATH.read_text(encoding="utf-8"))
    )
    result = validate_process(spec)
    assert result.valid is True, [issue.model_dump() for issue in result.issues]


def test_zero_failure_rates_keep_all_entities_available() -> None:
    process, reliability, result = _run(entities=3, horizon=60)
    assert result.runtime_semantic_version == "stepwise-detection/1.0"
    assert result.reliability_sampling_mode == "stepwise"
    assert result.total_failure_count == 0
    assert all(entity.failure_count == 0 for entity in result.entities)
    assert all(not entity.currently_failed for entity in result.entities)
    assert all(entity.unavailable_time == 0 for entity in result.entities)
    assert all(
        entity.available_time == 60 for entity in result.entities
    )
    assert all(
        not record.detected
        for entity in result.entities
        for record in entity.test_records
    )
    assert result.reliability_sample_count > 0
    assert all(
        sample.sampling_mode == "stepwise"
        for sample in result.reliability_samples
    )
    assert all(
        sample.reliability_probability == pytest.approx(1.0)
        for sample in result.reliability_samples
    )


def test_stage_sampling_matches_exponential_formula() -> None:
    _, _, result = _run(lambda1=0.002, lambda2=0.0, ft=0.0, entities=1, seed=11)
    storage_samples = [
        sample
        for sample in result.reliability_samples
        if sample.host_node_id == "n_storage"
    ]
    assert storage_samples
    for sample in storage_samples:
        assert sample.cumulative_exposure is not None
        assert sample.reliability_probability == pytest.approx(
            math.exp(-0.002 * sample.cumulative_exposure)
        )
        assert 0 <= sample.random_value <= 1
    failure_samples = [s for s in storage_samples if s.failure_occurred]
    if failure_samples:
        failed = failure_samples[0]
        assert failed.random_value > failed.reliability_probability
        assert failed.failure_time == pytest.approx(failed.time)


def test_lambda1_only_affects_storage_stage() -> None:
    _, _, result = _run(lambda1=0.05, lambda2=0.0, ft=0.0, entities=20, seed=21)
    failure_records = [
        record for entity in result.entities for record in entity.failure_records
    ]
    assert failure_records
    assert all(record.node_id == "n_storage" for record in failure_records)
    assert all(record.stage_task_id == "s_store" for record in failure_records)


def test_lambda2_only_affects_duty_stage() -> None:
    _, _, result = _run(lambda1=0.0, lambda2=0.05, ft=0.0, entities=20, seed=22)
    failure_records = [
        record for entity in result.entities for record in entity.failure_records
    ]
    assert failure_records
    assert all(record.node_id == "n_duty" for record in failure_records)
    assert all(record.stage_task_id == "d_duty" for record in failure_records)


def test_stepwise_sampling_follows_image_formula_and_exposes_bias() -> None:
    # The image compares p(t) with R(t)=exp(-lambda*t) at every step.  The
    # resulting no-failure probability after n unit steps is prod R(t), not
    # exp(-lambda*n).  This test pins the implemented semantics.
    entities = 400
    lam = 0.001
    _, _, result = _run(
        lambda1=lam,
        lambda2=0.0,
        ft=0.0,
        entities=entities,
        horizon=40.0,
        seed=99,
    )
    failed = sum(
        1 for entity in result.entities if entity.failure_records
    )
    empirical = failed / entities
    stepwise_theory = 1 - math.exp(-lam * (30 * 31 / 2))
    standard_exponential = 1 - math.exp(-lam * 30)
    assert abs(empirical - stepwise_theory) < 0.08
    assert empirical > standard_exponential + 0.2


def test_detection_rate_zero_never_detects() -> None:
    _, _, result = _run(
        lambda1=0.05, lambda2=0.0, ft=0.0, entities=30, seed=31
    )
    failed_entities = [
        entity for entity in result.entities if entity.failure_records
    ]
    assert failed_entities
    for entity in failed_entities:
        assert entity.repair_count == 0
        assert entity.currently_failed is True
        assert all(not record.detected for record in entity.failure_records)
        assert any(
            record.had_fault and not record.detected
            for record in entity.test_records
        )
        assert entity.unavailable_time > 0


def test_detection_rate_one_detects_and_repairs_every_fault() -> None:
    _, _, result = _run(
        lambda1=0.002, lambda2=0.0, ft=1.0, entities=20, seed=32, horizon=400
    )
    failed_entities = [
        entity for entity in result.entities if entity.failure_records
    ]
    assert failed_entities
    detected = 0
    for entity in failed_entities:
        for record in entity.failure_records:
            if record.detected:
                detected += 1
                assert record.repaired is True
                assert record.repair_end_time is not None
            else:
                assert record.open_at_end is True
        assert entity.repair_count == sum(
            1 for record in entity.failure_records if record.repaired
        )
        assert math.isclose(
            entity.available_time + entity.unavailable_time,
            result.simulation_end - result.simulation_start,
        )
    assert detected > 0


def test_partial_detection_rate_lies_between_extremes() -> None:
    def detected_ratio(ft):
        _, _, result = _run(
            lambda1=0.002,
            lambda2=0.0,
            ft=ft,
            entities=160,
            seed=33,
            horizon=300,
        )
        records = [
            record
            for entity in result.entities
            for record in entity.test_records
            if record.had_fault
        ]
        return (
            sum(1 for record in records if record.detected) / len(records)
            if records
            else 0.0
        )

    ratio_zero = detected_ratio(0.0)
    ratio_half = detected_ratio(0.5)
    ratio_one = detected_ratio(1.0)
    assert ratio_zero == 0.0
    assert ratio_one == 1.0
    assert 0.4 < ratio_half < 0.6


def test_one_detection_draw_per_completed_test_visit() -> None:
    _, _, result = _run(
        lambda1=0.02, lambda2=0.02, ft=0.5, entities=10, seed=34, horizon=80
    )
    for entity in result.entities:
        test_nodes = [record.node_id for record in entity.test_records]
        completed_nodes = [
            event.node_id
            for event in entity.history
            if event.event_type == "node_completed"
            and event.node_id in {"s_inspect", "n_first_test", "n_second_test", "d_inspect"}
        ]
        for node_id in ("s_inspect", "n_first_test", "n_second_test", "d_inspect"):
            assert test_nodes.count(node_id) == completed_nodes.count(node_id)
        assert all(0 <= record.random_value <= 1 for record in entity.test_records)
        assert all(
            record.detected
            == (record.had_fault and record.random_value <= record.detection_rate)
            for record in entity.test_records
        )


def test_detection_rate_does_not_change_actual_failure_times() -> None:
    _, _, no_detection = _run(
        lambda1=0.02, lambda2=0.02, ft=0.0, entities=20, seed=44, horizon=60
    )
    _, _, always_detection = _run(
        lambda1=0.02, lambda2=0.02, ft=1.0, entities=20, seed=44, horizon=60
    )
    for left, right in zip(no_detection.entities, always_detection.entities):
        left_first = left.failure_records[0].failure_time if left.failure_records else None
        right_first = right.failure_records[0].failure_time if right.failure_records else None
        assert left_first == right_first


def test_entities_can_be_in_different_stages_and_scopes() -> None:
    _, _, result = _run(
        lambda1=0.01, lambda2=0.01, ft=0.5, entities=60, seed=55, horizon=50
    )
    scopes = {
        tuple(entity.scope_path[-1:]) for entity in result.entities
    }
    assert len(scopes) > 1
    final_nodes = {entity.final_node_id for entity in result.entities}
    assert len(final_nodes) > 1


def test_same_seed_is_reproducible() -> None:
    _, _, first = _run(
        lambda1=0.01, lambda2=0.02, ft=0.4, entities=5, seed=66
    )
    _, _, second = _run(
        lambda1=0.01, lambda2=0.02, ft=0.4, entities=5, seed=66
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_lambda_unit_mismatch_is_rejected() -> None:
    process = _process()
    reliability = _reliability(process, lambda1=0.01, lambda2=0.01)
    with pytest.raises(SimulationValidationError) as error:
        run_simulation(
            process,
            reliability,
            SimulationConfig(
                entity_count=1,
                simulation_end=10,
                random_seed=1,
                simulation_unit="hour",
            ),
        )
    codes = {issue.code for issue in error.value.issues}
    assert "reliability_lambda_unit_mismatch" in codes


def test_project_parameters_are_traceable_in_result() -> None:
    process = _process()
    reliability = _reliability(process, lambda1=0.0, lambda2=0.0)
    project = ProjectParameters(
        name="装备保障项目",
        description="用于验证项目参数传递",
        reliability_target=0.9,
        readiness_target=0.85,
        simulation_unit="day",
        missile_count=2,
    )
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(
            entity_count=2,
            simulation_end=20,
            random_seed=3,
            project=project,
        ),
    )
    assert result.project == project
    assert result.simulation_unit == "day"
    assert result.entity_count == project.missile_count


def test_detected_failure_records_timestamps_and_availability() -> None:
    _, _, result = _run(
        lambda1=0.002, lambda2=0.0, ft=1.0, entities=20, seed=123, horizon=200
    )
    records = [
        record
        for entity in result.entities
        for record in entity.failure_records
        if record.detected
    ]
    assert records
    for record in records:
        assert record.failure_time is not None
        assert record.detection_time is not None
        assert record.repair_start_time is not None
        assert record.repair_end_time is not None
        assert record.failure_time <= record.detection_time
        assert record.detection_time <= record.repair_start_time
        assert record.repair_start_time <= record.repair_end_time
        assert record.unavailable_time == pytest.approx(
            record.repair_end_time - record.failure_time
        )
        assert record.repaired is True
