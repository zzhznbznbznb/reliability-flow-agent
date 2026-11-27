"""Discrete-event simulation engine.

The engine executes Process IR nodes for every entity independently. Reliability
sampling is layered on top of task completion using the separate Reliability IR.
"""

from __future__ import annotations

import copy
import heapq
import math
import random
from dataclasses import dataclass, field
from typing import Any

from app.domain.process_ir import (
    Condition,
    Effect,
    ProcessDocument,
    ProcessEdge,
    ProcessNode,
)
from app.domain.reliability_ir import (
    ReliabilityDocument,
    ReliabilityNodeConfig,
    lambda_unit_for_simulation_unit,
)
from app.domain.reliability_validation import validate_reliability
from app.domain.validation import CONFIG_PENDING_CODES, validate_process
from app.simulation.config import (
    DEFAULT_LIMITS,
    SimulationConfig,
    SimulationLimits,
)
from app.simulation.errors import (
    SimulationRuntimeError,
    SimulationValidationError,
)
from app.simulation.models import (
    EntitySimulationResult,
    FailureRecord,
    ReliabilitySample,
    SimulationEvent,
    SimulationIssue,
    SimulationResult,
    TestRecord,
)
from app.simulation.rng import (
    BUSINESS_STREAM,
    DETECTION_STREAM,
    RELIABILITY_STREAM,
    make_stream_rng,
)


@dataclass
class _ScopeFrame:
    block_node_id: str
    block_node: ProcessNode
    entry_time: float
    end_node_ids: set[str]


@dataclass
class _EntityRuntime:
    entity_id: str
    current_node_id: str
    current_status: str | None = None
    node_enter_time: float = 0.0
    node_elapsed_time: float = 0.0
    failure_count: int = 0
    repair_count: int = 0
    ever_failed: bool = False
    currently_failed: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)
    node_visits: dict[str, int] = field(default_factory=dict)
    scope_stack: list[_ScopeFrame] = field(default_factory=list)
    history: list[SimulationEvent] = field(default_factory=list)
    completed: bool = False
    stopped: bool = False
    stopped_reason: str | None = None
    pending_completion_time: float | None = None
    entry_token: int = 0
    pending_failure_time: float | None = None
    pending_failure_node_id: str | None = None
    pending_failure_random: float | None = None
    pending_failure_lambda: float | None = None
    pending_reliability_random: float | None = None
    pending_reliability_lambda: float | None = None
    repair_pending: bool = False
    repair_count_at_failure: int = 0
    repair_active: bool = False
    repair_start_recorded: bool = False
    test_detected: bool = False
    failure_records: list[FailureRecord] = field(default_factory=list)
    test_records: list[TestRecord] = field(default_factory=list)
    reliability_rng: random.Random = field(
        default_factory=random.Random, repr=False
    )
    business_rng: random.Random = field(
        default_factory=random.Random, repr=False
    )
    detection_rng: random.Random = field(
        default_factory=random.Random, repr=False
    )


_MISSING = object()


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _module_type(config: ReliabilityNodeConfig) -> str:
    return getattr(config, "module_type", "activity")


def _iter_subflow_tasks(node: ProcessNode) -> list[ProcessNode]:
    if node.subflow is None:
        return []
    tasks: list[ProcessNode] = []
    for child in node.subflow.nodes:
        if child.type == "task":
            tasks.append(child)
        if child.subflow is not None:
            tasks.extend(_iter_subflow_tasks(child))
    return tasks


def _first_stage_task(node: ProcessNode) -> ProcessNode | None:
    tasks = _iter_subflow_tasks(node)
    return tasks[0] if tasks else None


class SimulationRuntime:
    def __init__(
        self,
        process: ProcessDocument,
        config: SimulationConfig,
        reliability: ReliabilityDocument | None = None,
        limits: SimulationLimits | None = None,
    ) -> None:
        self.process = process
        self.config = config
        self.simulation_start = float(config.simulation_start)
        self.simulation_end = float(config.simulation_end or 0.0)
        self.reliability = reliability
        self.limits = limits or DEFAULT_LIMITS
        self.node_by_id: dict[str, ProcessNode] = {}
        self.node_scope: dict[str, tuple[str, ...]] = {}
        self.node_max_visits: dict[str, int] = {}
        self.outgoing: dict[str, list[ProcessEdge]] = {}
        self.max_node_visits = min(
            process.guards.max_node_visits, self.limits.max_node_visits
        )
        self._index_scope(
            process.nodes,
            process.edges,
            (),
            self.max_node_visits,
        )
        self.reliability_by_node = (
            {config.node_id: config for config in reliability.nodes}
            if reliability is not None
            else {}
        )
        self.module_type_by_node: dict[str, str] = {}
        self.stage_task_config: dict[str, tuple[ReliabilityNodeConfig, str]] = {}
        self.test_config_by_node: dict[str, ReliabilityNodeConfig] = {}
        self._index_reliability_modules()
        self._entities: list[_EntityRuntime] = []
        self._events: list[SimulationEvent] = []
        self._reliability_samples: list[ReliabilitySample] = []
        self._queue: list[tuple[float, int, str, str, str, int]] = []
        self._queue_order = 0
        self._event_seq = 0
        self._processed_events = 0
        self._reliability_sample_count = 0

    # ------------------------------------------------------------------ public
    def _index_scope(
        self,
        nodes: list[ProcessNode],
        edges: list[ProcessEdge],
        scope: tuple[str, ...],
        max_visits: int,
    ) -> None:
        effective_visits = min(max_visits, self.limits.max_node_visits)
        for node in nodes:
            self.node_by_id[node.id] = node
            self.node_scope[node.id] = scope
            self.node_max_visits[node.id] = effective_visits
            self.outgoing.setdefault(node.id, [])
        for edge in edges:
            if edge.source in self.outgoing:
                self.outgoing[edge.source].append(edge)
        for node in nodes:
            if node.subflow is not None:
                self._index_scope(
                    node.subflow.nodes,
                    node.subflow.edges,
                    scope + (node.id,),
                    min(
                        effective_visits,
                        node.subflow.guards.max_node_visits,
                    ),
                )

    def _index_reliability_modules(self) -> None:
        self.module_type_by_node = {}
        self.stage_task_config = {}
        self.test_config_by_node = {}
        if self.reliability is None:
            return
        for config in self.reliability.nodes:
            module_type = _module_type(config)
            self.module_type_by_node[config.node_id] = module_type
            if module_type == "test":
                self.test_config_by_node[config.node_id] = config
                continue
            if module_type != "stage":
                continue
            host = self.node_by_id.get(config.node_id)
            if host is None or host.type != "subprocess" or host.subflow is None:
                continue
            stage_task_id = getattr(config, "stage_task_id", None)
            if stage_task_id is None:
                stage_task = _first_stage_task(host)
                stage_task_id = stage_task.id if stage_task is not None else None
            if stage_task_id is None:
                continue
            self.stage_task_config[stage_task_id] = (config, host.id)

    def run(self) -> SimulationResult:
        self._reset_run_state()
        self._validate()
        self._prepare_entities()
        for entity in self._entities:
            self._push(
                self.simulation_start,
                "start",
                entity.entity_id,
                self.process.start_node_id,
            )

        while self._queue:
            if self._processed_events >= self.limits.max_events:
                raise SimulationRuntimeError(
                    "max_events_exceeded",
                    f"仿真事件数量超过上限 {self.limits.max_events}",
                )
            time, _order, kind, entity_id, node_id, token = heapq.heappop(
                self._queue
            )
            if time > self.simulation_end:
                heapq.heappush(
                    self._queue,
                    (time, _order, kind, entity_id, node_id, token),
                )
                break
            self._processed_events += 1
            entity = self._entity(entity_id)
            if entity.completed or entity.stopped:
                continue
            if kind == "start":
                self._enter_node(entity, self.process.start_node_id, time)
            elif kind == "complete_node":
                self._complete_node(entity, node_id, time, token=token)
            elif kind == "failure_node":
                self._process_scheduled_failure(
                    entity, node_id, time, token
                )
            else:
                raise SimulationRuntimeError(
                    "unknown_event_type",
                    f"未知内部事件类型: {kind}",
                    entity_id=entity_id,
                )

        self._finish_at_simulation_end()

        if not self._queue and not all(
            item.completed or item.stopped for item in self._entities
        ):
            stuck = next(
                item
                for item in self._entities
                if not item.completed and not item.stopped
            )
            raise SimulationRuntimeError(
                "simulation_stuck",
                "事件队列已空但设备仍未完成",
                entity_id=stuck.entity_id,
                node_id=stuck.current_node_id,
            )

        return self._build_result()

    def _reset_run_state(self) -> None:
        self._entities = []
        self._events = []
        self._reliability_samples = []
        self._queue = []
        self._queue_order = 0
        self._event_seq = 0
        self._processed_events = 0
        self._reliability_sample_count = 0

    # --------------------------------------------------------------- validation
    def _validate(self) -> None:
        issues: list[SimulationIssue] = []
        process_result = validate_process(self.process)
        if not process_result.valid:
            issues.extend(
                SimulationIssue(
                    severity=issue.severity,
                    code=issue.code,
                    message=issue.message,
                    node_id=issue.node_id,
                    edge_id=issue.edge_id,
                    field=issue.field,
                )
                for issue in process_result.issues
                if issue.severity == "error"
            )
        else:
            for issue in process_result.issues:
                if issue.code not in CONFIG_PENDING_CODES:
                    continue
                if (
                    issue.code == "missing_duration"
                    and issue.node_id in self.test_config_by_node
                    and self.test_config_by_node[issue.node_id].test_time
                    is not None
                ):
                    continue
                issues.append(
                    SimulationIssue(
                        severity="error",
                        code=issue.code,
                        message=issue.message,
                        node_id=issue.node_id,
                        edge_id=issue.edge_id,
                        field=issue.field,
                    )
                )

        if self.reliability is None:
            issues.append(
                SimulationIssue(
                    code="missing_reliability_ir",
                    message="仿真必须提供与当前 Process IR 绑定的 Reliability IR",
                    field="reliability",
                )
            )
        else:
            reliability_result = validate_reliability(
                self.process, self.reliability
            )
            if not reliability_result.valid:
                issues.extend(
                    SimulationIssue(
                        severity=issue.severity,
                        code=issue.code,
                        message=issue.message,
                        node_id=issue.node_id,
                        field=issue.field,
                    )
                    for issue in reliability_result.issues
                    if issue.severity == "error"
                )

            expected_unit = lambda_unit_for_simulation_unit(
                self.config.simulation_unit
            )
            for config in self.reliability.nodes:
                module_type = _module_type(config)
                if module_type == "test":
                    if config.detection_rate is None:
                        issues.append(
                            SimulationIssue(
                                code="missing_detection_rate",
                                message=(
                                    f"测试模块 {config.node_id} 缺少故障检测率 Ft"
                                ),
                                node_id=config.node_id,
                                field="detection_rate",
                            )
                        )
                    continue
                if not config.participates:
                    continue
                if config.lambda_per_day is None:
                    continue
                if config.lambda_unit != expected_unit:
                    issues.append(
                        SimulationIssue(
                            code="reliability_lambda_unit_mismatch",
                            message=(
                                f"节点 {config.node_id} 的 lambda 单位 "
                                f"{config.lambda_unit} 与仿真单位 "
                                f"{self.config.simulation_unit} 不一致"
                            ),
                            node_id=config.node_id,
                            field="lambda_unit",
                        )
                    )

            stage_tasks: dict[str, str] = {}
            for config in self.reliability.nodes:
                if _module_type(config) != "stage":
                    continue
                host = self.node_by_id.get(config.node_id)
                if host is None or host.type != "subprocess":
                    continue
                stage_task_id = getattr(config, "stage_task_id", None)
                if stage_task_id is None:
                    stage_task = _first_stage_task(host)
                    stage_task_id = (
                        stage_task.id if stage_task is not None else None
                    )
                if stage_task_id is None:
                    continue
                previous = stage_tasks.get(stage_task_id)
                if previous is not None and previous != config.node_id:
                    issues.append(
                        SimulationIssue(
                            code="duplicate_stage_task",
                            message=(
                                f"阶段主任务 {stage_task_id} 被多个阶段同时引用"
                            ),
                            node_id=config.node_id,
                            field="stage_task_id",
                        )
                    )
                stage_tasks[stage_task_id] = config.node_id

            if self.config.failure_policy == "require_failure_exit":
                for config in self.reliability.nodes:
                    if not config.participates:
                        continue
                    if _module_type(config) == "stage":
                        continue
                    if not config.lambda_per_day:
                        continue
                    failure_edges = [
                        edge
                        for edge in self.outgoing.get(config.node_id, [])
                        if edge.kind == "failure"
                    ]
                    if not failure_edges:
                        issues.append(
                            SimulationIssue(
                                code="missing_failure_exit",
                                message=(
                                    f"节点 {config.node_id} 参与可靠性计算且 "
                                    "lambda > 0，但没有 failure 出口"
                                ),
                                node_id=config.node_id,
                                field="edges",
                            )
                        )

        if self.config.entity_count > self.limits.max_entities:
            issues.append(
                SimulationIssue(
                    code="max_entities_exceeded",
                    message=(
                        f"设备数量 {self.config.entity_count} 超过上限 "
                        f"{self.limits.max_entities}"
                    ),
                    field="entity_count",
                )
            )
        if self.simulation_end > self.limits.max_simulation_days:
            issues.append(
                SimulationIssue(
                    code="max_simulation_days_exceeded",
                    message=(
                        f"仿真结束时间 {self.simulation_end} 天超过上限 "
                        f"{self.limits.max_simulation_days} 天"
                    ),
                    field="simulation_end",
                )
            )

        if issues:
            raise SimulationValidationError(issues)

    # ------------------------------------------------------------------ entities
    def _prepare_entities(self) -> None:
        self._entities = []
        for index in range(1, self.config.entity_count + 1):
            entity_id = f"entity_{index:04d}"
            self._entities.append(
                _EntityRuntime(
                    entity_id=entity_id,
                    current_node_id=self.process.start_node_id,
                    reliability_rng=make_stream_rng(
                        self.config.random_seed, entity_id, RELIABILITY_STREAM
                    ),
                    business_rng=make_stream_rng(
                        self.config.random_seed, entity_id, BUSINESS_STREAM
                    ),
                    detection_rng=make_stream_rng(
                        self.config.random_seed, entity_id, DETECTION_STREAM
                    ),
                )
            )

    def _entity(self, entity_id: str) -> _EntityRuntime:
        for entity in self._entities:
            if entity.entity_id == entity_id:
                return entity
        raise SimulationRuntimeError(
            "unknown_entity", f"未知设备: {entity_id}", entity_id=entity_id
        )

    # -------------------------------------------------------------- event queue
    def _push(
        self,
        time: float,
        kind: str,
        entity_id: str,
        node_id: str,
        token: int = -1,
    ) -> None:
        heapq.heappush(
            self._queue,
            (time, self._queue_order, kind, entity_id, node_id, token),
        )
        self._queue_order += 1

    def _record(
        self,
        entity: _EntityRuntime,
        event_type: str,
        time: float,
        node_id: str | None,
        data: dict[str, Any] | None = None,
    ) -> SimulationEvent:
        event = SimulationEvent(
            seq=self._event_seq,
            time=time,
            event_type=event_type,
            entity_id=entity.entity_id,
            node_id=node_id,
            scope=list(self.node_scope.get(node_id, ())),
            depth=len(self.node_scope.get(node_id, ())),
            data=data or {},
        )
        self._event_seq += 1
        self._events.append(event)
        entity.history.append(event)
        return event

    # ---------------------------------------------------------------- execution
    def _enter_node(
        self, entity: _EntityRuntime, node_id: str, time: float
    ) -> None:
        node = self.node_by_id.get(node_id)
        if node is None:
            raise SimulationRuntimeError(
                "unknown_node",
                f"无法进入未知节点: {node_id}",
                entity_id=entity.entity_id,
                node_id=node_id,
            )

        visits = entity.node_visits.get(node_id, 0) + 1
        entity.node_visits[node_id] = visits
        max_visits = self.node_max_visits.get(
            node_id, self.max_node_visits
        )
        if visits > max_visits:
            self._stop_entity(
                entity,
                "max_node_visits_exceeded",
                time,
                node_id,
                {
                    "node_id": node_id,
                    "visits": visits,
                    "max_node_visits": max_visits,
                },
            )
            return

        if node.id in self.test_config_by_node:
            entity.test_detected = False
        entity.current_node_id = node_id
        entity.node_enter_time = time
        entity.node_elapsed_time = 0.0
        entity.pending_completion_time = None
        entity.entry_token += 1
        entity.pending_failure_time = None
        entity.pending_failure_node_id = None
        entity.pending_failure_random = None
        entity.pending_failure_lambda = None
        entity.pending_reliability_random = None
        entity.pending_reliability_lambda = None
        token = entity.entry_token
        self._record(
            entity,
            "node_entered",
            time,
            node_id,
            {"node_type": node.type, "visit": visits},
        )
        self._maybe_mark_repair_start(entity, node, time)
        self._apply_status(entity, node.status_on_enter)
        self._apply_effects(
            entity, node.on_enter, time, node_id, phase="on_enter"
        )

        if node.type == "subprocess":
            subflow = node.subflow
            if subflow is None:
                raise SimulationRuntimeError(
                    "missing_subflow",
                    f"subprocess 节点 {node_id} 缺少 subflow",
                    entity_id=entity.entity_id,
                    node_id=node_id,
                )
            if len(entity.scope_stack) >= self.limits.max_nesting_depth:
                self._stop_entity(
                    entity,
                    "max_nesting_depth_exceeded",
                    time,
                    node_id,
                    {
                        "max_nesting_depth": self.limits.max_nesting_depth
                    },
                )
                return
            entity.scope_stack.append(
                _ScopeFrame(
                    block_node_id=node.id,
                    block_node=node,
                    entry_time=time,
                    end_node_ids=set(subflow.end_node_ids),
                )
            )
            self._record(
                entity,
                "subprocess_entered",
                time,
                node_id,
                {
                    "entry_node_id": subflow.start_node_id,
                    "end_node_ids": list(subflow.end_node_ids),
                },
            )
            self._enter_node(entity, subflow.start_node_id, time)
            return

        if node.type == "task":
            duration = self._effective_task_duration(node)
            if duration is None:
                raise SimulationRuntimeError(
                    "missing_duration",
                    f"task 节点 {node_id} 缺少持续时间",
                    entity_id=entity.entity_id,
                    node_id=node_id,
                )
            completion_time = time + duration
            entity.pending_completion_time = completion_time
            self._arm_reliability_for_task(
                entity, node, time, duration, token
            )
            self._push(
                completion_time,
                "complete_node",
                entity.entity_id,
                node_id,
                token,
            )
            return

        self._complete_node(entity, node_id, time)

    def _effective_task_duration(self, node: ProcessNode) -> float | None:
        test_config = self.test_config_by_node.get(node.id)
        if test_config is not None and test_config.test_time is not None:
            return float(test_config.test_time)
        if node.duration is None:
            return None
        return float(node.duration)

    def _maybe_mark_repair_start(
        self, entity: _EntityRuntime, node: ProcessNode, time: float
    ) -> None:
        if not entity.repair_pending or entity.repair_start_recorded:
            return
        is_repair_node = "repair" in node.id.lower() or "维修" in node.name
        if not is_repair_node:
            return
        entity.repair_started = True
        entity.repair_start_recorded = True
        record = self._open_failure_record(entity)
        if record is not None:
            record.repair_start_time = time
        self._record(
            entity,
            "repair_started",
            time,
            node.id,
            {
                "source": "detection",
                "failure_time": record.failure_time if record else None,
            },
        )

    def _arm_reliability_for_task(
        self,
        entity: _EntityRuntime,
        node: ProcessNode,
        time: float,
        duration: float,
        token: int,
    ) -> None:
        if node.id in self.stage_task_config or node.id in self.test_config_by_node:
            return
        config = self.reliability_by_node.get(node.id)
        if config is None or not config.participates:
            return
        lam = float(config.lambda_per_day or 0.0)
        if self.config.failure_sampling == "interval_end":
            return
        # Draw once per task visit. This keeps the per-entity reliability
        # stream stable and lets the completion record reuse the same draw.
        random_value = entity.reliability_rng.random()
        if lam <= 0 or duration <= 0:
            entity.pending_reliability_random = random_value
            entity.pending_reliability_lambda = lam
            return

        time_to_failure = -math.log1p(-random_value) / lam
        failure_time = time + time_to_failure
        entity.pending_reliability_random = random_value
        entity.pending_reliability_lambda = lam
        if failure_time <= time + duration:
            entity.pending_failure_time = failure_time
            entity.pending_failure_node_id = node.id
            entity.pending_failure_random = random_value
            entity.pending_failure_lambda = lam
            # Schedule the failure before the completion event so that an
            # exact tie at the same timestamp is resolved as a failure.
            self._push(
                failure_time,
                "failure_node",
                entity.entity_id,
                node.id,
                token,
            )

    def _exit_subflow(
        self,
        entity: _EntityRuntime,
        end_node: ProcessNode,
        time: float,
    ) -> None:
        if not entity.scope_stack:
            raise SimulationRuntimeError(
                "subflow_stack_empty",
                "子流程 end 没有对应的父流程作用域",
                entity_id=entity.entity_id,
                node_id=end_node.id,
            )
        frame = entity.scope_stack[-1]
        if end_node.id not in frame.end_node_ids:
            raise SimulationRuntimeError(
                "unknown_subflow_exit",
                (
                    f"节点 {end_node.id} 不是子流程 "
                    f"{frame.block_node_id} 声明的出口"
                ),
                entity_id=entity.entity_id,
                node_id=end_node.id,
            )
        entity.scope_stack.pop()
        elapsed = max(0.0, time - frame.entry_time)
        self._apply_effects(
            entity,
            frame.block_node.on_complete,
            time,
            frame.block_node.id,
            phase="subflow_on_complete",
        )
        self._apply_status(entity, frame.block_node.status_on_complete)
        self._record(
            entity,
            "subprocess_completed",
            time,
            frame.block_node.id,
            {
                "block_id": frame.block_node_id,
                "exit_node_id": end_node.id,
                "elapsed": elapsed,
            },
        )
        self._record(
            entity,
            "node_completed",
            time,
            frame.block_node.id,
            {
                "node_type": "subprocess",
                "elapsed": elapsed,
                "exit_node_id": end_node.id,
            },
        )

        parent_edges = self.outgoing.get(frame.block_node_id, [])
        mapped = [
            edge
            for edge in parent_edges
            if edge.subflow_exit == end_node.id
        ]
        if not mapped and len(frame.end_node_ids) == 1:
            mapped = [
                edge
                for edge in parent_edges
                if edge.subflow_exit is None
            ]
        if not mapped:
            raise SimulationRuntimeError(
                "subflow_exit_not_mapped",
                (
                    f"子流程 {frame.block_node_id} 的出口 "
                    f"{end_node.id} 没有父流程连接"
                ),
                entity_id=entity.entity_id,
                node_id=frame.block_node_id,
            )
        edge = mapped[0]
        if edge.kind == "failure":
            entity.repair_pending = True
            entity.repair_count_at_failure = entity.repair_count
            self._record(
                entity,
                "subflow_failure_routed",
                time,
                frame.block_node_id,
                {"edge_id": edge.id, "target": edge.target},
            )
            self._record(
                entity,
                "repair_started",
                time,
                edge.target,
                {
                    "source_node_id": frame.block_node_id,
                    "edge_id": edge.id,
                },
            )
        self._record(
            entity,
            "edge_taken",
            time,
            frame.block_node_id,
            {
                "edge_id": edge.id,
                "edge_kind": edge.kind,
                "target": edge.target,
                "subflow_exit": end_node.id,
            },
        )
        self._enter_node(entity, edge.target, time)

    def _complete_node(
        self,
        entity: _EntityRuntime,
        node_id: str,
        time: float,
        *,
        token: int | None = None,
    ) -> None:
        if token is not None and token != entity.entry_token:
            return
        if entity.current_node_id != node_id:
            return
        node = self.node_by_id.get(node_id)
        if node is None:
            raise SimulationRuntimeError(
                "unknown_node",
                f"无法完成未知节点: {node_id}",
                entity_id=entity.entity_id,
                node_id=node_id,
            )

        if (
            node.type == "task"
            and self.config.failure_sampling == "time_to_failure"
            and entity.pending_failure_node_id == node_id
            and entity.pending_failure_time is not None
            and entity.pending_failure_time <= time + 1e-12
        ):
            self._process_scheduled_failure(
                entity,
                node_id,
                entity.pending_failure_time,
                entity.entry_token,
            )
            return

        entity.node_elapsed_time = (
            self._effective_task_duration(node) or 0.0
            if node.type == "task"
            else 0.0
        )
        entity.pending_completion_time = None

        if node.type == "task":
            if node.id in self.stage_task_config:
                config, host_node_id = self.stage_task_config[node.id]
                self._sample_stage_task(
                    entity,
                    node,
                    host_node_id,
                    config,
                    entity.node_elapsed_time,
                    time,
                    partial=False,
                )
            else:
                config = self.reliability_by_node.get(node.id)
                if config is not None and config.participates:
                    if self.config.failure_sampling == "interval_end":
                        failure = self._sample_reliability(
                            entity,
                            node,
                            entity.node_elapsed_time,
                            time,
                            partial=False,
                        )
                        if failure:
                            self._handle_failure(
                                entity, node, time, partial=False
                            )
                            return
                    else:
                        lam = float(
                            entity.pending_reliability_lambda
                            if entity.pending_reliability_lambda is not None
                            else (config.lambda_per_day or 0.0)
                        )
                        random_value = entity.pending_reliability_random
                        if random_value is None:
                            random_value = entity.reliability_rng.random()
                        self._record_reliability_sample(
                            entity,
                            node,
                            time,
                            entity.node_elapsed_time,
                            lam,
                            random_value,
                            failure=False,
                            partial=False,
                        )
            entity.pending_failure_time = None
            entity.pending_failure_node_id = None
            if node.id in self.test_config_by_node:
                self._run_detection(entity, node, time)
            else:
                self._sample_business_outcome(entity, node, time)

        was_failed = entity.currently_failed
        self._apply_effects(
            entity, node.on_complete, time, node_id, phase="on_complete"
        )
        self._apply_status(entity, node.status_on_complete)
        self._maybe_complete_repair(
            entity,
            node,
            time,
            was_failed=was_failed,
        )

        self._record(
            entity,
            "node_completed",
            time,
            node_id,
            {"node_type": node.type, "elapsed": entity.node_elapsed_time},
        )

        if node.type == "end":
            if entity.scope_stack:
                self._exit_subflow(entity, node, time)
                return
            entity.completed = True
            self._record(entity, "entity_completed", time, node_id, {})
            return

        edge = self._select_edge(entity, node, time)
        self._record(
            entity,
            "edge_taken",
            time,
            node_id,
            {
                "edge_id": edge.id,
                "edge_kind": edge.kind,
                "target": edge.target,
            },
        )
        self._enter_node(entity, edge.target, time)

    def _select_edge(
        self, entity: _EntityRuntime, node: ProcessNode, time: float
    ) -> ProcessEdge:
        edges = self.outgoing.get(node.id, [])
        normals = [edge for edge in edges if edge.kind == "normal"]
        conditionals = [edge for edge in edges if edge.kind == "conditional"]
        defaults = [edge for edge in edges if edge.kind == "default"]

        if normals:
            return normals[0]
        if conditionals:
            matching = [
                edge
                for edge in conditionals
                if edge.condition is not None
                and self._evaluate_condition(entity, edge.condition)
            ]
            if matching:
                matching.sort(
                    key=lambda edge: (-edge.priority, edge.id)
                )
                return matching[0]
        if defaults:
            return defaults[0]

        raise SimulationRuntimeError(
            "no_matching_transition",
            f"节点 {node.id} 没有可执行的出口",
            entity_id=entity.entity_id,
            node_id=node.id,
        )

    # ------------------------------------------------------------------ effects
    def _apply_status(
        self, entity: _EntityRuntime, status: str | None
    ) -> None:
        if status is not None:
            entity.current_status = status

    def _apply_effects(
        self,
        entity: _EntityRuntime,
        effects: list[Effect],
        time: float,
        node_id: str,
        *,
        phase: str,
    ) -> None:
        if not effects:
            return
        applied: list[dict[str, Any]] = []
        for effect in effects:
            if effect.op == "set_attribute" and effect.name is not None:
                entity.attributes[effect.name] = copy.deepcopy(effect.value)
                applied.append(
                    {
                        "op": effect.op,
                        "name": effect.name,
                        "value": effect.value,
                    }
                )
            elif effect.op == "increment_counter" and effect.name is not None:
                if effect.name == "failure_count":
                    entity.failure_count += int(effect.by)
                elif effect.name == "repair_count":
                    entity.repair_count += int(effect.by)
                elif effect.name.startswith("attributes."):
                    key = effect.name.removeprefix("attributes.")
                    current = entity.attributes.get(key, 0)
                    if _finite(current):
                        entity.attributes[key] = float(current) + effect.by
                    else:
                        entity.attributes[key] = effect.by
                else:
                    raise SimulationRuntimeError(
                        "unsupported_counter",
                        f"不支持的计数器: {effect.name}",
                        entity_id=entity.entity_id,
                        node_id=node_id,
                    )
                applied.append(
                    {
                        "op": effect.op,
                        "name": effect.name,
                        "by": effect.by,
                    }
                )
            elif effect.op == "set_state" and effect.name is not None:
                if effect.name == "currently_failed":
                    entity.currently_failed = bool(effect.value)
                elif effect.name == "current_status":
                    entity.current_status = effect.value
                applied.append(
                    {
                        "op": effect.op,
                        "name": effect.name,
                        "value": effect.value,
                    }
                )
            elif effect.op == "set_status":
                entity.current_status = effect.value
                applied.append({"op": effect.op, "value": effect.value})

        self._record(
            entity,
            "effects_applied",
            time,
            node_id,
            {"phase": phase, "effects": applied},
        )

    def _future_repair_counter_exists(self, node_id: str) -> bool:
        seen: set[str] = set()
        stack = [
            edge.target for edge in self.outgoing.get(node_id, [])
        ]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            node = self.node_by_id.get(current)
            if node is not None:
                for effect in [*node.on_enter, *node.on_complete]:
                    if (
                        effect.op == "increment_counter"
                        and effect.name == "repair_count"
                    ):
                        return True
            for edge in self.outgoing.get(current, []):
                stack.append(edge.target)
        return False

    def _maybe_complete_repair(
        self,
        entity: _EntityRuntime,
        node: ProcessNode,
        time: float,
        *,
        was_failed: bool,
    ) -> None:
        if not entity.repair_pending:
            return
        recovered = was_failed and not entity.currently_failed
        repair_path_finished = node.type == "end" and not entity.scope_stack
        explicit_increment = (
            entity.repair_count != entity.repair_count_at_failure
        )
        if not explicit_increment:
            if not recovered and not repair_path_finished:
                return
            if recovered and self._future_repair_counter_exists(node.id):
                return
        auto_incremented = False
        if not explicit_increment:
            entity.repair_count += 1
            auto_incremented = True
        entity.repair_pending = False
        entity.repair_active = False
        if recovered:
            record = self._open_failure_record(entity)
            if record is not None:
                if record.repair_start_time is None:
                    record.repair_start_time = (
                        record.detection_time
                        if record.detection_time is not None
                        else time
                    )
                record.repair_end_time = time
                record.repaired = True
                record.unavailable_time = max(
                    0.0, time - record.failure_time
                )
        self._record(
            entity,
            "repair_completed",
            time,
            node.id,
            {
                "repair_count": entity.repair_count,
                "auto_incremented": auto_incremented,
                "explicit_effect_increment": explicit_increment,
                "currently_failed": entity.currently_failed,
            },
        )

    # -------------------------------------------------------------- reliability
    def _open_failure_record(
        self, entity: _EntityRuntime
    ) -> FailureRecord | None:
        for record in reversed(entity.failure_records):
            if not record.repaired and not record.open_at_end:
                return record
        return None

    def _register_failure(
        self,
        entity: _EntityRuntime,
        node_id: str,
        failure_time: float,
        lam: float,
        *,
        stage_task_id: str | None = None,
        event_time: float | None = None,
        partial: bool = False,
        sampling_mode: str = "time_to_failure",
    ) -> FailureRecord:
        entity.failure_count += 1
        entity.ever_failed = True
        entity.currently_failed = True
        record = FailureRecord(
            failure_time=failure_time,
            node_id=node_id,
            stage_task_id=stage_task_id,
            failure_lambda=lam,
        )
        entity.failure_records.append(record)
        self._record(
            entity,
            "reliability_failure",
            event_time if event_time is not None else failure_time,
            node_id,
            {
                "failure_count": entity.failure_count,
                "ever_failed": entity.ever_failed,
                "partial": partial,
                "failure_time": failure_time,
                "stage_task_id": stage_task_id,
                "sampling_mode": sampling_mode,
            },
        )
        return record

    def _sample_stage_task(
        self,
        entity: _EntityRuntime,
        node: ProcessNode,
        host_node_id: str,
        config: ReliabilityNodeConfig,
        duration: float,
        completion_time: float,
        *,
        partial: bool,
    ) -> None:
        if duration <= 0:
            return
        if entity.currently_failed:
            self._record(
                entity,
                "stage_sampling_skipped",
                completion_time,
                host_node_id,
                {
                    "reason": "entity_already_failed",
                    "stage_task_id": node.id,
                },
            )
            return
        lam = float(config.lambda_per_day or 0.0)
        step = float(self.config.reliability_step)
        start_time = entity.node_enter_time
        elapsed = 0.0
        step_index = 0
        failure_time: float | None = None
        failure_random: float | None = None
        failure_probability: float | None = None
        max_steps = 1_000_000
        while elapsed < duration - 1e-12:
            if step_index >= max_steps:
                raise SimulationRuntimeError(
                    "reliability_step_limit_exceeded",
                    f"阶段 {host_node_id} 的抽样步数超过上限 {max_steps}",
                    entity_id=entity.entity_id,
                    node_id=host_node_id,
                )
            length = min(step, duration - elapsed)
            elapsed += length
            step_index += 1
            random_value = entity.reliability_rng.random()
            reliability = math.exp(-lam * elapsed)
            failed = random_value > reliability
            sample_time = start_time + elapsed
            self._reliability_sample_count += 1
            self._reliability_samples.append(
                ReliabilitySample(
                    entity_id=entity.entity_id,
                    node_id=host_node_id,
                    time=sample_time,
                    lambda_per_day=lam,
                    exposure_time=length,
                    reliability_probability=reliability,
                    random_value=random_value,
                    failure_occurred=failed,
                    partial=partial,
                    failure_time=sample_time if failed else None,
                    scope_path=list(self.node_scope.get(node.id, ())),
                    module_type="stage",
                    sampling_mode="stepwise",
                    stage_task_id=node.id,
                    host_node_id=host_node_id,
                    cumulative_exposure=elapsed,
                    step_index=step_index,
                )
            )
            if failed:
                failure_time = sample_time
                failure_random = random_value
                failure_probability = reliability
                break
        self._record(
            entity,
            "stage_sampling",
            completion_time,
            host_node_id,
            {
                "stage_task_id": node.id,
                "lambda": lam,
                "lambda_unit": config.lambda_unit,
                "step": step,
                "sampled_steps": step_index,
                "duration": duration,
                "failure_time": failure_time,
                "failure_random": failure_random,
                "failure_probability": failure_probability,
                "partial": partial,
            },
        )
        if failure_time is not None:
            self._register_failure(
                entity,
                host_node_id,
                failure_time,
                lam,
                stage_task_id=node.id,
                event_time=completion_time,
                partial=partial,
                sampling_mode="stepwise",
            )

    def _run_detection(
        self, entity: _EntityRuntime, node: ProcessNode, time: float
    ) -> None:
        config = self.test_config_by_node.get(node.id)
        if config is None:
            return
        ft = float(config.detection_rate or 0.0)
        random_value = entity.detection_rng.random()
        had_fault = entity.currently_failed
        detected = bool(had_fault and random_value <= ft)
        record = self._open_failure_record(entity) if had_fault else None
        if detected and record is None:
            record = self._register_failure(
                entity,
                node.id,
                time,
                float(config.lambda_per_day or 0.0),
                event_time=time,
                sampling_mode="stepwise",
            )
        failure_time = record.failure_time if record is not None else None
        entity.test_records.append(
            TestRecord(
                node_id=node.id,
                time=time,
                detection_rate=ft,
                random_value=random_value,
                had_fault=had_fault,
                detected=detected,
                failure_time=failure_time,
                test_time=entity.node_elapsed_time,
            )
        )
        entity.test_detected = detected
        entity.attributes["test_detected"] = detected
        entity.attributes["last_test_detected"] = detected
        entity.attributes["detection_result"] = (
            "detected"
            if detected
            else ("not_detected" if had_fault else "pass")
        )
        self._record(
            entity,
            "test_detection",
            time,
            node.id,
            {
                "detection_rate": ft,
                "random_value": random_value,
                "had_fault": had_fault,
                "detected": detected,
                "failure_time": failure_time,
                "test_time": entity.node_elapsed_time,
            },
        )
        if detected and record is not None:
            record.detected = True
            record.detection_time = time
            record.detection_node_id = node.id
            record.detection_random = random_value
            record.detection_rate = ft
            entity.repair_pending = True
            entity.repair_count_at_failure = entity.repair_count
            entity.repair_active = False
            entity.repair_start_recorded = False
            entity.repair_started = False
            self._record(
                entity,
                "fault_detected",
                time,
                node.id,
                {
                    "detection_rate": ft,
                    "random_value": random_value,
                    "failure_time": failure_time,
                },
            )
        elif had_fault:
            self._record(
                entity,
                "fault_not_detected",
                time,
                node.id,
                {
                    "detection_rate": ft,
                    "random_value": random_value,
                    "failure_time": failure_time,
                },
            )
        else:
            self._record(
                entity,
                "test_passed",
                time,
                node.id,
                {"detection_rate": ft, "random_value": random_value},
            )

    def _record_reliability_sample(
        self,
        entity: _EntityRuntime,
        node: ProcessNode,
        time: float,
        exposure: float,
        lam: float,
        random_value: float,
        *,
        failure: bool,
        partial: bool,
        failure_time: float | None = None,
    ) -> bool:
        probability = math.exp(-lam * exposure)
        self._reliability_sample_count += 1
        self._reliability_samples.append(
            ReliabilitySample(
                entity_id=entity.entity_id,
                node_id=node.id,
                time=time,
                lambda_per_day=lam,
                exposure_time=exposure,
                reliability_probability=probability,
                random_value=random_value,
                failure_occurred=failure,
                partial=partial,
                failure_time=failure_time,
                scope_path=list(self.node_scope.get(node.id, ())),
            )
        )
        self._record(
            entity,
            "reliability_sample",
            time,
            node.id,
            {
                "lambda": lam,
                "exposure_time": exposure,
                "reliability_probability": probability,
                "random_value": random_value,
                "failure_occurred": failure,
                "partial": partial,
                "failure_time": failure_time,
            },
        )
        if failure:
            self._register_failure(
                entity,
                node.id,
                failure_time if failure_time is not None else time,
                lam,
                event_time=time,
                partial=partial,
                sampling_mode=self.config.failure_sampling,
            )
        return failure

    def _sample_reliability(
        self,
        entity: _EntityRuntime,
        node: ProcessNode,
        exposure: float,
        time: float,
        *,
        partial: bool,
    ) -> bool:
        config = self.reliability_by_node.get(node.id)
        if config is None or not config.participates:
            return False
        lam = float(config.lambda_per_day or 0.0)
        probability = math.exp(-lam * exposure)
        random_value = entity.reliability_rng.random()
        failure = random_value >= probability
        return self._record_reliability_sample(
            entity,
            node,
            time,
            exposure,
            lam,
            random_value,
            failure=failure,
            partial=partial,
        )

    def _process_scheduled_failure(
        self,
        entity: _EntityRuntime,
        node_id: str,
        time: float,
        token: int,
    ) -> None:
        if entity.completed or entity.stopped:
            return
        if token != entity.entry_token:
            return
        if entity.current_node_id != node_id:
            return
        if entity.pending_failure_node_id != node_id:
            return
        if entity.pending_failure_time is None:
            return
        if abs(entity.pending_failure_time - time) > 1e-9:
            return
        node = self.node_by_id.get(node_id)
        if node is None:
            raise SimulationRuntimeError(
                "unknown_node",
                f"无法处理未知节点的故障: {node_id}",
                entity_id=entity.entity_id,
                node_id=node_id,
            )
        exposure = max(0.0, time - entity.node_enter_time)
        lam = float(entity.pending_failure_lambda or 0.0)
        random_value = entity.pending_failure_random
        if random_value is None:
            random_value = entity.reliability_rng.random()
        entity.node_elapsed_time = exposure
        entity.pending_completion_time = None
        entity.pending_failure_time = None
        entity.pending_failure_node_id = None
        entity.pending_failure_random = None
        entity.pending_failure_lambda = None
        self._record_reliability_sample(
            entity,
            node,
            time,
            exposure,
            lam,
            random_value,
            failure=True,
            partial=False,
            failure_time=time,
        )
        self._handle_failure(entity, node, time, partial=False)

    def _handle_failure(
        self,
        entity: _EntityRuntime,
        node: ProcessNode,
        time: float,
        *,
        partial: bool,
    ) -> None:
        self._record(
            entity,
            "node_failed",
            time,
            node.id,
            {
                "failure_count": entity.failure_count,
                "currently_failed": entity.currently_failed,
                "partial": partial,
            },
        )
        if partial:
            return
        failure_edges = [
            edge for edge in self.outgoing.get(node.id, []) if edge.kind == "failure"
        ]
        if failure_edges:
            edge = failure_edges[0]
            target_node = self.node_by_id.get(edge.target)
            deferred_subflow_exit = bool(
                target_node is not None
                and target_node.type == "end"
                and entity.scope_stack
                and edge.target in entity.scope_stack[-1].end_node_ids
            )
            entity.current_node_id = edge.target
            if not deferred_subflow_exit:
                entity.repair_pending = True
                entity.repair_count_at_failure = entity.repair_count
            self._record(
                entity,
                "failure_routed",
                time,
                node.id,
                {
                    "edge_id": edge.id,
                    "target": edge.target,
                    "deferred_subflow_exit": deferred_subflow_exit,
                },
            )
            if not deferred_subflow_exit:
                self._record(
                    entity,
                    "repair_started",
                    time,
                    edge.target,
                    {"source_node_id": node.id, "edge_id": edge.id},
                )
            self._enter_node(entity, edge.target, time)
            return

        if self.config.failure_policy == "stop_entity":
            self._stop_entity(
                entity,
                "failure_without_exit",
                time,
                node.id,
                {"failure_count": entity.failure_count},
            )
            return

        raise SimulationRuntimeError(
            "failure_exit_not_configured",
            f"节点 {node.id} 发生可靠性故障，但没有 failure 出口或故障策略",
            entity_id=entity.entity_id,
            node_id=node.id,
        )

    # ---------------------------------------------------------------- business
    def _sample_business_outcome(
        self, entity: _EntityRuntime, node: ProcessNode, time: float
    ) -> None:
        if not node.outcomes:
            return
        weights = [outcome.weight for outcome in node.outcomes]
        total = sum(weights)
        if total <= 0:
            raise SimulationRuntimeError(
                "invalid_outcome_weights",
                f"节点 {node.id} 的业务结果权重之和必须大于 0",
                entity_id=entity.entity_id,
                node_id=node.id,
            )
        random_value = entity.business_rng.random() * total
        cumulative = 0.0
        chosen = node.outcomes[-1]
        for outcome, weight in zip(node.outcomes, weights):
            cumulative += weight
            if random_value < cumulative:
                chosen = outcome
                break
        for key, value in chosen.attributes.items():
            entity.attributes[key] = copy.deepcopy(value)
        self._record(
            entity,
            "business_outcome",
            time,
            node.id,
            {
                "outcome_id": chosen.id,
                "outcome_name": chosen.name,
                "random_value": random_value,
                "total_weight": total,
                "attributes": dict(chosen.attributes),
            },
        )

    # --------------------------------------------------------------- conditions
    def _field_value(self, entity: _EntityRuntime, field: str) -> Any:
        if field == "entity_id":
            return entity.entity_id
        if field == "currently_failed":
            return entity.currently_failed
        if field == "ever_failed":
            return entity.ever_failed
        if field == "failure_count":
            return entity.failure_count
        if field == "repair_count":
            return entity.repair_count
        if field == "current_status":
            return entity.current_status
        if field in {"test_detected", "last_test_detected"}:
            return entity.test_detected
        if field == "unavailable_time":
            return sum(
                record.unavailable_time for record in entity.failure_records
            )
        if field.startswith("attributes."):
            return entity.attributes.get(
                field.removeprefix("attributes."), _MISSING
            )
        if field.startswith("node_visits."):
            return entity.node_visits.get(field.removeprefix("node_visits."), 0)
        return _MISSING

    def _evaluate_condition(
        self, entity: _EntityRuntime, condition: Condition
    ) -> bool:
        if condition.op == "and":
            return all(
                self._evaluate_condition(entity, child)
                for child in condition.conditions or []
            )
        if condition.op == "or":
            return any(
                self._evaluate_condition(entity, child)
                for child in condition.conditions or []
            )
        if condition.op == "not":
            children = condition.conditions or []
            return not self._evaluate_condition(entity, children[0])

        value = self._field_value(entity, condition.field or "")
        if condition.op == "exists":
            return value is not _MISSING and value is not None
        if condition.op == "is_null":
            return value is _MISSING or value is None

        if value is _MISSING:
            return condition.op == "ne"
        if condition.op == "eq":
            return value == condition.value
        if condition.op == "ne":
            return value != condition.value
        if condition.op in {"gt", "gte", "lt", "lte"}:
            if not _finite(value) or not _finite(condition.value):
                return False
            left = float(value)
            right = float(condition.value)
            return {
                "gt": left > right,
                "gte": left >= right,
                "lt": left < right,
                "lte": left <= right,
            }[condition.op]
        if condition.op in {"in", "not_in"}:
            contained = value in (condition.value or [])
            return contained if condition.op == "in" else not contained
        return False

    # ----------------------------------------------------------------- stopping
    def _stop_entity(
        self,
        entity: _EntityRuntime,
        reason: str,
        time: float,
        node_id: str | None,
        data: dict[str, Any] | None = None,
    ) -> None:
        entity.stopped = True
        entity.stopped_reason = reason
        self._record(
            entity,
            "entity_stopped",
            time,
            node_id,
            {"reason": reason, **(data or {})},
        )

    def _finish_at_simulation_end(self) -> None:
        end = self.simulation_end
        for entity in self._entities:
            if entity.completed or entity.stopped:
                continue
            if entity.pending_completion_time is None:
                continue
            if entity.pending_completion_time <= end:
                continue
            exposure = end - entity.node_enter_time
            if exposure < 0:
                exposure = 0.0
            entity.node_elapsed_time = exposure
            node = self.node_by_id.get(entity.current_node_id)
            if node is None or node.type != "task" or exposure <= 0:
                continue
            stage = self.stage_task_config.get(node.id)
            if stage is not None:
                stage_config, host_node_id = stage
                self._sample_stage_task(
                    entity,
                    node,
                    host_node_id,
                    stage_config,
                    exposure,
                    end,
                    partial=True,
                )
                continue
            config = self.reliability_by_node.get(node.id)
            if config is None or not config.participates:
                continue
            if self.config.failure_sampling == "time_to_failure":
                lam = float(
                    entity.pending_reliability_lambda
                    if entity.pending_reliability_lambda is not None
                    else (config.lambda_per_day or 0.0)
                )
                random_value = entity.pending_reliability_random
                if random_value is None:
                    random_value = entity.reliability_rng.random()
                self._record_reliability_sample(
                    entity,
                    node,
                    end,
                    exposure,
                    lam,
                    random_value,
                    failure=False,
                    partial=True,
                )
                continue
            failure = self._sample_reliability(
                entity, node, exposure, end, partial=True
            )
            if failure:
                self._handle_failure(entity, node, end, partial=True)

    # ------------------------------------------------------------------ result
    def _finalize_availability(
        self, entity: _EntityRuntime
    ) -> tuple[float, float]:
        end = self.simulation_end
        start = self.simulation_start
        horizon = max(0.0, end - start)
        unavailable = 0.0
        for record in entity.failure_records:
            if record.repaired:
                interval_end = (
                    record.repair_end_time
                    if record.repair_end_time is not None
                    else end
                )
            else:
                record.open_at_end = True
                interval_end = end
                record.repair_end_time = (
                    record.repair_end_time
                    if record.repair_end_time is not None
                    else end
                )
            interval_start = max(start, record.failure_time)
            interval_end = min(end, max(interval_start, interval_end))
            record.unavailable_time = max(0.0, interval_end - interval_start)
            unavailable += record.unavailable_time
        unavailable = min(horizon, unavailable)
        available = max(0.0, horizon - unavailable)
        return available, unavailable

    def _build_result(self) -> SimulationResult:
        entities: list[EntitySimulationResult] = []
        for entity in self._entities:
            available_time, unavailable_time = self._finalize_availability(
                entity
            )
            entities.append(
                EntitySimulationResult(
                    entity_id=entity.entity_id,
                    final_node_id=entity.current_node_id,
                    current_status=entity.current_status,
                    node_enter_time=entity.node_enter_time,
                    node_elapsed_time=entity.node_elapsed_time,
                    failure_count=entity.failure_count,
                    repair_count=entity.repair_count,
                    ever_failed=entity.ever_failed,
                    currently_failed=entity.currently_failed,
                    attributes=dict(entity.attributes),
                    node_visits=dict(entity.node_visits),
                    scope_path=list(
                        self.node_scope.get(entity.current_node_id, ())
                    ),
                    completed=entity.completed,
                    stopped=entity.stopped,
                    stopped_reason=entity.stopped_reason,
                    history=list(entity.history),
                    available_time=available_time,
                    unavailable_time=unavailable_time,
                    failure_records=list(entity.failure_records),
                    test_records=list(entity.test_records),
                )
            )
        reliability = self.reliability
        if reliability is None:
            raise SimulationRuntimeError(
                "missing_reliability_ir",
                "仿真缺少 Reliability IR",
            )
        return SimulationResult(
            process_id=self.process.process_id,
            process_version=self.process.version,
            process_hash=self.process.content_hash,
            reliability_id=reliability.reliability_id,
            reliability_revision=reliability.revision,
            runtime_semantic_version=(
                "stepwise-detection/1.0"
                if self.stage_task_config
                else (
                    "time-to-failure/1.0"
                    if self.config.failure_sampling == "time_to_failure"
                    else "interval-end/1.0"
                )
            ),
            failure_sampling=self.config.failure_sampling,
            reliability_sampling_mode=(
                "stepwise" if self.stage_task_config else "legacy"
            ),
            random_seed=self.config.random_seed,
            entity_count=self.config.entity_count,
            simulation_start=self.simulation_start,
            simulation_end=self.simulation_end,
            simulation_duration=self.config.simulation_duration,
            simulation_unit=self.config.simulation_unit,
            project=self.config.project,
            event_count=len(self._events),
            reliability_sample_count=self._reliability_sample_count,
            total_failure_count=sum(
                entity.failure_count for entity in self._entities
            ),
            completed_count=sum(1 for entity in self._entities if entity.completed),
            stopped_count=sum(1 for entity in self._entities if entity.stopped),
            entities=entities,
            reliability_samples=list(self._reliability_samples),
            events=list(self._events),
        )


def run_simulation(
    process: ProcessDocument,
    reliability: ReliabilityDocument,
    config: SimulationConfig,
    limits: SimulationLimits | None = None,
) -> SimulationResult:
    return SimulationRuntime(process, config, reliability, limits).run()


__all__ = ["SimulationRuntime", "run_simulation"]
