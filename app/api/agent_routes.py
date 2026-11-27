"""Web Agent HTTP API and Server-Sent Events bridge."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.agent.requirements import (
    RequirementAnalysis,
    validate_requirement_analysis,
)
from app.agent.rpc_client import PiRpcError, PiRpcUnavailable
from app.agent.session import (
    AgentError,
    AgentSessionBusy,
    AgentSessionNotFound,
    AgentUnavailable,
)
from app.api.deps import get_agent_manager, get_experiment_store
from app.domain.process_ir import StrictModel
from app.experiments.store import ExperimentNotFound, ExperimentStore

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentMessageRequest(StrictModel):
    message: str = Field(min_length=1, max_length=100000)
    context: dict[str, Any] | None = None


class SimulationResultRequest(StrictModel):
    result_id: str = Field(min_length=1, max_length=64)


@router.post("/requirements/analyze")
def analyze_requirements(
    analysis: RequirementAnalysis,
) -> dict[str, Any]:
    result = validate_requirement_analysis(analysis)
    payload = analysis.model_dump(mode="json")
    return {
        "valid": result.valid,
        "issues": [issue.model_dump(mode="json") for issue in result.issues],
        "analysis": payload,
        "step_count": len(analysis.steps),
        "branch_count": len(analysis.branches),
        "ambiguity_count": len(analysis.ambiguities),
        "blocking_count": len(analysis.blocking_ambiguities),
    }


def _simulation_event_summary(record) -> dict[str, Any]:
    simulation = record.simulation
    evaluation = record.evaluation
    overall = evaluation.overall
    return {
        "result_id": record.result_id,
        "process_id": record.process_id,
        "process_version": record.process_version,
        "process_hash": record.process_hash,
        "reliability_revision": record.reliability_revision,
        "reliability_hash": record.reliability_hash,
        "simulation": {
            "entity_count": simulation.entity_count,
            "simulation_end": simulation.simulation_end,
            "random_seed": simulation.random_seed,
            "total_failure_count": simulation.total_failure_count,
            "completed_count": simulation.completed_count,
            "stopped_count": simulation.stopped_count,
            "reliability_sample_count": simulation.reliability_sample_count,
        },
        "evaluation": {
            "target_status": evaluation.target_status,
            "overall_reliability": overall.overall_reliability,
            "end_availability": overall.end_availability,
            "total_failure_count": overall.total_failure_count,
            "total_repair_count": overall.total_repair_count,
            "completed_entity_count": overall.completed_entity_count,
            "unfinished_entity_count": overall.unfinished_entity_count,
            "warning_count": len(evaluation.warnings),
        },
    }


def _sse(event: dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return (
        f"id: {event.get('seq', 0)}\n"
        f"event: {event.get('type', 'message')}\n"
        f"data: {payload}\n\n"
    )


def _agent_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AgentSessionNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AgentSessionBusy):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (PiRpcUnavailable, AgentUnavailable)):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, (PiRpcError, AgentError)):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Agent 服务内部错误。")


@router.get("/health")
def agent_health(manager=Depends(get_agent_manager)) -> dict[str, Any]:
    return manager.health()


@router.get("/sessions")
def list_agent_sessions(manager=Depends(get_agent_manager)) -> dict[str, Any]:
    sessions = [
        {
            "session_id": item["session_id"],
            "status": item["status"],
            "created_at": item["created_at"],
            "last_activity": item["last_activity"],
            "current_task_id": item["current_task_id"],
        }
        for item in manager.list_sessions()
    ]
    return {"sessions": sessions}


@router.post("/sessions")
async def create_agent_session(
    manager=Depends(get_agent_manager),
) -> dict[str, Any]:
    try:
        session = await manager.create_session()
    except Exception as exc:
        raise _agent_error(exc) from exc
    return session.snapshot()


@router.get("/sessions/{session_id}")
def get_agent_session(
    session_id: str,
    manager=Depends(get_agent_manager),
) -> dict[str, Any]:
    try:
        return manager.get_session(session_id).snapshot()
    except Exception as exc:
        raise _agent_error(exc) from exc


@router.post("/sessions/{session_id}/messages", status_code=202)
async def send_agent_message(
    session_id: str,
    body: AgentMessageRequest,
    manager=Depends(get_agent_manager),
) -> dict[str, Any]:
    try:
        task = await manager.send_message(
            session_id, body.message, body.context
        )
    except Exception as exc:
        raise _agent_error(exc) from exc
    return {
        "session_id": session_id,
        "task_id": task.task_id,
        "status": task.status,
    }


@router.post("/sessions/{session_id}/simulation-results")
def record_simulation_result(
    session_id: str,
    body: SimulationResultRequest,
    manager=Depends(get_agent_manager),
    experiment_store: ExperimentStore = Depends(get_experiment_store),
) -> dict[str, Any]:
    """Publish a real persisted experiment result to the Agent event stream.

    The browser references an already stored experiment. The backend loads the
    record itself, so a client cannot inject fabricated metrics.
    """

    try:
        session = manager.get_session(session_id)
        record = experiment_store.get(body.result_id)
    except ExperimentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise _agent_error(exc) from exc

    summary = _simulation_event_summary(record)
    event = session.emit(
        "simulation_result",
        summary,
        task_id=session.current_task_id,
    )
    session.last_simulation_result = summary
    return {"recorded": True, "result_id": record.result_id, "event": event}


@router.post("/sessions/{session_id}/cancel")
async def cancel_agent_task(
    session_id: str,
    manager=Depends(get_agent_manager),
) -> dict[str, Any]:
    try:
        return await manager.cancel(session_id)
    except Exception as exc:
        raise _agent_error(exc) from exc


@router.delete("/sessions/{session_id}")
async def delete_agent_session(
    session_id: str,
    manager=Depends(get_agent_manager),
) -> dict[str, Any]:
    try:
        await manager.delete_session(session_id)
    except Exception as exc:
        raise _agent_error(exc) from exc
    return {"closed": True, "session_id": session_id}


@router.get("/sessions/{session_id}/events")
async def agent_events(
    session_id: str,
    request: Request,
    last_event_id: int | None = Query(default=None, ge=0),
    manager=Depends(get_agent_manager),
) -> StreamingResponse:
    try:
        session = manager.get_session(session_id)
    except Exception as exc:
        raise _agent_error(exc) from exc

    raw_last_id = request.headers.get("last-event-id")
    if raw_last_id:
        try:
            last_event_id = int(raw_last_id)
        except ValueError:
            pass

    async def event_stream():
        queue = session.subscribe()
        try:
            yield "retry: 2000\n\n"
            for event in session.events_since(last_event_id):
                yield _sse(event)

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                yield _sse(event)
        finally:
            session.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
