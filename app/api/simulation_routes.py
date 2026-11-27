"""Simulation HTTP API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.api.deps import get_process_store, get_reliability_store
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from app.simulation.config import SimulationConfig
from app.simulation.engine import run_simulation
from app.simulation.errors import (
    SimulationRuntimeError,
    SimulationValidationError,
)

router = APIRouter(prefix="/api/processes", tags=["simulation"])


class SimulationRequest(SimulationConfig):
    process_version: int | None = Field(default=None, ge=1)


def _validation_detail(error: SimulationValidationError) -> dict[str, Any]:
    return {
        "code": "simulation_invalid",
        "valid": False,
        "message": "仿真配置或输入 IR 无效",
        "issues": [issue.model_dump(mode="json") for issue in error.issues],
    }


@router.post("/{process_id}/simulate")
def simulate_process(
    process_id: str,
    request: SimulationRequest,
    process_store: ProcessStore = Depends(get_process_store),
    reliability_store: ReliabilityStore = Depends(get_reliability_store),
) -> dict[str, Any]:
    process = process_store.get(process_id, request.process_version)
    reliability = reliability_store.get(
        process_id, process.version, process.content_hash
    )
    if reliability is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reliability_not_bound",
                "message": (
                    "当前 Process IR 版本没有绑定的 Reliability IR，"
                    "请先保存可靠性配置"
                ),
                "process_id": process_id,
                "process_version": process.version,
                "process_hash": process.content_hash,
            },
        )

    config = SimulationConfig.model_validate(
        request.model_dump(exclude={"process_version"})
    )
    try:
        result = run_simulation(process, reliability, config)
    except SimulationValidationError as error:
        raise HTTPException(
            status_code=400, detail=_validation_detail(error)
        ) from error
    except SimulationRuntimeError as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": error.code,
                "message": error.message,
                "entity_id": error.entity_id,
                "node_id": error.node_id,
            },
        ) from error

    return result.model_dump(mode="json", by_alias=True)


__all__ = ["SimulationRequest", "router"]
