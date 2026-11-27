from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from app.agent.session import AgentSessionManager
from app.api.agent_routes import _sse
from app.config import get_settings
from app.experiments.store import ExperimentStore
from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from tests.helpers import (
    failure_process_dict,
    minimal_process_dict,
    project_payload,
)


class ApiFakeClient:
    def __init__(self, *, settings, session_id, on_event, on_stderr, on_exit):
        self.settings = settings
        self.session_id = session_id
        self.on_event = on_event

    async def start(self) -> None:
        return None

    async def prompt(self, message: str):
        asyncio.create_task(self._emit())
        return {"success": True, "data": {"disposition": "started"}}

    async def abort(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def _emit(self) -> None:
        await asyncio.sleep(0)
        spec = minimal_process_dict()
        spec["name"] = "API 测试流程"
        await self.on_event(
            {"type": "message_start", "message": {"role": "assistant"}}
        )
        await self.on_event(
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": "生成中",
                },
            }
        )
        await self.on_event(
            {
                "type": "tool_execution_start",
                "toolCallId": "call_api",
                "toolName": "validate_process_model",
                "args": {"spec": spec},
            }
        )
        await self.on_event(
            {
                "type": "tool_execution_end",
                "toolCallId": "call_api",
                "toolName": "validate_process_model",
                "isError": False,
                "result": {
                    "details": {
                        "valid": True,
                        "content_hash": "sha256:" + "c" * 64,
                        "issues": [],
                    }
                },
            }
        )
        await self.on_event({"type": "agent_settled"})


def _app(tmp_path, manager: AgentSessionManager):
    return create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
        experiment_store=ExperimentStore(tmp_path / "experiments"),
        agent_manager=manager,
    )


def test_agent_api_session_lifecycle_and_sse(tmp_path) -> None:
    settings = replace(
        get_settings(),
        agent_session_dir=tmp_path / "agent_sessions",
        agent_timeout_seconds=5.0,
        agent_idle_timeout_seconds=60.0,
    )
    manager = AgentSessionManager(
        settings, client_factory=lambda **kwargs: ApiFakeClient(**kwargs)
    )
    app = _app(tmp_path, manager)

    with TestClient(app) as client:
        health = client.get("/api/agent/health")
        assert health.status_code == 200
        assert health.json()["tool_policy"] == "extension-allowlist"
        assert "validate_process_model" in health.json()["allowed_tools"]
        assert "pi_api_key" not in health.json()

        created = client.post("/api/agent/sessions")
        assert created.status_code == 200, created.text
        session_id = created.json()["session_id"]
        assert session_id.startswith("ags_")

        sent = client.post(
            f"/api/agent/sessions/{session_id}/messages",
            json={"message": "创建流程", "context": {"dirty": False}},
        )
        assert sent.status_code == 202, sent.text
        assert sent.json()["task_id"].startswith("task_")

        deadline = time.time() + 5
        snapshot = None
        while time.time() < deadline:
            snapshot = client.get(f"/api/agent/sessions/{session_id}").json()
            if snapshot["candidate_process_ir"] is not None:
                break
            time.sleep(0.05)
        assert snapshot["candidate_process_ir"]["name"] == "API 测试流程"
        assert snapshot["process_validation"]["valid"] is True
        event_types = [event["type"] for event in manager.sessions[session_id].events]
        assert "assistant_delta" in event_types
        assert "tool_start" in event_types
        assert "process_ir" in event_types
        assert "done" in event_types

        cancelled = client.post(f"/api/agent/sessions/{session_id}/cancel")
        assert cancelled.status_code == 200
        deleted = client.delete(f"/api/agent/sessions/{session_id}")
        assert deleted.status_code == 200
        missing = client.get(f"/api/agent/sessions/{session_id}")
        assert missing.status_code == 404


def test_simulation_result_endpoint_publishes_real_stored_experiment(tmp_path) -> None:
    settings = replace(
        get_settings(),
        agent_session_dir=tmp_path / "agent_sessions",
        agent_timeout_seconds=5.0,
        agent_idle_timeout_seconds=60.0,
    )
    manager = AgentSessionManager(
        settings, client_factory=lambda **kwargs: ApiFakeClient(**kwargs)
    )
    app = _app(tmp_path, manager)

    with TestClient(app) as client:
        session_id = client.post("/api/agent/sessions").json()["session_id"]
        process = client.post(
            "/api/processes", json=failure_process_dict()
        ).json()["process"]
        client.put(
            f"/api/processes/{process['process_id']}/reliability",
            json={
                "process_version": process["version"],
                "process_hash": process["content_hash"],
                "nodes": [
                    {"node_id": "inspect", "participates": True, "lambda": 0.0},
                    {"node_id": "repair", "participates": False},
                ],
            },
        )
        experiment = client.post(
            f"/api/processes/{process['process_id']}/experiments",
            json={
                "entity_count": 2,
                "simulation_end": 5,
                "random_seed": 3,
                "failure_policy": "require_failure_exit",
                "project": project_payload(
                    missile_count=2, simulation_total_time=5
                ),
            },
        )
        assert experiment.status_code == 200, experiment.text
        result_id = experiment.json()["result_id"]

        recorded = client.post(
            f"/api/agent/sessions/{session_id}/simulation-results",
            json={"result_id": result_id},
        )
        assert recorded.status_code == 200, recorded.text
        assert recorded.json()["result_id"] == result_id
        snapshot = client.get(f"/api/agent/sessions/{session_id}").json()
        assert snapshot["last_simulation_result"]["result_id"] == result_id
        assert snapshot["last_simulation_result"]["process_id"] == process["process_id"]
        event_types = [event["type"] for event in manager.sessions[session_id].events]
        assert "simulation_result" in event_types

        missing = client.post(
            f"/api/agent/sessions/{session_id}/simulation-results",
            json={"result_id": "exp_ffffffffffff"},
        )
        assert missing.status_code == 404


def test_sse_frame_contains_id_event_and_json_data() -> None:
    frame = _sse(
        {
            "seq": 3,
            "session_id": "ags_000000000000",
            "task_id": "task_000000000000",
            "type": "assistant_delta",
            "timestamp": "2026-11-26T00:00:00+00:00",
            "data": {"delta": "hi"},
        }
    )
    assert frame.startswith("id: 3\n")
    assert "event: assistant_delta\n" in frame
    assert '"delta":"hi"' in frame
    assert frame.endswith("\n\n")


def test_requirement_analysis_endpoint_validates_structure(tmp_path) -> None:
    settings = replace(
        get_settings(),
        agent_session_dir=tmp_path / "agent_sessions",
        agent_timeout_seconds=5.0,
        agent_idle_timeout_seconds=60.0,
    )
    manager = AgentSessionManager(
        settings, client_factory=lambda **kwargs: ApiFakeClient(**kwargs)
    )
    app = _app(tmp_path, manager)
    analysis = {
        "summary": "两步流程",
        "steps": [
            {"id": "start", "name": "开始", "kind": "start"},
            {"id": "work", "name": "工作", "kind": "task", "duration": 1},
            {"id": "end", "name": "结束", "kind": "end"},
        ],
        "branches": [
            {
                "id": "start_work",
                "from_step": "start",
                "to_step": "work",
                "kind": "normal",
            },
            {
                "id": "work_end",
                "from_step": "work",
                "to_step": "end",
                "kind": "normal",
            },
        ],
        "ambiguities": [],
    }
    with TestClient(app) as client:
        health = client.get("/api/agent/health").json()
        assert "analyze_requirements" in health["allowed_tools"]
        response = client.post(
            "/api/agent/requirements/analyze", json=analysis
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is True
        assert body["step_count"] == 3
        assert body["branch_count"] == 2
        assert body["blocking_count"] == 0

        broken = dict(analysis)
        broken["branches"] = [
            {
                "id": "bad_branch",
                "from_step": "start",
                "to_step": "ghost",
                "kind": "normal",
            }
        ]
        invalid = client.post("/api/agent/requirements/analyze", json=broken)
        assert invalid.status_code == 422

        bad_semantics = {
            **analysis,
            "steps": [dict(step) for step in analysis["steps"]],
        }
        bad_semantics["steps"][1]["kind"] = "decision"
        semantic = client.post(
            "/api/agent/requirements/analyze", json=bad_semantics
        )
        assert semantic.status_code == 200
        semantic_body = semantic.json()
        assert semantic_body["valid"] is False
        assert "requirement_decision_has_duration" in {
            issue["code"] for issue in semantic_body["issues"]
        }


def test_sse_frame_preserves_large_event_payload() -> None:
    large_text = "长文本" * 50000
    frame = _sse(
        {
            "seq": 9,
            "session_id": "ags_000000000000",
            "task_id": "task_000000000000",
            "type": "process_ir",
            "timestamp": "2026-11-26T00:00:00+00:00",
            "data": {"spec": {"description": large_text}},
        }
    )
    assert len(frame) > len(large_text)
    assert large_text in frame
    data_line = next(
        line for line in frame.splitlines() if line.startswith("data: ")
    )
    parsed = json.loads(data_line.removeprefix("data: "))
    assert parsed["data"]["spec"]["description"] == large_text
