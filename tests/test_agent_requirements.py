from __future__ import annotations

from copy import deepcopy

from app.agent.requirements import (
    RequirementAnalysis,
    evaluate_requirement_coverage,
)
from app.domain.process_ir import ProcessSpec
from app.domain.validation import validate_process


def equipment_support_spec() -> dict:
    return {
        "schema_version": "process-ir/1.0",
        "name": "装备岸上保障流程",
        "description": "贮存、运输、测试、维修、装舰、值班和岸上维修。",
        "status_catalog": [],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {
                "id": "storage",
                "type": "task",
                "name": "贮存",
                "duration": 30,
                "outcomes": [
                    {
                        "id": "storage_done",
                        "name": "贮存完成",
                        "weight": 1,
                        "attributes": {"storage_ok": True},
                    }
                ],
            },
            {
                "id": "storage_check",
                "type": "task",
                "name": "贮存内部检测",
                "duration": 1,
                "outcomes": [
                    {
                        "id": "check_ok",
                        "name": "检测合格",
                        "weight": 0.9,
                        "attributes": {"storage_ok": True},
                    },
                    {
                        "id": "check_bad",
                        "name": "检测不合格",
                        "weight": 0.1,
                        "attributes": {"storage_ok": False},
                    },
                ],
            },
            {"id": "storage_gate", "type": "decision", "name": "贮存检测判断"},
            {"id": "transport", "type": "task", "name": "运输", "duration": 2},
            {"id": "site", "type": "task", "name": "进入阵地测试场", "duration": 1},
            {
                "id": "test1",
                "type": "task",
                "name": "第一次测试",
                "duration": 1,
                "outcomes": [
                    {
                        "id": "test1_ok",
                        "name": "测试通过",
                        "weight": 0.8,
                        "attributes": {"test1_passed": True},
                    },
                    {
                        "id": "test1_bad",
                        "name": "测试不通过",
                        "weight": 0.2,
                        "attributes": {"test1_passed": False},
                    },
                ],
            },
            {"id": "test1_gate", "type": "decision", "name": "第一次测试判断"},
            {"id": "repair", "type": "task", "name": "维修", "duration": 2},
            {
                "id": "test2",
                "type": "task",
                "name": "第二次测试",
                "duration": 1,
                "outcomes": [
                    {
                        "id": "test2_ok",
                        "name": "测试通过",
                        "weight": 0.8,
                        "attributes": {"test2_passed": True},
                    },
                    {
                        "id": "test2_bad",
                        "name": "测试不通过",
                        "weight": 0.2,
                        "attributes": {"test2_passed": False},
                    },
                ],
            },
            {"id": "test2_gate", "type": "decision", "name": "第二次测试判断"},
            {
                "id": "short_transport",
                "type": "task",
                "name": "短途运输",
                "duration": 1,
            },
            {"id": "load_ship", "type": "task", "name": "装舰", "duration": 1},
            {
                "id": "duty",
                "type": "task",
                "name": "值班",
                "duration": 5,
                "outcomes": [
                    {
                        "id": "duty_ok",
                        "name": "值班检测合格",
                        "weight": 0.9,
                        "attributes": {"duty_ok": True},
                    },
                    {
                        "id": "duty_bad",
                        "name": "值班检测不合格",
                        "weight": 0.1,
                        "attributes": {"duty_ok": False},
                    },
                ],
            },
            {"id": "duty_gate", "type": "decision", "name": "值班检测判断"},
            {"id": "leave_duty", "type": "task", "name": "出值班", "duration": 1},
            {"id": "disembark", "type": "task", "name": "下舰", "duration": 1},
            {
                "id": "shore_repair",
                "type": "task",
                "name": "岸上维修",
                "duration": 3,
            },
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_storage", "from": "start", "to": "storage", "kind": "normal"},
            {
                "id": "e_storage_check",
                "from": "storage",
                "to": "storage_check",
                "kind": "normal",
            },
            {
                "id": "e_check_gate",
                "from": "storage_check",
                "to": "storage_gate",
                "kind": "normal",
            },
            {
                "id": "e_gate_transport",
                "from": "storage_gate",
                "to": "transport",
                "kind": "conditional",
                "priority": 10,
                "condition": {
                    "op": "eq",
                    "field": "attributes.storage_ok",
                    "value": True,
                },
            },
            {
                "id": "e_gate_recheck",
                "from": "storage_gate",
                "to": "storage_check",
                "kind": "default",
            },
            {
                "id": "e_transport_site",
                "from": "transport",
                "to": "site",
                "kind": "normal",
            },
            {"id": "e_site_test1", "from": "site", "to": "test1", "kind": "normal"},
            {
                "id": "e_test1_gate",
                "from": "test1",
                "to": "test1_gate",
                "kind": "normal",
            },
            {
                "id": "e_test1_test2",
                "from": "test1_gate",
                "to": "test2",
                "kind": "conditional",
                "priority": 10,
                "condition": {
                    "op": "eq",
                    "field": "attributes.test1_passed",
                    "value": True,
                },
            },
            {
                "id": "e_test1_repair",
                "from": "test1_gate",
                "to": "repair",
                "kind": "default",
            },
            {
                "id": "e_repair_test1",
                "from": "repair",
                "to": "test1",
                "kind": "normal",
            },
            {
                "id": "e_test2_gate",
                "from": "test2",
                "to": "test2_gate",
                "kind": "normal",
            },
            {
                "id": "e_test2_short",
                "from": "test2_gate",
                "to": "short_transport",
                "kind": "conditional",
                "priority": 10,
                "condition": {
                    "op": "eq",
                    "field": "attributes.test2_passed",
                    "value": True,
                },
            },
            {
                "id": "e_test2_repair",
                "from": "test2_gate",
                "to": "repair",
                "kind": "default",
            },
            {
                "id": "e_short_load",
                "from": "short_transport",
                "to": "load_ship",
                "kind": "normal",
            },
            {
                "id": "e_load_duty",
                "from": "load_ship",
                "to": "duty",
                "kind": "normal",
            },
            {"id": "e_duty_gate", "from": "duty", "to": "duty_gate", "kind": "normal"},
            {
                "id": "e_duty_loop",
                "from": "duty_gate",
                "to": "duty",
                "kind": "conditional",
                "priority": 10,
                "condition": {
                    "op": "eq",
                    "field": "attributes.duty_ok",
                    "value": True,
                },
            },
            {
                "id": "e_duty_leave",
                "from": "duty_gate",
                "to": "leave_duty",
                "kind": "default",
            },
            {
                "id": "e_leave_disembark",
                "from": "leave_duty",
                "to": "disembark",
                "kind": "normal",
            },
            {
                "id": "e_disembark_repair",
                "from": "disembark",
                "to": "shore_repair",
                "kind": "normal",
            },
            {
                "id": "e_shore_end",
                "from": "shore_repair",
                "to": "end",
                "kind": "normal",
            },
        ],
        "guards": {"max_node_visits": 10000},
    }


def equipment_support_analysis() -> dict:
    spec = equipment_support_spec()
    steps = [
        {
            "id": node["id"],
            "name": node["name"],
            "kind": node["type"],
            **(
                {"duration": node["duration"]}
                if node.get("duration") is not None
                else {}
            ),
        }
        for node in spec["nodes"]
    ]
    loop_targets = {
        ("storage_gate", "storage_check"),
        ("repair", "test1"),
        ("test2_gate", "repair"),
        ("duty_gate", "duty"),
    }
    branches = [
        {
            "id": edge["id"].removeprefix("e_"),
            "from_step": edge["from"],
            "to_step": edge["to"],
            "kind": edge["kind"],
            "loop": (edge["from"], edge["to"]) in loop_targets,
            **(
                {"condition": f"{edge['from']} 到 {edge['to']} 的条件"}
                if edge["kind"] == "conditional"
                else {}
            ),
        }
        for edge in spec["edges"]
    ]
    return {
        "summary": (
            "装备先贮存并循环检测，随后运输至测试场，完成两次测试与维修循环，"
            "再短途运输、装舰、循环值班检测，最后出值班、下舰并岸上维修。"
        ),
        "steps": steps,
        "branches": branches,
        "ambiguities": [],
    }


def test_equipment_support_case_is_structurally_complete() -> None:
    spec = ProcessSpec.model_validate(equipment_support_spec())
    result = validate_process(spec)
    assert result.valid is True, [issue.model_dump() for issue in result.issues]
    analysis = RequirementAnalysis.model_validate(equipment_support_analysis())
    coverage = evaluate_requirement_coverage(analysis, spec)
    assert coverage.covered is True, [
        issue.model_dump() for issue in coverage.issues
    ]
    assert coverage.step_count == coverage.covered_step_count
    assert coverage.branch_count == coverage.covered_branch_count
    assert coverage.step_count == len(spec.nodes)
    assert coverage.branch_count == len(spec.edges)


def test_coverage_rejects_dropped_step_branch_and_invented_node() -> None:
    spec = ProcessSpec.model_validate(equipment_support_spec())
    analysis = RequirementAnalysis.model_validate(equipment_support_analysis())

    missing_step = deepcopy(equipment_support_spec())
    missing_step["nodes"] = [
        node for node in missing_step["nodes"] if node["id"] != "duty"
    ]
    missing_step["edges"] = [
        edge
        for edge in missing_step["edges"]
        if edge["from"] != "duty" and edge["to"] != "duty"
    ]
    coverage = evaluate_requirement_coverage(
        analysis, ProcessSpec.model_validate(missing_step)
    )
    assert coverage.covered is False
    assert "requirement_step_missing" in {
        issue.code for issue in coverage.issues
    }

    missing_branch = deepcopy(equipment_support_spec())
    missing_branch["edges"] = [
        edge
        for edge in missing_branch["edges"]
        if edge["id"] != "e_repair_test1"
    ]
    coverage = evaluate_requirement_coverage(
        analysis, ProcessSpec.model_validate(missing_branch)
    )
    assert coverage.covered is False
    assert "requirement_branch_missing" in {
        issue.code for issue in coverage.issues
    }

    invented = deepcopy(equipment_support_spec())
    invented["nodes"].insert(
        -1,
        {
            "id": "extra_task",
            "type": "task",
            "name": "未在需求中出现的活动",
            "duration": 1,
        },
    )
    invented["edges"].insert(
        -1,
        {
            "id": "e_shore_extra",
            "from": "shore_repair",
            "to": "extra_task",
            "kind": "normal",
        },
    )
    invented["edges"].insert(
        -1,
        {
            "id": "e_extra_end",
            "from": "extra_task",
            "to": "end",
            "kind": "normal",
        },
    )
    coverage = evaluate_requirement_coverage(
        analysis, ProcessSpec.model_validate(invented)
    )
    assert coverage.covered is False
    assert "requirement_node_not_analyzed" in {
        issue.code for issue in coverage.issues
    }


def test_blocking_ambiguity_blocks_coverage() -> None:
    spec = ProcessSpec.model_validate(equipment_support_spec())
    data = equipment_support_analysis()
    data["ambiguities"] = [
        {
            "id": "missing_storage_duration",
            "question": "贮存持续多久？",
            "blocks_generation": True,
        }
    ]
    analysis = RequirementAnalysis.model_validate(data)
    coverage = evaluate_requirement_coverage(analysis, spec)
    assert coverage.covered is False
    assert "requirement_ambiguity_unresolved" in {
        issue.code for issue in coverage.issues
    }
from app.agent.requirements import validate_requirement_analysis


def test_analysis_is_valid_when_it_matches_process_ir_structure() -> None:
    analysis = RequirementAnalysis.model_validate(equipment_support_analysis())
    result = validate_requirement_analysis(analysis)
    assert result.valid is True, [issue.model_dump() for issue in result.issues]


def test_analysis_validator_rejects_timed_decision_and_missing_default() -> None:
    data = equipment_support_analysis()
    for step in data["steps"]:
        if step["id"] == "test1_gate":
            step["duration"] = 1
    data["branches"] = [
        branch
        for branch in data["branches"]
        if branch["id"] != "test1_repair"
    ]
    analysis = RequirementAnalysis.model_validate(data)
    result = validate_requirement_analysis(analysis)
    codes = {issue.code for issue in result.issues}
    assert result.valid is False
    assert "requirement_decision_has_duration" in codes
    assert "requirement_decision_without_default" in codes


def test_analysis_validator_rejects_conditional_without_condition() -> None:
    data = equipment_support_analysis()
    for branch in data["branches"]:
        if branch["id"] == "test1_test2":
            branch.pop("condition", None)
    analysis = RequirementAnalysis.model_validate(data)
    result = validate_requirement_analysis(analysis)
    assert result.valid is False
    assert "requirement_conditional_without_condition" in {
        issue.code for issue in result.issues
    }
