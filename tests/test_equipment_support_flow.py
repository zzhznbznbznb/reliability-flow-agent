from __future__ import annotations

import json
from pathlib import Path

from app.agent.requirements import (
    RequirementAnalysis,
    evaluate_requirement_coverage,
    validate_requirement_analysis,
)
from app.domain.process_ir import ProcessEdge, ProcessSpec
from app.domain.validation import validate_process
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from tests.helpers import document_from_spec, non_participating_reliability

ROOT = Path(__file__).resolve().parents[1]
PROCESS_PATH = ROOT / "examples" / "equipment_support_longtext_flow.json"
ANALYSIS_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "equipment_support_requirement_analysis.json"
)


def _load_process() -> ProcessSpec:
    return ProcessSpec.model_validate(
        json.loads(PROCESS_PATH.read_text(encoding="utf-8"))
    )


def _load_analysis() -> RequirementAnalysis:
    return RequirementAnalysis.model_validate(
        json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    )


def _edges(
    spec: ProcessSpec,
    source: str,
    target: str,
    kind: str | None = None,
) -> list[ProcessEdge]:
    return [
        edge
        for edge in spec.edges
        if edge.source == source
        and edge.target == target
        and (kind is None or edge.kind == kind)
    ]


def _reachable(spec: ProcessSpec, start: str) -> set[str]:
    adjacency: dict[str, list[str]] = {node.id: [] for node in spec.nodes}
    for edge in spec.edges:
        adjacency[edge.source].append(edge.target)
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop()
        for target in adjacency[current]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _assert_condition(edge: ProcessEdge, field: str, value: object) -> None:
    assert edge.condition is not None
    assert edge.condition.op == "eq"
    assert edge.condition.field == field
    assert edge.condition.value == value


def test_equipment_support_process_is_valid_and_fully_covered() -> None:
    spec = _load_process()
    process_result = validate_process(spec)
    assert process_result.valid is True, [
        issue.model_dump() for issue in process_result.issues
    ]

    analysis = _load_analysis()
    analysis_result = validate_requirement_analysis(analysis)
    assert analysis_result.valid is True, [
        issue.model_dump() for issue in analysis_result.issues
    ]

    coverage = evaluate_requirement_coverage(analysis, spec)
    assert coverage.covered is True, [
        issue.model_dump() for issue in coverage.issues
    ]
    assert coverage.covered_step_count == coverage.step_count == 20
    assert coverage.covered_branch_count == coverage.branch_count == 23

    ambiguity_ids = {item.id for item in analysis.ambiguities}
    assert "amb_storage_nesting" in ambiguity_ids
    assert "amb_duty_nesting" in ambiguity_ids
    assert "amb_detection_predicates" in ambiguity_ids
    assert "amb_repair_reentry" in ambiguity_ids
    assert "amb_exit_duty_vs_end" in ambiguity_ids
    assert "amb_second_test_fail_target" not in ambiguity_ids


def test_first_test_failure_repairs_and_returns_to_first_test() -> None:
    spec = _load_process()
    abnormal = _edges(spec, "n_dec_first_test", "n_repair", "default")
    assert len(abnormal) == 1
    assert abnormal[0].condition is None
    returns = _edges(spec, "n_repair", "n_first_test", "normal")
    assert len(returns) == 1
    assert not _edges(spec, "n_dec_first_test", "n_short_transport", "default")


def test_first_test_normal_chain_reaches_second_test() -> None:
    spec = _load_process()
    normal = _edges(
        spec, "n_dec_first_test", "n_short_transport", "conditional"
    )
    assert len(normal) == 1
    _assert_condition(normal[0], "attributes.first_test_result", "normal")
    assert len(_edges(spec, "n_short_transport", "n_load_ship", "normal")) == 1
    assert len(_edges(spec, "n_load_ship", "n_second_test", "normal")) == 1


def test_second_test_normal_goes_to_duty_and_reaches_end() -> None:
    spec = _load_process()
    normal = _edges(spec, "n_dec_second_test", "n_duty", "conditional")
    assert len(normal) == 1
    _assert_condition(normal[0], "attributes.second_test_result", "normal")
    assert "n_end" in _reachable(spec, "n_duty")


def test_second_test_failure_uses_exit_duty_chain() -> None:
    spec = _load_process()
    abnormal = _edges(spec, "n_dec_second_test", "n_exit_duty", "default")
    assert len(abnormal) == 1
    assert abnormal[0].condition is None
    assert not _edges(spec, "n_dec_second_test", "n_repair")
    assert len(_edges(spec, "n_exit_duty", "n_disembark", "normal")) == 1
    assert len(_edges(spec, "n_disembark", "n_shore_repair", "normal")) == 1
    assert len(_edges(spec, "n_shore_repair", "n_end", "normal")) == 1


def test_storage_failure_loops_to_storage_inspection() -> None:
    spec = _load_process()
    failed = _edges(
        spec, "n_dec_storage_inspect", "n_storage_inspect", "default"
    )
    assert len(failed) == 1
    assert failed[0].condition is None
    passed = _edges(
        spec, "n_dec_storage_inspect", "n_transport", "conditional"
    )
    assert len(passed) == 1
    _assert_condition(
        passed[0], "attributes.storage_inspection_result", "pass"
    )


def test_duty_failure_goes_to_exit_duty() -> None:
    spec = _load_process()
    failed = _edges(
        spec, "n_dec_duty_inspect", "n_exit_duty", "default"
    )
    assert len(failed) == 1
    assert failed[0].condition is None
    passed = _edges(spec, "n_dec_duty_inspect", "n_duty", "conditional")
    assert len(passed) == 1
    _assert_condition(passed[0], "attributes.duty_inspection_result", "pass")


def test_all_conditional_edges_have_explicit_conditions() -> None:
    spec = _load_process()
    conditional = [edge for edge in spec.edges if edge.kind == "conditional"]
    assert len(conditional) == 4
    for edge in conditional:
        assert edge.condition is not None
        assert edge.condition.field is not None
        assert edge.condition.field.startswith("attributes.")
def test_duty_pass_reenters_full_five_day_duty() -> None:
    spec = _load_process()
    process = document_from_spec(spec)
    reliability = non_participating_reliability(process)
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(entity_count=1, simulation_end=200, random_seed=0),
    )
    entity = result.entities[0]
    duty_entries = [
        event
        for event in entity.history
        if event.event_type == "node_entered" and event.node_id == "n_duty"
    ]
    duty_outcomes = [
        event
        for event in entity.history
        if event.event_type == "business_outcome"
        and event.node_id == "n_duty_inspect"
    ]
    assert len(duty_entries) == 2
    assert duty_entries[1].time - duty_entries[0].time == 6.0
    assert [event.data["outcome_id"] for event in duty_outcomes] == [
        "pass",
        "fail",
    ]
    next_duty = next(
        event
        for event in duty_entries[1:]
        if event.time == duty_outcomes[0].time
    )
    assert next_duty.time == duty_outcomes[0].time
    exit_duty = next(
        event
        for event in entity.history
        if event.event_type == "node_entered" and event.node_id == "n_exit_duty"
    )
    assert exit_duty.time == duty_outcomes[1].time
    assert entity.completed is True
