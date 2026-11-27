from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.domain_rules import validate_process_with_domain
from app.agent.requirements import (
    RequirementAnalysis,
    evaluate_requirement_coverage,
    validate_requirement_analysis,
)
from app.domain.process_ir import ProcessSpec
from app.domain.validation import validate_process
from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from app.simulation.errors import SimulationValidationError
from tests.helpers import (
    document_from_spec,
    minimal_process_dict,
    non_participating_reliability,
    spec_from,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = (
    ROOT / "tests" / "fixtures" / "equipment_support_parent_repair_flow.json"
)
ANALYSIS_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "equipment_support_parent_repair_analysis.json"
)


def _load_spec() -> ProcessSpec:
    return ProcessSpec.model_validate(
        json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    )


def _load_analysis() -> RequirementAnalysis:
    return RequirementAnalysis.model_validate(
        json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    )


def _edge(spec: ProcessSpec, source: str, target: str, kind: str | None = None):
    return next(
        edge
        for edge in spec.edges
        if edge.source == source
        and edge.target == target
        and (kind is None or edge.kind == kind)
    )


def test_requirement_analysis_allows_structure_only_and_continuous_loop() -> None:
    result = validate_requirement_analysis(_load_analysis())
    assert result.valid is True, [issue.model_dump() for issue in result.issues]
    assert all(issue.severity != "error" for issue in result.issues)
    codes = {issue.code for issue in result.issues}
    assert "requirement_task_missing_duration" in codes
    assert "requirement_continuous_loop" in codes
    assert "requirement_cannot_reach_end" not in codes


def test_structure_valid_ir_can_preview_but_not_simulate() -> None:
    spec = _load_spec()
    result = validate_process_with_domain(spec)
    assert result.valid is True, [issue.model_dump() for issue in result.issues]
    assert result.structure_valid is True
    assert result.config_pending is True
    assert result.simulation_ready is False
    assert result.errors == []

    coverage = evaluate_requirement_coverage(_load_analysis(), spec)
    assert coverage.covered is True, [
        issue.model_dump() for issue in coverage.issues
    ]

    process = document_from_spec(spec)
    reliability = non_participating_reliability(process)
    with pytest.raises(SimulationValidationError) as captured:
        run_simulation(
            process,
            reliability,
            SimulationConfig(entity_count=1, simulation_end=10, random_seed=0),
        )
    codes = {issue.code for issue in captured.value.issues}
    assert "missing_duration" in codes


def test_storage_subprocess_fault_exit_parent_repair_and_reentry() -> None:
    spec = _load_spec()
    storage = next(node for node in spec.nodes if node.id == "n_storage_phase")
    assert storage.type == "subprocess"
    assert storage.subflow is not None
    assert storage.subflow.end_node_ids == ["st_normal_end", "st_fault_end"]

    normal = _edge(spec, "n_storage_phase", "n_transport", "normal")
    assert normal.subflow_exit == "st_normal_end"
    failure = _edge(spec, "n_storage_phase", "n_storage_repair", "failure")
    assert failure.subflow_exit == "st_fault_end"
    _edge(spec, "n_storage_repair", "n_storage_phase", "normal")

    internal_ids = {node.id for node in storage.subflow.nodes}
    assert internal_ids == {
        "st_start",
        "st_store",
        "st_check",
        "st_fault_judge",
        "st_normal_end",
        "st_fault_end",
    }
    assert _edge(storage.subflow, "st_fault_judge", "st_fault_end", "default")
    assert _edge(
        storage.subflow, "st_fault_judge", "st_normal_end", "conditional"
    )


def test_duty_continuous_internal_loop_fault_exit_parent_repair() -> None:
    spec = _load_spec()
    duty = next(node for node in spec.nodes if node.id == "n_duty_phase")
    assert duty.type == "subprocess"
    assert duty.subflow is not None
    assert duty.subflow.end_node_ids == ["du_fault_end"]

    loop = _edge(
        duty.subflow, "du_fault_judge", "du_duty", "conditional"
    )
    assert loop.target == "du_duty"
    assert "循环" in (loop.label or "")
    assert duty.subflow.start_node_id == "du_start"
    assert _edge(duty.subflow, "du_fault_judge", "du_fault_end", "default")

    failure = _edge(spec, "n_duty_phase", "n_duty_repair", "failure")
    assert failure.subflow_exit == "du_fault_end"
    _edge(spec, "n_duty_repair", "n_duty_phase", "normal")

    # No normal parent exit: duty only loops internally or exits on fault.
    assert not any(
        edge.source == "n_duty_phase" and edge.kind == "normal"
        for edge in spec.edges
    )


def test_first_and_second_test_failure_paths_are_independent() -> None:
    spec = _load_spec()
    _edge(spec, "n_test1_judge", "n_short_haul", "conditional")
    _edge(spec, "n_test1_judge", "n_test1_repair", "default")
    _edge(spec, "n_test1_repair", "n_spare_replace", "normal")
    _edge(spec, "n_spare_replace", "n_test1", "normal")
    assert not any(
        edge.source == "n_test1_judge" and edge.target == "n_leave_mission"
        for edge in spec.edges
    )

    _edge(spec, "n_test2_judge", "n_duty_phase", "conditional")
    _edge(spec, "n_test2_judge", "n_leave_mission", "default")
    _edge(spec, "n_leave_mission", "n_debark", "normal")
    _edge(spec, "n_debark", "n_shore_repair", "normal")
    _edge(spec, "n_shore_repair", "s_end", "normal")
    assert not any(
        edge.source == "n_test2_judge" and edge.target == "n_test1_repair"
        for edge in spec.edges
    )


def test_plain_non_nested_flow_remains_strictly_valid() -> None:
    result = validate_process(spec_from(minimal_process_dict()))
    assert result.valid is True
    assert result.structure_valid is True
    assert result.config_pending is False
    assert result.simulation_ready is True
    assert result.errors == []


def test_invalid_references_duplicate_ids_and_bad_nesting_are_blocked() -> None:
    duplicate = minimal_process_dict()
    duplicate["nodes"].append(
        {"id": "work", "type": "task", "name": "重复", "duration": 1}
    )
    duplicate_result = validate_process(spec_from(duplicate))
    assert duplicate_result.structure_valid is False
    assert "duplicate_node_id" in {issue.code for issue in duplicate_result.issues}

    unknown = minimal_process_dict()
    unknown["edges"].append(
        {"id": "e_bad", "from": "missing", "to": "end", "kind": "normal"}
    )
    unknown_result = validate_process(spec_from(unknown))
    assert unknown_result.structure_valid is False
    assert "unknown_edge_source" in {issue.code for issue in unknown_result.issues}

    bad_nesting = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    for node in bad_nesting["nodes"]:
        if node["id"] == "n_storage_phase":
            node.pop("subflow", None)
    with pytest.raises(ValidationError):
        ProcessSpec.model_validate(bad_nesting)

    nested_on_1_0 = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    nested_on_1_0["schema_version"] = "process-ir/1.0"
    nesting_result = validate_process(ProcessSpec.model_validate(nested_on_1_0))
    assert nesting_result.structure_valid is False
    assert "nested_requires_schema_1_1" in {
        issue.code for issue in nesting_result.issues
    }


def test_preview_svg_renders_without_saving(tmp_path) -> None:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
    )
    spec_payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    with TestClient(app) as client:
        before = client.get("/api/processes").json()
        response = client.post("/api/processes/preview.svg", json=spec_payload)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in response.text
        assert "n_storage_phase" in response.text
        assert "n_duty_phase" in response.text
        after = client.get("/api/processes").json()
        assert after == before


def test_preview_targets_the_agent_generated_ir_exactly() -> None:
    spec = _load_spec()
    # The fixture is the IR produced in the failing session; do not regenerate.
    assert spec.schema_version == "process-ir/1.1"
    assert len(spec.nodes) == 18
    assert len(spec.edges) == 20
    storage = next(node for node in spec.nodes if node.id == "n_storage_phase")
    duty = next(node for node in spec.nodes if node.id == "n_duty_phase")
    assert storage.subflow is not None and len(storage.subflow.nodes) == 6
    assert duty.subflow is not None and len(duty.subflow.nodes) == 5
