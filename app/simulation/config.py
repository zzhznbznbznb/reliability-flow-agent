"""Central simulation configuration and safety limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from app.domain.process_ir import StrictModel

FailurePolicy = Literal["require_failure_exit", "stop_entity"]


@dataclass(frozen=True)
class SimulationLimits:
    """Central safety limits. Keep all runtime caps here."""

    max_entities: int = 10_000
    max_events: int = 1_000_000
    max_node_visits: int = 1_000_000
    max_simulation_days: float = 365_000.0


DEFAULT_LIMITS = SimulationLimits()


class SimulationConfig(StrictModel):
    entity_count: int = Field(ge=1)
    simulation_end: float = Field(gt=0)
    random_seed: int = Field(default=0, ge=0, le=2**63 - 1)
    failure_policy: FailurePolicy = "require_failure_exit"


__all__ = [
    "DEFAULT_LIMITS",
    "FailurePolicy",
    "SimulationConfig",
    "SimulationLimits",
]
