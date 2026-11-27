"""Minimal JSONL client for Pi CLI RPC mode.

The FastAPI backend is the only process allowed to spawn Pi. This module keeps
the child process, JSONL framing, request/response matching, event forwarding
and process cleanup in one place.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import Settings


class PiRpcError(RuntimeError):
    """Raised when the Pi RPC process cannot start or communicate."""


class PiRpcUnavailable(PiRpcError):
    """Raised when the Pi CLI executable or its project resources are missing."""


# Only these extension tools may be called by the web Agent. Built-in tools
# (read/bash/edit/write/...), MCP tools, user extensions and unrelated skills are
# disabled at process startup. This is an enforced runtime allowlist, not a
# prompt-level suggestion.
PROJECT_EXTENSION_RELATIVE = (
    Path(".pi") / "extensions" / "get-project-capabilities.ts"
)
PROJECT_SKILL_RELATIVE = Path(".pi") / "skills" / "reliability-flow-modeling"
ALLOWED_AGENT_TOOLS = (
    "get_project_capabilities",
    "get_process_ir_schema",
    "get_reliability_ir_schema",
    "list_process_models",
    "get_process_model",
    "get_reliability_config",
    "analyze_requirements",
    "validate_process_model",
    "validate_reliability_model",
)

AGENT_APPEND_SYSTEM_PROMPT = (
    "You are the reliability-flow-agent modeling assistant running behind a "
    "web application. Load and follow the reliability-flow-modeling skill. "
    "For long multi-step requirements, first extract and submit a complete "
    "structured requirement graph with analyze_requirements, then build the "
    "Process IR from that exact graph and validate it. The requirement graph "
    "must already match Process IR structure: timed activities are tasks, "
    "judgement points are separate duration=null decisions, decisions use "
    "conditional plus default exits, and structural decision nodes must be "
    "present in the analysis. A named phase with internal steps must be a "
    "subprocess block with parent_id children, child start/end, internal "
    "branches, and parent-branch exit_step_id mappings; do not flatten it into "
    "a task. If analyze_requirements returns valid=false, "
    "fix the analysis before generating. If validation reports any "
    "requirement_* coverage issue, reconcile the analysis and the IR instead "
    "of merely patching the IR. Never drop a named business step, branch, "
    "exception path, or loop. If a required relation or parameter is "
    "ambiguous, list it as a blocking ambiguity and ask the user instead of "
    "inventing it. In particular, never assume that a missing abnormal target "
    "reuses another stage's repair or fallback branch. Use only the provided "
    "extension tools. Produce "
    "proposal-only Process IR or Reliability IR candidates and validate them "
    "through the provided backend tools. Never save, overwrite, simulate, "
    "evaluate, or claim a validation or simulation result without a real tool "
    "call. You cannot read or write files, run shell commands, or call "
    "unrelated tools in this session."
)


def project_resources(settings: Settings) -> tuple[Path, Path]:
    """Return the project extension and skill, failing closed if missing."""

    extension = (settings.project_root / PROJECT_EXTENSION_RELATIVE).resolve()
    skill = (settings.project_root / PROJECT_SKILL_RELATIVE).resolve()
    if not extension.is_file():
        raise PiRpcUnavailable(
            f"找不到项目 Pi 扩展: {extension}。请确认仓库文件完整。"
        )
    if not (skill / "SKILL.md").is_file():
        raise PiRpcUnavailable(
            f"找不到项目 Pi Skill: {skill}。请确认仓库文件完整。"
        )
    return extension, skill


EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]
StderrHandler = Callable[[str], Awaitable[None] | None]
ExitHandler = Callable[[int | None, str], Awaitable[None] | None]


def _default_cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    appdata = os.getenv("APPDATA")
    if appdata:
        candidates.append(
            Path(appdata)
            / "npm"
            / "node_modules"
            / "@earendil-works"
            / "pi-coding-agent"
            / "dist"
            / "bundle"
            / "cli.js"
        )
    candidates.append(
        Path.home()
        / "AppData"
        / "Roaming"
        / "npm"
        / "node_modules"
        / "@earendil-works"
        / "pi-coding-agent"
        / "dist"
        / "bundle"
        / "cli.js"
    )
    candidates.append(
        Path.home()
        / ".npm-global"
        / "lib"
        / "node_modules"
        / "@earendil-works"
        / "pi-coding-agent"
        / "dist"
        / "bundle"
        / "cli.js"
    )
    return candidates


def resolve_pi_launch(settings: Settings) -> list[str]:
    """Resolve a non-shell command that starts the Pi CLI in RPC mode.

    On Windows the npm ``pi.cmd`` shim cannot be executed reliably without a
    shell, so the default path uses ``node`` plus the installed CLI bundle.
    """

    configured = settings.pi_cli_path
    cli_path = Path(configured).expanduser() if configured else None
    if cli_path is None:
        for candidate in _default_cli_candidates():
            if candidate.is_file():
                cli_path = candidate
                break

    node_path = settings.pi_node_path or shutil.which("node") or shutil.which(
        "node.exe"
    )

    if cli_path and cli_path.is_file():
        if cli_path.suffix.lower() == ".js":
            if not node_path:
                raise PiRpcUnavailable(
                    "找不到 node 可执行文件，无法启动 Pi CLI RPC。"
                )
            return [node_path, str(cli_path)]
        return [str(cli_path)]

    pi_path = shutil.which("pi")
    if pi_path:
        return [pi_path]

    raise PiRpcUnavailable(
        "找不到 Pi CLI。请确认已安装 @earendil-works/pi-coding-agent，"
        "或设置 RFA_PI_CLI_PATH / RFA_PI_NODE_PATH。"
    )


class PiRpcClient:
    """A single long-lived Pi RPC child process."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_id: str,
        on_event: EventHandler,
        on_stderr: StderrHandler | None = None,
        on_exit: ExitHandler | None = None,
        request_timeout: float = 30.0,
        max_message_bytes: int | None = None,
        read_chunk_bytes: int | None = None,
    ) -> None:
        self.settings = settings
        self.session_id = session_id
        self.on_event = on_event
        self.on_stderr = on_stderr
        self.on_exit = on_exit
        self.request_timeout = request_timeout
        self.max_message_bytes = max(
            1,
            max_message_bytes
            if max_message_bytes is not None
            else settings.agent_rpc_max_message_bytes,
        )
        self.read_chunk_bytes = max(
            1,
            read_chunk_bytes
            if read_chunk_bytes is not None
            else settings.agent_rpc_read_chunk_bytes,
        )
        self.process: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._request_counter = 0
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._wait_task: asyncio.Task[None] | None = None
        self._closing = False
        self._stderr_tail = ""

    @property
    def stderr_tail(self) -> str:
        return self._stderr_tail[-4000:]

    def _command(self) -> list[str]:
        extension, skill = project_resources(self.settings)
        cmd = resolve_pi_launch(self.settings)
        cmd.extend(
            [
                "--mode",
                "rpc",
                "--approve",
                # Load exactly the project extension and skill. This prevents
                # user-level packages, unrelated extensions, and foreign skills
                # from widening the Agent's capability surface.
                "--no-extensions",
                "--extension",
                str(extension),
                "--no-skills",
                "--skill",
                str(skill),
                "--no-prompt-templates",
                "--no-themes",
                "--no-context-files",
                "--no-mcp",
                # No read/bash/powershell/edit/write tools. The --tools
                # allowlist below is the enforced tool boundary.
                "--no-builtin-tools",
                "--tools",
                ",".join(ALLOWED_AGENT_TOOLS),
                "--append-system-prompt",
                AGENT_APPEND_SYSTEM_PROMPT,
                "--provider",
                self.settings.llm_provider,
                "--model",
                self.settings.llm_model,
                "--session-dir",
                str(self.settings.agent_session_dir),
                "--session-id",
                self.session_id,
            ]
        )
        if self.settings.pi_api_key:
            cmd.extend(["--api-key", self.settings.pi_api_key])
        return cmd

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["RFA_API_BASE_URL"] = self.settings.api_base_url.rstrip("/")
        env["PI_TELEMETRY"] = "0"
        env.setdefault("PYTHONUNBUFFERED", "1")
        return env

    async def start(self) -> None:
        if self.process is not None:
            return
        self.settings.agent_session_dir.mkdir(parents=True, exist_ok=True)
        command = self._command()
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self.settings.project_root),
                env=self._env(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            raise PiRpcUnavailable(f"无法启动 Pi CLI RPC: {exc}") from exc

        self._stdout_task = asyncio.create_task(
            self._read_stdout(), name=f"pi-rpc-stdout-{self.session_id}"
        )
        self._stderr_task = asyncio.create_task(
            self._read_stderr(), name=f"pi-rpc-stderr-{self.session_id}"
        )
        self._wait_task = asyncio.create_task(
            self._wait_for_exit(), name=f"pi-rpc-wait-{self.session_id}"
        )
        try:
            await self.request({"type": "get_state"}, timeout=self.request_timeout)
        except Exception:
            await self.close()
            raise

    async def request(
        self,
        command: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        process = self.process
        if process is None or process.stdin is None:
            raise PiRpcError("Pi RPC 进程尚未启动。")
        if process.returncode is not None:
            raise PiRpcError(
                f"Pi RPC 进程已退出（code={process.returncode}）。"
            )
        self._request_counter += 1
        request_id = f"req_{self._request_counter}"
        payload = {**command, "id": request_id}
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[request_id] = future
        try:
            process.stdin.write(
                (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            self._pending.pop(request_id, None)
            raise PiRpcError(f"写入 Pi RPC 失败: {exc}") from exc

        try:
            response = await asyncio.wait_for(
                future, timeout=timeout or self.request_timeout
            )
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise PiRpcError(
                f"Pi RPC 请求超时: {command.get('type', 'unknown')}"
            ) from exc
        if not response.get("success", False):
            raise PiRpcError(
                str(response.get("error") or "Pi RPC 请求失败")
            )
        return response

    async def prompt(self, message: str) -> dict[str, Any]:
        return await self.request(
            {"type": "prompt", "message": message}, timeout=self.request_timeout
        )

    async def abort(self) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        try:
            await self.request({"type": "abort"}, timeout=10.0)
        except Exception:
            # The abort response can race process teardown; do not mask it.
            pass

    async def close(self) -> None:
        self._closing = True
        process = self.process
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
        for task in (self._stdout_task, self._stderr_task, self._wait_task):
            if task is not None:
                task.cancel()
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(PiRpcError("Pi RPC 会话已关闭。"))
        self._pending.clear()
        self.process = None
        self._stdout_task = None
        self._stderr_task = None
        self._wait_task = None

    async def _emit_protocol_error(
        self,
        message: str,
        *,
        code: str = "protocol_error",
        **details: Any,
    ) -> None:
        await self._call_event(
            {
                "type": "protocol_error",
                "code": code,
                "message": message,
                **details,
            }
        )

    async def _message_too_large(self, size: int) -> None:
        message = (
            f"Pi RPC 单条 JSONL 消息达到 {size} 字节，超过上限 "
            f"{self.max_message_bytes} 字节；消息未被截断。"
            "请检查过长的工具结果，或通过 "
            "RFA_AGENT_RPC_MAX_MESSAGE_BYTES 调整上限。"
        )
        await self._emit_protocol_error(
            message,
            code="rpc_message_too_large",
            received_bytes=size,
            limit_bytes=self.max_message_bytes,
        )
        process = self.process
        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            try:
                terminate()
            except Exception:
                pass

    async def _consume_stdout_line(self, raw: bytes) -> bool:
        if len(raw) > self.max_message_bytes:
            await self._message_too_large(len(raw))
            return False
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return True
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            await self._emit_protocol_error(
                "Pi RPC 返回了非 JSON 行。",
                code="rpc_json_invalid",
                line=text[:500],
            )
            return True
        await self._handle_message(payload)
        return True

    async def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        buffer = bytearray()
        try:
            while True:
                chunk = await process.stdout.read(self.read_chunk_bytes)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    newline = buffer.find(b"\n")
                    if newline < 0:
                        break
                    raw = bytes(buffer[:newline])
                    del buffer[:newline + 1]
                    if not await self._consume_stdout_line(raw):
                        return
                if len(buffer) > self.max_message_bytes:
                    await self._message_too_large(len(buffer))
                    return
            if buffer:
                await self._consume_stdout_line(bytes(buffer))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            await self._emit_protocol_error(
                f"读取 Pi RPC 输出失败: {exc}",
                code="rpc_stdout_error",
            )

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        if payload.get("type") == "response":
            request_id = payload.get("id")
            future = self._pending.pop(str(request_id), None)
            if future is not None and not future.done():
                future.set_result(payload)
            return

        if payload.get("type") == "extension_ui_request":
            method = payload.get("method")
            if method in {"select", "confirm", "input", "editor"}:
                response = {
                    "type": "extension_ui_response",
                    "id": payload.get("id"),
                    "cancelled": True,
                }
                process = self.process
                if process is not None and process.stdin is not None:
                    try:
                        process.stdin.write(
                            (
                                json.dumps(response, ensure_ascii=False) + "\n"
                            ).encode("utf-8")
                        )
                        await process.stdin.drain()
                    except Exception:
                        pass
                return

        await self._call_event(payload)

    async def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                chunk = await process.stderr.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                self._stderr_tail = (self._stderr_tail + text)[-8000:]
                if self.on_stderr is not None:
                    result = self.on_stderr(text)
                    if asyncio.iscoroutine(result):
                        await result
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _wait_for_exit(self) -> None:
        process = self.process
        if process is None:
            return
        code = await process.wait()
        if self._closing:
            return
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(
                    PiRpcError(
                        f"Pi RPC 进程异常退出（code={code}）。"
                    )
                )
        self._pending.clear()
        if self.on_exit is not None:
            result = self.on_exit(code, self.stderr_tail)
            if asyncio.iscoroutine(result):
                await result

    async def _call_event(self, payload: dict[str, Any]) -> None:
        result = self.on_event(payload)
        if asyncio.iscoroutine(result):
            await result


__all__ = [
    "AGENT_APPEND_SYSTEM_PROMPT",
    "ALLOWED_AGENT_TOOLS",
    "PROJECT_EXTENSION_RELATIVE",
    "PROJECT_SKILL_RELATIVE",
    "PiRpcClient",
    "PiRpcError",
    "PiRpcUnavailable",
    "project_resources",
    "resolve_pi_launch",
]
