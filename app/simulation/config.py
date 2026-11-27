"""Central simulation configuration and safety limits."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, model_validator

from app.domain.process_ir import StrictModel

FailurePolicy = Literal["require_failure_exit", "stop_entity"]
FailureSampling = Literal["time_to_failure", "interval_end"]
SimulationUnit = Literal["hour", "day", "month", "year"]

SIMULATION_UNIT_LABELS: dict[str, str] = {
    "hour": "小时",
    "day": "天",
    "month": "月",
    "year": "年",
}


@dataclass(frozen=True)
class SimulationLimits:
    """Central safety limits. Keep all runtime caps here."""

    max_entities: int = 10_000
    max_events: int = 1_000_000
    max_node_visits: int = 1_000_000
    max_simulation_days: float = 365_000.0
    max_nesting_depth: int = 8


DEFAULT_LIMITS = SimulationLimits()


class ProjectParameters(StrictModel):
    """Project-level metadata and simulation goals.

    These values are evaluation inputs and traceability metadata. They are not
    failure rates or detection rates and must never be used as substitutes for
    the Reliability IR parameters.
    """

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    reliability_target: float = Field(ge=0, le=1)
    readiness_target: float = Field(ge=0, le=1)
    simulation_unit: SimulationUnit = "day"
    missile_count: int = Field(ge=1)
    simulation_total_time: float | None = Field(default=None, gt=0)


class SimulationConfig(StrictModel):
    entity_count: int = Field(ge=1)
    simulation_start: float = Field(default=0.0, ge=0)
    simulation_end: float | None = Field(default=None, gt=0)
    simulation_duration: float | None = Field(default=None, gt=0)
    random_seed: int = Field(default=0, ge=0, le=2**63 - 1)
    failure_policy: FailurePolicy = "require_failure_exit"
    failure_sampling: FailureSampling = "time_to_failure"
    reliability_step: float = Field(default=1.0, gt=0)
    simulation_unit: SimulationUnit = "day"
    project: ProjectParameters | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_from_project(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        project = data.get("project")
        if isinstance(project, dict):
            if "entity_count" not in data and "missile_count" in project:
                data = {**data, "entity_count": project["missile_count"]}
            if "simulation_unit" not in data and "simulation_unit" in project:
                data = {**data, "simulation_unit": project["simulation_unit"]}
        return data

    @model_validator(mode="after")
    def _resolve_time_window(self) -> "SimulationConfig":
        total_time = (
            self.project.simulation_total_time
            if self.project is not None
            else None
        )
        if total_time is not None:
            # The project total time is expressed in the selected simulation
            # unit and is the authoritative runtime duration. It is never
            # converted through fixed month/year day counts.
            if self.simulation_duration is None and self.simulation_end is None:
                self.simulation_duration = total_time
            elif self.simulation_duration is not None and not math.isclose(
                self.simulation_duration,
                total_time,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    "project.simulation_total_time 必须与 "
                    "simulation_duration 保持一致"
                )
            elif self.simulation_end is not None and not math.isclose(
                self.simulation_end - self.simulation_start,
                total_time,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    "project.simulation_total_time 必须等于 "
                    "simulation_end - simulation_start"
                )
        if self.simulation_duration is not None:
            computed_end = self.simulation_start + self.simulation_duration
            if self.simulation_end is None:
                self.simulation_end = computed_end
            elif not math.isclose(
                self.simulation_end,
                computed_end,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    "simulation_end 必须等于 simulation_start + simulation_duration"
                )
        if self.simulation_end is None:
            raise ValueError("必须提供 simulation_end 或 simulation_duration")
        if self.simulation_end <= self.simulation_start:
            raise ValueError("simulation_end 必须大于 simulation_start")
        if self.project is not None:
            if self.project.simulation_unit != self.simulation_unit:
                raise ValueError(
                    "project.simulation_unit 必须与 simulation_unit 保持一致"
                )
            if self.project.missile_count != self.entity_count:
                raise ValueError(
                    "project.missile_count 必须与 entity_count 保持一致"
                )
        return self


__all__ = [
    "DEFAULT_LIMITS",
    "FailurePolicy",
    "FailureSampling",
    "ProjectParameters",
    "SIMULATION_UNIT_LABELS",
    "SimulationConfig",
    "SimulationLimits",
    "SimulationUnit",
]
