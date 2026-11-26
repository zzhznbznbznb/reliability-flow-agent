from __future__ import annotations

from copy import deepcopy

from app.domain.validation import condition_to_text, validate_process
from tests.helpers import issue_codes, loop_process_dict, minimal_process_dict, spec_from


def test_minimal_process_is_valid() -> None:
    result = validate_process(spec_from(minimal_process_dict()))
    assert result.valid is True
    assert result.errors == []


def test_duplicate_node_id_is_reported() -> None:
    data = minimal_process_dict()
    data["nodes"].append({"id": "work", "type": "task", "name": "重复", "duration": 1})
    result = validate_process(spec_from(data))
    assert "duplicate_node_id" in issue_codes(result.issues)


def test_unknown_edge_endpoints_are_reported() -> None:
    data = minimal_process_dict()
    data["edges"].append(
        {"id": "e_bad_source", "from": "missing", "to": "end", "kind": "normal"}
    )
    data["edges"].append(
        {"id": "e_bad_target", "from": "start", "to": "missing", "kind": "normal"}
    )
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "unknown_edge_source" in codes
    assert "unknown_edge_target" in codes


def test_start_reference_errors_are_reported() -> None:
    data = minimal_process_dict()
    data["start_node_id"] = "work"
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "start_node_type_mismatch" in codes

    data = minimal_process_dict()
    data["start_node_id"] = "missing"
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "unknown_start_node" in codes

    data = minimal_process_dict()
    data["nodes"].append({"id": "start2", "type": "start", "name": "另一个开始"})
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "multiple_start_nodes" in codes


def test_end_reference_errors_are_reported() -> None:
    data = minimal_process_dict()
    data["end_node_ids"] = []
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "missing_end_reference" in codes

    data = minimal_process_dict()
    data["end_node_ids"] = ["work"]
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "end_node_type_mismatch" in codes
    assert "end_node_not_listed" in codes


def test_duration_rules_are_enforced() -> None:
    data = minimal_process_dict()
    data["nodes"][1]["duration"] = None
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "missing_duration" in codes

    data = minimal_process_dict()
    data["nodes"][0]["duration"] = 0
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "duration_not_allowed" in codes


def test_decision_branch_rules_are_enforced() -> None:
    data = loop_process_dict()
    data["edges"] = [
        edge for edge in data["edges"] if edge["id"] != "e_check_end"
    ]
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "decision_without_condition" in codes or "decision_too_few_branches" in codes

    data = loop_process_dict()
    data["edges"] = [
        edge for edge in data["edges"] if edge["id"] != "e_check_rework"
    ]
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "decision_without_default" in codes


def test_conditional_edges_require_conditions() -> None:
    data = minimal_process_dict()
    data["edges"][1]["kind"] = "conditional"
    data["edges"][1]["condition"] = None
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "missing_condition" in codes


def test_default_edges_must_not_have_conditions() -> None:
    data = loop_process_dict()
    for edge in data["edges"]:
        if edge["id"] == "e_check_rework":
            edge["condition"] = {
                "op": "eq",
                "field": "attributes.quality_ok",
                "value": False,
            }
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "condition_not_allowed" in codes


def test_unreachable_node_and_dead_end_are_reported() -> None:
    data = minimal_process_dict()
    data["nodes"].append(
        {"id": "orphan", "type": "task", "name": "孤立任务", "duration": 1}
    )
    data["edges"].append(
        {"id": "e_orphan_end", "from": "orphan", "to": "end", "kind": "normal"}
    )
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "unreachable_node" in codes

    data = minimal_process_dict()
    data["nodes"].append(
        {"id": "dead", "type": "task", "name": "死路", "duration": 1}
    )
    data["edges"].append(
        {"id": "e_work_dead", "from": "work", "to": "dead", "kind": "normal"}
    )
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "cannot_reach_end" in codes or "multiple_normal_edges" in codes


def test_valid_loop_with_decision_and_updated_exit_state_passes() -> None:
    result = validate_process(spec_from(loop_process_dict()))
    assert result.valid is True


def test_cycle_without_exit_is_reported() -> None:
    data = minimal_process_dict()
    data["nodes"] = [
        {"id": "start", "type": "start", "name": "开始"},
        {"id": "a", "type": "task", "name": "A", "duration": 1},
        {"id": "b", "type": "task", "name": "B", "duration": 1},
        {"id": "end", "type": "end", "name": "结束"},
    ]
    data["edges"] = [
        {"id": "e_start_a", "from": "start", "to": "a", "kind": "normal"},
        {"id": "e_a_b", "from": "a", "to": "b", "kind": "normal"},
        {"id": "e_b_a", "from": "b", "to": "a", "kind": "normal"},
    ]
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "cycle_without_exit" in codes


def test_cycle_without_decision_is_reported() -> None:
    data = loop_process_dict()
    data["nodes"][2] = {
        "id": "check",
        "type": "task",
        "name": "检查任务",
        "duration": 0.1,
    }
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "cycle_without_decision" in codes


def test_cycle_exit_state_must_be_updated_inside_cycle() -> None:
    data = loop_process_dict()
    for node in data["nodes"]:
        if node["id"] == "rework":
            node.pop("outcomes", None)
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "cycle_exit_not_updated" in codes


def test_unknown_condition_fields_and_visit_targets_are_reported() -> None:
    data = loop_process_dict()
    data["edges"][2]["condition"] = {
        "op": "eq",
        "field": "not_a_field",
        "value": True,
    }
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "unsupported_condition_field" in codes

    data = loop_process_dict()
    data["edges"][2]["condition"] = {
        "op": "gte",
        "field": "node_visits.missing",
        "value": 2,
    }
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "unknown_visit_target" in codes


def test_unknown_status_reference_is_reported() -> None:
    data = minimal_process_dict()
    data["status_catalog"] = [
        {"id": "operational", "name": "运行", "counts_as_available": True}
    ]
    data["nodes"][1]["status_on_enter"] = "missing_status"
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "unknown_status" in codes


def test_condition_to_text_renders_nested_expression() -> None:
    data = loop_process_dict()
    condition = spec_from(data).edges[2].condition
    text = condition_to_text(condition)
    assert "attributes.quality_ok" in text
    assert "==" in text


def test_duplicate_edge_and_start_end_degree_rules_are_reported() -> None:
    data = minimal_process_dict()
    data["edges"].append(
        {
            "id": "e_work_end",
            "from": "work",
            "to": "end",
            "kind": "normal",
        }
    )
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "duplicate_edge_id" in codes

    data = minimal_process_dict()
    data["edges"].append(
        {"id": "e_end_start", "from": "end", "to": "start", "kind": "normal"}
    )
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "start_has_incoming_edge" in codes
    assert "end_has_outgoing_edge" in codes


def test_multiple_defaults_are_reported() -> None:
    data = loop_process_dict()
    data["edges"].append(
        {
            "id": "e_check_rework_default_2",
            "from": "check",
            "to": "rework",
            "kind": "default",
        }
    )
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "multiple_default_edges" in codes


def test_outcomes_are_only_allowed_on_task_nodes() -> None:
    data = loop_process_dict()
    data["nodes"][2]["outcomes"] = [
        {"id": "x", "name": "X", "weight": 1, "attributes": {"quality_ok": True}}
    ]
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "outcomes_not_allowed" in codes
    assert "decision_outcomes_not_allowed" in codes


def test_unknown_counter_is_reported() -> None:
    data = minimal_process_dict()
    data["nodes"][1]["on_complete"] = [
        {"op": "increment_counter", "name": "mystery_counter", "by": 1}
    ]
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "unsupported_counter" in codes


def test_condition_depth_limit_is_reported() -> None:
    data = loop_process_dict()
    condition = {"op": "eq", "field": "attributes.quality_ok", "value": True}
    for _ in range(10):
        condition = {"op": "not", "conditions": [condition]}
    data["edges"][2]["condition"] = condition
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "condition_too_deep" in codes


def test_start_and_end_must_have_correct_degrees() -> None:
    data = minimal_process_dict()
    data["edges"] = [
        {"id": "e_start_work", "from": "start", "to": "work", "kind": "normal"},
        {"id": "e_start_end", "from": "start", "to": "end", "kind": "normal"},
        {"id": "e_work_end", "from": "work", "to": "end", "kind": "normal"},
    ]
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "invalid_start_exit" in codes
    assert "end_without_incoming_edge" not in codes


def test_nan_numeric_condition_is_rejected() -> None:
    data = loop_process_dict()
    data["edges"][2]["condition"] = {
        "op": "gte",
        "field": "node_visits.rework",
        "value": float("nan"),
    }
    codes = issue_codes(validate_process(spec_from(data)).issues)
    assert "invalid_comparison_value" in codes
