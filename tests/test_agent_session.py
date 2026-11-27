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


def test_long_requirement_analysis_covers_full_process_proposal(tmp_path) -> None:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    nested_analysis = json.loads(
        (
            root
            / "tests"
            / "fixtures"
            / "equipment_support_nested_requirement_analysis.json"
        ).read_text(encoding="utf-8")
    )
    nested_spec = json.loads(
        (root / "examples" / "equipment_support_nested_flow.json").read_text(
            encoding="utf-8"
        )
    )

    class AnalysisClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            asyncio.create_task(self._emit_analysis())
            return {"success": True, "data": {"disposition": "started"}}

        async def _emit_analysis(self):
            await asyncio.sleep(0)
            analysis = nested_analysis
            spec = nested_spec
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_analysis",
                    "toolName": "analyze_requirements",
                    "args": {"analysis": analysis},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_analysis",
                    "toolName": "analyze_requirements",
                    "isError": False,
                    "result": {
                        "details": {
                            "valid": True,
                            "step_count": len(analysis["steps"]),
                            "branch_count": len(analysis["branches"]),
                        }
                    },
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_process",
                    "toolName": "validate_process_model",
                    "args": {"spec": spec},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_process",
                    "toolName": "validate_process_model",
                    "isError": False,
                    "result": {
                        "details": {
                            "valid": False,
                            "content_hash": "sha256:" + "e" * 64,
                            "issues": [
                                {
                                    "severity": "error",
                                    "code": "fake_tool_result",
                                    "message": "tool result must not be trusted",
                                }
                            ],
                        }
                    },
                }
            )
            await self.on_event({"type": "agent_settled"})

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: AnalysisClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "完整装备保障流程")
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            types = [event["type"] for event in events]
            assert "requirement_analysis" in types
            assert "process_ir" in types
            process_event = next(
                event for event in events if event["type"] == "process_ir"
            )
            validation = process_event["data"]["validation"]
            assert validation["valid"] is True
            assert validation["schema_valid"] is True
            assert validation["coverage"]["covered"] is True
            assert validation["coverage"]["step_count"] == 28
            assert validation["coverage"]["branch_count"] == 29
            assert validation["coverage"]["step_count"] == validation["coverage"][
                "covered_step_count"
            ]
            assert process_event["data"]["requirement_coverage"]["covered"] is True
            snapshot = session.snapshot()
            assert snapshot["requirement_analysis"]["steps"]
            assert snapshot["requirement_coverage"]["covered"] is True
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_server_revalidation_rejects_invalid_candidate_despite_tool_success(
    tmp_path,
) -> None:
    class InvalidSpecClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            asyncio.create_task(self._emit_invalid())
            return {"success": True, "data": {"disposition": "started"}}

        async def _emit_invalid(self):
            await asyncio.sleep(0)
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_bad",
                    "toolName": "validate_process_model",
                    "args": {"spec": {"name": "缺字段流程", "nodes": []}},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_bad",
                    "toolName": "validate_process_model",
                    "isError": False,
                    "result": {
                        "details": {
                            "valid": True,
                            "content_hash": "sha256:" + "f" * 64,
                            "issues": [],
                        }
                    },
                }
            )
            await self.on_event({"type": "agent_settled"})

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: InvalidSpecClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "非法流程")
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            process_event = next(
                event for event in events if event["type"] == "process_ir"
            )
            validation = process_event["data"]["validation"]
            assert validation["valid"] is False
            assert validation["schema_valid"] is True
            assert "missing_start" in {
                issue["code"] for issue in validation["issues"]
            }
            done = next(event for event in events if event["type"] == "done")
            assert done["data"]["has_process_ir"] is True
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_blocking_ambiguity_emits_clarification_without_process_ir(tmp_path) -> None:
    class ClarifyClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            asyncio.create_task(self._emit_clarification())
            return {"success": True, "data": {"disposition": "started"}}

        async def _emit_clarification(self):
            await asyncio.sleep(0)
            analysis = {
                "summary": "缺少持续时间",
                "steps": [
                    {"id": "start", "name": "开始", "kind": "start"},
                    {"id": "work", "name": "业务活动", "kind": "task"},
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
                "ambiguities": [
                    {
                        "id": "missing_duration",
                        "question": "业务活动持续多少天？",
                        "blocks_generation": True,
                    }
                ],
            }
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_clarify",
                    "toolName": "analyze_requirements",
                    "args": {"analysis": analysis},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_clarify",
                    "toolName": "analyze_requirements",
                    "isError": False,
                    "result": {"details": {"valid": True}},
                }
            )
            await self.on_event({"type": "agent_settled"})

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: ClarifyClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "缺少持续时间的需求")
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            types = [event["type"] for event in events]
            assert "requirement_analysis" in types
            assert "clarification" in types
            assert "process_ir" not in types
            clarification = next(
                event for event in events if event["type"] == "clarification"
            )
            assert clarification["data"]["questions"][0]["id"] == (
                "missing_duration"
            )
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_long_request_text_is_forwarded_to_agent_intact(tmp_path) -> None:
    long_text = "装备保障流程。" * 800

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: FakePiClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            await manager.send_message(session.session_id, long_text)
            await asyncio.sleep(0.1)
            assert session.client.prompts[0] == long_text
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_protocol_error_code_is_propagated_to_agent_event(tmp_path) -> None:
    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: FakePiClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await session.handle_rpc_event(
                {
                    "type": "protocol_error",
                    "code": "rpc_message_too_large",
                    "message": "Pi RPC 单条 JSONL 消息超过上限",
                }
            )
            event = await asyncio.wait_for(queue.get(), timeout=5.0)
            assert event["type"] == "error"
            assert event["data"]["code"] == "rpc_message_too_large"
            assert "超过上限" in event["data"]["message"]
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_invalid_requirement_analysis_blocks_process_validation(tmp_path) -> None:
    from tests.test_agent_requirements import (
        equipment_support_analysis,
        equipment_support_spec,
    )

    class BadAnalysisClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            asyncio.create_task(self._emit_bad_analysis())
            return {"success": True, "data": {"disposition": "started"}}

        async def _emit_bad_analysis(self):
            await asyncio.sleep(0)
            analysis = equipment_support_analysis()
            for step in analysis["steps"]:
                if step["id"] == "test1_gate":
                    step["duration"] = 1
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_bad_analysis",
                    "toolName": "analyze_requirements",
                    "args": {"analysis": analysis},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_bad_analysis",
                    "toolName": "analyze_requirements",
                    "isError": False,
                    "result": {"details": {"valid": True}},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_after_bad",
                    "toolName": "validate_process_model",
                    "args": {"spec": equipment_support_spec()},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_after_bad",
                    "toolName": "validate_process_model",
                    "isError": False,
                    "result": {"details": {"valid": True}},
                }
            )
            await self.on_event({"type": "agent_settled"})

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: BadAnalysisClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "分析错误后仍生成流程")
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            analysis_event = next(
                event for event in events if event["type"] == "requirement_analysis"
            )
            assert analysis_event["data"]["valid"] is False
            process_event = next(
                event for event in events if event["type"] == "process_ir"
            )
            validation = process_event["data"]["validation"]
            assert validation["valid"] is False
            codes = {issue["code"] for issue in validation["issues"]}
            assert "requirement_decision_has_duration" in codes
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_long_request_without_analysis_is_blocked(tmp_path) -> None:
    from tests.test_agent_requirements import equipment_support_spec

    class NoAnalysisClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            asyncio.create_task(self._emit_process())
            return {"success": True, "data": {"disposition": "started"}}

        async def _emit_process(self):
            await asyncio.sleep(0)
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_no_analysis",
                    "toolName": "validate_process_model",
                    "args": {"spec": equipment_support_spec()},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_no_analysis",
                    "toolName": "validate_process_model",
                    "isError": False,
                    "result": {"details": {"valid": True}},
                }
            )
            await self.on_event({"type": "agent_settled"})

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: NoAnalysisClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "长需求" * 120)
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            process_event = next(
                event for event in events if event["type"] == "process_ir"
            )
            validation = process_event["data"]["validation"]
            assert validation["valid"] is False
            assert "requirement_analysis_missing" in {
                issue["code"] for issue in validation["issues"]
            }
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_nested_requirement_analysis_and_process_ir_are_accepted(tmp_path) -> None:
    from tests.test_agent_requirements import (
        equipment_support_analysis,
        equipment_support_spec,
    )

    nested_analysis = {
        **equipment_support_analysis(),
        "steps": [
            {
                "id": "n_start",
                "name": "开始",
                "kind": "start",
                "parent_id": None,
            },
            {
                "id": "n_block",
                "name": "复合块",
                "kind": "subprocess",
                "parent_id": None,
            },
            {
                "id": "b_start",
                "name": "子开始",
                "kind": "start",
                "parent_id": "n_block",
            },
            {
                "id": "b_work",
                "name": "子任务",
                "kind": "task",
                "parent_id": "n_block",
                "duration": 1,
            },
            {
                "id": "b_end",
                "name": "子结束",
                "kind": "end",
                "parent_id": "n_block",
            },
            {
                "id": "n_end",
                "name": "结束",
                "kind": "end",
                "parent_id": None,
            },
        ],
        "branches": [
            {
                "id": "e_start_block",
                "from_step": "n_start",
                "to_step": "n_block",
                "kind": "normal",
            },
            {
                "id": "e_b_start",
                "from_step": "b_start",
                "to_step": "b_work",
                "kind": "normal",
            },
            {
                "id": "e_b_end",
                "from_step": "b_work",
                "to_step": "b_end",
                "kind": "normal",
            },
            {
                "id": "e_block_end",
                "from_step": "n_block",
                "to_step": "n_end",
                "kind": "normal",
                "exit_step_id": "b_end",
            },
        ],
        "ambiguities": [],
    }
    nested_spec = {
        "schema_version": "process-ir/1.1",
        "name": "嵌套块测试",
        "start_node_id": "n_start",
        "end_node_ids": ["n_end"],
        "nodes": [
            {"id": "n_start", "type": "start", "name": "开始"},
            {
                "id": "n_block",
                "type": "subprocess",
                "name": "复合块",
                "subflow": {
                    "start_node_id": "b_start",
                    "end_node_ids": ["b_end"],
                    "nodes": [
                        {"id": "b_start", "type": "start", "name": "子开始"},
                        {
                            "id": "b_work",
                            "type": "task",
                            "name": "子任务",
                            "duration": 1,
                        },
                        {"id": "b_end", "type": "end", "name": "子结束"},
                    ],
                    "edges": [
                        {
                            "id": "e_b_start",
                            "from": "b_start",
                            "to": "b_work",
                            "kind": "normal",
                        },
                        {
                            "id": "e_b_end",
                            "from": "b_work",
                            "to": "b_end",
                            "kind": "normal",
                        },
                    ],
                },
            },
            {"id": "n_end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {
                "id": "e_start_block",
                "from": "n_start",
                "to": "n_block",
                "kind": "normal",
            },
            {
                "id": "e_block_end",
                "from": "n_block",
                "to": "n_end",
                "kind": "normal",
                "subflow_exit": "b_end",
            },
        ],
    }

    class NestedClient(FakePiClient):
        async def prompt(self, message: str):
            self.prompts.append(message)
            asyncio.create_task(self._emit_nested())
            return {"success": True, "data": {"disposition": "started"}}

        async def _emit_nested(self):
            await asyncio.sleep(0)
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_nested_analysis",
                    "toolName": "analyze_requirements",
                    "args": {"analysis": nested_analysis},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_nested_analysis",
                    "toolName": "analyze_requirements",
                    "isError": False,
                    "result": {"details": {"valid": True}},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call_nested_process",
                    "toolName": "validate_process_model",
                    "args": {"spec": nested_spec},
                }
            )
            await self.on_event(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call_nested_process",
                    "toolName": "validate_process_model",
                    "isError": False,
                    "result": {"details": {"valid": False}},
                }
            )
            await self.on_event({"type": "agent_settled"})

    async def run():
        settings = _settings(tmp_path)
        manager = AgentSessionManager(
            settings, client_factory=lambda **kwargs: NestedClient(**kwargs)
        )
        await manager.start()
        try:
            session = await manager.create_session()
            queue = session.subscribe()
            await manager.send_message(session.session_id, "生成嵌套流程")
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                events.append(event)
                if event["type"] == "done":
                    break
            analysis_event = next(
                event for event in events if event["type"] == "requirement_analysis"
            )
            assert analysis_event["data"]["valid"] is True
            process_event = next(
                event for event in events if event["type"] == "process_ir"
            )
            validation = process_event["data"]["validation"]
            assert validation["valid"] is True
            assert validation["coverage"]["covered"] is True
            assert validation["coverage"]["step_count"] == 6
            assert validation["coverage"]["branch_count"] == 4
        finally:
            await manager.shutdown()

    asyncio.run(run())
