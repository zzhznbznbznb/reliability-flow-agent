"""Serializable simulation inputs, events and results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.domain.process_ir import StrictModel


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
    completed: bool
    stopped: bool
    stopped_reason: str | None = None
    history: list[SimulationEvent] = Field(default_factory=list)


class SimulationResult(StrictModel):
    process_id: str
    process_version: int = Field(ge=1)
    process_hash: str
    reliability_id: str
    reliability_revision: int = Field(ge=1)
    random_seed: int
    entity_count: int = Field(ge=1)
    simulation_end: float = Field(gt=0)
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
    "ReliabilitySample",
    "SimulationEvent",
    "SimulationIssue",
    "SimulationResult",
]
