"""Domain-specific business rules for the equipment-support modeling profile.

These rules intentionally live in the Agent/domain layer, not in Process IR or
the Simulation Runtime. The generic engine remains name-agnostic.
"""

from __future__ import annotations

from typing import Any

from app.agent.requirements import RequirementAnalysis
from app.domain.process_ir import ProcessNode, ProcessSpec
from app.domain.validation import ValidationIssue, ValidationResult, validate_process

EQUIPMENT_TERMS = (
    "装备保障",
    "贮存",
    "值班",
    "装舰",
    "出值班",
    "下舰",
    "岸上维修",
)
ORDINARY_EQUIPMENT_NAMES = (
    "运输",
    "阵地",
    "测试",
    "短途运输",
    "装舰",
    "出值班",
    "下舰",
    "岸上维修",
    "维修",
)


def _text(value: str | None) -> str:
    return (value or "").strip()


def is_equipment_support_request(
    prompt: str,
    analysis: RequirementAnalysis | None = None,
    spec: ProcessSpec | None = None,
) -> bool:
    text = prompt or ""
    if analysis is not None:
        text += " " + (analysis.summary or "")
        text += " " + " ".join(step.name for step in analysis.steps)
    if spec is not None:
        text += " " + " ".join(node.name for node in spec.nodes)
    matches = sum(1 for term in EQUIPMENT_TERMS if term in text)
    return ("装备" in text and ("贮存" in text or "值班" in text)) or matches >= 3


def _find_root_node(spec: ProcessSpec, keyword: str) -> ProcessNode | None:
    exact = [
        node for node in spec.nodes if node.name.strip() == keyword
    ]
    if exact:
        return exact[0]
    subprocess = [
        node
        for node in spec.nodes
        if keyword in node.name and node.type == "subprocess"
    ]
    if subprocess:
        return subprocess[0]
    for node in spec.nodes:
        if keyword in node.name:
            return node
    return None


def _has_task(subflow_nodes: list[ProcessNode], keyword: str) -> bool:
    return any(
        node.type == "task" and keyword in node.name for node in subflow_nodes
    )


def _has_repair_task(subflow_nodes: list[ProcessNode]) -> bool:
    return any(
        node.type == "task" and "维修" in node.name for node in subflow_nodes
    )


def _has_detection_task(subflow_nodes: list[ProcessNode]) -> bool:
    return any(
        node.type == "task"
        and ("检测" in node.name or "测试" in node.name)
        for node in subflow_nodes
    )


def _has_fault_decision(subflow_nodes: list[ProcessNode]) -> bool:
    return any(
        node.type == "decision"
        and ("故障" in node.name or "是否" in node.name)
        for node in subflow_nodes
    )


def _ids_for(subflow_nodes: list[ProcessNode], predicate) -> set[str]:
    return {node.id for node in subflow_nodes if predicate(node)}


def _parent_repair_node(
    block: ProcessNode,
    parent_edges: list,
    node_map: dict[str, ProcessNode],
    all_edges: list,
    end_ids: set[str],
) -> ProcessNode | None:
    """Find a repair task in the parent scope wired from a failure exit.

    The user's confirmed equipment-support semantics allow repair to live in the
    parent process: subprocess -> failure exit -> parent repair -> re-enter
    subprocess. In that case repair must not be forced inside the subflow.
    """

    failure_edges = [
        edge
        for edge in parent_edges
        if edge.kind == "failure" and edge.subflow_exit in end_ids
    ]
    if not failure_edges:
        return None
    candidates: list[ProcessNode] = []
    for edge in failure_edges:
        target = node_map.get(edge.target)
        if target is not None and target.type == "task" and "维修" in target.name:
            candidates.append(target)
    for candidate in candidates:
        if any(
            edge.source == candidate.id and edge.target == block.id
            for edge in all_edges
        ):
            return candidate
    return candidates[0] if candidates else None


def _validate_block_internal(
    block: ProcessNode,
    parent_edges: list,
    node_map: dict[str, ProcessNode],
    all_edges: list,
    *,
    label: str,
    main_keyword: str,
    issues: list[dict[str, Any]],
) -> None:
    subflow = block.subflow
    if subflow is None:
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_subflow",
                "message": f"{label}必须是包含 subflow 的嵌套流程块",
                "node_id": block.id,
                "field": "subflow",
            }
        )
        return
    nodes = subflow.nodes
    if not _has_task(nodes, main_keyword):
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_main_task",
                "message": f"{label}子流程缺少{main_keyword}主任务",
                "node_id": block.id,
                "field": "subflow.nodes",
            }
        )
    if not _has_detection_task(nodes):
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_detection",
                "message": f"{label}子流程缺少检测/测试 task",
                "node_id": block.id,
                "field": "subflow.nodes",
            }
        )
    if not _has_fault_decision(nodes):
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_fault_decision",
                "message": f"{label}子流程缺少是否故障 decision",
                "node_id": block.id,
                "field": "subflow.nodes",
            }
        )
    internal_repair = _has_repair_task(nodes)
    repair_exit_ids = set(subflow.end_node_ids)
    parent_repair = (
        None
        if internal_repair
        else _parent_repair_node(
            block, parent_edges, node_map, all_edges, repair_exit_ids
        )
    )
    failure_exit_ids = {
        edge.subflow_exit
        for edge in parent_edges
        if edge.kind == "failure" and edge.subflow_exit in repair_exit_ids
    }
    if not internal_repair and parent_repair is None:
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_repair",
                "message": (
                    f"{label}子流程缺少维修 task，父流程也没有通过 "
                    "failure 出口回到本子流程的维修节点"
                ),
                "node_id": block.id,
                "field": "subflow.nodes",
            }
        )

    main_ids = _ids_for(
        nodes, lambda node: node.type == "task" and main_keyword in node.name
    )
    detect_ids = _ids_for(
        nodes,
        lambda node: node.type == "task"
        and ("检测" in node.name or "测试" in node.name),
    )
    decision_ids = _ids_for(nodes, lambda node: node.type == "decision")
    repair_ids = _ids_for(
        nodes, lambda node: node.type == "task" and "维修" in node.name
    )
    end_ids = set(subflow.end_node_ids)

    def edge_exists(source_ids: set[str], target_ids: set[str]) -> bool:
        return any(
            edge.source in source_ids and edge.target in target_ids
            for edge in subflow.edges
        )

    if not edge_exists(detect_ids, decision_ids):
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_detection_edge",
                "message": f"{label}检测任务没有连接到故障判断",
                "node_id": block.id,
                "field": "subflow.edges",
            }
        )
    fault_edges = [
        edge
        for edge in subflow.edges
        if edge.source in decision_ids
        and edge.target in repair_ids
        and edge.kind == "conditional"
    ]
    fault_exit_edges = [
        edge
        for edge in subflow.edges
        if edge.source in decision_ids and edge.target in failure_exit_ids
    ]
    if internal_repair:
        if not fault_edges:
            issues.append(
                {
                    "severity": "error",
                    "code": f"equipment_domain_{label}_missing_repair_edge",
                    "message": f"{label}故障判断没有条件分支进入维修任务",
                    "node_id": block.id,
                    "field": "subflow.edges",
                }
            )
    elif parent_repair is not None:
        if not fault_exit_edges:
            issues.append(
                {
                    "severity": "error",
                    "code": f"equipment_domain_{label}_missing_repair_edge",
                    "message": (
                        f"{label}故障判断没有连接到由父流程 failure 出口"
                        "映射的内部 end 节点"
                    ),
                    "node_id": block.id,
                    "field": "subflow.edges",
                }
            )
    elif not fault_edges:
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_repair_edge",
                "message": f"{label}故障判断没有条件分支进入维修任务",
                "node_id": block.id,
                "field": "subflow.edges",
            }
        )
    detection_nodes = [node for node in nodes if node.id in detect_ids]
    # The runtime writes test_detected/last_test_detected for every configured
    # test module. These are first-class detection results, not business
    # outcomes, so the domain rule accepts them as data-driven fault predicates.
    runtime_detection_fields = {"test_detected", "last_test_detected"}
    written_fault_attrs: set[str] = set(runtime_detection_fields)
    for detection in detection_nodes:
        for outcome in detection.outcomes:
            written_fault_attrs.update(outcome.attributes)
        for effect in [*detection.on_enter, *detection.on_complete]:
            if effect.op == "set_attribute" and effect.name:
                written_fault_attrs.add(effect.name)
            elif effect.op == "increment_counter" and effect.name:
                written_fault_attrs.add(effect.name.removeprefix("attributes."))
    if not written_fault_attrs:
        issues.append(
            {
                "severity": "warning",
                "code": f"equipment_domain_{label}_missing_detection_outcomes",
                "message": (
                    f"{label}检测任务尚未配置 outcomes/效果写出故障结果属性，"
                    "结构保留，仿真前需要补齐"
                ),
                "node_id": block.id,
                "field": "subflow.nodes",
            }
        )
    for edge in fault_edges:
        condition = edge.condition
        if (
            condition is not None
            and condition.field in runtime_detection_fields
        ):
            continue
        if (
            condition is None
            or condition.field is None
            or not condition.field.startswith("attributes.")
        ):
            issues.append(
                {
                    "severity": "error",
                    "code": f"equipment_domain_{label}_fault_condition_not_data_driven",
                    "message": (
                        f"{label}故障分支必须使用检测任务写出的 attributes.* 条件，"
                        "不能使用 failure_count/repair_count 等无关状态"
                    ),
                    "node_id": block.id,
                    "edge_id": edge.id,
                    "field": "condition",
                }
            )
            continue
        attribute = condition.field.removeprefix("attributes.")
        if attribute not in written_fault_attrs:
            issues.append(
                {
                    "severity": "error",
                    "code": f"equipment_domain_{label}_fault_condition_unwritten",
                    "message": (
                        f"{label}故障分支引用的属性 {attribute} "
                        "没有被检测任务的 outcomes/效果写入"
                    ),
                    "node_id": block.id,
                    "edge_id": edge.id,
                    "field": "condition",
                }
            )
    parent_loop = parent_repair is not None and any(
        edge.source == parent_repair.id and edge.target == block.id
        for edge in all_edges
    )
    if not edge_exists(repair_ids, main_ids) and not parent_loop:
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_loop",
                "message": (
                    f"{label}维修后没有返回{main_keyword}主任务，"
                    "子流程内部和父流程都没有形成回路"
                ),
                "node_id": block.id,
                "field": "subflow.edges",
            }
        )
    if not edge_exists(decision_ids, end_ids):
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_normal_exit",
                "message": f"{label}故障判断没有正常退出子流程的连接",
                "node_id": block.id,
                "field": "subflow.edges",
            }
        )

    mapped_exits = {
        edge.subflow_exit
        for edge in parent_edges
        if edge.subflow_exit in end_ids
    }
    if not mapped_exits:
        issues.append(
            {
                "severity": "error",
                "code": f"equipment_domain_{label}_missing_parent_exit_mapping",
                "message": f"{label}子流程没有父连接 subflow_exit 映射",
                "node_id": block.id,
                "field": "subflow_exit",
            }
        )




def validate_equipment_support_domain(
    spec: ProcessSpec,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    storage = _find_root_node(spec, "贮存")
    duty = _find_root_node(spec, "值班")

    for label, keyword, block in (
        ("storage", "贮存", storage),
        ("duty", "值班", duty),
    ):
        if block is None:
            issues.append(
                {
                    "severity": "error",
                    "code": f"equipment_domain_{label}_missing",
                    "message": f"装备保障流程缺少{keyword}流程块",
                    "field": "nodes",
                }
            )
            continue
        parent_edges = [
            edge for edge in spec.edges if edge.source == block.id
        ]
        if block.type != "subprocess":
            issues.append(
                {
                    "severity": "error",
                    "code": f"equipment_domain_{label}_not_subprocess",
                    "message": (
                        f"装备保障领域默认要求 {keyword} 为 subprocess 嵌套流程块，"
                        f"当前类型是 {block.type}"
                    ),
                    "node_id": block.id,
                    "field": "type",
                }
            )
            continue
        _validate_block_internal(
            block,
            parent_edges,
            {node.id: node for node in spec.nodes},
            spec.edges,
            label=label,
            main_keyword=keyword,
            issues=issues,
        )

    for node in spec.nodes:
        if node.type != "subprocess":
            continue
        if node is storage or node is duty:
            continue
        if any(keyword in node.name for keyword in ORDINARY_EQUIPMENT_NAMES):
            issues.append(
                {
                    "severity": "error",
                    "code": "equipment_domain_unexpected_subprocess",
                    "message": (
                        f"装备保障默认案例只有贮存和值班是嵌套块；"
                        f"节点 {node.id}「{node.name}」不应为 subprocess"
                    ),
                    "node_id": node.id,
                    "field": "type",
                }
            )

    return issues


__all__ = [
    "is_equipment_support_request",
    "validate_equipment_support_domain",
    "validate_process_with_domain",
]


def validate_process_with_domain(spec: ProcessSpec) -> ValidationResult:
    result = validate_process(spec)
    issues = list(result.issues)
    if is_equipment_support_request("", None, spec):
        for item in validate_equipment_support_domain(spec):
            issues.append(ValidationIssue(**item))
    return ValidationResult.from_issues(issues, result.content_hash)
