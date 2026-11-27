"""Simulation + evaluation HTTP API.

The existing /simulate endpoint remains the low-level raw simulation API. This
endpoint orchestrates the same runtime execution and then evaluates the result
through the existing Evaluation layer.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.analysis.service import simulate_and_evaluate
from app.api.deps import get_process_store, get_reliability_store
from app.api.simulation_routes import SimulationRequest
from app.evaluation.models import EvaluationConfig, EvaluationTargets
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from app.simulation.config import SimulationConfig
from app.simulation.errors import (
    SimulationRuntimeError,
    SimulationValidationError,
)
from app.simulation.readiness import check_simulation_readiness

router = APIRouter(prefix="/api/processes", tags=["evaluation"])
logger = logging.getLogger(__name__)


class SimulationEvaluationRequest(SimulationRequest):
    evaluation_targets: EvaluationTargets | None = None
    evaluation_config: EvaluationConfig | None = None


def _validation_detail(error: SimulationValidationError) -> dict[str, Any]:
    return {
        "code": "simulation_invalid",
        "valid": False,
        "message": "仿真配置或输入 IR 无效",
        "issues": [issue.model_dump(mode="json") for issue in error.issues],
    }


def _reliability_not_bound(
    process_id: str, process: Any
) -> HTTPException:
    return HTTPException(
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


@router.post("/{process_id}/simulate/evaluate")
def simulate_and_evaluate_process(
    process_id: str,
    request: SimulationEvaluationRequest,
    process_store: ProcessStore = Depends(get_process_store),
    reliability_store: ReliabilityStore = Depends(get_reliability_store),
) -> dict[str, Any]:
    process = process_store.get(process_id, request.process_version)
    reliability = reliability_store.get(
        process_id, process.version, process.content_hash
    )
    if reliability is None:
        raise _reliability_not_bound(process_id, process)

    readiness_issues = check_simulation_readiness(
        process, reliability, request.simulation_unit
    )
    if readiness_issues:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "simulation_parameters_missing",
                "valid": False,
                "message": "仿真前参数检查未通过",
                "issues": [
                    issue.model_dump(mode="json")
                    for issue in readiness_issues
                ],
            },
        )

    config = SimulationConfig.model_validate(
        request.model_dump(
            exclude={
                "process_version",
                "evaluation_targets",
                "evaluation_config",
            }
        )
    )
    try:
        simulation, evaluation, explanation = simulate_and_evaluate(
            process,
            reliability,
            config,
            evaluation_targets=request.evaluation_targets,
            evaluation_config=request.evaluation_config,
        )
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
    except Exception as error:
        logger.exception(
            "Simulation evaluation failed for process %s", process_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "evaluation_failed",
                "message": "仿真已完成，但评价执行失败",
                "error": str(error),
            },
        ) from error

    return {
        "simulation": simulation.model_dump(mode="json", by_alias=True),
        "evaluation": evaluation.model_dump(mode="json", by_alias=True),
        "explanation": explanation,
    }


__all__ = ["SimulationEvaluationRequest", "router"]
