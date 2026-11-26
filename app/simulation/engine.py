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
from app.domain.reliability_ir import ReliabilityDocument
from app.domain.reliability_validation import validate_reliability
from app.domain.validation import validate_process
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
    ReliabilitySample,
    SimulationEvent,
    SimulationIssue,
    SimulationResult,
)
from app.simulation.rng import (
    BUSINESS_STREAM,
    RELIABILITY_STREAM,
    make_stream_rng,
)


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
    history: list[SimulationEvent] = field(default_factory=list)
    completed: bool = False
    stopped: bool = False
    stopped_reason: str | None = None
    pending_completion_time: float | None = None
    repair_pending: bool = False
    repair_count_at_failure: int = 0
    reliability_rng: random.Random = field(
        default_factory=random.Random, repr=False
    )
    business_rng: random.Random = field(
        default_factory=random.Random, repr=False
    )


_MISSING = object()


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


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
        self.reliability = reliability
        self.limits = limits or DEFAULT_LIMITS
        self.node_by_id = {node.id: node for node in process.nodes}
        self.outgoing: dict[str, list[ProcessEdge]] = {
            node.id: [] for node in process.nodes
        }
        for edge in process.edges:
            if edge.source in self.outgoing:
                self.outgoing[edge.source].append(edge)
        self.reliability_by_node = (
            {config.node_id: config for config in reliability.nodes}
            if reliability is not None
            else {}
        )
        self.max_node_visits = min(
            process.guards.max_node_visits, self.limits.max_node_visits
        )
        self._entities: list[_EntityRuntime] = []
        self._events: list[SimulationEvent] = []
        self._reliability_samples: list[ReliabilitySample] = []
        self._queue: list[tuple[float, int, str, str, str]] = []
        self._queue_order = 0
        self._event_seq = 0
        self._processed_events = 0
        self._reliability_sample_count = 0

    # ------------------------------------------------------------------ public
    def run(self) -> SimulationResult:
        self._reset_run_state()
        self._validate()
        self._prepare_entities()
        for entity in self._entities:
            self._push(0.0, "start", entity.entity_id, self.process.start_node_id)

        while self._queue:
            if self._processed_events >= self.limits.max_events:
                raise SimulationRuntimeError(
                    "max_events_exceeded",
                    f"仿真事件数量超过上限 {self.limits.max_events}",
                )
            time, _order, kind, entity_id, node_id = heapq.heappop(self._queue)
            if time > self.config.simulation_end:
                heapq.heappush(
                    self._queue, (time, _order, kind, entity_id, node_id)
                )
                break
            self._processed_events += 1
            entity = self._entity(entity_id)
            if entity.completed or entity.stopped:
                continue
            if kind == "start":
                self._enter_node(entity, self.process.start_node_id, time)
            elif kind == "complete_node":
                self._complete_node(entity, node_id, time)
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

            if self.config.failure_policy == "require_failure_exit":
                for config in self.reliability.nodes:
                    if not config.participates:
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
        if self.config.simulation_end > self.limits.max_simulation_days:
            issues.append(
                SimulationIssue(
                    code="max_simulation_days_exceeded",
                    message=(
                        f"仿真结束时间 {self.config.simulation_end} 天超过上限 "
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
    def _push(self, time: float, kind: str, entity_id: str, node_id: str) -> None:
        heapq.heappush(
            self._queue,
            (time, self._queue_order, kind, entity_id, node_id),
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
        if visits > self.max_node_visits:
            self._stop_entity(
                entity,
                "max_node_visits_exceeded",
                time,
                node_id,
                {
                    "node_id": node_id,
                    "visits": visits,
                    "max_node_visits": self.max_node_visits,
                },
            )
            return

        entity.current_node_id = node_id
        entity.node_enter_time = time
        entity.node_elapsed_time = 0.0
        entity.pending_completion_time = None
        self._record(
            entity,
            "node_entered",
            time,
            node_id,
            {"node_type": node.type, "visit": visits},
        )
        self._apply_status(entity, node.status_on_enter)
        self._apply_effects(
            entity, node.on_enter, time, node_id, phase="on_enter"
        )

        if node.type == "task":
            if node.duration is None:
                raise SimulationRuntimeError(
                    "missing_duration",
                    f"task 节点 {node_id} 缺少持续时间",
                    entity_id=entity.entity_id,
                    node_id=node_id,
                )
            completion_time = time + float(node.duration)
            entity.pending_completion_time = completion_time
            self._push(completion_time, "complete_node", entity.entity_id, node_id)
            return

        self._complete_node(entity, node_id, time)

    def _complete_node(
        self, entity: _EntityRuntime, node_id: str, time: float
    ) -> None:
        node = self.node_by_id.get(node_id)
        if node is None:
            raise SimulationRuntimeError(
                "unknown_node",
                f"无法完成未知节点: {node_id}",
                entity_id=entity.entity_id,
                node_id=node_id,
            )

        entity.node_elapsed_time = (
            float(node.duration or 0.0) if node.type == "task" else 0.0
        )
        entity.pending_completion_time = None

        if node.type == "task":
            config = self.reliability_by_node.get(node.id)
            if config is not None and config.participates:
                failure = self._sample_reliability(
                    entity,
                    node,
                    entity.node_elapsed_time,
                    time,
                    partial=False,
                )
                if failure:
                    self._handle_failure(entity, node, time, partial=False)
                    return
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
        repair_path_finished = node.type == "end"
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
            },
        )
        if failure:
            entity.failure_count += 1
            entity.ever_failed = True
            entity.currently_failed = True
            self._record(
                entity,
                "reliability_failure",
                time,
                node.id,
                {
                    "failure_count": entity.failure_count,
                    "ever_failed": entity.ever_failed,
                    "partial": partial,
                },
            )
        return failure

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
            entity.current_node_id = edge.target
            entity.repair_pending = True
            entity.repair_count_at_failure = entity.repair_count
            self._record(
                entity,
                "failure_routed",
                time,
                node.id,
                {"edge_id": edge.id, "target": edge.target},
            )
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
        end = self.config.simulation_end
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
            config = self.reliability_by_node.get(node.id)
            if config is None or not config.participates:
                continue
            failure = self._sample_reliability(
                entity, node, exposure, end, partial=True
            )
            if failure:
                self._handle_failure(entity, node, end, partial=True)

    # ------------------------------------------------------------------ result
    def _build_result(self) -> SimulationResult:
        entities = [
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
                completed=entity.completed,
                stopped=entity.stopped,
                stopped_reason=entity.stopped_reason,
                history=list(entity.history),
            )
            for entity in self._entities
        ]
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
            random_seed=self.config.random_seed,
            entity_count=self.config.entity_count,
            simulation_end=self.config.simulation_end,
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
