from __future__ import annotations

import sys
from dataclasses import replace

import pytest

from app.agent.rpc_client import (
    ALLOWED_AGENT_TOOLS,
    PiRpcClient,
    PiRpcUnavailable,
    project_resources,
)
from app.config import get_settings


def _client(tmp_path, *, api_key: str | None = None) -> PiRpcClient:
    settings = replace(
        get_settings(),
        pi_cli_path=sys.executable,
        pi_node_path=None,
        pi_api_key=api_key,
        agent_session_dir=tmp_path / "agent_sessions",
    )

    async def on_event(_event):
        return None

    return PiRpcClient(
        settings=settings,
        session_id="ags_000000000000",
        on_event=on_event,
    )


def test_rpc_command_enforces_project_tools_and_resources(tmp_path) -> None:
    client = _client(tmp_path, api_key="secret-test-key")
    command = client._command()

    assert command[0] == sys.executable
    assert "--mode" in command and command[command.index("--mode") + 1] == "rpc"
    assert "--approve" in command
    assert "--no-extensions" in command
    assert "--extension" in command
    extension = command[command.index("--extension") + 1]
    assert extension.endswith("get-project-capabilities.ts")
    assert "--no-skills" in command
    assert "--skill" in command
    skill = command[command.index("--skill") + 1]
    assert skill.endswith("reliability-flow-modeling")
    assert "--no-builtin-tools" in command
    assert "--no-mcp" in command
    assert "--no-context-files" in command
    tools = command[command.index("--tools") + 1].split(",")
    assert tuple(tools) == ALLOWED_AGENT_TOOLS
    assert "bash" not in tools
    assert "powershell" not in tools
    assert "write" not in tools
    assert command[command.index("--provider") + 1] == client.settings.llm_provider
    assert command[command.index("--model") + 1] == client.settings.llm_model
    assert command[command.index("--api-key") + 1] == "secret-test-key"


def test_rpc_command_omits_api_key_when_not_configured(tmp_path) -> None:
    command = _client(tmp_path)._command()
    assert "--api-key" not in command


def test_project_resources_fail_closed_when_missing(tmp_path) -> None:
    settings = replace(get_settings(), project_root=tmp_path)
    with pytest.raises(PiRpcUnavailable):
        project_resources(settings)
import asyncio
import json


class _FakeStdout:
    def __init__(self, data: bytes, chunk_size: int) -> None:
        self.data = data
        self.chunk_size = chunk_size
        self.offset = 0

    async def read(self, _n: int) -> bytes:
        if self.offset >= len(self.data):
            return b""
        end = self.offset + self.chunk_size
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk


class _FakeProcess:
    def __init__(self, data: bytes, chunk_size: int) -> None:
        self.stdout = _FakeStdout(data, chunk_size)
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True



def _read_events(
    tmp_path,
    data: bytes,
    *,
    chunk_size: int = 4096,
    max_message_bytes: int = 4 * 1024 * 1024,
    read_chunk_bytes: int = 8192,
):
    events = []

    async def on_event(event):
        events.append(event)

    settings = replace(
        get_settings(),
        agent_session_dir=tmp_path / "agent_sessions",
        agent_rpc_max_message_bytes=max_message_bytes,
        agent_rpc_read_chunk_bytes=read_chunk_bytes,
    )
    client = PiRpcClient(
        settings=settings,
        session_id="ags_000000000000",
        on_event=on_event,
    )
    process = _FakeProcess(data, chunk_size)
    client.process = process
    asyncio.run(client._read_stdout())
    return events, process


def test_rpc_reader_accepts_jsonl_message_larger_than_default_64k(tmp_path) -> None:
    payload = {
        "type": "tool_execution_end",
        "toolCallId": "call_long",
        "toolName": "validate_process_model",
        "result": {
            "details": {
                "spec": {
                    "name": "长 JSON 流程",
                    "nodes": [
                        {
                            "id": f"node_{index}",
                            "name": "长节点" * 20,
                            "description": "x" * 2000,
                        }
                        for index in range(80)
                    ],
                }
            }
        },
    }
    line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    assert len(line) > 64 * 1024

    events, _ = _read_events(tmp_path, line, chunk_size=1024)
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "tool_execution_end"
    assert event["result"]["details"]["spec"]["nodes"][-1][
        "description"
    ] == "x" * 2000
    assert not any(item.get("type") == "protocol_error" for item in events)


def test_rpc_reader_handles_line_split_across_many_reads(tmp_path) -> None:
    first = {
        "type": "message_start",
        "message": {"role": "assistant"},
    }
    second = {
        "type": "message_update",
        "assistantMessageEvent": {
            "type": "text_delta",
            "delta": "长文本" * 30000,
        },
    }
    data = (
        json.dumps(first, ensure_ascii=False)
        + "\n"
        + json.dumps(second, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    events, _ = _read_events(tmp_path, data, chunk_size=97)
    assert [event["type"] for event in events] == [
        "message_start",
        "message_update",
    ]
    assert events[1]["assistantMessageEvent"]["delta"] == "长文本" * 30000


def test_rpc_reader_handles_final_line_without_newline(tmp_path) -> None:
    payload = {"type": "message_end", "message": {"role": "assistant"}}
    events, _ = _read_events(
        tmp_path,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        chunk_size=11,
    )
    assert events == [payload]


def test_rpc_reader_reports_message_over_limit_without_truncation(tmp_path) -> None:
    payload = {"type": "message_update", "delta": "y" * 5000}
    line = (json.dumps(payload) + "\n").encode("utf-8")
    events, process = _read_events(
        tmp_path,
        line,
        chunk_size=64,
        max_message_bytes=1024,
    )
    assert len(events) == 1
    error = events[0]
    assert error["type"] == "protocol_error"
    assert error["code"] == "rpc_message_too_large"
    assert error["limit_bytes"] == 1024
    assert error["received_bytes"] > 1024
    assert "未被截断" in error["message"]
    assert process.terminated is True


def test_rpc_reader_reports_invalid_json_line(tmp_path) -> None:
    events, _ = _read_events(tmp_path, b"not json\n", chunk_size=4)
    assert len(events) == 1
    assert events[0]["type"] == "protocol_error"
    assert events[0]["code"] == "rpc_json_invalid"


def test_rpc_reader_handles_real_subprocess_line_over_64k(tmp_path) -> None:
    code = (
        "import json;"
        "print(json.dumps({'type':'message_update','assistantMessageEvent':"
        "{'type':'text_delta','delta':'x'*120000}}))"
    )

    async def run():
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            stdout=asyncio.subprocess.PIPE,
        )
        events = []

        async def on_event(event):
            events.append(event)

        settings = replace(
            get_settings(),
            agent_session_dir=tmp_path / "agent_sessions",
        )
        client = PiRpcClient(
            settings=settings,
            session_id="ags_000000000000",
            on_event=on_event,
        )
        client.process = process
        await client._read_stdout()
        await process.wait()
        return events

    events = asyncio.run(run())
    assert len(events) == 1
    assert events[0]["type"] == "message_update"
    assert len(events[0]["assistantMessageEvent"]["delta"]) == 120000
