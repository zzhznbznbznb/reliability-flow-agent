from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.domain_rules import (
    is_equipment_support_request,
    validate_equipment_support_domain,
    validate_process_with_domain,
)
from app.agent.process_candidate import validate_candidate
from app.domain.process_ir import ProcessSpec
from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore

ROOT = Path(__file__).resolve().parents[1]
FLAT = ROOT / "examples" / "equipment_support_longtext_flow.json"
NESTED = ROOT / "examples" / "equipment_support_nested_flow.json"


def _spec(path: Path) -> ProcessSpec:
    return ProcessSpec.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def test_flat_equipment_support_model_is_rejected() -> None:
    spec = _spec(FLAT)
    result = validate_process_with_domain(spec)
    assert result.valid is False
    codes = {issue.code for issue in result.issues}
    assert "equipment_domain_storage_not_subprocess" in codes
    assert "equipment_domain_duty_not_subprocess" in codes


def test_nested_equipment_support_model_satisfies_domain_rules() -> None:
    spec = _spec(NESTED)
    result = validate_process_with_domain(spec)
    assert result.valid is True, [issue.model_dump() for issue in result.issues]
    assert validate_equipment_support_domain(spec) == []


def test_domain_rules_require_internal_detection_fault_repair_and_loop() -> None:
    spec = _spec(NESTED)
    storage = next(node for node in spec.nodes if node.id == "n_storage")
    storage.subflow.nodes = [
        node for node in storage.subflow.nodes if node.id != "s_repair"
    ]
    storage.subflow.edges = [
        edge
        for edge in storage.subflow.edges
        if edge.source != "s_repair" and edge.target != "s_repair"
    ]
    issues = validate_equipment_support_domain(spec)
    codes = {issue["code"] for issue in issues}
    assert "equipment_domain_storage_missing_repair" in codes
    assert "equipment_domain_storage_missing_loop" in codes


def test_domain_rules_reject_unexpected_equipment_subprocess() -> None:
    spec = _spec(NESTED)
    transport = next(node for node in spec.nodes if node.id == "n_transport")
    transport.type = "subprocess"
    from app.domain.process_ir import ProcessSubflow

    transport.subflow = ProcessSubflow(
        start_node_id="t_start",
        end_node_ids=["t_end"],
        nodes=[
            {"id": "t_start", "type": "start", "name": "运输开始"},
            {"id": "t_end", "type": "end", "name": "运输结束"},
        ],
        edges=[
            {
                "id": "e_t_start_end",
                "from": "t_start",
                "to": "t_end",
                "kind": "normal",
            }
        ],
    )
    issues = validate_equipment_support_domain(spec)
    assert "equipment_domain_unexpected_subprocess" in {
        issue["code"] for issue in issues
    }


def test_candidate_validation_applies_domain_rules() -> None:
    flat = json.loads(FLAT.read_text(encoding="utf-8"))
    validation, _ = validate_candidate(flat)
    assert validation["valid"] is False
    codes = {issue["code"] for issue in validation["issues"]}
    assert "equipment_domain_storage_not_subprocess" in codes
    assert "equipment_domain_duty_not_subprocess" in codes


def test_public_validate_api_rejects_flat_equipment_support(tmp_path) -> None:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/processes/validate",
            json=json.loads(FLAT.read_text(encoding="utf-8")),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        codes = {issue["code"] for issue in body["issues"]}
        assert "equipment_domain_storage_not_subprocess" in codes
        assert "equipment_domain_duty_not_subprocess" in codes


def test_equipment_support_detection_uses_domain_structure() -> None:
    spec = _spec(FLAT)
    assert is_equipment_support_request("", None, spec) is True
    generic = ProcessSpec(
        name="普通审批流程",
        start_node_id="start",
        end_node_ids=["end"],
        nodes=[
            {"id": "start", "type": "start", "name": "开始"},
            {"id": "work", "type": "task", "name": "审批", "duration": 1},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        edges=[
            {"id": "e1", "from": "start", "to": "work", "kind": "normal"},
            {"id": "e2", "from": "work", "to": "end", "kind": "normal"},
        ],
    )
    assert is_equipment_support_request("", None, generic) is False


def test_domain_rules_require_data_driven_fault_condition() -> None:
    spec = _spec(NESTED)
    storage = next(node for node in spec.nodes if node.id == "n_storage")
    edge = next(
        edge for edge in storage.subflow.edges if edge.id == "e_s_dec_repair"
    )
    from app.domain.process_ir import Condition

    edge.condition = Condition(op="gt", field="failure_count", value=0)
    issues = validate_equipment_support_domain(spec)
    assert "equipment_domain_storage_fault_condition_not_data_driven" in {
        issue["code"] for issue in issues
    }


def test_domain_rules_find_exact_duty_block_even_after_exit_duty() -> None:
    spec = _spec(NESTED)
    spec.nodes = sorted(
        spec.nodes,
        key=lambda node: 0 if node.id == "n_exit_duty" else 1,
    )
    issues = validate_equipment_support_domain(spec)
    assert "equipment_domain_duty_not_subprocess" not in {
        issue["code"] for issue in issues
    }
    assert "equipment_domain_duty_missing_subflow" not in {
        issue["code"] for issue in issues
    }
