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


def validate_reliability(
    process: ProcessDocument, spec: ReliabilitySpec
) -> ReliabilityValidationResult:
    issues = _Issues()
    participant_count = 0

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

    node_map = {node.id: node for node in process.nodes}
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
        node = node_map.get(config.node_id)
        if node is None:
            issues.error(
                "reliability_unknown_node",
                f"可靠性配置引用了当前流程中不存在的节点: {config.node_id}",
                node_id=config.node_id,
                field="nodes",
            )
            continue
        if node.type != "task":
            issues.error(
                "reliability_invalid_node_type",
                f"只有 task 节点可以配置可靠性，节点 {node.id} 的类型是 {node.type}",
                node_id=node.id,
                field="participates",
            )
            continue
        if config.distribution != "exponential":
            issues.error(
                "reliability_unsupported_distribution",
                f"节点 {node.id} 使用了不支持的分布: {config.distribution}",
                node_id=node.id,
                field="distribution",
            )
        if config.lambda_per_day is not None and not _lambda_is_valid(
            config.lambda_per_day
        ):
            issues.error(
                "reliability_invalid_lambda",
                f"节点 {node.id} 的 lambda 必须是有限的非负数",
                node_id=node.id,
                field="lambda",
            )
        if config.participates:
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
    for node in process.nodes:
        if node.type != "task" or node.id in configured_set:
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
    )


__all__ = [
    "ReliabilityIssue",
    "ReliabilityValidationResult",
    "validate_reliability",
]
