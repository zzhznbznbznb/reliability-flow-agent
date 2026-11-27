"""Semantic validation for Process IR.

Validation is intentionally strict: unsupported or ambiguous process semantics
are reported instead of being silently repaired. The validator never mutates
the supplied ProcessSpec.
"""

from __future__ import annotations

import math
import re
from collections import Counter, deque
from typing import Any, Literal

from pydantic import Field

from app.domain.process_ir import (
    ATTRIBUTE_PATTERN,
    Condition,
    Effect,
    ProcessEdge,
    ProcessNode,
    ProcessSpec,
    StrictModel,
)
from app.domain.versioning import compute_content_hash

BUILTIN_CONDITION_FIELDS = {
    "entity_id",
    "currently_failed",
    "ever_failed",
    "failure_count",
    "repair_count",
    "current_status",
    "test_detected",
    "last_test_detected",
    "unavailable_time",
}
NUMERIC_COMPARISONS = {"gt", "gte", "lt", "lte"}
LOGICAL_OPS = {"and", "or", "not"}
MAX_NESTING_DEPTH = 8

# Codes that describe machine-executable configuration still missing from a
# structurally valid process. They do not block previewing/editing the canvas,
# but they must block simulation until the user supplies real values.
CONFIG_PENDING_CODES = {
    "missing_duration",
    "missing_condition",
    "attribute_not_written",
}


class ValidationIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None
    scope_path: list[str] | None = None


class ValidationResult(StrictModel):
    valid: bool
    structure_valid: bool = True
    config_pending: bool = False
    simulation_ready: bool = True
    issues: list[ValidationIssue] = Field(default_factory=list)
    content_hash: str

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @classmethod
    def from_issues(
        cls,
        issues: list[ValidationIssue],
        content_hash: str,
    ) -> "ValidationResult":
        errors = [issue for issue in issues if issue.severity == "error"]
        config_pending = any(
            issue.code in CONFIG_PENDING_CODES for issue in issues
        )
        structure_valid = not errors
        return cls(
            valid=structure_valid,
            structure_valid=structure_valid,
            config_pending=config_pending,
            simulation_ready=structure_valid and not config_pending,
            issues=issues,
            content_hash=content_hash,
        )


class _Issues:
    def __init__(self) -> None:
        self.items: list[ValidationIssue] = []

    def error(
        self,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        edge_id: str | None = None,
        field: str | None = None,
    ) -> None:
        self.items.append(
            ValidationIssue(
                severity="error",
                code=code,
                message=message,
                node_id=node_id,
                edge_id=edge_id,
                field=field,
            )
        )

    def warning(
        self,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        edge_id: str | None = None,
        field: str | None = None,
    ) -> None:
        self.items.append(
            ValidationIssue(
                severity="warning",
                code=code,
                message=message,
                node_id=node_id,
                edge_id=edge_id,
                field=field,
            )
        )


def _describe_field(field: str) -> str:
    return field


def _validate_condition_field(
    field: str,
    node_map: dict[str, ProcessNode],
    issues: _Issues,
    *,
    node_id: str | None,
    edge_id: str | None,
) -> str | None:
    if field in BUILTIN_CONDITION_FIELDS:
        return None

    if field.startswith("attributes."):
        name = field.removeprefix("attributes.")
        if not name or not re.fullmatch(ATTRIBUTE_PATTERN, name):
            issues.error(
                "invalid_condition_field",
                f"条件字段 {field} 中的属性名不合法",
                node_id=node_id,
                edge_id=edge_id,
                field=field,
            )
        return name

    if field.startswith("node_visits."):
        target = field.removeprefix("node_visits.")
        if target not in node_map:
            issues.error(
                "unknown_visit_target",
                f"条件字段 {field} 引用了不存在的节点 {target}",
                node_id=node_id,
                edge_id=edge_id,
                field=field,
            )
        return None

    issues.error(
        "unsupported_condition_field",
        f"不支持的条件字段: {field}",
        node_id=node_id,
        edge_id=edge_id,
        field=field,
    )
    return None


def _validate_condition(
    condition: Condition,
    node_map: dict[str, ProcessNode],
    issues: _Issues,
    *,
    node_id: str | None,
    edge_id: str | None,
    depth: int = 0,
    counter: list[int] | None = None,
    attribute_refs: set[str] | None = None,
) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if depth > 8:
        issues.error(
            "condition_too_deep",
            "条件表达式嵌套超过 8 层",
            node_id=node_id,
            edge_id=edge_id,
        )
        return
    if counter[0] > 64:
        if counter[0] == 65:
            issues.error(
                "condition_too_large",
                "条件表达式包含超过 64 个子条件",
                node_id=node_id,
                edge_id=edge_id,
            )
        return

    if condition.op in LOGICAL_OPS:
        for child in condition.conditions or []:
            _validate_condition(
                child,
                node_map,
                issues,
                node_id=node_id,
                edge_id=edge_id,
                depth=depth + 1,
                counter=counter,
                attribute_refs=attribute_refs,
            )
        return

    field = condition.field or ""
    attribute = _validate_condition_field(
        field,
        node_map,
        issues,
        node_id=node_id,
        edge_id=edge_id,
    )
    if attribute and attribute_refs is not None:
        attribute_refs.add(attribute)

    if condition.op in NUMERIC_COMPARISONS:
        value = condition.value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            issues.error(
                "invalid_comparison_value",
                f"{condition.op} 条件的比较值必须是有限数字",
                node_id=node_id,
                edge_id=edge_id,
                field=field,
            )
    if condition.op in {"in", "not_in"} and not isinstance(condition.value, list):
        issues.error(
            "invalid_membership_value",
            f"{condition.op} 条件的 value 必须是数组",
            node_id=node_id,
            edge_id=edge_id,
            field=field,
        )


def _condition_references(condition: Condition | None) -> tuple[set[str], bool]:
    """Return custom attributes plus whether the condition has dynamic state."""
    if condition is None:
        return set(), False
    if condition.op in LOGICAL_OPS:
        attributes: set[str] = set()
        dynamic = False
        for child in condition.conditions or []:
            child_attributes, child_dynamic = _condition_references(child)
            attributes.update(child_attributes)
            dynamic = dynamic or child_dynamic
        return attributes, dynamic
    field = condition.field or ""
    if field.startswith("attributes."):
        return {field.removeprefix("attributes.")}, False
    return set(), True


def _validate_effect(
    effect: Effect,
    node: ProcessNode,
    status_ids: set[str],
    issues: _Issues,
    written_attributes: set[str],
) -> None:
    if effect.op == "set_attribute" and effect.name:
        written_attributes.add(effect.name)
    if effect.op == "increment_counter" and effect.name:
        if not (
            effect.name in {"failure_count", "repair_count"}
            or effect.name.startswith("attributes.")
        ):
            issues.error(
                "unsupported_counter",
                f"不支持的计数器: {effect.name}",
                node_id=node.id,
                field="on_enter/on_complete",
            )
    if effect.op == "set_status" and isinstance(effect.value, str):
        if effect.value not in status_ids:
            issues.error(
                "unknown_status",
                f"效果引用了未定义状态: {effect.value}",
                node_id=node.id,
                field="on_enter/on_complete",
            )
    if (
        effect.op == "set_state"
        and effect.name == "current_status"
        and isinstance(effect.value, str)
    ):
        if effect.value not in status_ids:
            issues.error(
                "unknown_status",
                f"状态转换引用了未定义状态: {effect.value}",
                node_id=node.id,
                field="on_enter/on_complete",
            )


def _validate_node_effects(
    node: ProcessNode,
    status_ids: set[str],
    issues: _Issues,
    written_attributes: set[str],
) -> None:
    for effect in [*node.on_enter, *node.on_complete]:
        _validate_effect(effect, node, status_ids, issues, written_attributes)


def _strongly_connected_components(
    node_ids: list[str], adjacency: dict[str, list[str]]
) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def strong_connect(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)

        for target in adjacency.get(node_id, []):
            if target not in indices:
                strong_connect(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])

        if lowlinks[node_id] == indices[node_id]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node_id:
                    break
            components.append(component)

    for node_id in node_ids:
        if node_id not in indices:
            strong_connect(node_id)
    return components


def _reachable(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for target in adjacency.get(current, []):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _scope_has_decision(nodes: list[ProcessNode]) -> bool:
    """Return True when a scope contains a decision, including nested blocks."""

    for node in nodes:
        if node.type == "decision":
            return True
        if node.type == "subprocess" and node.subflow is not None:
            if _scope_has_decision(node.subflow.nodes):
                return True
    return False


def _iter_all_nodes(spec: ProcessSpec):
    for node in spec.nodes:
        yield node
        if node.subflow is not None:
            sub_spec = ProcessSpec(
                schema_version=spec.schema_version,
                name=f"{spec.name}/{node.name}",
                status_catalog=spec.status_catalog,
                start_node_id=node.subflow.start_node_id,
                end_node_ids=node.subflow.end_node_ids,
                nodes=node.subflow.nodes,
                edges=node.subflow.edges,
                guards=node.subflow.guards,
            )
            yield from _iter_all_nodes(sub_spec)


def _iter_all_edges(spec: ProcessSpec):
    for edge in spec.edges:
        yield edge
    for node in spec.nodes:
        if node.subflow is not None:
            sub_spec = ProcessSpec(
                schema_version=spec.schema_version,
                name=f"{spec.name}/{node.name}",
                status_catalog=spec.status_catalog,
                start_node_id=node.subflow.start_node_id,
                end_node_ids=node.subflow.end_node_ids,
                nodes=node.subflow.nodes,
                edges=node.subflow.edges,
                guards=node.subflow.guards,
            )
            yield from _iter_all_edges(sub_spec)


def validate_process(
    spec: ProcessSpec,
    *,
    _scope_path: tuple[str, ...] = (),
    _check_global_ids: bool = True,
) -> ValidationResult:
    issues = _Issues()
    node_ids = [node.id for node in spec.nodes]
    node_map = {node.id: node for node in spec.nodes}

    if _check_global_ids:
        all_node_ids = [node.id for node in _iter_all_nodes(spec)]
        for node_id, count in Counter(all_node_ids).items():
            if count > 1:
                issues.error(
                    "duplicate_global_node_id",
                    f"嵌套流程中节点 ID 全局重复: {node_id}",
                    node_id=node_id,
                    field="nodes",
                )
        all_edge_ids = [edge.id for edge in _iter_all_edges(spec)]
        for edge_id, count in Counter(all_edge_ids).items():
            if count > 1:
                issues.error(
                    "duplicate_global_edge_id",
                    f"嵌套流程中连接 ID 全局重复: {edge_id}",
                    edge_id=edge_id,
                    field="edges",
                )

    duplicates = [node_id for node_id, count in Counter(node_ids).items() if count > 1]
    for node_id in duplicates:
        issues.error(
            "duplicate_node_id",
            f"节点 ID 重复: {node_id}",
            node_id=node_id,
            field="nodes",
        )

    status_ids: set[str] = set()
    for status in spec.status_catalog:
        if status.id in status_ids:
            issues.error(
                "duplicate_status_id",
                f"状态 ID 重复: {status.id}",
                field="status_catalog",
            )
        status_ids.add(status.id)

    start_nodes = [node for node in spec.nodes if node.type == "start"]
    if not start_nodes:
        issues.error("missing_start", "流程缺少 start 节点", field="nodes")
    elif len(start_nodes) > 1:
        issues.error(
            "multiple_start_nodes",
            f"流程包含多个 start 节点: {', '.join(n.id for n in start_nodes)}",
            field="nodes",
        )

    if not spec.start_node_id:
        issues.error("missing_start_reference", "start_node_id 不能为空", field="start_node_id")
    else:
        start_node = node_map.get(spec.start_node_id)
        if start_node is None:
            issues.error(
                "unknown_start_node",
                f"start_node_id 引用了不存在的节点: {spec.start_node_id}",
                node_id=spec.start_node_id,
                field="start_node_id",
            )
        elif start_node.type != "start":
            issues.error(
                "start_node_type_mismatch",
                f"start_node_id 指向的节点 {start_node.id} 不是 start 类型",
                node_id=start_node.id,
                field="start_node_id",
            )
        if len(start_nodes) == 1 and spec.start_node_id != start_nodes[0].id:
            issues.error(
                "start_reference_mismatch",
                f"start_node_id 应为 {start_nodes[0].id}",
                field="start_node_id",
            )

    end_nodes = [node for node in spec.nodes if node.type == "end"]
    if not end_nodes:
        issues.error("missing_end", "流程缺少 end 节点", field="nodes")
    if not spec.end_node_ids:
        issues.error("missing_end_reference", "end_node_ids 不能为空", field="end_node_ids")

    end_refs = set(spec.end_node_ids)
    if len(end_refs) != len(spec.end_node_ids):
        issues.error("duplicate_end_reference", "end_node_ids 包含重复项", field="end_node_ids")
    for end_id in spec.end_node_ids:
        end_node = node_map.get(end_id)
        if end_node is None:
            issues.error(
                "unknown_end_node",
                f"end_node_ids 引用了不存在的节点: {end_id}",
                node_id=end_id,
                field="end_node_ids",
            )
        elif end_node.type != "end":
            issues.error(
                "end_node_type_mismatch",
                f"end_node_ids 指向的节点 {end_id} 不是 end 类型",
                node_id=end_id,
                field="end_node_ids",
            )
    for end_node in end_nodes:
        if end_node.id not in end_refs:
            issues.error(
                "end_node_not_listed",
                f"end 节点 {end_node.id} 未列入 end_node_ids",
                node_id=end_node.id,
                field="end_node_ids",
            )

    outgoing: dict[str, list[ProcessEdge]] = {node_id: [] for node_id in node_map}
    incoming: dict[str, list[ProcessEdge]] = {node_id: [] for node_id in node_map}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}
    edge_ids = [edge.id for edge in spec.edges]
    for edge_id, count in Counter(edge_ids).items():
        if count > 1:
            issues.error(
                "duplicate_edge_id",
                f"连接 ID 重复: {edge_id}",
                edge_id=edge_id,
                field="edges",
            )

    attribute_refs: set[tuple[str, str | None]] = set()
    for edge in spec.edges:
        source = node_map.get(edge.source)
        target = node_map.get(edge.target)
        if source is None:
            issues.error(
                "unknown_edge_source",
                f"连接 {edge.id} 的起点不存在: {edge.source}",
                edge_id=edge.id,
                field="from",
            )
        if target is None:
            issues.error(
                "unknown_edge_target",
                f"连接 {edge.id} 的终点不存在: {edge.target}",
                edge_id=edge.id,
                field="to",
            )
        if source is not None:
            outgoing[source.id].append(edge)
        if target is not None:
            incoming[target.id].append(edge)
        if source is not None and target is not None:
            adjacency[source.id].append(target.id)

        if edge.kind == "conditional":
            if edge.condition is None:
                issues.warning(
                    "missing_condition",
                    (
                        f"条件连接 {edge.id} 暂未配置机器可执行 condition，"
                        "已按业务分支语义保留，仿真前需要补齐"
                    ),
                    edge_id=edge.id,
                    field="condition",
                )
            else:
                refs: set[str] = set()
                _validate_condition(
                    edge.condition,
                    node_map,
                    issues,
                    node_id=edge.source,
                    edge_id=edge.id,
                    attribute_refs=refs,
                )
                for ref in refs:
                    attribute_refs.add((ref, edge.id))
        elif edge.condition is not None:
            issues.error(
                "condition_not_allowed",
                f"{edge.kind} 类型的连接 {edge.id} 不应包含 condition",
                edge_id=edge.id,
                field="condition",
            )

        if edge.source == edge.target and edge.kind in {"normal", "failure"}:
            issues.error(
                "unconditional_self_loop",
                f"自循环连接 {edge.id} 必须使用 conditional 或 default 类型",
                edge_id=edge.id,
            )

        if edge.subflow_exit is not None:
            if source is None or source.type != "subprocess":
                issues.error(
                    "subflow_exit_on_non_subprocess",
                    f"连接 {edge.id} 的 subflow_exit 只能用于 subprocess 出口",
                    edge_id=edge.id,
                    field="subflow_exit",
                )
            elif edge.kind not in {"normal", "failure"}:
                issues.error(
                    "invalid_subflow_exit_edge_kind",
                    f"连接 {edge.id} 映射子流程出口时只能是 normal 或 failure",
                    edge_id=edge.id,
                    field="subflow_exit",
                )

    for node_id, edges in outgoing.items():
        counts = Counter(edge.kind for edge in edges)
        if node_map[node_id].type != "subprocess":
            for kind in ("normal", "failure", "default"):
                if counts[kind] > 1:
                    issues.error(
                        f"multiple_{kind}_edges",
                        f"节点 {node_id} 包含多个 {kind} 出口",
                        node_id=node_id,
                        field="edges",
                    )
        if any(edge.kind == "default" for edge in edges):
            for edge in edges:
                if edge.kind in {"normal", "failure"}:
                    issues.error(
                        "ambiguous_default_mix",
                        f"节点 {node_id} 的 default 出口不能与 {edge.kind} 出口混用",
                        node_id=node_id,
                        edge_id=edge.id,
                    )

        if not edges and node_map[node_id].type != "end":
            issues.error(
                "missing_outgoing_edge",
                f"节点 {node_id} 没有出口，流程会在此处中断",
                node_id=node_id,
            )

        if node_map[node_id].type == "decision":
            if len(edges) < 2:
                issues.error(
                    "decision_too_few_branches",
                    f"判断节点 {node_id} 至少需要两个出口",
                    node_id=node_id,
                )
            if counts["normal"] or counts["failure"]:
                issues.error(
                    "decision_invalid_edge_kind",
                    f"判断节点 {node_id} 只能使用 conditional 或 default 出口",
                    node_id=node_id,
                )
            if counts["conditional"] == 0:
                issues.error(
                    "decision_without_condition",
                    f"判断节点 {node_id} 缺少条件出口",
                    node_id=node_id,
                )
            if counts["default"] == 0:
                issues.error(
                    "decision_without_default",
                    f"判断节点 {node_id} 缺少 default 兜底出口",
                    node_id=node_id,
                )
        elif node_map[node_id].type == "start":
            if len(edges) != 1 or edges[0].kind != "normal":
                issues.error(
                    "invalid_start_exit",
                    f"start 节点 {node_id} 必须且只能有一个 normal 出口",
                    node_id=node_id,
                )
        elif node_map[node_id].type == "task":
            kinds = set(counts)
            if counts["conditional"]:
                if counts["default"] == 0:
                    issues.error(
                        "missing_default_branch",
                        f"节点 {node_id} 含条件出口，必须提供 default 兜底出口",
                        node_id=node_id,
                    )
            elif len(edges) > 1:
                if kinds != {"normal", "failure"}:
                    issues.error(
                        "ambiguous_branching",
                        f"节点 {node_id} 的多出口组合不受支持；请使用 conditional + default，或 normal + failure",
                        node_id=node_id,
                    )
            elif edges and edges[0].kind != "normal":
                issues.error(
                    "invalid_single_exit",
                    f"节点 {node_id} 只有一个出口时必须是 normal",
                    node_id=node_id,
                )

    if start_nodes:
        for edge in incoming.get(start_nodes[0].id, []):
            issues.error(
                "start_has_incoming_edge",
                f"start 节点 {start_nodes[0].id} 不应有入边: {edge.id}",
                node_id=start_nodes[0].id,
                edge_id=edge.id,
            )
    components = _strongly_connected_components(list(node_map), adjacency)
    cycle_nodes: set[str] = set()
    for component in components:
        component_set = set(component)
        is_cycle = len(component) > 1 or any(
            edge.source == edge.target and edge.source in component_set
            for edge in spec.edges
        )
        if is_cycle:
            cycle_nodes.update(component)

    for end_node in end_nodes:
        if outgoing.get(end_node.id):
            for edge in outgoing[end_node.id]:
                issues.error(
                    "end_has_outgoing_edge",
                    f"end 节点 {end_node.id} 不应有出边: {edge.id}",
                    node_id=end_node.id,
                    edge_id=edge.id,
                )
        if not incoming.get(end_node.id):
            if cycle_nodes:
                issues.warning(
                    "unreachable_end",
                    (
                        f"end 节点 {end_node.id} 没有入边；当前流程包含持续循环，"
                        "该 end 仅作为结构占位，运行时会由仿真终止时间结束"
                    ),
                    node_id=end_node.id,
                )
            else:
                issues.error(
                    "end_without_incoming_edge",
                    f"end 节点 {end_node.id} 没有入边",
                    node_id=end_node.id,
                )

    written_attributes: set[str] = set()
    node_written_attributes: dict[str, set[str]] = {}
    for node in spec.nodes:
        node_attributes: set[str] = set()
        if node.type != "task" and node.duration is not None:
            issues.error(
                "duration_not_allowed",
                f"{node.type} 节点 {node.id} 不应设置 duration",
                node_id=node.id,
                field="duration",
            )
        if node.type == "task" and node.duration is None:
            issues.warning(
                "missing_duration",
                (
                    f"task 节点 {node.id} 尚未配置 duration，"
                    "结构允许保留，仿真前必须补齐"
                ),
                node_id=node.id,
                field="duration",
            )
        for status_field in ("status_on_enter", "status_on_complete"):
            status_value = getattr(node, status_field)
            if status_value is not None and status_value not in status_ids:
                issues.error(
                    "unknown_status",
                    f"节点 {node.id} 的 {status_field} 引用了未定义状态: {status_value}",
                    node_id=node.id,
                    field=status_field,
                )
        if node.outcomes and node.type != "task":
            issues.error(
                "outcomes_not_allowed",
                f"只有 task 节点可以设置 outcomes，节点 {node.id} 不合法",
                node_id=node.id,
                field="outcomes",
            )
        if node.outcomes:
            outcome_ids = [outcome.id for outcome in node.outcomes]
            for outcome_id, count in Counter(outcome_ids).items():
                if count > 1:
                    issues.error(
                        "duplicate_outcome_id",
                        f"节点 {node.id} 的业务结果 ID 重复: {outcome_id}",
                        node_id=node.id,
                        field="outcomes",
                    )
            total_weight = sum(outcome.weight for outcome in node.outcomes)
            if total_weight <= 0:
                issues.error(
                    "invalid_outcome_weights",
                    f"节点 {node.id} 的业务结果权重之和必须大于 0",
                    node_id=node.id,
                    field="outcomes",
                )
            for outcome in node.outcomes:
                node_attributes.update(outcome.attributes)
        _validate_node_effects(node, status_ids, issues, node_attributes)
        node_written_attributes[node.id] = node_attributes
        written_attributes.update(node_attributes)

        if node.type == "subprocess":
            if spec.schema_version == "process-ir/1.0":
                issues.error(
                    "nested_requires_schema_1_1",
                    f"subprocess 节点 {node.id} 需要使用 process-ir/1.1",
                    node_id=node.id,
                    field="schema_version",
                )
            if len(_scope_path) >= MAX_NESTING_DEPTH:
                issues.error(
                    "max_nesting_depth_exceeded",
                    f"嵌套层级超过上限 {MAX_NESTING_DEPTH}",
                    node_id=node.id,
                )
            elif node.subflow is None:
                issues.error(
                    "missing_subflow",
                    f"subprocess 节点 {node.id} 缺少 subflow",
                    node_id=node.id,
                    field="subflow",
                )
            else:
                sub_spec = ProcessSpec(
                    schema_version=spec.schema_version,
                    name=f"{spec.name}/{node.name}",
                    status_catalog=spec.status_catalog,
                    start_node_id=node.subflow.start_node_id,
                    end_node_ids=node.subflow.end_node_ids,
                    nodes=node.subflow.nodes,
                    edges=node.subflow.edges,
                    guards=node.subflow.guards,
                )
                sub_result = validate_process(
                    sub_spec,
                    _scope_path=_scope_path + (node.id,),
                    _check_global_ids=False,
                )
                for sub_issue in sub_result.issues:
                    if sub_issue.scope_path is None:
                        sub_issue.scope_path = list(
                            _scope_path + (node.id,)
                        )
                    issues.items.append(sub_issue)

                subflow = node.subflow
                exit_ids = set(subflow.end_node_ids)
                mapped: dict[str, list[ProcessEdge]] = {}
                for edge in outgoing.get(node.id, []):
                    if edge.subflow_exit is None:
                        continue
                    if edge.subflow_exit not in exit_ids:
                        issues.error(
                            "unknown_subflow_exit",
                            (
                                f"连接 {edge.id} 引用了子流程 {node.id} 中"
                                f"不存在的出口 {edge.subflow_exit}"
                            ),
                            node_id=node.id,
                            edge_id=edge.id,
                            field="subflow_exit",
                        )
                        continue
                    mapped.setdefault(edge.subflow_exit, []).append(edge)
                for end_id, mapped_edges in mapped.items():
                    if len(mapped_edges) > 1:
                        issues.error(
                            "duplicate_subflow_exit_mapping",
                            (
                                f"子流程 {node.id} 的出口 {end_id} "
                                "被多个父连接重复映射"
                            ),
                            node_id=node.id,
                            field="subflow_exit",
                        )
                if len(exit_ids) > 1:
                    for end_id in exit_ids:
                        if end_id not in mapped:
                            issues.error(
                                "subflow_exit_not_mapped",
                                (
                                    f"子流程 {node.id} 的出口 {end_id} "
                                    "没有对应的父流程连接"
                                ),
                                node_id=node.id,
                                field="subflow_exit",
                            )
                parent_edges = outgoing.get(node.id, [])
                for edge in parent_edges:
                    if edge.kind not in {"normal", "failure"}:
                        issues.error(
                            "subprocess_invalid_exit_kind",
                            (
                                f"子流程 {node.id} 的父连接 {edge.id} "
                                "只能是 normal 或 failure"
                            ),
                            node_id=node.id,
                            edge_id=edge.id,
                            field="kind",
                        )
                if len(parent_edges) > 1:
                    for edge in parent_edges:
                        if edge.subflow_exit is None:
                            issues.error(
                                "subflow_exit_required",
                                (
                                    f"子流程 {node.id} 有多个父出口时，"
                                    f"连接 {edge.id} 必须指定 subflow_exit"
                                ),
                                node_id=node.id,
                                edge_id=edge.id,
                                field="subflow_exit",
                            )

    for attribute, edge_id in sorted(attribute_refs):
        if attribute not in written_attributes:
            issues.warning(
                "attribute_not_written",
                (
                    f"条件引用的属性 {attribute} 在当前作用域内没有被任何 "
                    "outcomes 或效果写入，仿真前需要补齐；"
                    "当前先保留业务分支结构"
                ),
                edge_id=edge_id,
                field=f"attributes.{attribute}",
            )

    if start_nodes and spec.start_node_id == start_nodes[0].id:
        reachable = _reachable(start_nodes[0].id, adjacency)
        for node in spec.nodes:
            if node.id not in reachable:
                issues.error(
                    "unreachable_node",
                    f"节点 {node.id} 无法从 start 到达",
                    node_id=node.id,
                )

    valid_end_ids = [end_id for end_id in spec.end_node_ids if end_id in node_map]
    if valid_end_ids:
        reverse: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        for edge in spec.edges:
            if edge.source in node_map and edge.target in node_map:
                reverse[edge.target].append(edge.source)
        can_reach_end: set[str] = set(valid_end_ids)
        queue = deque(valid_end_ids)
        while queue:
            current = queue.popleft()
            for previous in reverse.get(current, []):
                if previous not in can_reach_end:
                    can_reach_end.add(previous)
                    queue.append(previous)
        can_reach_cycle = set(cycle_nodes)
        queue = list(cycle_nodes)
        while queue:
            current = queue.pop()
            for previous in reverse.get(current, []):
                if previous not in can_reach_cycle:
                    can_reach_cycle.add(previous)
                    queue.append(previous)
        start_continuous = bool(
            start_nodes
            and spec.start_node_id not in can_reach_end
            and spec.start_node_id in can_reach_cycle
        )
        for node in spec.nodes:
            if node.id not in can_reach_end:
                if node.id in can_reach_cycle:
                    issues.warning(
                        "continuous_loop",
                        (
                            f"节点 {node.id} 处于持续循环或其前置路径中，"
                            "按设计不会到达 end，视为合法的持续流程"
                        ),
                        node_id=node.id,
                    )
                else:
                    issues.error(
                        "cannot_reach_end",
                        f"节点 {node.id} 无法到达任何 end 节点",
                        node_id=node.id,
                    )
        if start_continuous:
            issues.warning(
                "continuous_process",
                (
                    "从 start 节点进入持续循环，按设计不会到达 end；"
                    "运行时会由仿真终止时间结束"
                ),
                node_id=spec.start_node_id,
            )
        elif start_nodes and spec.start_node_id not in can_reach_end:
            issues.error(
                "no_path_to_end",
                "从 start 节点无法到达任何 end 节点",
                node_id=spec.start_node_id,
            )

    for component in components:
        component_set = set(component)
        is_cycle = len(component) > 1 or any(
            edge.source == edge.target and edge.source in component_set
            for edge in spec.edges
        )
        if not is_cycle:
            continue
        members = ", ".join(sorted(component))
        exit_edges = [
            edge
            for edge in spec.edges
            if edge.source in component_set and edge.target not in component_set
        ]
        has_decision = any(
            node_map[node_id].type == "decision"
            or (
                node_map[node_id].type == "subprocess"
                and node_map[node_id].subflow is not None
                and _scope_has_decision(node_map[node_id].subflow.nodes)
            )
            for node_id in component
        )
        has_subprocess = any(
            node_map[node_id].type == "subprocess" for node_id in component
        )
        if not has_decision:
            issues.error(
                "cycle_without_decision",
                f"循环 {members} 缺少 decision 节点，无法表达退出条件",
                field="nodes",
            )
        if not exit_edges:
            if has_decision and has_subprocess:
                issues.warning(
                    "continuous_loop",
                    (
                        f"循环 {members} 通过子流程内部判断持续运行，"
                        "没有外层退出连接，视为合法的持续循环"
                    ),
                    field="edges",
                )
            else:
                issues.error(
                    "cycle_without_exit",
                    f"循环 {members} 没有退出连接，可能无限执行",
                    field="edges",
                )
        component_attributes: set[str] = set()
        for node_id in component:
            component_attributes.update(node_written_attributes.get(node_id, set()))
        for exit_edge in exit_edges:
            attributes, dynamic = _condition_references(exit_edge.condition)
            missing = attributes - component_attributes
            if missing and not dynamic:
                issues.error(
                    "cycle_exit_not_updated",
                    f"循环 {members} 的退出条件依赖属性 {', '.join(sorted(missing))}，"
                    "但循环内部没有任何节点更新这些属性",
                    edge_id=exit_edge.id,
                    field="condition",
                )

    for node in spec.nodes:
        if node.type == "decision" and node.outcomes:
            issues.error(
                "decision_outcomes_not_allowed",
                f"判断节点 {node.id} 不能设置 outcomes",
                node_id=node.id,
                field="outcomes",
            )

    for issue in issues.items:
        if issue.scope_path is None:
            issue.scope_path = list(_scope_path)

    return ValidationResult.from_issues(
        issues.items,
        compute_content_hash(spec),
    )


def condition_to_text(condition: Condition | None) -> str:
    if condition is None:
        return ""
    if condition.op in LOGICAL_OPS:
        joined = {
            "and": " 且 ",
            "or": " 或 ",
            "not": "非 ",
        }[condition.op]
        parts = [condition_to_text(item) for item in condition.conditions or []]
        if condition.op == "not":
            return f"非 ({parts[0] if parts else ''})"
        return f"({joined.join(parts)})"
    field = condition.field or "?"
    if condition.op == "exists":
        return f"{field} 存在"
    if condition.op == "is_null":
        return f"{field} 为空"
    if condition.op in {"in", "not_in"}:
        operator = "属于" if condition.op == "in" else "不属于"
        return f"{field} {operator} {condition.value}"
    symbols = {
        "eq": "==",
        "ne": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }
    return f"{field} {symbols.get(condition.op, condition.op)} {condition.value}"
