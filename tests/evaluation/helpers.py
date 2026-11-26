from __future__ import annotations

from typing import Any

from app.domain.process_ir import ProcessDocument
from app.domain.reliability_ir import ReliabilityDocument
from app.simulation.models import (
    EntitySimulationResult,
    ReliabilitySample,
    SimulationEvent,
    SimulationResult,
)
from tests.helpers import document_from_spec, reliability_document_from_process, spec_from


def make_process(
    *,
    status_catalog: list[dict[str, Any]] | None = None,
    duration: float = 1.0,
    status_on_enter: str | None = None,
) -> ProcessDocument:
    data = {
        "schema_version": "process-ir/1.0",
        "name": "评价测试流程",
        "description": "",
        "status_catalog": status_catalog or [],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {
                "id": "work",
                "type": "task",
                "name": "可靠性任务",
                "duration": duration,
                **(
                    {"status_on_enter": status_on_enter}
                    if status_on_enter
                    else {}
                ),
            },
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_work", "from": "start", "to": "work", "kind": "normal"},
            {"id": "e_work_end", "from": "work", "to": "end", "kind": "normal"},
        ],
        "guards": {"max_node_visits": 10000},
    }
    return document_from_spec(spec_from(data))


def make_reliability(
    process: ProcessDocument,
    *,
    lam: float | None = 0.1,
    participates: bool = True,
    revision: int = 1,
) -> ReliabilityDocument:
    node: dict[str, Any] = {
        "node_id": "work",
        "participates": participates,
    }
    if participates and lam is not None:
        node["lambda"] = lam
    return reliability_document_from_process(
        process, [node], revision=revision
    )


def ev(
    seq: int,
    time: float,
    event_type: str,
    entity_id: str,
    node_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> SimulationEvent:
    return SimulationEvent(
        seq=seq,
        time=time,
        event_type=event_type,
        entity_id=entity_id,
        node_id=node_id,
        data=data or {},
    )


def sample(
    entity_id: str,
    *,
    lam: float = 0.1,
    exposure: float = 1.0,
    failure: bool = False,
    partial: bool = False,
    time: float = 1.0,
    random_value: float = 0.5,
    node_id: str = "work",
) -> ReliabilitySample:
    import math

    return ReliabilitySample(
        entity_id=entity_id,
        node_id=node_id,
        time=time,
        lambda_per_day=lam,
        exposure_time=exposure,
        reliability_probability=math.exp(-lam * exposure),
        random_value=random_value,
        failure_occurred=failure,
        partial=partial,
    )


def entity(
    entity_id: str,
    *,
    final_node_id: str = "end",
    status: str | None = "operational",
    history: list[SimulationEvent] | None = None,
    node_visits: dict[str, int] | None = None,
    failure_count: int = 0,
    repair_count: int = 0,
    ever_failed: bool = False,
    currently_failed: bool = False,
    completed: bool = True,
    stopped: bool = False,
    stopped_reason: str | None = None,
    node_enter_time: float = 0.0,
    node_elapsed_time: float = 0.0,
) -> EntitySimulationResult:
    return EntitySimulationResult(
        entity_id=entity_id,
        final_node_id=final_node_id,
        current_status=status,
        node_enter_time=node_enter_time,
        node_elapsed_time=node_elapsed_time,
        failure_count=failure_count,
        repair_count=repair_count,
        ever_failed=ever_failed,
        currently_failed=currently_failed,
        attributes={},
        node_visits=node_visits or {},
        completed=completed,
        stopped=stopped,
        stopped_reason=stopped_reason,
        history=history or [],
    )


def completed_history(
    entity_id: str,
    *,
    seq_base: int = 0,
    duration: float = 1.0,
) -> list[SimulationEvent]:
    return [
        ev(seq_base, 0, "node_entered", entity_id, "start", {"node_type": "start", "visit": 1}),
        ev(seq_base + 1, 0, "node_completed", entity_id, "start", {"node_type": "start", "elapsed": 0}),
        ev(seq_base + 2, 0, "node_entered", entity_id, "work", {"node_type": "task", "visit": 1}),
        ev(seq_base + 3, duration, "node_completed", entity_id, "work", {"node_type": "task", "elapsed": duration}),
        ev(seq_base + 4, duration, "node_entered", entity_id, "end", {"node_type": "end", "visit": 1}),
        ev(seq_base + 5, duration, "node_completed", entity_id, "end", {"node_type": "end", "elapsed": 0}),
        ev(seq_base + 6, duration, "entity_completed", entity_id, "end"),
    ]


def completed_entity(
    entity_id: str,
    *,
    seq_base: int = 0,
    duration: float = 1.0,
    status: str | None = "operational",
) -> EntitySimulationResult:
    return entity(
        entity_id,
        status=status,
        history=completed_history(
            entity_id, seq_base=seq_base, duration=duration
        ),
        node_visits={"start": 1, "work": 1, "end": 1},
        node_enter_time=duration,
        node_elapsed_time=0.0,
    )


def make_result(
    process: ProcessDocument,
    reliability: ReliabilityDocument,
    entities: list[EntitySimulationResult],
    samples: list[ReliabilitySample] | None = None,
    *,
    entity_count: int | None = None,
    simulation_end: float = 10.0,
    random_seed: int = 1,
) -> SimulationResult:
    samples = samples or []
    all_events = [
        event for item in entities for event in item.history
    ]
    all_events.sort(key=lambda item: item.seq)
    return SimulationResult(
        process_id=process.process_id,
        process_version=process.version,
        process_hash=process.content_hash,
        reliability_id=reliability.reliability_id,
        reliability_revision=reliability.revision,
        random_seed=random_seed,
        entity_count=entity_count or len(entities),
        simulation_end=simulation_end,
        event_count=len(all_events),
        reliability_sample_count=len(samples),
        total_failure_count=sum(item.failure_count for item in entities),
        completed_count=sum(1 for item in entities if item.completed),
        stopped_count=sum(1 for item in entities if item.stopped),
        entities=entities,
        reliability_samples=samples,
        events=all_events,
    )


def failed_repaired_entity(
    entity_id: str,
    *,
    seq_base: int = 0,
    lam: float = 0.1,
    exposure: float = 1.0,
    repair_duration: float = 0.5,
) -> EntitySimulationResult:
    import math

    probability = math.exp(-lam * exposure)
    history = [
        ev(seq_base, 0, "node_entered", entity_id, "start", {"node_type": "start", "visit": 1}),
        ev(seq_base + 1, 0, "node_completed", entity_id, "start", {"node_type": "start", "elapsed": 0}),
        ev(seq_base + 2, 0, "node_entered", entity_id, "work", {"node_type": "task", "visit": 1}),
        ev(
            seq_base + 3,
            exposure,
            "reliability_sample",
            entity_id,
            "work",
            {
                "lambda": lam,
                "exposure_time": exposure,
                "reliability_probability": probability,
                "random_value": 0.9,
                "failure_occurred": True,
                "partial": False,
            },
        ),
        ev(
            seq_base + 4,
            exposure,
            "reliability_failure",
            entity_id,
            "work",
            {"failure_count": 1, "ever_failed": True, "partial": False},
        ),
        ev(
            seq_base + 5,
            exposure,
            "failure_routed",
            entity_id,
            "work",
            {"target": "repair"},
        ),
        ev(
            seq_base + 6,
            exposure,
            "repair_started",
            entity_id,
            "repair",
            {"source_node_id": "work"},
        ),
        ev(seq_base + 7, exposure, "node_entered", entity_id, "repair", {"node_type": "task", "visit": 1}),
        ev(
            seq_base + 8,
            exposure + repair_duration,
            "node_completed",
            entity_id,
            "repair",
            {"node_type": "task", "elapsed": repair_duration},
        ),
        ev(
            seq_base + 9,
            exposure + repair_duration,
            "repair_completed",
            entity_id,
            "repair",
            {"repair_count": 1, "auto_incremented": False, "explicit_effect_increment": True},
        ),
        ev(
            seq_base + 10,
            exposure + repair_duration,
            "node_entered",
            entity_id,
            "end",
            {"node_type": "end", "visit": 1},
        ),
        ev(
            seq_base + 11,
            exposure + repair_duration,
            "node_completed",
            entity_id,
            "end",
            {"node_type": "end", "elapsed": 0},
        ),
        ev(seq_base + 12, exposure + repair_duration, "entity_completed", entity_id, "end"),
    ]
    return entity(
        entity_id,
        status="operational",
        history=history,
        node_visits={"start": 1, "work": 1, "repair": 1, "end": 1},
        failure_count=1,
        repair_count=1,
        ever_failed=True,
        currently_failed=False,
        completed=True,
    )


def partial_entity(
    entity_id: str,
    *,
    seq_base: int = 0,
    lam: float = 0.1,
    exposure: float = 0.5,
    failure: bool = False,
) -> EntitySimulationResult:
    import math

    probability = math.exp(-lam * exposure)
    history = [
        ev(seq_base, 0, "node_entered", entity_id, "start", {"node_type": "start", "visit": 1}),
        ev(seq_base + 1, 0, "node_completed", entity_id, "start", {"node_type": "start", "elapsed": 0}),
        ev(seq_base + 2, 0, "node_entered", entity_id, "work", {"node_type": "task", "visit": 1}),
        ev(
            seq_base + 3,
            exposure,
            "reliability_sample",
            entity_id,
            "work",
            {
                "lambda": lam,
                "exposure_time": exposure,
                "reliability_probability": probability,
                "random_value": 0.9 if failure else 0.1,
                "failure_occurred": failure,
                "partial": True,
            },
        ),
    ]
    if failure:
        history.append(
            ev(
                seq_base + 4,
                exposure,
                "reliability_failure",
                entity_id,
                "work",
                {"failure_count": 1, "ever_failed": True, "partial": True},
            )
        )
    return entity(
        entity_id,
        final_node_id="work",
        status="operational",
        history=history,
        node_visits={"start": 1, "work": 1},
        failure_count=1 if failure else 0,
        ever_failed=failure,
        currently_failed=failure,
        completed=False,
        node_enter_time=0.0,
        node_elapsed_time=exposure,
    )


STATUS_CATALOG = [
    {"id": "operational", "name": "可运行", "counts_as_available": True},
    {"id": "under_repair", "name": "维修中", "counts_as_available": False},
    {"id": "retired", "name": "已退役", "counts_as_available": False},
]
