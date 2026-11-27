"""Pre-run parameter checks for formal simulations.

The low-level runtime still supports legacy task-level reliability. The formal
experiment endpoint uses these checks to reject equipment-support simulations
that silently omit stage lambdas, test detection rates or activity durations.
"""

from __future__ import annotations

from app.domain.process_ir import ProcessDocument, ProcessNode
from app.domain.reliability_ir import (
    ReliabilityDocument,
    lambda_unit_for_simulation_unit,
)
from app.simulation.models import SimulationIssue

EQUIPMENT_STAGE_TERMS = ("贮存", "值班")


def _iter_nodes(nodes: list[ProcessNode]):
    for node in nodes:
        yield node
        if node.subflow is not None:
            yield from _iter_nodes(node.subflow.nodes)


def _module_type(config) -> str:
    return getattr(config, "module_type", "activity")


def _is_test_name(name: str) -> bool:
    text = (name or "").strip()
    if "场" in text:
        return False
    return "检测" in text or text.endswith("测试")


def check_simulation_readiness(
    process: ProcessDocument,
    reliability: ReliabilityDocument,
    simulation_unit: str,
) -> list[SimulationIssue]:
    nodes = list(_iter_nodes(process.nodes))
    text = " ".join(
        [process.name, process.description, *(node.name for node in nodes)]
    )
    if not any(term in text for term in EQUIPMENT_STAGE_TERMS):
        return []

    issues: list[SimulationIssue] = []
    configs = {config.node_id: config for config in reliability.nodes}
    expected_unit = lambda_unit_for_simulation_unit(simulation_unit)

    for node in nodes:
        if node.type == "subprocess" and any(
            term in node.name for term in EQUIPMENT_STAGE_TERMS
        ):
            config = configs.get(node.id)
            if config is None or _module_type(config) != "stage":
                issues.append(
                    SimulationIssue(
                        code="missing_stage_reliability",
                        message=(
                            f"阶段流程块「{node.name}」缺少阶段故障率 λ 配置"
                        ),
                        node_id=node.id,
                        field="reliability.nodes",
                    )
                )
                continue
            if config.lambda_per_day is None:
                issues.append(
                    SimulationIssue(
                        code="missing_stage_lambda",
                        message=f"阶段流程块「{node.name}」缺少故障率 λ",
                        node_id=node.id,
                        field="lambda",
                    )
                )
            if config.lambda_unit != expected_unit:
                issues.append(
                    SimulationIssue(
                        code="reliability_lambda_unit_mismatch",
                        message=(
                            f"阶段流程块「{node.name}」的 λ 单位 "
                            f"{config.lambda_unit} 与仿真单位 "
                            f"{simulation_unit} 不一致"
                        ),
                        node_id=node.id,
                        field="lambda_unit",
                    )
                )

    for node in nodes:
        if node.type != "task":
            continue
        is_test = _is_test_name(node.name)
        config = configs.get(node.id)
        if is_test:
            if config is None or _module_type(config) != "test":
                issues.append(
                    SimulationIssue(
                        code="missing_test_detection_module",
                        message=(
                            f"测试节点「{node.name}」尚未配置为测试模块"
                        ),
                        node_id=node.id,
                        field="module_type",
                    )
                )
                continue
            if config.detection_rate is None:
                issues.append(
                    SimulationIssue(
                        code="missing_detection_rate",
                        message=f"测试模块「{node.name}」缺少故障检测率 Ft",
                        node_id=node.id,
                        field="detection_rate",
                    )
                )
            if config.test_time is None and node.duration is None:
                issues.append(
                    SimulationIssue(
                        code="missing_test_time",
                        message=f"测试模块「{node.name}」缺少测试时间",
                        node_id=node.id,
                        field="test_time",
                    )
                )
        else:
            if (
                config is not None
                and _module_type(config) == "activity"
                and getattr(config, "participates", False)
            ):
                issues.append(
                    SimulationIssue(
                        code="activity_lambda_not_allowed",
                        message=(
                            f"普通活动「{node.name}」不应配置故障率 λ；"
                            "故障率只能配置在贮存/值班阶段 subprocess 上"
                        ),
                        node_id=node.id,
                        field="participates",
                    )
                )
            if node.duration is None:
                issues.append(
                    SimulationIssue(
                        code="missing_duration",
                        message=f"普通活动「{node.name}」缺少持续时间",
                        node_id=node.id,
                        field="duration",
                    )
                )

    return issues


__all__ = ["check_simulation_readiness"]
