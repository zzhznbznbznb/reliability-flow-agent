from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.agent.session import (
    AgentSessionBusy,
    AgentSessionManager,
    build_agent_prompt,
)
from app.config import get_settings
from tests.helpers import minimal_process_dict


class FakePiClient:
    def __init__(self, *, settings, session_id, on_event, on_stderr, on_exit):
        self.settings = settings
        self.session_id = session_id
        self.on_event = on_event
        self.on_stderr = on_stderr
        self.on_exit = on_exit
        self.started = False
        self.closed = False
        self.prompts: list[str] = []
        self.aborted = False
        self.auto_events = True

    async def start(self) -> None:
        self.started = True

    async def prompt(self, message: str):
        self.prompts.append(message)
        if self.auto_events:
            asyncio.create_task(self._emit())
        return {"success": True, "data": {"disposition": "started"}}

    async def abort(self) -> None:
        self.aborted = True

    async def close(self) -> None:
        self.closed = True

    async def _emit(self) -> None:
        await asyncio.sleep(0)
        spec = minimal_process_dict()
        spec["name"] = "装备保障流程"
        spec["nodes"][1]["position"] = {"x": 200, "y": 120}
        await self.on_event({"type": "agent_start"})
        await self.on_event(
            {"type": "message_start", "message": {"role": "assistant"}}
        )
        await self.on_event(
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": "正在生成流程模型。",
                },
            }
        )
        await self.on_event(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "已生成并校验流程模型。"}
                    ],
                },
            }
        )
        await self.on_event(
            {
                "type": "tool_execution_start",
                "toolCallId": "call_1",
                "toolName": "validate_process_model",
                "args": {"spec": spec},
            }
        )
        await self.on_event(
            {
                "type": "tool_execution_end",
                "toolCallId": "call_1",
                "toolName": "validate_process_model",
                "isError": False,
                "result": {
                    "content": [{"type": "text", "text": "{}"}],
                    "details": {
                        "valid": True,
                        "content_hash": "sha256:" + "a" * 64,
                        "issues": [],
                    },
                },
            }
        )
        await self.on_event({"type": "agent_settled"})


def _settings(tmp_path):
    return replace(
        get_settings(),
        agent_session_dir=tmp_path / "agent_sessions",
        agent_timeout_seconds=5.0,
        agent_idle_timeout_seconds=60.0,
        agent_max_sessions=4,
    )


def _collect_until_done(session, timeout=5.0):
    async def collect():
        queue = session.subscribe()
        events = []
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=timeout)
            events.append(event)
            if event and event["type"] == "done":
                break
        return events

    return collect()


def test_prompt_context_includes_current_model_and_proposal_only() -> None:
    context = {
        "current_process": {
            "process_id": "proc_000000000000",
            "version": 2,
            "content_hash": "sha256:" + "b" * 64,
            "spec": {"name": "旧模型", "nodes": [], "edges": []},
        },
        "dirty": True,
        "latest_version": 2,
        "viewing_version": 2,
        "reliability": {"nodes": []},
    }
    prompt = build_agent_prompt("修改当前流程", context)
    assert "proposal-only" in prompt
    assert "current_process_id: proc_000000000000" in prompt
    assert "旧模型" in prompt
    assert "[user request]" in prompt


def test_session_maps_text_tool_and_process_ir_events(tmp_path) -> None:
    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: FakePiClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(
                session.session_id,
                "创建一个装备保障流程",
                {
                    "current_process": {
                        "process_id": None,
                        "version": None,
                        "content_hash": None,
                        "spec": None,
                    },
                    "dirty": False,
                },
            )
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            types = [event["type"] for event in events]
            assert "assistant_delta" in types
            assert "assistant_message" in types
            assert "tool_start" in types
            assert "tool_end" in types
            assert "validation_result" in types
            assert "process_ir" in types
            assert "done" in types
            process_event = next(
                event for event in events if event["type"] == "process_ir"
            )
            assert process_event["data"]["spec"]["name"] == "装备保障流程"
            assert process_event["data"]["validation"]["valid"] is True
            snapshot = session.snapshot()
            assert snapshot["status"] == "idle"
            assert snapshot["candidate_process_ir"]["name"] == "装备保障流程"
            assert snapshot["messages"][0]["role"] == "assistant"
            assert "proposal-only" in session.client.prompts[0]
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_one_task_per_session_is_enforced(tmp_path) -> None:
    class PendingClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            return {"success": True, "data": {"disposition": "started"}}

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: PendingClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            await manager.send_message(session.session_id, "第一条")
            with pytest.raises(AgentSessionBusy):
                await manager.send_message(session.session_id, "第二条")
            result = await manager.cancel(session.session_id)
            assert result["cancelled"] is True
            assert session.client.aborted is True
            assert session.snapshot()["current_task_id"] is None
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_process_exit_marks_running_task_as_error(tmp_path) -> None:
    class PendingClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            return {"success": True, "data": {"disposition": "started"}}

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: PendingClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "测试退出")
            await session.handle_process_exit(1, "boom")
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event and event["type"] == "done":
                    break
            assert any(event["type"] == "error" for event in events)
            task = next(iter(session.tasks.values()))
            assert task.status == "error"
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_reliability_tool_result_emits_candidate_and_binding(tmp_path) -> None:
    class PendingClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            return {"success": True, "data": {"disposition": "started"}}

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: PendingClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "配置可靠性")
            spec = {
                "schema_version": "reliability-ir/1.0",
                "process_version": 2,
                "process_hash": "sha256:" + "d" * 64,
                "nodes": [
                    {"node_id": "work", "participates": True, "lambda": 0.1}
                ],
            }
            await session.handle_rpc_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_rel",
                    "toolName": "validate_reliability_model",
                    "args": {"process_id": "proc_000000000000", "spec": spec},
                }
            )
            await session.handle_rpc_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_rel",
                    "toolName": "validate_reliability_model",
                    "isError": False,
                    "result": {
                        "details": {
                            "valid": True,
                            "issues": [],
                            "process_id": "proc_000000000000",
                            "process_version": 2,
                            "process_hash": spec["process_hash"],
                            "participant_count": 1,
                        }
                    },
                }
            )
            await session.handle_rpc_event(
                {"type": "agent_settled", "aborted": False}
            )
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            reliability_events = [
                event for event in events if event["type"] == "reliability_ir"
            ]
            assert reliability_events
            data = reliability_events[-1]["data"]
            assert data["process_id"] == "proc_000000000000"
            assert data["spec"]["process_version"] == 2
            assert data["validation"]["valid"] is True
            snapshot = session.snapshot()
            assert snapshot["reliability_process_id"] == "proc_000000000000"
            assert snapshot["candidate_reliability_ir"]["nodes"][0]["lambda"] == 0.1
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_provider_error_and_aborted_settle_are_reported(tmp_path) -> None:
    class PendingClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            return {"success": True, "data": {"disposition": "started"}}

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: PendingClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "测试 Provider 错误")
            await session.handle_rpc_event(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [],
                        "stopReason": "error",
                        "errorMessage": "provider unavailable",
                    },
                }
            )
            await session.handle_rpc_event(
                {"type": "agent_settled", "aborted": True}
            )
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            error_events = [event for event in events if event["type"] == "error"]
            assert any(
                event["data"].get("code") == "provider_error"
                for event in error_events
            )
            task = next(iter(session.tasks.values()))
            assert task.status == "cancelled"
            assert task.error is None
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_concurrent_sessions_are_isolated(tmp_path) -> None:
    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: FakePiClient(**kwargs)
        )
        await manager.start()
        try:
            first = await manager.create_session()
            second = await manager.create_session()
            assert first.session_id != second.session_id
            assert first.client is not second.client
            first.candidate_process_ir = {"name": "first"}
            assert second.candidate_process_ir is None
        finally:
            await manager.shutdown()

    asyncio.run(run())
