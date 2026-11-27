from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.agent.domain_rules import validate_process_with_domain
from app.domain.process_ir import ProcessSpec
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from tests.helpers import document_from_spec, reliability_document_from_process

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "time_driven_nested_conditions_flow.json"
)
TARGET_CONDITIONS = {
    "e_7": {"op": "eq", "field": "test_detected", "value": True},
    "e_13": {"op": "eq", "field": "test_detected", "value": True},
    "s_store_4": {"op": "eq", "field": "test_detected", "value": True},
    "s_duty_4": {"op": "eq", "field": "test_detected", "value": True},
    "s_duty_5": {"op": "eq", "field": "test_detected", "value": False},
}
REPAIR_NODES = {"repair_1", "repair_2", "repair_storage", "repair_duty"}
TEST_NODES = {"test_1", "test_2", "store_test", "duty_test"}


def _spec() -> ProcessSpec:
    return ProcessSpec.model_validate(
        json.loads(FIXTURE.read_text(encoding="utf-8"))
    )


def _iter_nodes(nodes):
    for node in nodes:
        yield node
        if node.subflow is not None:
            yield from _iter_nodes(node.subflow.nodes)


def _edges(spec: ProcessSpec) -> dict[str, object]:
    found = {}

    def walk(scope):
        for edge in scope.edges:
            found[edge.id] = edge
        for node in scope.nodes:
            if node.subflow is not None:
                walk(node.subflow)

    walk(spec)
    return found


def _reliability_nodes(process) -> list[dict]:
    nodes = []
    for node in _iter_nodes(process.nodes):
        if node.type != "task":
            continue
        if node.id in TEST_NODES:
            nodes.append(
                {
                    "node_id": node.id,
                    "module_type": "test",
                    "participates": False,
                    "detection_rate": 0.4,
                    "lambda_unit": "per_day",
                }
            )
        else:
            nodes.append(
                {
                    "node_id": node.id,
                    "module_type": "activity",
                    "participates": False,
                    "lambda_unit": "per_day",
                }
            )
    nodes.extend(
        [
            {
                "node_id": "sub_store",
                "module_type": "stage",
                "participates": True,
                "lambda": 0.4,
                "lambda_unit": "per_day",
                "stage_task_id": "store_task",
            },
            {
                "node_id": "sub_duty",
                "module_type": "stage",
                "participates": True,
                "lambda": 0.5,
                "lambda_unit": "per_day",
                "stage_task_id": "duty_task",
            },
        ]
    )
    return nodes


def test_five_business_conditions_are_machine_executable_and_persisted() -> None:
    spec = _spec()
    result = validate_process_with_domain(spec)
    assert result.simulation_ready is True
    assert not [
        issue for issue in result.issues if issue.code == "missing_condition"
    ]

    edges = _edges(spec)
    for edge_id, expected in TARGET_CONDITIONS.items():
        edge = edges[edge_id]
        assert edge.condition is not None
        assert edge.condition.model_dump(exclude={"conditions"}) == expected

    for node in _iter_nodes(spec.nodes):
        if node.id in REPAIR_NODES:
            assert any(
                effect.op == "set_state"
                and effect.name == "currently_failed"
                and effect.value is False
                for effect in node.on_complete
            )


def test_runtime_takes_all_configured_normal_and_fault_branches() -> None:
    spec = _spec()
    process = document_from_spec(spec)
    reliability = reliability_document_from_process(
        process, _reliability_nodes(process)
    )
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(
            entity_count=6,
            simulation_start=0,
            simulation_end=150,
            random_seed=0,
            simulation_unit="day",
            failure_sampling="time_to_failure",
        ),
    )

    taken = Counter(
        event.data["edge_id"]
        for event in result.events
        if event.event_type == "edge_taken"
    )
    for edge_id in TARGET_CONDITIONS:
        assert taken[edge_id] > 0, edge_id

    # The complementary normal branches must remain reachable.
    for edge_id in ("e_8", "e_14", "s_store_5", "s_duty_5"):
        assert taken[edge_id] > 0, edge_id

    repair_events = [
        event
        for event in result.events
        if event.event_type == "repair_completed"
    ]
    assert repair_events
    assert all(
        event.data["currently_failed"] is False
        for event in repair_events
        if event.node_id in REPAIR_NODES
    )
    # A subflow fault exit must not count as a completed repair before the
    # parent repair task actually runs.
    assert not any(
        event.node_id in {"store_exit_fault", "duty_exit_fault"}
        for event in repair_events
    )
