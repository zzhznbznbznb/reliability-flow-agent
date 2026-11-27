"""Validation for Reliability IR.

This validator only checks reliability configuration and its binding to a
Process IR document. It never runs a simulation, never samples failures and
never mutates the supplied models.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from app.domain.process_ir import ProcessDocument, StrictModel
from app.domain.reliability_ir import ReliabilitySpec

VALID_LAMBDA_UNITS = {"per_hour", "per_day", "per_month", "per_year"}
VALID_MODULE_TYPES = {"activity", "stage", "test"}


class ReliabilityIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    field: str | None = None


class ReliabilityValidationResult(StrictModel):
    valid: bool
    issues: list[ReliabilityIssue] = Field(default_factory=list)
    process_id: str
    process_version: int
    process_hash: str
    participant_count: int = 0
    test_module_count: int = 0
    stage_module_count: int = 0

    @property
    def errors(self) -> list[ReliabilityIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


class _Issues:
    def __init__(self) -> None:
        self.items: list[ReliabilityIssue] = []

    def error(
        self,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        field: str | None = None,
    ) -> None:
        self.items.append(
            ReliabilityIssue(
                severity="error",
                code=code,
                message=message,
                node_id=node_id,
                field=field,
            )
        )

    def warning(
        self,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        field: str | None = None,
    ) -> None:
        self.items.append(
            ReliabilityIssue(
                severity="warning",
                code=code,
                message=message,
                node_id=node_id,
                field=field,
            )
        )


def _lambda_is_valid(value: float | None) -> bool:
    if value is None:
        return False
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    numeric = float(value)
    return math.isfinite(numeric) and numeric >= 0


def _rate_is_valid(value: float | None) -> bool:
    if value is None:
        return False
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    numeric = float(value)
    return math.isfinite(numeric) and 0 <= numeric <= 1


def _iter_process_nodes(process: ProcessDocument):
    yield from _iter_nodes_from_list(process.nodes)


def _iter_nodes_from_list(nodes):
    for node in nodes:
        yield node
        if node.subflow is not None:
            yield from _iter_nodes_from_list(node.subflow.nodes)


def _iter_subflow_tasks(node) -> list:
    if node.subflow is None:
        return []
    result = []
    for child in node.subflow.nodes:
        if child.type == "task":
            result.append(child)
        if child.subflow is not None:
            result.extend(_iter_subflow_tasks(child))
    return result


def _first_stage_task(node):
    tasks = _iter_subflow_tasks(node)
    return tasks[0] if tasks else None


def validate_reliability(
    process: ProcessDocument, spec: ReliabilitySpec
) -> ReliabilityValidationResult:
    issues = _Issues()
    participant_count = 0
    test_module_count = 0
    stage_module_count = 0

    if spec.process_version != process.version:
        issues.error(
            "reliability_process_version_mismatch",
            f"可靠性配置绑定流程版本 v{spec.process_version}，"
            f"但当前流程文档为 v{process.version}",
            field="process_version",
        )
    if spec.process_hash != process.content_hash:
        issues.error(
            "reliability_process_hash_mismatch",
            "可靠性配置绑定的流程内容哈希与当前 Process IR 不一致",
            field="process_hash",
        )

    all_nodes = {node.id: node for node in _iter_process_nodes(process)}
    task_map = {
        node_id: node
        for node_id, node in all_nodes.items()
        if node.type == "task"
    }
    configured_ids = [config.node_id for config in spec.nodes]
    duplicate_ids = sorted(
        {node_id for node_id in configured_ids if configured_ids.count(node_id) > 1}
    )
    for node_id in duplicate_ids:
        issues.error(
            "reliability_duplicate_node",
            f"节点 {node_id} 存在重复的可靠性配置",
            node_id=node_id,
            field="nodes",
        )

    for config in spec.nodes:
        node = all_nodes.get(config.node_id)
        if node is None:
            issues.error(
                "reliability_unknown_node",
                f"可靠性配置引用了当前流程中不存在的节点: {config.node_id}",
                node_id=config.node_id,
                field="nodes",
            )
            continue

        module_type = getattr(config, "module_type", "activity")
        if module_type not in VALID_MODULE_TYPES:
            issues.error(
                "reliability_unsupported_module_type",
                f"节点 {node.id} 使用了不支持的可靠性模块类型: {module_type}",
                node_id=node.id,
                field="module_type",
            )
            continue

        lambda_unit = getattr(config, "lambda_unit", "per_day")
        if lambda_unit not in VALID_LAMBDA_UNITS:
            issues.error(
                "reliability_invalid_lambda_unit",
                f"节点 {node.id} 的 lambda 单位不受支持: {lambda_unit}",
                node_id=node.id,
                field="lambda_unit",
            )
        if getattr(config, "distribution", "exponential") != "exponential":
            issues.error(
                "reliability_unsupported_distribution",
                f"节点 {node.id} 使用了不支持的分布: {config.distribution}",
                node_id=node.id,
                field="distribution",
            )

        if module_type == "stage":
            stage_module_count += 1
            if node.type != "subprocess":
                issues.error(
                    "reliability_invalid_node_type",
                    f"阶段故障率只能配置在 subprocess 节点上，节点 {node.id} "
                    f"的类型是 {node.type}",
                    node_id=node.id,
                    field="module_type",
                )
                continue
            if not getattr(config, "participates", False):
                issues.error(
                    "reliability_stage_not_participating",
                    f"阶段节点 {node.id} 必须参与指数故障抽样",
                    node_id=node.id,
                    field="participates",
                )
            if config.lambda_per_day is None:
                issues.error(
                    "reliability_missing_lambda",
                    f"阶段节点 {node.id} 没有配置故障率 lambda",
                    node_id=node.id,
                    field="lambda",
                )
            elif not _lambda_is_valid(config.lambda_per_day):
                issues.error(
                    "reliability_invalid_lambda",
                    f"节点 {node.id} 的 lambda 必须是有限的非负数",
                    node_id=node.id,
                    field="lambda",
                )
            else:
                participant_count += 1
            stage_task_id = getattr(config, "stage_task_id", None)
            if stage_task_id is not None:
                stage_task = all_nodes.get(stage_task_id)
                allowed_ids = {
                    task.id for task in _iter_subflow_tasks(node)
                }
                if stage_task is None or stage_task.id not in allowed_ids:
                    issues.error(
                        "reliability_invalid_stage_task",
                        f"阶段节点 {node.id} 的主任务 {stage_task_id} "
                        "不是该 subprocess 内部的活动节点",
                        node_id=node.id,
                        field="stage_task_id",
                    )
            elif _first_stage_task(node) is None:
                issues.error(
                    "reliability_missing_stage_task",
                    f"阶段节点 {node.id} 内部没有可抽样的活动节点",
                    node_id=node.id,
                    field="stage_task_id",
                )
            continue

        if module_type == "test":
            test_module_count += 1
            if node.type != "task":
                issues.error(
                    "reliability_invalid_node_type",
                    f"测试模块只能配置在 task 节点上，节点 {node.id} "
                    f"的类型是 {node.type}",
                    node_id=node.id,
                    field="module_type",
                )
                continue
            detection_rate = getattr(config, "detection_rate", None)
            if detection_rate is None:
                issues.error(
                    "reliability_missing_detection_rate",
                    f"测试模块 {node.id} 必须配置故障检测率 Ft",
                    node_id=node.id,
                    field="detection_rate",
                )
            elif not _rate_is_valid(detection_rate):
                issues.error(
                    "reliability_invalid_detection_rate",
                    f"节点 {node.id} 的故障检测率 Ft 必须是 0 到 1 的有限数字",
                    node_id=node.id,
                    field="detection_rate",
                )
            if config.lambda_per_day is not None:
                issues.error(
                    "reliability_test_has_lambda",
                    f"测试模块 {node.id} 不能配置故障率 lambda",
                    node_id=node.id,
                    field="lambda",
                )
            if getattr(config, "participates", False):
                issues.error(
                    "reliability_test_participates",
                    f"测试模块 {node.id} 不参与独立的指数故障抽样",
                    node_id=node.id,
                    field="participates",
                )
            test_time = getattr(config, "test_time", None)
            if test_time is not None and (
                isinstance(test_time, bool)
                or not isinstance(test_time, (int, float))
                or not math.isfinite(float(test_time))
                or float(test_time) <= 0
            ):
                issues.error(
                    "reliability_invalid_test_time",
                    f"节点 {node.id} 的测试时间必须是大于 0 的有限数字",
                    node_id=node.id,
                    field="test_time",
                )
            continue

        # module_type == "activity" (legacy task-level reliability is retained
        # for old models, but the new UI never writes lambda on ordinary tasks).
        if node.type != "task":
            issues.error(
                "reliability_invalid_node_type",
                f"只有 task 节点可以配置活动级可靠性，节点 {node.id} 的类型是 "
                f"{node.type}",
                node_id=node.id,
                field="participates",
            )
            continue
        if config.lambda_per_day is not None and not _lambda_is_valid(
            config.lambda_per_day
        ):
            issues.error(
                "reliability_invalid_lambda",
                f"节点 {node.id} 的 lambda 必须是有限的非负数",
                node_id=node.id,
                field="lambda",
            )
        if getattr(config, "participates", False):
            if config.lambda_per_day is None:
                issues.error(
                    "reliability_missing_lambda",
                    f"节点 {node.id} 参与可靠性计算，但没有配置 lambda",
                    node_id=node.id,
                    field="lambda",
                )
            elif _lambda_is_valid(config.lambda_per_day):
                participant_count += 1

    configured_set = set(configured_ids)
    for node in task_map.values():
        if node.id in configured_set:
            continue
        issues.error(
            "reliability_missing_config",
            f"task 节点 {node.id} 缺少可靠性参与配置；"
            "请显式选择参与或不参与",
            node_id=node.id,
            field="nodes",
        )

    return ReliabilityValidationResult(
        valid=not any(issue.severity == "error" for issue in issues.items),
        issues=issues.items,
        process_id=process.process_id,
        process_version=process.version,
        process_hash=process.content_hash,
        participant_count=participant_count,
        test_module_count=test_module_count,
        stage_module_count=stage_module_count,
    )


__all__ = [
    "ReliabilityIssue",
    "ReliabilityValidationResult",
    "validate_reliability",
]
