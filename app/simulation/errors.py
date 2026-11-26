"""Simulation exceptions."""

from __future__ import annotations

from app.simulation.models import SimulationIssue


class SimulationError(Exception):
    """Base simulation error."""


class SimulationValidationError(SimulationError):
    def __init__(self, issues: list[SimulationIssue]) -> None:
        super().__init__("仿真配置无效")
        self.issues = issues


class SimulationRuntimeError(SimulationError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        entity_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.entity_id = entity_id
        self.node_id = node_id


__all__ = [
    "SimulationError",
    "SimulationRuntimeError",
    "SimulationValidationError",
]
