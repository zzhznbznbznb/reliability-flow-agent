"""Serializable simulation inputs, events and results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.domain.process_ir import StrictModel
from app.simulation.config import FailureSampling, ProjectParameters


class SimulationIssue(StrictModel):
    severity: Literal["error", "warning"] = "error"
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None


class SimulationEvent(StrictModel):
    seq: int = Field(ge=0)
    time: float
    event_type: str
    entity_id: str | None = None
    node_id: str | None = None
    scope: list[str] = Field(default_factory=list)
    depth: int = Field(default=0, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)


class ReliabilitySample(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        populate_by_name=True,
    )

    entity_id: str
    node_id: str
    time: float
    lambda_per_day: float = Field(alias="lambda")
    exposure_time: float
    reliability_probability: float
    random_value: float
    failure_occurred: bool
    partial: bool
    failure_time: float | None = None
    scope_path: list[str] = Field(default_factory=list)
    module_type: Literal["activity", "stage", "test"] = "activity"
    sampling_mode: Literal[
        "time_to_failure", "interval_end", "stepwise"
    ] = "interval_end"
    stage_task_id: str | None = None
    host_node_id: str | None = None
    cumulative_exposure: float | None = None
    step_index: int | None = None


class FailureRecord(StrictModel):
    failure_time: float
    node_id: str
    stage_task_id: str | None = None
    failure_lambda: float | None = None
    detected: bool = False
    detection_time: float | None = None
    detection_node_id: str | None = None
    detection_random: float | None = None
    detection_rate: float | None = None
    repair_start_time: float | None = None
    repair_end_time: float | None = None
    repaired: bool = False
    unavailable_time: float = Field(default=0.0, ge=0)
    open_at_end: bool = False


class TestRecord(StrictModel):
    node_id: str
    time: float
    detection_rate: float = Field(ge=0, le=1)
    random_value: float = Field(ge=0, le=1)
    had_fault: bool
    detected: bool
    failure_time: float | None = None
    test_time: float | None = None


class EntitySimulationResult(StrictModel):
    entity_id: str
    final_node_id: str
    current_status: str | None = None
    node_enter_time: float
    node_elapsed_time: float
    failure_count: int = Field(ge=0)
    repair_count: int = Field(ge=0)
    ever_failed: bool
    currently_failed: bool
    attributes: dict[str, Any] = Field(default_factory=dict)
    node_visits: dict[str, int] = Field(default_factory=dict)
    scope_path: list[str] = Field(default_factory=list)
    completed: bool
    stopped: bool
    stopped_reason: str | None = None
    history: list[SimulationEvent] = Field(default_factory=list)
    available_time: float = Field(default=0.0, ge=0)
    unavailable_time: float = Field(default=0.0, ge=0)
    failure_records: list[FailureRecord] = Field(default_factory=list)
    test_records: list[TestRecord] = Field(default_factory=list)


class SimulationResult(StrictModel):
    process_id: str
    process_version: int = Field(ge=1)
    process_hash: str
    reliability_id: str
    reliability_revision: int = Field(ge=1)
    runtime_semantic_version: str = "interval-end/1.0"
    failure_sampling: FailureSampling = "interval_end"
    reliability_sampling_mode: Literal[
        "legacy", "stepwise"
    ] = "legacy"
    random_seed: int
    entity_count: int = Field(ge=1)
    simulation_start: float = 0.0
    simulation_end: float = Field(gt=0)
    simulation_duration: float | None = None
    simulation_unit: Literal["hour", "day", "month", "year"] = "day"
    project: ProjectParameters | None = None
    event_count: int = Field(ge=0)
    reliability_sample_count: int = Field(ge=0)
    total_failure_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    stopped_count: int = Field(ge=0)
    entities: list[EntitySimulationResult] = Field(default_factory=list)
    reliability_samples: list[ReliabilitySample] = Field(default_factory=list)
    events: list[SimulationEvent] = Field(default_factory=list)


__all__ = [
    "EntitySimulationResult",
    "FailureRecord",
    "ReliabilitySample",
    "SimulationEvent",
    "SimulationIssue",
    "SimulationResult",
    "TestRecord",
]
