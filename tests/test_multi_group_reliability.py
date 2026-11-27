from __future__ import annotations

import json
from pathlib import Path

from app.domain.process_ir import ProcessSpec
from app.evaluation.evaluator import evaluate_simulation
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from tests.helpers import (
    document_from_spec,
    equipment_reliability_nodes,
    reliability_document_from_process,
)

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "examples" / "equipment_support_reliability_flow.json"

GROUPS = {
    "A": (0.0, 0.0),
    "B": (0.001, 0.001),
    "C": (0.01, 0.01),
    "D": (0.05, 0.05),
    "E": (0.01, 0.05),
    "F": (0.05, 0.001),
}


def _matrix(detection_rate: float = 0.5):
    spec = ProcessSpec.model_validate(
        json.loads(CASE_PATH.read_text(encoding="utf-8"))
    )
    process = document_from_spec(spec)
    rows = {}
    for name, (lambda1, lambda2) in GROUPS.items():
        reliability = reliability_document_from_process(
            process,
            equipment_reliability_nodes(
                process,
                lambda1=lambda1,
                lambda2=lambda2,
                detection_rate=detection_rate,
            ),
        )
        result = run_simulation(
            process,
            reliability,
            SimulationConfig(
                entity_count=120,
                simulation_end=120,
                random_seed=2026,
                simulation_unit="day",
            ),
        )
        evaluation = evaluate_simulation(process, reliability, result)
        rows[name] = {
            "result": result,
            "evaluation": evaluation,
            "storage_failures": sum(
                1
                for entity in result.entities
                for record in entity.failure_records
                if record.node_id == "n_storage"
            ),
            "duty_failures": sum(
                1
                for entity in result.entities
                for record in entity.failure_records
                if record.node_id == "n_duty"
            ),
        }
    return rows


def test_six_failure_rate_groups_show_expected_trends() -> None:
    rows = _matrix()
    assert rows["A"]["result"].total_failure_count == 0
    assert rows["A"]["evaluation"].overall.readiness == 1.0
    assert (
        rows["B"]["result"].total_failure_count
        < rows["C"]["result"].total_failure_count
        < rows["D"]["result"].total_failure_count
    )
    assert rows["A"]["evaluation"].overall.readiness > rows["D"]["evaluation"].overall.readiness
    assert rows["E"]["duty_failures"] > rows["E"]["storage_failures"]
    assert rows["F"]["storage_failures"] > rows["F"]["duty_failures"]
    for row in rows.values():
        result = row["result"]
        for entity in result.entities:
            assert entity.available_time + entity.unavailable_time == result.simulation_end
        assert row["evaluation"].overall.total_unavailable_time >= 0


def test_detection_rate_controls_detection_frequency_not_failure_rate() -> None:
    spec = ProcessSpec.model_validate(
        json.loads(CASE_PATH.read_text(encoding="utf-8"))
    )
    process = document_from_spec(spec)

    def run(ft: float):
        reliability = reliability_document_from_process(
            process,
            equipment_reliability_nodes(
                process,
                lambda1=0.002,
                lambda2=0.0,
                detection_rate=ft,
            ),
        )
        result = run_simulation(
            process,
            reliability,
            SimulationConfig(
                entity_count=120,
                simulation_end=240,
                random_seed=77,
            ),
        )
        records = [
            record
            for entity in result.entities
            for record in entity.test_records
            if record.had_fault
        ]
        frequency = (
            sum(1 for record in records if record.detected) / len(records)
            if records
            else 0.0
        )
        return result, frequency

    zero_result, zero_frequency = run(0.0)
    half_result, half_frequency = run(0.5)
    one_result, one_frequency = run(1.0)
    assert zero_frequency == 0.0
    assert one_frequency == 1.0
    assert 0.4 < half_frequency < 0.6

    for left, right in zip(zero_result.entities, one_result.entities):
        left_first = left.failure_records[0].failure_time if left.failure_records else None
        right_first = right.failure_records[0].failure_time if right.failure_records else None
        assert left_first == right_first

    assert zero_result.total_failure_count > 0
    assert one_result.total_failure_count > 0
