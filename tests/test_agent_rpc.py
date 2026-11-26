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
