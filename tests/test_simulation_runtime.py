from __future__ import annotations

import math
from copy import deepcopy

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.reliability_ir import ReliabilityDocument, ReliabilityNodeConfig
from app.simulation.config import SimulationConfig, SimulationLimits
from app.simulation.engine import SimulationRuntime
from app.simulation.errors import (
    SimulationRuntimeError,
    SimulationValidationError,
)
from tests.helpers import (
    branching_process_dict,
    document_from_spec,
    failure_process_dict,
    loop_process_dict,
    minimal_process_dict,
    non_participating_reliability,
    reliability_document_from_process,
    spec_from,
)


def _run(process, reliability, config):
    return SimulationRuntime(process, config, reliability).run()


def _failure_setup(lam: float, participate: bool = True):
    process = document_from_spec(spec_from(failure_process_dict()))
    reliability = reliability_document_from_process(
        process,
        [
            {
                "node_id": "inspect",
                "participates": participate,
                **({"lambda": lam} if participate else {}),
            },
            {"node_id": "repair", "participates": False},
        ],
    )
    return process, reliability


def _samples(result, event_type="reliability_sample"):
    return [event for event in result.events if event.event_type == event_type]


def _repeat_reliability_setup():
    data = {
        "schema_version": "process-ir/1.0",
        "name": "重复可靠性节点",
        "status_catalog": [],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {"id": "work", "type": "task", "name": "重复任务", "duration": 1},
            {"id": "gate", "type": "decision", "name": "是否继续"},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_work", "from": "start", "to": "work", "kind": "normal"},
            {"id": "e_work_gate", "from": "work", "to": "gate", "kind": "normal"},
            {
                "id": "e_gate_work",
                "from": "gate",
                "to": "work",
                "kind": "conditional",
                "priority": 10,
                "condition": {
                    "op": "lt",
                    "field": "node_visits.work",
                    "value": 2,
                },
            },
            {"id": "e_gate_end", "from": "gate", "to": "end", "kind": "default"},
        ],
        "guards": {"max_node_visits": 100},
    }
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0}],
    )
    return process, reliability


def test_single_entity_completes_minimal_process() -> None:
    process = document_from_spec()
    reliability = non_participating_reliability(process)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=1),
    )
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.stopped is False
    assert entity.final_node_id == "end"
    assert entity.node_visits == {"start": 1, "work": 1, "end": 1}
    assert entity.failure_count == 0
    assert entity.ever_failed is False
    assert result.completed_count == 1
    assert result.stopped_count == 0
    event_types = [event.event_type for event in entity.history]
    assert event_types[0] == "node_entered"
    assert "node_completed" in event_types
    assert event_types[-1] == "entity_completed"


def test_multiple_entities_have_independent_history_and_state() -> None:
    process = document_from_spec()
    reliability = non_participating_reliability(process)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=3, simulation_end=10, random_seed=2),
    )
    assert [entity.entity_id for entity in result.entities] == [
        "entity_0001",
        "entity_0002",
        "entity_0003",
    ]
    histories = [entity.history for entity in result.entities]
    assert all(history for history in histories)
    assert histories[0] is not histories[1]
    assert result.completed_count == 3
    assert result.event_count == len(result.events)


def test_decision_loop_executes_and_terminates() -> None:
    process = document_from_spec(spec_from(loop_process_dict()))
    reliability = non_participating_reliability(process)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=20, random_seed=3),
    )
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.node_visits["check"] == 2
    assert entity.node_visits["rework"] == 1
    assert entity.attributes["quality_ok"] is True


def test_entities_can_be_in_different_nodes_at_same_time() -> None:
    process = document_from_spec(spec_from(branching_process_dict()))
    reliability = non_participating_reliability(process)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=40, simulation_end=2.5, random_seed=7),
    )
    final_nodes = {entity.final_node_id for entity in result.entities}
    assert final_nodes == {"end", "slow_task"}
    completed = [entity for entity in result.entities if entity.completed]
    active = [entity for entity in result.entities if not entity.completed]
    assert completed and active
    assert all(entity.final_node_id == "end" for entity in completed)
    assert all(entity.final_node_id == "slow_task" for entity in active)


def test_event_order_and_results_are_stable_for_same_seed() -> None:
    process = document_from_spec(spec_from(branching_process_dict()))
    reliability = non_participating_reliability(process)
    config = SimulationConfig(
        entity_count=12, simulation_end=3, random_seed=99
    )
    first = _run(process, reliability, config)
    second = _run(process, reliability, config)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [event.seq for event in first.events] == list(
        range(len(first.events))
    )
    times = [event.time for event in first.events]
    assert times == sorted(times)


def test_exponential_reliability_sample_is_recorded_correctly() -> None:
    process, reliability = _failure_setup(lam=0.5)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=5, random_seed=11),
    )
    samples = _samples(result)
    assert len(samples) == 1
    data = samples[0].data
    assert data["lambda"] == 0.5
    assert data["exposure_time"] == 1.0
    assert data["reliability_probability"] == math.exp(-0.5)
    assert 0.0 <= data["random_value"] < 1.0
    assert data["failure_occurred"] == (
        data["random_value"] >= data["reliability_probability"]
    )
    assert data["partial"] is False


def test_lambda_zero_never_causes_failure() -> None:
    process, reliability = _failure_setup(lam=0)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=5, simulation_end=10, random_seed=12),
    )
    assert result.reliability_sample_count == 5
    assert all(
        sample.data["failure_occurred"] is False for sample in _samples(result)
    )
    assert result.total_failure_count == 0
    assert all(entity.ever_failed is False for entity in result.entities)
    assert all(entity.completed for entity in result.entities)


def test_non_participating_node_is_not_sampled() -> None:
    process, reliability = _failure_setup(lam=0.9, participate=False)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=2, simulation_end=10, random_seed=13),
    )
    assert result.reliability_sample_count == 0
    assert _samples(result) == []
    assert all(entity.completed for entity in result.entities)


def test_partial_exposure_is_sampled_at_simulation_end() -> None:
    process, reliability = _failure_setup(lam=0.8)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=0.4, random_seed=14),
    )
    entity = result.entities[0]
    assert entity.completed is False
    assert entity.final_node_id == "inspect"
    assert entity.node_elapsed_time == 0.4
    sample = _samples(result)[0]
    assert sample.data["exposure_time"] == 0.4
    assert sample.data["reliability_probability"] == math.exp(-0.8 * 0.4)
    assert sample.data["partial"] is True


def test_partial_exposure_failure_is_recorded_without_routing() -> None:
    process, reliability = _failure_setup(lam=1e9)
    result = _run(
        process,
        reliability,
        SimulationConfig(
            entity_count=1,
            simulation_end=0.4,
            random_seed=15,
            failure_sampling="interval_end",
        ),
    )
    entity = result.entities[0]
    assert entity.completed is False
    assert entity.final_node_id == "inspect"
    assert entity.node_elapsed_time == 0.4
    assert entity.failure_count == 1
    assert entity.ever_failed is True
    assert entity.currently_failed is True
    sample = _samples(result)[0]
    assert sample.data["failure_occurred"] is True
    assert sample.data["partial"] is True
    assert sample.time == 0.4
    assert sample.data["exposure_time"] == 0.4
    assert sample.data["reliability_probability"] == math.exp(-1e9 * 0.4)
    assert len(_samples(result)) == 1
    assert all(event.time <= 0.4 for event in entity.history)
    types = {event.event_type for event in entity.history}
    assert "failure_routed" not in types
    assert "repair_started" not in types
    assert "repair_completed" not in types
    assert "business_outcome" not in types
    assert not any(
        event.event_type == "node_completed" and event.node_id == "inspect"
        for event in entity.history
    )
    assert "entity_completed" not in types
    assert entity.currently_failed is True
    assert entity.completed is False
    assert entity.stopped is False


def test_business_sampling_does_not_shift_reliability_stream() -> None:
    process_with_outcomes = document_from_spec(spec_from(failure_process_dict()))
    reliability_with_outcomes = reliability_document_from_process(
        process_with_outcomes,
        [
            {"node_id": "inspect", "participates": True, "lambda": 0},
            {"node_id": "repair", "participates": False},
        ],
    )
    config = SimulationConfig(entity_count=1, simulation_end=5, random_seed=16)
    with_business = _run(
        process_with_outcomes, reliability_with_outcomes, config
    )

    data = deepcopy(failure_process_dict())
    data["nodes"][1].pop("outcomes")
    process_without_outcomes = document_from_spec(spec_from(data))
    reliability_without_outcomes = reliability_document_from_process(
        process_without_outcomes,
        [
            {"node_id": "inspect", "participates": True, "lambda": 0},
            {"node_id": "repair", "participates": False},
        ],
    )
    without_business = _run(
        process_without_outcomes, reliability_without_outcomes, config
    )

    assert any(
        event.event_type == "business_outcome" for event in with_business.events
    )
    assert not any(
        event.event_type == "business_outcome"
        for event in without_business.events
    )
    assert _samples(with_business)[0].data["random_value"] == _samples(
        without_business
    )[0].data["random_value"]


def test_failure_exit_routes_to_repair_and_restores_operational_status() -> None:
    process, reliability = _failure_setup(lam=1e9)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=21),
    )
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.final_node_id == "end"
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert entity.ever_failed is True
    assert entity.currently_failed is False
    assert entity.current_status == "operational"
    assert entity.node_visits["inspect"] == 1
    assert entity.node_visits["repair"] == 1
    types = [event.event_type for event in entity.history]
    assert "reliability_failure" in types
    assert "failure_routed" in types
    assert "repair_started" in types
    assert "repair_completed" in types
    assert types.count("repair_started") == 1
    assert types.count("repair_completed") == 1


def test_subflow_failure_exit_records_repair_started_once() -> None:
    spec = spec_from(
        {
            "schema_version": "process-ir/1.1",
            "name": "子流程故障进入父流程维修",
            "start_node_id": "start",
            "end_node_ids": ["end"],
            "nodes": [
                {"id": "start", "type": "start", "name": "开始"},
                {
                    "id": "block",
                    "type": "subprocess",
                    "name": "阶段块",
                    "subflow": {
                        "start_node_id": "s_start",
                        "end_node_ids": ["s_normal", "s_fault"],
                        "nodes": [
                            {"id": "s_start", "type": "start", "name": "子开始"},
                            {
                                "id": "s_work",
                                "type": "task",
                                "name": "阶段任务",
                                "duration": 1,
                            },
                            {"id": "s_normal", "type": "end", "name": "阶段正常"},
                            {"id": "s_fault", "type": "end", "name": "阶段故障"},
                        ],
                        "edges": [
                            {
                                "id": "s_e_start",
                                "from": "s_start",
                                "to": "s_work",
                                "kind": "normal",
                            },
                            {
                                "id": "s_e_normal",
                                "from": "s_work",
                                "to": "s_normal",
                                "kind": "normal",
                            },
                            {
                                "id": "s_e_fault",
                                "from": "s_work",
                                "to": "s_fault",
                                "kind": "failure",
                            },
                        ],
                    },
                },
                {
                    "id": "parent_repair",
                    "type": "task",
                    "name": "维修",
                    "duration": 2,
                    "on_complete": [
                        {
                            "op": "set_state",
                            "name": "currently_failed",
                            "value": False,
                        }
                    ],
                },
                {"id": "end", "type": "end", "name": "结束"},
            ],
            "edges": [
                {
                    "id": "e_start_block",
                    "from": "start",
                    "to": "block",
                    "kind": "normal",
                },
                {
                    "id": "e_block_normal",
                    "from": "block",
                    "to": "end",
                    "kind": "normal",
                    "subflow_exit": "s_normal",
                },
                {
                    "id": "e_block_fault",
                    "from": "block",
                    "to": "parent_repair",
                    "kind": "failure",
                    "subflow_exit": "s_fault",
                },
                {
                    "id": "e_repair_end",
                    "from": "parent_repair",
                    "to": "end",
                    "kind": "normal",
                },
            ],
        }
    )
    process = document_from_spec(spec)
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "s_work", "participates": True, "lambda": 1e9},
            {"node_id": "parent_repair", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=31),
    )
    entity = result.entities[0]
    repair_started = [
        event
        for event in entity.history
        if event.event_type == "repair_started"
    ]
    repair_completed = [
        event
        for event in entity.history
        if event.event_type == "repair_completed"
    ]

    assert len(repair_started) == 1
    assert len(repair_completed) == 1
    assert repair_started[0].node_id == "parent_repair"
    assert repair_completed[0].node_id == "parent_repair"
    assert math.isclose(
        repair_completed[0].time - repair_started[0].time,
        2.0,
        abs_tol=1e-9,
    )
    assert entity.completed is True
    assert entity.currently_failed is False
    assert entity.repair_count == 1
    assert entity.failure_records[0].repair_start_time == repair_started[0].time
    assert entity.failure_records[0].repair_end_time == repair_completed[0].time
    assert entity.failure_records[0].repaired is True


def test_repair_count_is_not_double_counted_when_explicit_effect_exists() -> None:
    data = failure_process_dict()
    data["nodes"][2]["on_complete"].append(
        {"op": "increment_counter", "name": "repair_count", "by": 1}
    )
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "inspect", "participates": True, "lambda": 1e9},
            {"node_id": "repair", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=22),
    )
    entity = result.entities[0]
    assert entity.repair_count == 1
    repair_event = next(
        event
        for event in entity.history
        if event.event_type == "repair_completed"
    )
    assert repair_event.data["auto_incremented"] is False


def test_multistage_repair_does_not_double_count_with_late_explicit_effect() -> None:
    data = failure_process_dict()
    diagnose = {
        "id": "diagnose",
        "type": "task",
        "name": "故障诊断",
        "duration": 0.2,
        "status_on_enter": "under_repair",
    }
    data["nodes"].insert(2, diagnose)
    for node in data["nodes"]:
        if node["id"] == "repair":
            node["on_complete"].append(
                {
                    "op": "increment_counter",
                    "name": "repair_count",
                    "by": 1,
                }
            )
    data["edges"] = [
        edge
        for edge in data["edges"]
        if edge["id"] != "e_inspect_repair"
        and edge["id"] != "e_repair_end"
    ] + [
        {
            "id": "e_inspect_repair",
            "from": "inspect",
            "to": "diagnose",
            "kind": "failure",
        },
        {"id": "e_diagnose_repair", "from": "diagnose", "to": "repair", "kind": "normal"},
        {"id": "e_repair_end", "from": "repair", "to": "end", "kind": "normal"},
    ]
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "inspect", "participates": True, "lambda": 1e9},
            {"node_id": "diagnose", "participates": False},
            {"node_id": "repair", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=25),
    )
    entity = result.entities[0]
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert entity.ever_failed is True
    assert entity.currently_failed is False
    repair_events = [
        event
        for event in entity.history
        if event.event_type == "repair_completed"
    ]
    assert len(repair_events) == 1
    assert repair_events[0].node_id == "repair"
    assert repair_events[0].data["auto_incremented"] is False
    assert repair_events[0].data["explicit_effect_increment"] is True


def test_multistage_repair_with_decision_loop_counts_once() -> None:
    data = failure_process_dict()
    data["nodes"].insert(
        2,
        {
            "id": "diagnose",
            "type": "task",
            "name": "故障诊断",
            "duration": 0.2,
            "status_on_enter": "under_repair",
        },
    )
    data["nodes"].insert(
        3,
        {"id": "repair_gate", "type": "decision", "name": "是否需要复检"},
    )
    for node in data["nodes"]:
        if node["id"] == "repair":
            node["on_complete"].append(
                {
                    "op": "increment_counter",
                    "name": "repair_count",
                    "by": 1,
                }
            )
    data["edges"] = [
        edge
        for edge in data["edges"]
        if edge["id"] not in {"e_inspect_repair", "e_repair_end"}
    ] + [
        {
            "id": "e_inspect_repair",
            "from": "inspect",
            "to": "diagnose",
            "kind": "failure",
        },
        {
            "id": "e_diagnose_gate",
            "from": "diagnose",
            "to": "repair_gate",
            "kind": "normal",
        },
        {
            "id": "e_gate_diagnose",
            "from": "repair_gate",
            "to": "diagnose",
            "kind": "conditional",
            "priority": 10,
            "condition": {
                "op": "lt",
                "field": "node_visits.diagnose",
                "value": 2,
            },
        },
        {
            "id": "e_gate_repair",
            "from": "repair_gate",
            "to": "repair",
            "kind": "default",
        },
        {
            "id": "e_repair_end",
            "from": "repair",
            "to": "end",
            "kind": "normal",
        },
    ]
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "inspect", "participates": True, "lambda": 1e9},
            {"node_id": "diagnose", "participates": False},
            {"node_id": "repair", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=26),
    )
    entity = result.entities[0]
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert entity.ever_failed is True
    assert entity.currently_failed is False
    assert entity.node_visits["diagnose"] == 2
    repair_events = [
        event
        for event in entity.history
        if event.event_type == "repair_completed"
    ]
    assert len(repair_events) == 1
    assert repair_events[0].node_id == "repair"
    assert repair_events[0].data["auto_incremented"] is False


def test_early_recovery_waits_for_late_explicit_counter() -> None:
    data = failure_process_dict()
    data["nodes"].insert(
        2,
        {
            "id": "diagnose",
            "type": "task",
            "name": "诊断并恢复",
            "duration": 0.2,
            "status_on_enter": "under_repair",
            "on_complete": [
                {"op": "set_state", "name": "currently_failed", "value": False}
            ],
        },
    )
    for node in data["nodes"]:
        if node["id"] == "repair":
            node["on_complete"].append(
                {
                    "op": "increment_counter",
                    "name": "repair_count",
                    "by": 1,
                }
            )
    data["edges"] = [
        edge
        for edge in data["edges"]
        if edge["id"] not in {"e_inspect_repair", "e_repair_end"}
    ] + [
        {
            "id": "e_inspect_repair",
            "from": "inspect",
            "to": "diagnose",
            "kind": "failure",
        },
        {
            "id": "e_diagnose_repair",
            "from": "diagnose",
            "to": "repair",
            "kind": "normal",
        },
        {"id": "e_repair_end", "from": "repair", "to": "end", "kind": "normal"},
    ]
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "inspect", "participates": True, "lambda": 1e9},
            {"node_id": "diagnose", "participates": False},
            {"node_id": "repair", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=28),
    )
    entity = result.entities[0]
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert entity.ever_failed is True
    assert entity.currently_failed is False
    repair_events = [
        event
        for event in entity.history
        if event.event_type == "repair_completed"
    ]
    assert len(repair_events) == 1
    assert repair_events[0].node_id == "repair"
    assert repair_events[0].data["auto_incremented"] is False
    assert repair_events[0].data["explicit_effect_increment"] is True


def test_repair_branch_without_explicit_effect_still_counts_once() -> None:
    data = failure_process_dict()
    explicit_repair = data["nodes"][2]
    explicit_repair["on_complete"].append(
        {"op": "increment_counter", "name": "repair_count", "by": 1}
    )
    data["nodes"].insert(
        2, {"id": "repair_gate", "type": "decision", "name": "维修分支"}
    )
    data["nodes"].append(
        {
            "id": "simple_repair",
            "type": "task",
            "name": "简单维修",
            "duration": 0.5,
            "status_on_enter": "under_repair",
            "status_on_complete": "operational",
            "on_complete": [
                {"op": "set_state", "name": "currently_failed", "value": False}
            ],
        }
    )
    data["edges"] = [
        edge
        for edge in data["edges"]
        if edge["id"] not in {"e_inspect_repair", "e_repair_end"}
    ] + [
        {
            "id": "e_inspect_repair",
            "from": "inspect",
            "to": "repair_gate",
            "kind": "failure",
        },
        {
            "id": "e_gate_explicit",
            "from": "repair_gate",
            "to": "repair",
            "kind": "conditional",
            "priority": 10,
            "condition": {"op": "eq", "field": "ever_failed", "value": False},
        },
        {
            "id": "e_gate_simple",
            "from": "repair_gate",
            "to": "simple_repair",
            "kind": "default",
        },
        {"id": "e_repair_end", "from": "repair", "to": "end", "kind": "normal"},
        {
            "id": "e_simple_end",
            "from": "simple_repair",
            "to": "end",
            "kind": "normal",
        },
    ]
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "inspect", "participates": True, "lambda": 1e9},
            {"node_id": "repair", "participates": False},
            {"node_id": "simple_repair", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=27),
    )
    entity = result.entities[0]
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert entity.ever_failed is True
    assert entity.currently_failed is False
    repair_events = [
        event
        for event in entity.history
        if event.event_type == "repair_completed"
    ]
    assert len(repair_events) == 1
    assert repair_events[0].node_id == "simple_repair"
    assert repair_events[0].data["auto_incremented"] is True
    assert repair_events[0].data["explicit_effect_increment"] is False


def test_repair_count_updates_even_without_explicit_state_effect() -> None:
    data = failure_process_dict()
    data["nodes"][2]["on_complete"] = []
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "inspect", "participates": True, "lambda": 1e9},
            {"node_id": "repair", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=24),
    )
    entity = result.entities[0]
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert entity.ever_failed is True
    assert entity.currently_failed is True
    assert entity.completed is True


def test_missing_failure_exit_is_rejected_by_default_policy() -> None:
    process = document_from_spec()
    reliability = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.1}],
    )
    try:
        _run(
            process,
            reliability,
            SimulationConfig(
                entity_count=1, simulation_end=10, random_seed=23
            ),
        )
    except SimulationValidationError as error:
        assert "missing_failure_exit" in {
            issue.code for issue in error.issues
        }
    else:
        raise AssertionError("expected SimulationValidationError")


def test_stop_entity_policy_does_not_stop_other_entities() -> None:
    data = branching_process_dict()
    data["nodes"][3] = {
        "id": "slow_task",
        "type": "task",
        "name": "高风险任务",
        "duration": 1,
    }
    data["nodes"][4] = {
        "id": "fast_task",
        "type": "task",
        "name": "安全任务",
        "duration": 0.5,
    }
    process = document_from_spec(spec_from(data))
    reliability = reliability_document_from_process(
        process,
        [
            {"node_id": "prepare", "participates": False},
            {"node_id": "slow_task", "participates": True, "lambda": 1e9},
            {"node_id": "fast_task", "participates": False},
        ],
    )
    result = _run(
        process,
        reliability,
        SimulationConfig(
            entity_count=40,
            simulation_end=5,
            random_seed=7,
            failure_policy="stop_entity",
        ),
    )
    stopped = [entity for entity in result.entities if entity.stopped]
    completed = [entity for entity in result.entities if entity.completed]
    assert stopped and completed
    assert all(
        entity.stopped_reason == "failure_without_exit" for entity in stopped
    )
    assert all(entity.final_node_id == "slow_task" for entity in stopped)
    assert all(entity.failure_count == 1 for entity in stopped)
    assert all(entity.failure_count == 0 for entity in completed)
    assert all(entity.final_node_id == "end" for entity in completed)
    assert result.stopped_count == len(stopped)
    assert result.completed_count == len(completed)


def test_same_seed_reproduces_failure_simulation_exactly() -> None:
    process, reliability = _failure_setup(lam=0.7)
    config = SimulationConfig(
        entity_count=8, simulation_end=10, random_seed=12345
    )
    first = _run(process, reliability, config)
    second = _run(process, reliability, config)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    runtime = SimulationRuntime(process, config, reliability)
    assert runtime.run().model_dump(mode="json") == first.model_dump(
        mode="json"
    )
    assert runtime.run().model_dump(mode="json") == first.model_dump(
        mode="json"
    )


def test_different_seed_changes_reliability_draws() -> None:
    process, reliability = _failure_setup(lam=0)
    first = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=5, random_seed=1),
    )
    second = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=5, random_seed=2),
    )
    assert _samples(first)[0].data["random_value"] != _samples(second)[0].data[
        "random_value"
    ]


def test_entity_reliability_streams_are_independent() -> None:
    process, reliability = _failure_setup(lam=0)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=4, simulation_end=5, random_seed=55),
    )
    draws = [
        sample.data["random_value"] for sample in _samples(result)
    ]
    assert len(draws) == 4
    assert len(set(draws)) == 4


def test_max_node_visits_stops_entity() -> None:
    data = loop_process_dict()
    data["guards"]["max_node_visits"] = 2
    data["nodes"][3]["outcomes"] = [
        {
            "id": "still_bad",
            "name": "仍不合格",
            "weight": 1,
            "attributes": {"quality_ok": False},
        }
    ]
    process = document_from_spec(spec_from(data))
    reliability = non_participating_reliability(process)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=50, random_seed=31),
    )
    entity = result.entities[0]
    assert entity.completed is False
    assert entity.stopped is True
    assert entity.stopped_reason == "max_node_visits_exceeded"
    assert entity.failure_count == 0
    assert entity.ever_failed is False
    stopped = next(
        event
        for event in entity.history
        if event.event_type == "entity_stopped"
    )
    assert stopped.data["visits"] == 3
    assert stopped.data["max_node_visits"] == 2


def test_max_events_limit_is_enforced() -> None:
    data = loop_process_dict()
    data["nodes"][3]["outcomes"] = [
        {
            "id": "still_bad",
            "name": "仍不合格",
            "weight": 1,
            "attributes": {"quality_ok": False},
        }
    ]
    process = document_from_spec(spec_from(data))
    reliability = non_participating_reliability(process)
    try:
        SimulationRuntime(
            process,
            SimulationConfig(
                entity_count=1, simulation_end=100, random_seed=32
            ),
            reliability,
            SimulationLimits(max_events=5),
        ).run()
    except SimulationRuntimeError as error:
        assert error.code == "max_events_exceeded"
    else:
        raise AssertionError("expected SimulationRuntimeError")


def test_max_entities_and_max_simulation_days_are_enforced() -> None:
    process = document_from_spec()
    reliability = non_participating_reliability(process)
    limits = SimulationLimits(max_entities=2, max_simulation_days=1)
    for config in (
        SimulationConfig(entity_count=3, simulation_end=1),
        SimulationConfig(entity_count=1, simulation_end=2),
    ):
        try:
            SimulationRuntime(process, config, reliability, limits).run()
        except SimulationValidationError as error:
            codes = {issue.code for issue in error.issues}
            assert codes & {
                "max_entities_exceeded",
                "max_simulation_days_exceeded",
            }
        else:
            raise AssertionError("expected SimulationValidationError")


def test_invalid_process_is_rejected_before_running() -> None:
    data = minimal_process_dict()
    data["end_node_ids"] = []
    process = document_from_spec(spec_from(data))
    reliability = non_participating_reliability(process)
    try:
        _run(
            process,
            reliability,
            SimulationConfig(entity_count=1, simulation_end=5),
        )
    except SimulationValidationError as error:
        assert "missing_end_reference" in {
            issue.code for issue in error.issues
        }
    else:
        raise AssertionError("expected SimulationValidationError")


def test_process_without_outgoing_transition_is_rejected() -> None:
    data = minimal_process_dict()
    data["edges"] = [data["edges"][0]]
    process = document_from_spec(spec_from(data))
    reliability = non_participating_reliability(process)
    try:
        _run(
            process,
            reliability,
            SimulationConfig(entity_count=1, simulation_end=5),
        )
    except SimulationValidationError as error:
        codes = {issue.code for issue in error.issues}
        assert "missing_outgoing_edge" in codes
        assert "cannot_reach_end" in codes
    else:
        raise AssertionError("expected SimulationValidationError")


def test_reliability_version_mismatch_and_unknown_nodes_are_rejected() -> None:
    process = document_from_spec()
    mismatched = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": False}],
        process_version=2,
    )
    try:
        _run(
            process,
            mismatched,
            SimulationConfig(entity_count=1, simulation_end=5),
        )
    except SimulationValidationError as error:
        assert "reliability_process_version_mismatch" in {
            issue.code for issue in error.issues
        }
    else:
        raise AssertionError("expected SimulationValidationError")

    unknown = reliability_document_from_process(
        process,
        [
            {"node_id": "work", "participates": False},
            {"node_id": "ghost", "participates": False},
        ],
    )
    try:
        _run(
            process,
            unknown,
            SimulationConfig(entity_count=1, simulation_end=5),
        )
    except SimulationValidationError as error:
        assert "reliability_unknown_node" in {
            issue.code for issue in error.issues
        }
    else:
        raise AssertionError("expected SimulationValidationError")


def test_invalid_lambda_is_rejected_before_running() -> None:
    process = document_from_spec()
    node = ReliabilityNodeConfig.model_construct(
        node_id="work",
        participates=True,
        distribution="exponential",
        lambda_per_day=-1.0,
        lambda_unit="per_day",
    )
    reliability = ReliabilityDocument.model_construct(
        schema_version="reliability-ir/1.0",
        process_id=process.process_id,
        process_version=process.version,
        process_hash=process.content_hash,
        reliability_id="rel_000000000000",
        revision=1,
        created_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
        nodes=[node],
    )
    try:
        _run(
            process,
            reliability,
            SimulationConfig(entity_count=1, simulation_end=5),
        )
    except SimulationValidationError as error:
        assert "reliability_invalid_lambda" in {
            issue.code for issue in error.issues
        }
    else:
        raise AssertionError("expected SimulationValidationError")


def test_entity_history_matches_global_event_log() -> None:
    process, reliability = _failure_setup(lam=0.3)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=3, simulation_end=10, random_seed=44),
    )
    for entity in result.entities:
        for event in entity.history:
            assert event.entity_id == entity.entity_id
        global_for_entity = [
            event
            for event in result.events
            if event.entity_id == entity.entity_id
        ]
        assert entity.history == global_for_entity


def test_business_branch_on_another_node_does_not_shift_reliability_samples() -> None:
    base = {
        "schema_version": "process-ir/1.0",
        "name": "随机流隔离",
        "status_catalog": [],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {"id": "prep", "type": "task", "name": "准备", "duration": 0.5},
            {"id": "work", "type": "task", "name": "可靠性任务", "duration": 1},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_prep", "from": "start", "to": "prep", "kind": "normal"},
            {"id": "e_prep_work", "from": "prep", "to": "work", "kind": "normal"},
            {"id": "e_work_end", "from": "work", "to": "end", "kind": "normal"},
        ],
        "guards": {"max_node_visits": 10000},
    }
    process_a = document_from_spec(spec_from(base))
    reliability_a = reliability_document_from_process(
        process_a,
        [
            {"node_id": "prep", "participates": False},
            {"node_id": "work", "participates": True, "lambda": 0},
        ],
    )

    data_b = deepcopy(base)
    data_b["nodes"][1]["outcomes"] = [
        {
            "id": "variant",
            "name": "业务分支",
            "weight": 1,
            "attributes": {"business_variant": "A"},
        }
    ]
    process_b = document_from_spec(spec_from(data_b))
    reliability_b = reliability_document_from_process(
        process_b,
        [
            {"node_id": "prep", "participates": False},
            {"node_id": "work", "participates": True, "lambda": 0},
        ],
    )
    config = SimulationConfig(entity_count=3, simulation_end=5, random_seed=777)
    result_a = _run(process_a, reliability_a, config)
    result_b = _run(process_b, reliability_b, config)
    assert not any(
        sample.node_id == "prep" for sample in result_a.reliability_samples
    )
    assert not any(
        sample.node_id == "prep" for sample in result_b.reliability_samples
    )
    assert any(
        event.event_type == "business_outcome" for event in result_b.events
    )
    assert not any(
        event.event_type == "business_outcome" for event in result_a.events
    )
    for entity_id in ("entity_0001", "entity_0002", "entity_0003"):
        samples_a = [
            sample
            for sample in result_a.reliability_samples
            if sample.entity_id == entity_id and sample.node_id == "work"
        ]
        samples_b = [
            sample
            for sample in result_b.reliability_samples
            if sample.entity_id == entity_id and sample.node_id == "work"
        ]
        assert len(samples_a) == len(samples_b) == 1
        assert samples_a[0].random_value == samples_b[0].random_value
        assert (
            samples_a[0].reliability_probability
            == samples_b[0].reliability_probability
        )


def test_repeated_reliability_node_visits_get_independent_samples() -> None:
    process, reliability = _repeat_reliability_setup()
    config = SimulationConfig(entity_count=1, simulation_end=10, random_seed=88)
    result = _run(process, reliability, config)
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.node_visits["work"] == 2
    samples = _samples(result)
    assert len(samples) == 2
    assert [sample.data["exposure_time"] for sample in samples] == [1.0, 1.0]
    assert all(sample.node_id == "work" for sample in samples)
    assert all(sample.data["partial"] is False for sample in samples)
    assert samples[0].data["random_value"] != samples[1].data["random_value"]
    repeated = _run(process, reliability, config)
    assert repeated.model_dump(mode="json") == result.model_dump(mode="json")


def test_repeated_reliability_node_full_then_partial_exposure() -> None:
    process, reliability = _repeat_reliability_setup()
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=1.5, random_seed=89),
    )
    entity = result.entities[0]
    assert entity.completed is False
    assert entity.node_visits["work"] == 2
    assert entity.final_node_id == "work"
    assert entity.node_enter_time == 1.0
    assert entity.node_elapsed_time == 0.5
    samples = _samples(result)
    assert len(samples) == 2
    assert samples[0].data["exposure_time"] == 1.0
    assert samples[0].data["partial"] is False
    assert samples[1].data["exposure_time"] == 0.5
    assert samples[1].data["partial"] is True
    assert samples[1].time == 1.5
    assert samples[0].data["random_value"] != samples[1].data["random_value"]


def test_partial_exposure_keeps_entity_at_task() -> None:
    process = document_from_spec()
    reliability = non_participating_reliability(process)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=0.5, random_seed=4),
    )
    entity = result.entities[0]
    assert entity.completed is False
    assert entity.final_node_id == "work"
    assert entity.node_enter_time == 0
    assert entity.node_elapsed_time == 0.5


def test_time_to_failure_is_sampled_inside_task_and_routed_at_failure_time() -> None:
    process, reliability = _failure_setup(lam=1000)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=5, random_seed=101),
    )
    entity = result.entities[0]
    sample = result.reliability_samples[0]
    assert sample.failure_occurred is True
    assert sample.failure_time is not None
    assert 0.0 <= sample.exposure_time < 1.0
    assert math.isclose(sample.exposure_time, sample.failure_time)
    assert math.isclose(sample.time, sample.failure_time)
    assert sample.reliability_probability == math.exp(
        -1000.0 * sample.exposure_time
    )
    failure_routed = next(
        event for event in entity.history if event.event_type == "failure_routed"
    )
    assert math.isclose(failure_routed.time, sample.failure_time)
    assert entity.failure_count == 1
    assert entity.node_visits["inspect"] == 1
    assert not any(
        event.event_type == "node_completed" and event.node_id == "inspect"
        for event in entity.history
    )
    assert entity.completed is True


def test_time_to_failure_survival_when_sampled_failure_exceeds_duration() -> None:
    process, reliability = _failure_setup(lam=1e-6)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=5, random_seed=102),
    )
    entity = result.entities[0]
    sample = result.reliability_samples[0]
    assert sample.failure_occurred is False
    assert sample.failure_time is None
    assert sample.exposure_time == 1.0
    assert sample.partial is False
    assert sample.reliability_probability == math.exp(-1e-6)
    assert sample.random_value > 1.0 - sample.reliability_probability
    assert entity.completed is True
    assert entity.failure_count == 0


def test_failure_sampling_mode_changes_failure_time_for_same_seed() -> None:
    process, reliability = _failure_setup(lam=1e9)
    time_to_failure = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=21),
    )
    interval_end = _run(
        process,
        reliability,
        SimulationConfig(
            entity_count=1,
            simulation_end=10,
            random_seed=21,
            failure_sampling="interval_end",
        ),
    )
    sampled = time_to_failure.reliability_samples[0]
    interval = interval_end.reliability_samples[0]
    assert sampled.failure_occurred is True
    assert interval.failure_occurred is True
    assert sampled.time < 1.0
    assert interval.time == 1.0
    assert sampled.random_value == interval.random_value
    assert time_to_failure.runtime_semantic_version == "time-to-failure/1.0"
    assert interval_end.runtime_semantic_version == "interval-end/1.0"
    assert time_to_failure.failure_sampling == "time_to_failure"
    assert interval_end.failure_sampling == "interval_end"


def test_lambda_changes_observed_failure_count() -> None:
    process, no_failure = _failure_setup(lam=0)
    zero = _run(
        process,
        no_failure,
        SimulationConfig(entity_count=20, simulation_end=10, random_seed=103),
    )
    process, high_failure = _failure_setup(lam=5)
    high = _run(
        process,
        high_failure,
        SimulationConfig(entity_count=20, simulation_end=10, random_seed=103),
    )
    assert zero.total_failure_count == 0
    assert all(sample.failure_occurred is False for sample in zero.reliability_samples)
    assert high.total_failure_count > 0
    assert high.total_failure_count > zero.total_failure_count


def test_partial_time_to_failure_returns_survival_sample() -> None:
    process, reliability = _failure_setup(lam=0.01)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=0.4, random_seed=104),
    )
    entity = result.entities[0]
    sample = result.reliability_samples[0]
    assert sample.failure_occurred is False
    assert sample.failure_time is None
    assert sample.exposure_time == 0.4
    assert sample.partial is True
    assert sample.time == 0.4
    assert entity.final_node_id == "inspect"
    assert entity.node_elapsed_time == 0.4
    assert entity.failure_count == 0
    assert entity.completed is False
    types = {event.event_type for event in entity.history}
    assert "failure_routed" not in types


def test_stale_completion_event_after_mid_task_failure_is_ignored() -> None:
    process, reliability = _failure_setup(lam=1e9)
    result = _run(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=21),
    )
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.final_node_id == "end"
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert not any(
        event.event_type == "node_completed" and event.node_id == "inspect"
        for event in entity.history
    )
    assert (
        sum(
            1
            for event in entity.history
            if event.event_type == "entity_completed"
        )
        == 1
    )


def test_simulation_window_derives_end_from_duration_and_start() -> None:
    config = SimulationConfig(
        entity_count=1,
        simulation_start=5,
        simulation_duration=10,
        random_seed=201,
    )
    assert config.simulation_end == 15
    process = document_from_spec()
    reliability = non_participating_reliability(process)
    result = _run(process, reliability, config)
    assert result.simulation_start == 5
    assert result.simulation_end == 15
    assert result.simulation_duration == 10
    assert result.completed_count == 1
    assert min(event.time for event in result.events) == 5
    assert max(event.time for event in result.events) <= 15


def test_simulation_window_rejects_missing_or_conflicting_bounds() -> None:
    with pytest.raises(ValidationError):
        SimulationConfig(entity_count=1)
    with pytest.raises(ValidationError):
        SimulationConfig(entity_count=1, simulation_start=5, simulation_end=5)
    with pytest.raises(ValidationError):
        SimulationConfig(
            entity_count=1,
            simulation_start=2,
            simulation_end=10,
            simulation_duration=5,
        )


def test_simulation_window_partial_exposure_uses_absolute_start() -> None:
    process = document_from_spec()
    reliability = non_participating_reliability(process)
    result = _run(
        process,
        reliability,
        SimulationConfig(
            entity_count=1,
            simulation_start=4,
            simulation_duration=0.5,
            random_seed=202,
        ),
    )
    entity = result.entities[0]
    assert entity.completed is False
    assert entity.final_node_id == "work"
    assert entity.node_enter_time == 4
    assert entity.node_elapsed_time == 0.5
    assert result.simulation_end == 4.5
