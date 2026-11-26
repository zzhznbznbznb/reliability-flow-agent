"""Pure evaluation of a completed SimulationResult."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.domain.process_ir import ProcessDocument, StatusDefinition
from app.domain.reliability_ir import ReliabilityDocument
from app.evaluation.models import (
    EntityMetrics,
    EvaluationConfig,
    EvaluationResult,
    EvaluationTargets,
    EvaluationWarning,
    NodeMetrics,
    OverallMetrics,
    PerEntityNodeMetrics,
    ProcessBinding,
    ReliabilityBinding,
    TargetResult,
    TargetStatus,
)
from app.simulation.models import (
    EntitySimulationResult,
    ReliabilitySample,
    SimulationResult,
)

_LIMITATIONS = [
    "单次仿真经验指标，不提供统计置信区间。",
    "Runtime 使用区间可靠性抽样，不提供精确故障时刻。",
    "不同节点的理论可靠度不会被合并为系统整体理论可靠度。",
    "维修周期依赖事件顺序重建，当前 Runtime 没有唯一维修周期 ID。",
]


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _canonical_number(value: float) -> int | float:
    numeric = float(value)
    if numeric == 0:
        return 0
    if numeric.is_integer():
        return int(numeric)
    return numeric


def compute_reliability_hash(reliability: ReliabilityDocument) -> str:
    nodes = []
    for config in sorted(reliability.nodes, key=lambda item: item.node_id):
        nodes.append(
            {
                "node_id": config.node_id,
                "participates": bool(config.participates),
                "distribution": config.distribution,
                "lambda": (
                    None
                    if config.lambda_per_day is None
                    else _canonical_number(config.lambda_per_day)
                ),
                "lambda_unit": config.lambda_unit,
            }
        )
    payload = {
        "schema_version": reliability.schema_version,
        "nodes": nodes,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass
class _ActualReconstruction:
    totals: dict[str, float] = field(default_factory=dict)
    complete: dict[str, bool] = field(default_factory=dict)
    visits: dict[str, int] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)


def _reconstruct_actual_elapsed(
    entity: EntitySimulationResult,
) -> _ActualReconstruction:
    reconstruction = _ActualReconstruction()
    open_node: str | None = None
    last_sample_exposure: float | None = None

    def mark_incomplete(node_id: str, code: str, message: str, **details: Any) -> None:
        reconstruction.complete[node_id] = False
        reconstruction.anomalies.append(
            {
                "code": code,
                "node_id": node_id,
                "message": message,
                **details,
            }
        )

    for event in entity.history:
        event_type = event.event_type
        node_id = event.node_id
        if event_type == "node_entered" and node_id is not None:
            reconstruction.totals.setdefault(node_id, 0.0)
            reconstruction.complete.setdefault(node_id, True)
            reconstruction.visits[node_id] = (
                reconstruction.visits.get(node_id, 0) + 1
            )
            if open_node is not None:
                mark_incomplete(
                    open_node,
                    "event_sequence_invalid",
                    "节点访问尚未结束就进入了下一个节点。",
                    next_node_id=node_id,
                )
            open_node = node_id
            last_sample_exposure = None
        elif event_type == "node_completed" and node_id is not None:
            reconstruction.totals.setdefault(node_id, 0.0)
            if open_node is None or open_node != node_id:
                mark_incomplete(
                    node_id,
                    "event_sequence_invalid",
                    "节点完成事件没有对应的打开访问。",
                )
                open_node = None
                last_sample_exposure = None
                continue
            elapsed = event.data.get("elapsed")
            if not _finite(elapsed) or float(elapsed) < 0:
                mark_incomplete(
                    node_id,
                    "event_sequence_invalid",
                    "节点完成事件缺少合法的 elapsed。",
                )
            else:
                reconstruction.totals[node_id] += float(elapsed)
            open_node = None
            last_sample_exposure = None
        elif event_type == "reliability_sample" and node_id is not None:
            if open_node == node_id:
                exposure = event.data.get("exposure_time")
                if _finite(exposure) and float(exposure) >= 0:
                    last_sample_exposure = float(exposure)
                else:
                    mark_incomplete(
                        node_id,
                        "event_sequence_invalid",
                        "可靠性抽样事件缺少合法的 exposure_time。",
                    )
        elif event_type == "reliability_failure" and node_id is not None:
            reconstruction.totals.setdefault(node_id, 0.0)
            if open_node != node_id:
                mark_incomplete(
                    node_id,
                    "event_sequence_invalid",
                    "可靠性故障事件没有对应的打开访问。",
                )
                continue
            if last_sample_exposure is None:
                mark_incomplete(
                    node_id,
                    "event_sequence_invalid",
                    "可靠性故障事件缺少匹配的抽样暴露时间。",
                )
            else:
                reconstruction.totals[node_id] += last_sample_exposure
            open_node = None
            last_sample_exposure = None

    if open_node is not None:
        reconstruction.totals.setdefault(open_node, 0.0)
        if (
            entity.final_node_id == open_node
            and _finite(entity.node_elapsed_time)
            and float(entity.node_elapsed_time) >= 0
        ):
            reconstruction.totals[open_node] += float(entity.node_elapsed_time)
        else:
            mark_incomplete(
                open_node,
                "actual_elapsed_incomplete",
                "仿真结束时打开的节点访问无法还原实际停留时间。",
            )

    for node_id, visits in entity.node_visits.items():
        if visits <= 0:
            continue
        reconstruction.totals.setdefault(node_id, 0.0)
        if node_id not in reconstruction.complete:
            reconstruction.complete[node_id] = False
            reconstruction.anomalies.append(
                {
                    "code": "actual_elapsed_incomplete",
                    "node_id": node_id,
                    "message": "node_visits 记录了一次访问，但事件历史中没有对应访问。",
                }
            )
        elif reconstruction.visits.get(node_id, 0) != visits:
            reconstruction.complete[node_id] = False
            reconstruction.anomalies.append(
                {
                    "code": "node_visit_history_mismatch",
                    "node_id": node_id,
                    "message": "node_visits 计数与 node_entered 事件数不一致。",
                    "node_visits": visits,
                    "event_visits": reconstruction.visits.get(node_id, 0),
                }
            )

    return reconstruction


def _classify_end_state(
    entity: EntitySimulationResult,
    status_map: dict[str, StatusDefinition],
) -> str:
    if entity.currently_failed:
        return "bad"
    status = entity.current_status
    if status is None or status not in status_map:
        return "unknown"
    return "good" if status_map[status].counts_as_available else "bad"


def _repair_activity(
    entities: Iterable[EntitySimulationResult],
) -> tuple[set[str], int, list[EntitySimulationResult]]:
    active_entities: set[str] = set()
    overlap_entities: list[EntitySimulationResult] = []
    completed_count = 0
    for entity in entities:
        active = False
        overlapped = False
        for event in entity.history:
            if event.event_type == "repair_started":
                if active:
                    overlapped = True
                active = True
            elif event.event_type == "repair_completed":
                completed_count += 1
                active = False
        if active:
            active_entities.add(entity.entity_id)
        if overlapped:
            overlap_entities.append(entity)
    return active_entities, completed_count, overlap_entities


def _target_result(
    metric: str,
    configured: bool,
    actual: float | None,
    target: float | None,
    *,
    unevaluable_reason: str | None = None,
) -> TargetResult:
    if not configured or target is None:
        return TargetResult(
            metric=metric,
            configured=False,
            actual=actual,
            target=None,
            met=None,
            gap=None,
            status="not_configured",
            reason="用户未设置该目标",
        )
    if unevaluable_reason is not None or actual is None:
        return TargetResult(
            metric=metric,
            configured=True,
            actual=None,
            target=target,
            met=None,
            gap=None,
            status="unevaluable",
            reason=unevaluable_reason or "评价数据不完整，无法判断目标。",
        )
    met = actual >= target
    return TargetResult(
        metric=metric,
        configured=True,
        actual=actual,
        target=target,
        met=met,
        gap=actual - target,
        status="achieved" if met else "not_achieved",
        reason=None if met else "实际值低于目标值。",
    )


def _overall_target_status(targets: list[TargetResult]) -> TargetStatus:
    configured = [target for target in targets if target.configured]
    if not configured:
        return "not_configured"
    if any(target.status == "not_achieved" for target in configured):
        return "not_achieved"
    if any(target.status == "unevaluable" for target in configured):
        return "unevaluable"
    if all(target.status == "achieved" for target in configured):
        return "achieved"
    return "not_configured"


def evaluate_simulation(
    process: ProcessDocument,
    reliability: ReliabilityDocument,
    result: SimulationResult,
    targets: EvaluationTargets | None = None,
    evaluation_config: EvaluationConfig | None = None,
) -> EvaluationResult:
    config = evaluation_config or EvaluationConfig()
    target_config = targets or EvaluationTargets()
    warnings: list[EvaluationWarning] = []

    def warn(
        code: str,
        scope: str,
        message: str,
        *,
        node_id: str | None = None,
        entity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        warnings.append(
            EvaluationWarning(
                code=code,
                scope=scope,
                message=message,
                node_id=node_id,
                entity_id=entity_id,
                details=details or {},
            )
        )

    if (
        result.process_id != process.process_id
        or result.process_version != process.version
        or result.process_hash != process.content_hash
    ):
        warn(
            "process_binding_mismatch",
            "experiment",
            "SimulationResult 与给定 Process IR 的绑定不一致。",
            details={
                "result_process_id": result.process_id,
                "result_process_version": result.process_version,
                "result_process_hash": result.process_hash,
            },
        )
    if (
        result.reliability_id != reliability.reliability_id
        or result.reliability_revision != reliability.revision
    ):
        warn(
            "reliability_binding_mismatch",
            "experiment",
            "SimulationResult 与给定 Reliability IR 的绑定不一致。",
            details={
                "result_reliability_id": result.reliability_id,
                "result_reliability_revision": result.reliability_revision,
            },
        )

    entities = sorted(result.entities, key=lambda item: item.entity_id)
    entity_ids = {entity.entity_id for entity in entities}
    n_total = result.entity_count
    if len(entities) != n_total:
        warn(
            "entity_count_mismatch",
            "system",
            "SimulationResult.entity_count 与实际 entities 数量不一致。",
            details={
                "entity_count": n_total,
                "entities_length": len(entities),
            },
        )

    status_map = {status.id: status for status in process.status_catalog}
    reconstructed = {
        entity.entity_id: _reconstruct_actual_elapsed(entity)
        for entity in entities
    }
    for entity in entities:
        for anomaly in reconstructed[entity.entity_id].anomalies:
            warn(
                anomaly["code"],
                "entity",
                anomaly["message"],
                entity_id=entity.entity_id,
                node_id=anomaly.get("node_id"),
                details={
                    key: value
                    for key, value in anomaly.items()
                    if key not in {"code", "message", "node_id"}
                },
            )

    classifications = {
        entity.entity_id: _classify_end_state(entity, status_map)
        for entity in entities
    }
    good_count = sum(1 for value in classifications.values() if value == "good")
    bad_count = sum(1 for value in classifications.values() if value == "bad")
    unknown_count = sum(
        1 for value in classifications.values() if value == "unknown"
    )
    availability_evaluable = unknown_count == 0
    if unknown_count:
        warn(
            "unknown_end_state",
            "system",
            f"存在 {unknown_count} 台设备结束时状态无法判定。",
            details={
                "unknown_end_count": unknown_count,
                "entity_ids": [
                    entity_id
                    for entity_id, value in classifications.items()
                    if value == "unknown"
                ],
            },
        )
    if not availability_evaluable:
        warn(
            "availability_unevaluable",
            "system",
            "存在 unknown 结束状态，正式结束时完好率不可评价。",
            details={"unknown_end_count": unknown_count},
        )

    status_distribution: dict[str, int] = {}
    for entity in entities:
        key = (
            entity.current_status
            if entity.current_status in status_map
            else "unknown"
        )
        status_distribution[key] = status_distribution.get(key, 0) + 1

    ever_failed_count = sum(1 for entity in entities if entity.ever_failed)
    overall_reliability = 1.0 - ever_failed_count / n_total
    sample_failure_count = sum(
        1 for sample in result.reliability_samples if sample.failure_occurred
    )
    runtime_failure_counter_total = sum(
        entity.failure_count for entity in entities
    )
    failure_consistent = sample_failure_count == runtime_failure_counter_total
    if not failure_consistent:
        warn(
            "failure_counter_mismatch",
            "system",
            "可靠性样本故障数与 Runtime failure_count 总和不一致。",
            details={
                "sample_failure_count": sample_failure_count,
                "runtime_failure_counter_total": runtime_failure_counter_total,
            },
        )

    active_repairs, repair_completed_count, overlap_entities = _repair_activity(
        entities
    )
    for entity in overlap_entities:
        warn(
            "repair_cycle_overlap",
            "entity",
            "同一设备在已有维修活动时再次开始维修，维修周期存在歧义。",
            entity_id=entity.entity_id,
        )
    total_repair_count = sum(entity.repair_count for entity in entities)
    if total_repair_count != repair_completed_count:
        warn(
            "repair_counter_mismatch",
            "system",
            "Runtime repair_count 总和与 repair_completed 事件数不一致。",
            details={
                "total_repair_count": total_repair_count,
                "repair_completed_count": repair_completed_count,
            },
        )

    is_small_sample = n_total < config.small_sample_threshold
    if is_small_sample:
        warn(
            "small_sample",
            "system",
            f"设备数量 {n_total} 小于 {config.small_sample_threshold}，经验指标存在统计不确定性。",
            details={
                "entity_count": n_total,
                "threshold": config.small_sample_threshold,
            },
        )

    overall = OverallMetrics(
        entity_count=n_total,
        ever_failed_entity_count=ever_failed_count,
        overall_reliability=overall_reliability,
        good_end_count=good_count,
        bad_end_count=bad_count,
        unknown_end_count=unknown_count,
        availability_evaluable=availability_evaluable,
        end_availability=(
            good_count / n_total if availability_evaluable else None
        ),
        observed_good_end_fraction=good_count / n_total,
        total_failure_count=sample_failure_count,
        runtime_failure_counter_total=runtime_failure_counter_total,
        failure_counter_consistent=failure_consistent,
        total_repair_count=total_repair_count,
        repair_completed_count=repair_completed_count,
        repair_pending_count=len(active_repairs),
        repair_in_progress_count=len(active_repairs),
        currently_failed_entity_count=sum(
            1 for entity in entities if entity.currently_failed
        ),
        completed_entity_count=sum(1 for entity in entities if entity.completed),
        stopped_entity_count=sum(1 for entity in entities if entity.stopped),
        unfinished_entity_count=sum(
            1
            for entity in entities
            if not entity.completed and not entity.stopped
        ),
        mean_failure_count_per_entity=sample_failure_count / n_total,
        mean_repair_count_per_entity=total_repair_count / n_total,
        status_distribution=status_distribution,
    )

    samples_by_node: dict[str, list[ReliabilitySample]] = {}
    sample_entity_ids: dict[str, set[str]] = {}
    for sample in result.reliability_samples:
        samples_by_node.setdefault(sample.node_id, []).append(sample)
        sample_entity_ids.setdefault(sample.node_id, set()).add(
            sample.entity_id
        )
        if sample.entity_id not in entity_ids:
            warn(
                "sample_unknown_entity",
                "node",
                "可靠性抽样引用了 SimulationResult 中不存在的设备。",
                node_id=sample.node_id,
                entity_id=sample.entity_id,
            )

    node_metrics: list[NodeMetrics] = []
    entity_node_map: dict[str, list[PerEntityNodeMetrics]] = {
        entity.entity_id: [] for entity in entities
    }
    participating = sorted(
        (
            config_item
            for config_item in reliability.nodes
            if config_item.participates
        ),
        key=lambda item: item.node_id,
    )
    for config_item in participating:
        process_node = next(
            (node for node in process.nodes if node.id == config_item.node_id),
            None,
        )
        if process_node is None:
            warn(
                "reliability_unknown_node",
                "node",
                "Reliability IR 引用了当前 Process IR 中不存在的节点。",
                node_id=config_item.node_id,
            )
            continue
        if process_node.type != "task":
            warn(
                "reliability_invalid_node_type",
                "node",
                "只有 task 节点可以参与可靠性评价。",
                node_id=config_item.node_id,
            )
            continue

        lam = float(config_item.lambda_per_day or 0.0)
        samples = samples_by_node.get(config_item.node_id, [])
        for sample in samples:
            if not math.isclose(
                sample.lambda_per_day, lam, rel_tol=1e-12, abs_tol=1e-12
            ):
                warn(
                    "reliability_lambda_mismatch",
                    "node",
                    "可靠性抽样中的 lambda 与当前 Reliability IR 不一致。",
                    node_id=config_item.node_id,
                    details={
                        "sample_lambda": sample.lambda_per_day,
                        "configured_lambda": lam,
                    },
                )
                break

        exposure_by_entity: dict[str, float] = {}
        sample_count_by_entity: dict[str, int] = {}
        failure_by_entity: dict[str, int] = {}
        for sample in samples:
            exposure_by_entity[sample.entity_id] = (
                exposure_by_entity.get(sample.entity_id, 0.0)
                + sample.exposure_time
            )
            sample_count_by_entity[sample.entity_id] = (
                sample_count_by_entity.get(sample.entity_id, 0) + 1
            )
            failure_by_entity[sample.entity_id] = (
                failure_by_entity.get(sample.entity_id, 0)
                + (1 if sample.failure_occurred else 0)
            )

        total_exposure = sum(exposure_by_entity.values())
        unique_exposed = sum(
            1 for value in exposure_by_entity.values() if value > 0
        )
        visit_count = sum(
            entity.node_visits.get(config_item.node_id, 0)
            for entity in entities
        )
        failure_count = sum(failure_by_entity.values())
        sample_count = len(samples)

        actual_incomplete_entities: list[str] = []
        for entity in entities:
            if entity.node_visits.get(config_item.node_id, 0) <= 0:
                continue
            reconstruction = reconstructed[entity.entity_id]
            if not reconstruction.complete.get(config_item.node_id, False):
                actual_incomplete_entities.append(entity.entity_id)
        actual_complete = not actual_incomplete_entities
        total_actual = (
            sum(
                reconstructed[entity.entity_id].totals.get(
                    config_item.node_id, 0.0
                )
                for entity in entities
            )
            if actual_complete
            else None
        )
        if not actual_complete:
            warn(
                "actual_elapsed_incomplete",
                "node",
                "节点实际停留时间无法完整还原，结果中保留 null。",
                node_id=config_item.node_id,
                details={"entity_ids": actual_incomplete_entities},
            )

        theoretical_evaluable = total_exposure > 0
        if not theoretical_evaluable:
            warn(
                "no_valid_exposure",
                "node",
                "该节点没有有效的正可靠性暴露时间，理论指标不可评价。",
                node_id=config_item.node_id,
                details={
                    "sample_count": sample_count,
                    "total_reliability_exposure_time": total_exposure,
                },
            )

        per_entity_metrics: list[PerEntityNodeMetrics] = []
        theoretical_values: list[float] = []
        for entity in entities:
            visits = entity.node_visits.get(config_item.node_id, 0)
            if visits <= 0 and sample_count_by_entity.get(entity.entity_id, 0) == 0:
                continue
            exposure = exposure_by_entity.get(entity.entity_id, 0.0)
            entity_reconstruction = reconstructed[entity.entity_id]
            actual_complete_entity = entity_reconstruction.complete.get(
                config_item.node_id, False
            )
            actual_elapsed = (
                entity_reconstruction.totals.get(config_item.node_id, 0.0)
                if actual_complete_entity
                else None
            )
            theoretical = (
                math.exp(-lam * exposure)
                if theoretical_evaluable
                else None
            )
            if (
                theoretical is not None
                and exposure > 0
                and theoretical_evaluable
            ):
                theoretical_values.append(theoretical)
            per_entity = PerEntityNodeMetrics(
                entity_id=entity.entity_id,
                node_id=config_item.node_id,
                planned_duration=process_node.duration,
                visit_count=visits,
                sample_count=sample_count_by_entity.get(entity.entity_id, 0),
                failure_count=failure_by_entity.get(entity.entity_id, 0),
                actual_elapsed_time=actual_elapsed,
                actual_elapsed_complete=actual_complete_entity,
                reliability_exposure_time=exposure,
                theoretical_reliability=theoretical,
            )
            per_entity_metrics.append(per_entity)
            entity_node_map[entity.entity_id].append(per_entity)

        mean_reliability = (
            sum(theoretical_values) / len(theoretical_values)
            if theoretical_values
            else None
        )
        joint_probability = (
            math.exp(-lam * total_exposure)
            if theoretical_evaluable
            else None
        )
        empirical_frequency = (
            failure_count / sample_count if sample_count > 0 else None
        )
        node_small_sample = (
            unique_exposed > 0
            and unique_exposed < config.small_sample_threshold
        )
        if node_small_sample:
            warn(
                "small_sample",
                "node",
                (
                    f"该节点唯一暴露设备数 {unique_exposed} 小于 "
                    f"{config.small_sample_threshold}，节点经验故障频率存在统计不确定性。"
                ),
                node_id=config_item.node_id,
                details={
                    "unique_exposed_entity_count": unique_exposed,
                    "sample_count": sample_count,
                    "threshold": config.small_sample_threshold,
                },
            )

        node_metric = NodeMetrics(
            node_id=config_item.node_id,
            node_name=process_node.name,
            lambda_per_day=lam,
            lambda_unit=config_item.lambda_unit,
            planned_duration=process_node.duration,
            visit_count=visit_count,
            sample_count=sample_count,
            failure_count=failure_count,
            total_actual_elapsed_time=total_actual,
            actual_elapsed_complete=actual_complete,
            total_reliability_exposure_time=total_exposure,
            unique_exposed_entity_count=unique_exposed,
            node_is_small_sample=node_small_sample,
            empirical_failure_frequency=empirical_frequency,
            mean_entity_theoretical_reliability=mean_reliability,
            joint_theoretical_no_failure_probability=joint_probability,
            per_entity_metrics=sorted(
                per_entity_metrics, key=lambda item: item.entity_id
            ),
        )
        node_metrics.append(node_metric)

    entity_metrics = [
        EntityMetrics(
            entity_id=entity.entity_id,
            final_node_id=entity.final_node_id,
            final_status=entity.current_status,
            end_state_classification=classifications[entity.entity_id],
            failure_count=entity.failure_count,
            repair_count=entity.repair_count,
            ever_failed=entity.ever_failed,
            currently_failed=entity.currently_failed,
            repair_in_progress=entity.entity_id in active_repairs,
            completed=entity.completed,
            stopped=entity.stopped,
            stopped_reason=entity.stopped_reason,
            node_metrics=sorted(
                entity_node_map[entity.entity_id],
                key=lambda item: item.node_id,
            ),
        )
        for entity in entities
    ]

    target_results = [
        _target_result(
            "overall_reliability",
            target_config.overall_reliability_min is not None,
            overall_reliability,
            target_config.overall_reliability_min,
        ),
        _target_result(
            "end_availability",
            target_config.end_availability_min is not None,
            (
                overall.end_availability
                if availability_evaluable
                else None
            ),
            target_config.end_availability_min,
            unevaluable_reason=(
                None
                if availability_evaluable
                else "存在 unknown 结束状态，正式结束完好率不可评价。"
            ),
        ),
    ]

    return EvaluationResult(
        process_binding=ProcessBinding(
            process_id=process.process_id,
            version=process.version,
            content_hash=process.content_hash,
            name=process.name,
        ),
        reliability_binding=ReliabilityBinding(
            reliability_id=reliability.reliability_id,
            revision=reliability.revision,
            hash=compute_reliability_hash(reliability),
            process_version=reliability.process_version,
            process_hash=reliability.process_hash,
        ),
        sample_size=n_total,
        small_sample_threshold=config.small_sample_threshold,
        is_small_sample=is_small_sample,
        overall=overall,
        nodes=node_metrics,
        entities=entity_metrics,
        targets=target_results,
        target_status=_overall_target_status(target_results),
        warnings=warnings,
        limitations=list(_LIMITATIONS),
    )


__all__ = ["compute_reliability_hash", "evaluate_simulation"]
