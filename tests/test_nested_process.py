from __future__ import annotations

import json
from pathlib import Path

from app.agent.requirements import (
    RequirementAnalysis,
    evaluate_requirement_coverage,
    validate_requirement_analysis,
)
from app.domain.process_ir import ProcessSpec
from app.domain.validation import validate_process
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from tests.helpers import (
    document_from_spec,
    non_participating_reliability,
    reliability_document_from_process,
)

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "examples" / "equipment_support_nested_flow.json"
ANALYSIS_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "equipment_support_nested_requirement_analysis.json"
)


def _case_spec() -> ProcessSpec:
    return ProcessSpec.model_validate(
        json.loads(CASE_PATH.read_text(encoding="utf-8"))
    )


def _run_case(seed: int = 0, simulations_end: float = 200.0):
    process = document_from_spec(_case_spec())
    reliability = non_participating_reliability(process)
    return run_simulation(
        process,
        reliability,
        SimulationConfig(
            entity_count=1,
            simulation_end=simulations_end,
            random_seed=seed,
        ),
    )


def test_nested_case_has_real_storage_and_duty_subflows() -> None:
    spec = _case_spec()
    result = validate_process(spec)
    assert result.valid is True, [issue.model_dump() for issue in result.issues]

    node_map = {node.id: node for node in spec.nodes}
    assert node_map["n_storage"].type == "subprocess"
    assert node_map["n_duty"].type == "subprocess"
    assert {node.id for node in node_map["n_storage"].subflow.nodes} == {
        "s_start",
        "s_store",
        "s_inspect",
        "s_dec",
        "s_repair",
        "s_done",
    }
    assert {node.id for node in node_map["n_duty"].subflow.nodes} == {
        "d_start",
        "d_duty",
        "d_inspect",
        "d_dec",
        "d_repair",
        "d_done",
    }
    assert node_map["n_storage"].subflow.end_node_ids == ["s_done"]
    assert node_map["n_duty"].subflow.end_node_ids == ["d_done"]

    analysis = RequirementAnalysis.model_validate(
        json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    )
    analysis_result = validate_requirement_analysis(analysis)
    assert analysis_result.valid is True, [
        issue.model_dump() for issue in analysis_result.issues
    ]
    coverage = evaluate_requirement_coverage(analysis, spec)
    assert coverage.covered is True, [
        issue.model_dump() for issue in coverage.issues
    ]
    assert coverage.covered_step_count == coverage.step_count == 28
    assert coverage.covered_branch_count == coverage.branch_count == 29


def test_nested_runtime_executes_storage_duty_and_outer_branches() -> None:
    result = _run_case(seed=0)
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.final_node_id == "n_end"

    events = entity.history
    entered = {
        event.node_id
        for event in events
        if event.event_type == "node_entered"
    }
    assert {"n_storage", "s_store", "s_inspect", "s_dec", "s_repair", "s_done"} <= entered
    assert {"n_duty", "d_duty", "d_inspect", "d_dec", "d_done"} <= entered
    assert {"n_repair", "n_end"} <= entered

    storage_completed = next(
        event
        for event in events
        if event.event_type == "subprocess_completed"
        and event.node_id == "n_storage"
    )
    assert storage_completed.time == 64.0
    assert storage_completed.data["exit_node_id"] == "s_done"
    assert entity.node_visits["s_store"] == 2
    assert entity.node_visits["s_repair"] == 1

    first_test_outcomes = [
        event.data["outcome_id"]
        for event in events
        if event.event_type == "business_outcome"
        and event.node_id == "n_first_test"
    ]
    assert first_test_outcomes == ["fault", "fault", "fault", "ok"]
    assert entity.node_visits["n_repair"] == 3
    assert entity.node_visits["n_first_test"] == 4

    duty_completed = next(
        event
        for event in events
        if event.event_type == "subprocess_completed"
        and event.node_id == "n_duty"
    )
    assert duty_completed.data["exit_node_id"] == "d_done"
    assert entity.node_visits["d_duty"] == 1
    assert entity.final_node_id == "n_end"
    assert any(
        event.node_id == "s_inspect" and event.scope == ["n_storage"]
        for event in events
    )
    assert any(
        event.node_id == "d_duty" and event.scope == ["n_duty"]
        for event in events
    )


def test_storage_internal_loop_repeats_inspection_with_time() -> None:
    process = document_from_spec(_case_spec())
    reliability = non_participating_reliability(process)
    result = None
    for seed in range(80):
        candidate = run_simulation(
            process,
            reliability,
            SimulationConfig(
                entity_count=1,
                simulation_end=300,
                random_seed=seed,
            ),
        )
        entity = candidate.entities[0]
        if entity.node_visits.get("s_inspect", 0) > 1 and entity.completed:
            result = candidate
            break
    assert result is not None
    events = result.entities[0].history
    inspections = [
        event
        for event in events
        if event.event_type == "node_entered"
        and event.node_id == "s_inspect"
    ]
    assert len(inspections) > 1
    assert inspections[1].time - inspections[0].time == 33.0
    assert result.entities[0].node_visits["s_repair"] >= 1
    assert result.entities[0].node_visits["s_store"] >= 2


def test_nested_internal_reliability_failure_and_repair() -> None:
    spec = ProcessSpec.model_validate(
        {
            "schema_version": "process-ir/1.1",
            "name": "nested-reliability",
            "start_node_id": "start",
            "end_node_ids": ["end"],
            "nodes": [
                {"id": "start", "type": "start", "name": "开始"},
                {
                    "id": "block",
                    "type": "subprocess",
                    "name": "嵌套块",
                    "subflow": {
                        "start_node_id": "b_start",
                        "end_node_ids": ["b_end"],
                        "nodes": [
                            {"id": "b_start", "type": "start", "name": "子开始"},
                            {
                                "id": "inner_inspect",
                                "type": "task",
                                "name": "内部检测",
                                "duration": 1,
                            },
                            {
                                "id": "inner_repair",
                                "type": "task",
                                "name": "内部维修",
                                "duration": 0.5,
                                "on_complete": [
                                    {
                                        "op": "set_state",
                                        "name": "currently_failed",
                                        "value": False,
                                    }
                                ],
                            },
                            {"id": "b_end", "type": "end", "name": "子结束"},
                        ],
                        "edges": [
                            {
                                "id": "e_b_start",
                                "from": "b_start",
                                "to": "inner_inspect",
                                "kind": "normal",
                            },
                            {
                                "id": "e_inner_end",
                                "from": "inner_inspect",
                                "to": "b_end",
                                "kind": "normal",
                            },
                            {
                                "id": "e_inner_repair",
                                "from": "inner_inspect",
                                "to": "inner_repair",
                                "kind": "failure",
                            },
                            {
                                "id": "e_repair_end",
                                "from": "inner_repair",
                                "to": "b_end",
                                "kind": "normal",
                            },
                        ],
                    },
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
                    "id": "e_block_end",
                    "from": "block",
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
            {"node_id": "inner_inspect", "participates": True, "lambda": 1e9},
            {"node_id": "inner_repair", "participates": False},
        ],
    )
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=1),
    )
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.failure_count == 1
    assert entity.repair_count == 1
    assert entity.currently_failed is False
    assert result.reliability_samples[0].scope_path == ["block"]
    assert any(
        event.event_type == "repair_started"
        and event.node_id == "inner_repair"
        and event.scope == ["block"]
        for event in entity.history
    )


def test_two_level_nested_subflows_execute() -> None:
    spec = ProcessSpec.model_validate(
        {
            "schema_version": "process-ir/1.1",
            "name": "two-level",
            "start_node_id": "start",
            "end_node_ids": ["end"],
            "nodes": [
                {"id": "start", "type": "start", "name": "开始"},
                {
                    "id": "outer_block",
                    "type": "subprocess",
                    "name": "外层",
                    "subflow": {
                        "start_node_id": "o_start",
                        "end_node_ids": ["o_end"],
                        "nodes": [
                            {"id": "o_start", "type": "start", "name": "外开始"},
                            {
                                "id": "inner_block",
                                "type": "subprocess",
                                "name": "内层",
                                "subflow": {
                                    "start_node_id": "i_start",
                                    "end_node_ids": ["i_end"],
                                    "nodes": [
                                        {
                                            "id": "i_start",
                                            "type": "start",
                                            "name": "内开始",
                                        },
                                        {
                                            "id": "deep_task",
                                            "type": "task",
                                            "name": "深层任务",
                                            "duration": 1,
                                        },
                                        {
                                            "id": "i_end",
                                            "type": "end",
                                            "name": "内结束",
                                        },
                                    ],
                                    "edges": [
                                        {
                                            "id": "e_i_start",
                                            "from": "i_start",
                                            "to": "deep_task",
                                            "kind": "normal",
                                        },
                                        {
                                            "id": "e_i_end",
                                            "from": "deep_task",
                                            "to": "i_end",
                                            "kind": "normal",
                                        },
                                    ],
                                },
                            },
                            {"id": "o_end", "type": "end", "name": "外结束"},
                        ],
                        "edges": [
                            {
                                "id": "e_o_start",
                                "from": "o_start",
                                "to": "inner_block",
                                "kind": "normal",
                            },
                            {
                                "id": "e_o_end",
                                "from": "inner_block",
                                "to": "o_end",
                                "kind": "normal",
                            },
                        ],
                    },
                },
                {"id": "end", "type": "end", "name": "结束"},
            ],
            "edges": [
                {
                    "id": "e_start_outer",
                    "from": "start",
                    "to": "outer_block",
                    "kind": "normal",
                },
                {
                    "id": "e_outer_end",
                    "from": "outer_block",
                    "to": "end",
                    "kind": "normal",
                },
            ],
        }
    )
    process = document_from_spec(spec)
    reliability = non_participating_reliability(process)
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=10, random_seed=2),
    )
    entity = result.entities[0]
    assert entity.completed is True
    assert entity.node_visits["deep_task"] == 1
    deep_event = next(
        event
        for event in entity.history
        if event.event_type == "node_entered" and event.node_id == "deep_task"
    )
    assert deep_event.scope == ["outer_block", "inner_block"]
    assert deep_event.depth == 2


def test_nested_runtime_is_reproducible() -> None:
    first = _run_case(seed=7)
    second = _run_case(seed=7)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_duty_internal_fault_repairs_and_loops() -> None:
    process = document_from_spec(_case_spec())
    reliability = non_participating_reliability(process)
    result = None
    for seed in range(120):
        candidate = run_simulation(
            process,
            reliability,
            SimulationConfig(
                entity_count=1,
                simulation_end=500,
                random_seed=seed,
            ),
        )
        entity = candidate.entities[0]
        if entity.node_visits.get("d_inspect", 0) > 1 and entity.completed:
            result = candidate
            break
    assert result is not None
    entity = result.entities[0]
    events = entity.history
    duty_entries = [
        event
        for event in events
        if event.event_type == "node_entered" and event.node_id == "d_duty"
    ]
    assert len(duty_entries) > 1
    assert duty_entries[1].time - duty_entries[0].time == 8.0
    assert entity.node_visits.get("d_repair", 0) >= 1
    duty_completed = next(
        event
        for event in events
        if event.event_type == "subprocess_completed"
        and event.node_id == "n_duty"
    )
    assert duty_completed.data["exit_node_id"] == "d_done"
    assert entity.final_node_id == "n_end"


def test_second_test_fault_outer_path_to_shore_repair() -> None:
    process = document_from_spec(_case_spec())
    reliability = non_participating_reliability(process)
    result = None
    for seed in range(120):
        candidate = run_simulation(
            process,
            reliability,
            SimulationConfig(
                entity_count=1,
                simulation_end=500,
                random_seed=seed,
            ),
        )
        entity = candidate.entities[0]
        if (
            entity.node_visits.get("n_exit_duty", 0) == 1
            and entity.node_visits.get("n_shore_repair", 0) == 1
            and entity.completed
        ):
            result = candidate
            break
    assert result is not None
    entity = result.entities[0]
    entered = [
        event.node_id
        for event in entity.history
        if event.event_type == "node_entered"
    ]
    order = [
        entered.index(node_id)
        for node_id in ("n_exit_duty", "n_disembark", "n_shore_repair", "n_end")
    ]
    assert order == sorted(order)
    assert entity.final_node_id == "n_end"


def test_agent_generated_nested_case_is_valid_and_executable() -> None:
    path = ROOT / "examples" / "agent_generated_equipment_support_nested_flow.json"
    spec = ProcessSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))
    result = validate_process(spec)
    assert result.valid is True, [issue.model_dump() for issue in result.issues]
    subprocesses = [node for node in spec.nodes if node.type == "subprocess"]
    assert [node.id for node in subprocesses] == ["storage", "duty"]
    total_nodes = 0
    total_edges = 0

    def count_scope(scope):
        nonlocal total_nodes, total_edges
        total_nodes += len(scope.nodes)
        total_edges += len(scope.edges)
        for node in scope.nodes:
            if node.subflow is not None:
                count_scope(node.subflow)

    count_scope(spec)
    assert total_nodes == 29
    assert total_edges == 29

    process = document_from_spec(spec)
    reliability = non_participating_reliability(process)
    run = run_simulation(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=500, random_seed=0),
    )
    entity = run.entities[0]
    assert entity.completed is True
    assert entity.node_visits["sto_30d"] >= 1
    assert entity.node_visits["duty_5d"] >= 1
    completed_blocks = {
        event.node_id
        for event in entity.history
        if event.event_type == "subprocess_completed"
    }
    assert {"storage", "duty"} <= completed_blocks


def test_agent_generated_nested_analysis_covers_agent_process() -> None:
    process_path = (
        ROOT / "examples" / "agent_generated_equipment_support_nested_flow.json"
    )
    analysis_path = (
        ROOT
        / "tests"
        / "fixtures"
        / "agent_generated_equipment_support_nested_analysis.json"
    )
    spec = ProcessSpec.model_validate(
        json.loads(process_path.read_text(encoding="utf-8"))
    )
    analysis = RequirementAnalysis.model_validate(
        json.loads(analysis_path.read_text(encoding="utf-8"))
    )
    analysis_result = validate_requirement_analysis(analysis)
    assert analysis_result.valid is True, [
        issue.model_dump() for issue in analysis_result.issues
    ]
    coverage = evaluate_requirement_coverage(analysis, spec)
    assert coverage.covered is True, [
        issue.model_dump() for issue in coverage.issues
    ]
    assert coverage.covered_step_count == coverage.step_count == 29
    assert coverage.covered_branch_count == coverage.branch_count == 29
    assert [
        step.id for step in analysis.steps if step.kind == "subprocess"
    ] == ["storage", "duty"]


def test_nested_content_hash_is_independent_of_scope_order() -> None:
    from app.domain.versioning import compute_content_hash

    spec = _case_spec()
    reversed_spec = _case_spec()
    reversed_spec.nodes = list(reversed(reversed_spec.nodes))
    reversed_spec.edges = list(reversed(reversed_spec.edges))
    for node in reversed_spec.nodes:
        if node.subflow is not None:
            node.subflow.nodes = list(reversed(node.subflow.nodes))
            node.subflow.edges = list(reversed(node.subflow.edges))
    assert compute_content_hash(spec) == compute_content_hash(reversed_spec)
