"""Experiment persistence HTTP API.

The existing /simulate/evaluate endpoint stays backward compatible. This
endpoint performs the same real Runtime + Evaluation execution and also stores
the complete result as an experiment record.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.analysis.service import simulate_and_evaluate
from app.api.deps import (
    get_experiment_store,
    get_process_store,
    get_reliability_store,
)
from app.api.evaluation_routes import SimulationEvaluationRequest
from app.evaluation.models import EvaluationConfig, EvaluationTargets
from app.experiments.store import ExperimentNotFound, ExperimentStore
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from app.simulation.config import SimulationConfig
from app.simulation.errors import (
    SimulationRuntimeError,
    SimulationValidationError,
)

router = APIRouter(tags=["experiments"])


def _validation_detail(error: SimulationValidationError) -> dict[str, Any]:
    return {
        "code": "simulation_invalid",
        "valid": False,
        "message": "仿真配置或输入 IR 无效",
        "issues": [issue.model_dump(mode="json") for issue in error.issues],
    }


def _reliability_not_bound(process_id: str, process: Any) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "reliability_not_bound",
            "message": (
                "当前 Process IR 版本没有绑定到 Reliability IR，"
                "请先保存可靠性配置。"
            ),
            "process_id": process_id,
            "process_version": process.version,
            "process_hash": process.content_hash,
        },
    )


@router.post("/api/processes/{process_id}/experiments")
def run_experiment(
    process_id: str,
    request: SimulationEvaluationRequest,
    process_store: ProcessStore = Depends(get_process_store),
    reliability_store: ReliabilityStore = Depends(get_reliability_store),
    experiment_store: ExperimentStore = Depends(get_experiment_store),
) -> dict[str, Any]:
    process = process_store.get(process_id, request.process_version)
    reliability = reliability_store.get(
        process_id, process.version, process.content_hash
    )
    if reliability is None:
        raise _reliability_not_bound(process_id, process)

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
        raise HTTPException(
            status_code=500,
            detail={
                "code": "evaluation_failed",
                "message": "仿真已完成，但评价执行失败",
                "error": str(error),
            },
        ) from error

    record = experiment_store.save(
        process=process,
        reliability=reliability,
        simulation_config=config,
        evaluation_targets=request.evaluation_targets,
        simulation=simulation,
        evaluation=evaluation,
        explanation=explanation,
    )
    return {
        "result_id": record.result_id,
        "simulation": simulation.model_dump(mode="json", by_alias=True),
        "evaluation": evaluation.model_dump(mode="json", by_alias=True),
        "explanation": explanation,
    }


@router.get("/api/experiments")
def list_experiments(
    experiment_store: ExperimentStore = Depends(get_experiment_store),
) -> dict[str, Any]:
    return {"experiments": experiment_store.list_summaries()}


@router.get("/api/experiments/{result_id}")
def get_experiment(
    result_id: str,
    experiment_store: ExperimentStore = Depends(get_experiment_store),
) -> dict[str, Any]:
    try:
        record = experiment_store.get(result_id)
    except ExperimentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "experiment": record.model_dump(mode="json", by_alias=True),
    }


__all__ = ["router"]
