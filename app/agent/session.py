"""Agent session, task and event management.

A session owns exactly one Pi RPC child process. Tasks are business-level
requests inside that session and never share another session's process or
conversation state.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from app.agent.process_candidate import apply_coverage, validate_candidate
from app.agent.requirements import (
    RequirementAnalysis,
    validate_requirement_analysis,
)
from app.agent.rpc_client import (
    ALLOWED_AGENT_TOOLS,
    PiRpcClient,
    PiRpcError,
    PiRpcUnavailable,
    project_resources,
    resolve_pi_launch,
)
from app.config import Settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class AgentError(RuntimeError):
    """Base error for the web Agent layer."""


class AgentSessionNotFound(AgentError):
    pass


class AgentSessionBusy(AgentError):
    pass


class AgentUnavailable(AgentError):
    pass


@dataclass
class AgentTask:
    task_id: str
    prompt: str
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str = "queued"
    error: str | None = None
    assistant_messages: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    pending_tool_args: dict[str, Any] = field(default_factory=dict)
    process_ir: dict[str, Any] | None = None
    process_validation: dict[str, Any] | None = None
    requirement_analysis: dict[str, Any] | None = None
    requirement_analysis_valid: bool | None = None
    requirement_analysis_issues: list[dict[str, Any]] = field(
        default_factory=list
    )
    requirement_coverage: dict[str, Any] | None = None
    requires_requirement_analysis: bool = False
    reliability_ir: dict[str, Any] | None = None
    reliability_validation: dict[str, Any] | None = None
    reliability_process_id: str | None = None
    message_index: int = 0
    current_message_id: str | None = None
    current_text: str = ""
    context: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at) if self.started_at else None,
            "finished_at": _iso(self.finished_at) if self.finished_at else None,
            "error": self.error,
            "has_process_ir": self.process_ir is not None,
            "has_requirement_analysis": self.requirement_analysis is not None,
            "requires_requirement_analysis": self.requires_requirement_analysis,
            "has_reliability_ir": self.reliability_ir is not None,
        }


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _tool_details(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    details = result.get("details")
    if isinstance(details, dict):
        return details
    if any(key in result for key in ("valid", "issues", "content_hash")):
        return result
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
    return None


def _tool_args_summary(tool_name: str, args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    if tool_name == "validate_process_model":
        spec = args.get("spec")
        if isinstance(spec, dict):
            return {
                "process_name": spec.get("name"),
                "node_count": len(spec.get("nodes") or []),
                "edge_count": len(spec.get("edges") or []),
            }
    if tool_name == "analyze_requirements":
        analysis = args.get("analysis")
        if isinstance(analysis, dict):
            return {
                "step_count": len(analysis.get("steps") or []),
                "branch_count": len(analysis.get("branches") or []),
                "ambiguity_count": len(analysis.get("ambiguities") or []),
            }
    if tool_name == "validate_reliability_model":
        spec = args.get("spec")
        if isinstance(spec, dict):
            return {
                "process_id": args.get("process_id"),
                "node_count": len(spec.get("nodes") or []),
                "process_version": spec.get("process_version"),
            }
    if tool_name == "get_process_model":
        return {
            "process_id": args.get("process_id"),
            "version": args.get("version"),
        }
    return {}


def build_agent_prompt(message: str, context: dict[str, Any] | None) -> str:
    if not context:
        return message
    current = context.get("current_process") or {}
    spec = current.get("spec")
    lines = [
        "[reliability-flow-agent session context]",
        "This is a proposal-only session. Never save, update, simulate, or evaluate.",
        "If the user asks to modify the current process, use current_process_spec as the base.",
        f"current_process_id: {current.get('process_id')}",
        f"current_process_version: {current.get('version')}",
        f"current_process_hash: {current.get('content_hash')}",
        f"current_process_dirty: {bool(context.get('dirty'))}",
        f"latest_version: {context.get('latest_version')}",
        f"viewing_version: {context.get('viewing_version')}",
    ]
    reliability = context.get("reliability")
    if isinstance(reliability, dict):
        lines.append("current_reliability_json:")
        lines.append(
            json.dumps(reliability, ensure_ascii=False, separators=(",", ":"))
        )
    if isinstance(spec, dict):
        lines.append("current_process_spec_json:")
        lines.append(json.dumps(spec, ensure_ascii=False, separators=(",", ":")))
    lines.extend(["[user request]", message])
    return "\n".join(lines)


class AgentSession:
    def __init__(
        self,
        *,
        settings: Settings,
        session_id: str,
        client: Any,
    ) -> None:
        self.settings = settings
        self.session_id = session_id
        self.client = client
        self.created_at = _utc_now()
        self.last_activity = self.created_at
        self.status = "starting"
        self.current_task_id: str | None = None
        self.current_tool: str | None = None
        self.tasks: dict[str, AgentTask] = {}
        self.messages: list[dict[str, Any]] = []
        self.candidate_process_ir: dict[str, Any] | None = None
        self.process_validation: dict[str, Any] | None = None
        self.requirement_analysis: dict[str, Any] | None = None
        self.requirement_analysis_valid: bool | None = None
        self.requirement_analysis_issues: list[dict[str, Any]] = []
        self.requirement_coverage: dict[str, Any] | None = None
        self.candidate_reliability_ir: dict[str, Any] | None = None
        self.reliability_validation: dict[str, Any] | None = None
        self.reliability_process_id: str | None = None
        self.last_simulation_result: dict[str, Any] | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=2000)
        self._seq = 0
        self._subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._lock = asyncio.Lock()
        self._watchdog: asyncio.Task[None] | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        self._subscribers.discard(queue)

    def events_since(self, last_event_id: int | None) -> list[dict[str, Any]]:
        if last_event_id is None:
            return list(self.events)
        return [event for event in self.events if event["seq"] > last_event_id]

    def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        event = {
            "seq": self._seq,
            "session_id": self.session_id,
            "task_id": task_id or self.current_task_id,
            "type": event_type,
            "timestamp": _iso(_utc_now()),
            "data": data or {},
        }
        self.events.append(event)
        self.last_activity = _utc_now()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - unbounded queues
                pass
        return event

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------
    def current_task(self) -> AgentTask | None:
        if self.current_task_id is None:
            return None
        return self.tasks.get(self.current_task_id)

    def start_task(
        self,
        *,
        message: str,
        context: dict[str, Any] | None,
    ) -> AgentTask:
        if self.current_task() is not None:
            raise AgentSessionBusy("当前会话已有正在执行的 Agent 任务。")
        task = AgentTask(
            task_id=_new_id("task"),
            prompt=message,
            context=context,
            requires_requirement_analysis=len(message.strip()) >= 200,
        )
        task.status = "running"
        task.started_at = _utc_now()
        self.tasks[task.task_id] = task
        self.current_task_id = task.task_id
        self.status = "running"
        self.emit(
            "task_status",
            {"status": "running", "message": "Agent 已开始处理"},
            task_id=task.task_id,
        )
        return task

    def finish_task(
        self,
        task: AgentTask,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        if task.status in {"completed", "cancelled", "error"}:
            return
        task.status = status
        task.error = error
        task.finished_at = _utc_now()
        self.status = "idle" if status == "completed" else status
        self.current_tool = None
        if self.current_task_id == task.task_id:
            self.current_task_id = None
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None
        self.emit(
            "done",
            {
                "status": status,
                "error": error,
                "has_process_ir": task.process_ir is not None,
                "has_reliability_ir": task.reliability_ir is not None,
            },
            task_id=task.task_id,
        )

    async def cancel_current(self) -> dict[str, Any]:
        task = self.current_task()
        if task is None:
            return {"cancelled": False, "message": "没有正在执行的任务。"}
        try:
            await self.client.abort()
        except Exception:
            pass
        self.finish_task(task, status="cancelled")
        return {"cancelled": True, "task_id": task.task_id}

    async def watchdog(self, task: AgentTask, timeout: float) -> None:
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        if task.status != "running":
            return
        task.error = f"Agent 执行超时（{timeout:.0f} 秒）。"
        try:
            await self.client.abort()
        except Exception:
            pass
        self.emit(
            "error",
            {"message": task.error, "code": "agent_timeout"},
            task_id=task.task_id,
        )
        self.finish_task(task, status="error", error=task.error)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        task = self.current_task()
        if task is not None:
            self.finish_task(task, status="cancelled", error="会话已关闭。")
        try:
            await self.client.close()
        finally:
            for queue in list(self._subscribers):
                try:
                    queue.put_nowait(None)
                except Exception:
                    pass
            self._subscribers.clear()

    # ------------------------------------------------------------------
    # Pi RPC event mapping
    # ------------------------------------------------------------------
    async def handle_process_exit(self, code: int | None, stderr: str) -> None:
        message = f"Pi RPC 进程已退出（code={code}）。"
        if stderr.strip():
            message += " 请检查后端日志和 Pi Provider 配置。"
        self.emit("error", {"message": message, "code": "pi_process_exit"})
        task = self.current_task()
        if task is not None:
            self.finish_task(task, status="error", error=message)

    async def handle_rpc_event(self, event: dict[str, Any]) -> None:
        async with self._lock:
            event_type = event.get("type")
            task = self.current_task()

            if event_type == "agent_start" and task is not None:
                self.status = "running"
                self.emit(
                    "task_status",
                    {"status": "running", "message": "Agent 正在生成"},
                    task_id=task.task_id,
                )
                return

            if event_type == "message_start" and task is not None:
                message = event.get("message") or {}
                if isinstance(message, dict) and message.get("role") == "assistant":
                    task.message_index += 1
                    task.current_message_id = (
                        f"{task.task_id}:m{task.message_index}"
                    )
                    task.current_text = ""
                return

            if event_type == "message_update" and task is not None:
                assistant_event = event.get("assistantMessageEvent") or event.get(
                    "assistant_message_event"
                )
                if isinstance(assistant_event, dict) and (
                    assistant_event.get("type") == "text_delta"
                ):
                    delta = assistant_event.get("delta")
                    if isinstance(delta, str) and delta:
                        if task.current_message_id is None:
                            task.message_index += 1
                            task.current_message_id = (
                                f"{task.task_id}:m{task.message_index}"
                            )
                        task.current_text += delta
                        self.emit(
                            "assistant_delta",
                            {
                                "message_id": task.current_message_id,
                                "delta": delta,
                            },
                            task_id=task.task_id,
                        )
                return

            if event_type == "message_end" and task is not None:
                message = event.get("message") or {}
                if isinstance(message, dict) and message.get("role") == "assistant":
                    stop_reason = message.get("stopReason")
                    error_message = message.get("errorMessage")
                    if stop_reason == "error" or error_message:
                        self.emit(
                            "error",
                            {
                                "message": str(
                                    error_message
                                    or "Pi Provider 调用失败，未生成有效回复。"
                                ),
                                "code": "provider_error",
                            },
                            task_id=task.task_id,
                        )
                    text = _message_text(message)
                    if text:
                        message_id = task.current_message_id or (
                            f"{task.task_id}:m{task.message_index or 1}"
                        )
                        task.assistant_messages.append(text)
                        self.messages.append(
                            {
                                "role": "assistant",
                                "text": text,
                                "task_id": task.task_id,
                                "message_id": message_id,
                            }
                        )
                        self.emit(
                            "assistant_message",
                            {"message_id": message_id, "text": text},
                            task_id=task.task_id,
                        )
                    task.current_message_id = None
                    task.current_text = ""
                return

            if event_type == "tool_execution_start" and task is not None:
                tool_name = str(event.get("toolName") or "unknown")
                tool_call_id = str(event.get("toolCallId") or "")
                args = event.get("args")
                task.pending_tool_args[tool_call_id] = args
                task.tool_calls.append(
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "status": "running",
                        "args_summary": _tool_args_summary(tool_name, args),
                    }
                )
                self.current_tool = tool_name
                self.emit(
                    "tool_start",
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "label": tool_name,
                        "args_summary": _tool_args_summary(tool_name, args),
                    },
                    task_id=task.task_id,
                )
                self.emit(
                    "task_status",
                    {
                        "status": "running",
                        "message": f"正在执行 {tool_name}",
                        "tool": tool_name,
                    },
                    task_id=task.task_id,
                )
                return

            if event_type == "tool_execution_end" and task is not None:
                tool_name = str(event.get("toolName") or "unknown")
                tool_call_id = str(event.get("toolCallId") or "")
                args = task.pending_tool_args.pop(tool_call_id, None)
                is_error = bool(event.get("isError"))
                details = _tool_details(event.get("result"))
                self.current_tool = None
                self.emit(
                    "tool_end",
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "is_error": is_error,
                        "duration_ms": event.get("durationMs"),
                        "summary": _tool_args_summary(tool_name, args),
                    },
                    task_id=task.task_id,
                )
                if tool_name == "analyze_requirements" and isinstance(args, dict):
                    analysis_raw = args.get("analysis")
                    if isinstance(analysis_raw, dict):
                        try:
                            analysis = RequirementAnalysis.model_validate(
                                analysis_raw
                            )
                        except ValidationError as error:
                            self.emit(
                                "error",
                                {
                                    "message": "需求分析结构不合法",
                                    "code": "requirement_analysis_invalid",
                                    "issues": [
                                        {
                                            "field": ".".join(
                                                str(part)
                                                for part in item.get("loc", ())
                                            ),
                                            "message": item.get("msg"),
                                        }
                                        for item in error.errors()
                                    ],
                                },
                                task_id=task.task_id,
                            )
                        else:
                            analysis_result = validate_requirement_analysis(
                                analysis
                            )
                            payload = analysis.model_dump(mode="json")
                            issue_payload = [
                                issue.model_dump(mode="json")
                                for issue in analysis_result.issues
                            ]
                            task.requirement_analysis = payload
                            task.requirement_analysis_valid = (
                                analysis_result.valid
                            )
                            task.requirement_analysis_issues = issue_payload
                            task.requirement_coverage = None
                            self.requirement_analysis = payload
                            self.requirement_analysis_valid = (
                                analysis_result.valid
                            )
                            self.requirement_analysis_issues = issue_payload
                            self.requirement_coverage = None
                            self.emit(
                                "requirement_analysis",
                                {
                                    "analysis": payload,
                                    "valid": analysis_result.valid,
                                    "validation": {
                                        "valid": analysis_result.valid,
                                        "issues": issue_payload,
                                    },
                                    "step_count": len(analysis.steps),
                                    "branch_count": len(analysis.branches),
                                    "ambiguity_count": len(
                                        analysis.ambiguities
                                    ),
                                    "blocking_count": len(
                                        analysis.blocking_ambiguities
                                    ),
                                },
                                task_id=task.task_id,
                            )
                            if not analysis_result.valid:
                                self.emit(
                                    "error",
                                    {
                                        "message": (
                                            "需求分析与 Process IR 结构不一致，"
                                            "请修正需求分析后重新提交，"
                                            "不要直接生成流程。"
                                        ),
                                        "code": "requirement_analysis_invalid",
                                        "issues": issue_payload,
                                    },
                                    task_id=task.task_id,
                                )
                            if analysis.blocking_ambiguities:
                                self.emit(
                                    "clarification",
                                    {
                                        "message": (
                                            "需求中存在必须先澄清的问题，"
                                            "Agent 不会在澄清前生成流程。"
                                        ),
                                        "questions": [
                                            item.model_dump(mode="json")
                                            for item in analysis.blocking_ambiguities
                                        ],
                                    },
                                    task_id=task.task_id,
                                )
                if tool_name == "validate_process_model" and isinstance(args, dict):
                    spec = args.get("spec")
                    if isinstance(spec, dict):
                        validation, parsed = validate_candidate(spec)
                        analysis = None
                        if task.requirement_analysis_valid is True and (
                            task.requirement_analysis is not None
                        ):
                            try:
                                analysis = RequirementAnalysis.model_validate(
                                    task.requirement_analysis
                                )
                            except ValidationError:
                                analysis = None
                        if task.requirement_analysis_valid is False:
                            issues = list(validation.get("issues") or [])
                            for issue in task.requirement_analysis_issues:
                                issues.append(
                                    {
                                        "severity": issue.get(
                                            "severity", "error"
                                        ),
                                        "code": issue.get(
                                            "code",
                                            "requirement_analysis_invalid",
                                        ),
                                        "message": issue.get("message", ""),
                                        "node_id": None,
                                        "edge_id": None,
                                        "step_id": issue.get("step_id"),
                                        "branch_id": issue.get("branch_id"),
                                        "field": "requirement_analysis",
                                    }
                                )
                            validation = dict(validation)
                            validation["issues"] = issues
                            validation["valid"] = False
                            validation["requirement_analysis_valid"] = False
                        if (
                            task.requires_requirement_analysis
                            and task.requirement_analysis is None
                        ):
                            issues = list(validation.get("issues") or [])
                            issues.append(
                                {
                                    "severity": "error",
                                    "code": "requirement_analysis_missing",
                                    "message": (
                                        "长文本需求必须先提交完整的 "
                                        "analyze_requirements 结果，"
                                        "再生成 Process IR"
                                    ),
                                    "node_id": None,
                                    "edge_id": None,
                                    "step_id": None,
                                    "branch_id": None,
                                    "field": "requirement_analysis",
                                }
                            )
                            validation = dict(validation)
                            validation["issues"] = issues
                            validation["valid"] = False
                        validation, coverage = apply_coverage(
                            validation, analysis, parsed
                        )
                        task.process_ir = spec
                        task.process_validation = validation
                        task.requirement_coverage = (
                            coverage.model_dump(mode="json")
                            if coverage is not None
                            else None
                        )
                        self.candidate_process_ir = spec
                        self.process_validation = validation
                        self.requirement_coverage = task.requirement_coverage
                        self.emit(
                            "validation_result",
                            {
                                "model": "process_ir",
                                "validation": validation,
                            },
                            task_id=task.task_id,
                        )
                        self.emit(
                            "process_ir",
                            {
                                "spec": spec,
                                "validation": validation,
                                "requirement_coverage": task.requirement_coverage,
                                "base_process_id": (
                                    task.context or {}
                                    .get("current_process", {})
                                    .get("process_id")
                                ),
                            },
                            task_id=task.task_id,
                        )
                if tool_name == "validate_reliability_model" and isinstance(
                    args, dict
                ):
                    spec = args.get("spec")
                    if isinstance(spec, dict):
                        validation = details if isinstance(details, dict) else None
                        process_id = args.get("process_id")
                        task.reliability_ir = spec
                        task.reliability_validation = validation
                        task.reliability_process_id = (
                            process_id if isinstance(process_id, str) else None
                        )
                        self.candidate_reliability_ir = spec
                        self.reliability_validation = validation
                        self.reliability_process_id = task.reliability_process_id
                        if validation is not None:
                            self.emit(
                                "validation_result",
                                {
                                    "model": "reliability_ir",
                                    "validation": validation,
                                },
                                task_id=task.task_id,
                            )
                        self.emit(
                            "reliability_ir",
                            {
                                "process_id": process_id,
                                "spec": spec,
                                "validation": validation,
                            },
                            task_id=task.task_id,
                        )
                self.emit(
                    "task_status",
                    {
                        "status": "running",
                        "message": "Agent 正在继续处理",
                    },
                    task_id=task.task_id,
                )
                return

            if event_type == "agent_settled":
                if task is not None:
                    if event.get("aborted") and task.status == "running":
                        self.finish_task(task, status="cancelled")
                    else:
                        self.finish_task(task, status="completed")
                return

            if event_type in {"auto_retry_start", "auto_retry_end"}:
                self.emit(
                    "task_status",
                    {
                        "status": "retrying",
                        "message": "Provider 调用失败，Agent 正在重试",
                        "detail": event,
                    },
                    task_id=task.task_id if task else None,
                )
                return

            if event_type in {"extension_error", "protocol_error"}:
                message = (
                    event.get("error")
                    or event.get("message")
                    or "Pi 扩展或协议发生错误。"
                )
                self.emit(
                    "error",
                    {
                        "message": str(message),
                        "code": str(event.get("code") or event_type),
                        "tool": event.get("event"),
                    },
                    task_id=task.task_id if task else None,
                )
                return

            if event_type == "process_exit":
                await self.handle_process_exit(
                    event.get("code"), str(event.get("stderr") or "")
                )
                return

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "current_task_id": self.current_task_id,
            "current_tool": self.current_tool,
            "created_at": _iso(self.created_at),
            "last_activity": _iso(self.last_activity),
            "provider": self.settings.llm_provider,
            "model": self.settings.llm_model,
            "messages": list(self.messages),
            "candidate_process_ir": self.candidate_process_ir,
            "process_validation": self.process_validation,
            "requirement_analysis": self.requirement_analysis,
            "requirement_analysis_valid": self.requirement_analysis_valid,
            "requirement_analysis_issues": self.requirement_analysis_issues,
            "requirement_coverage": self.requirement_coverage,
            "candidate_reliability_ir": self.candidate_reliability_ir,
            "reliability_validation": self.reliability_validation,
            "reliability_process_id": self.reliability_process_id,
            "last_simulation_result": self.last_simulation_result,
            "tasks": [
                task.summary()
                for task in sorted(
                    self.tasks.values(),
                    key=lambda item: item.created_at,
                    reverse=True,
                )
            ],
        }


ClientFactory = Callable[..., Any]


class AgentSessionManager:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.settings = settings
        self.sessions: dict[str, AgentSession] = {}
        self._client_factory = client_factory
        self._lock = asyncio.Lock()
        self._janitor: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._janitor is None:
            self._janitor = asyncio.create_task(
                self._janitor_loop(), name="agent-session-janitor"
            )

    async def shutdown(self) -> None:
        if self._janitor is not None:
            self._janitor.cancel()
            self._janitor = None
        for session in list(self.sessions.values()):
            await session.close()
        self.sessions.clear()

    async def _janitor_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                await self.prune_idle()
        except asyncio.CancelledError:
            return

    async def prune_idle(self) -> None:
        now = _utc_now()
        for session_id, session in list(self.sessions.items()):
            if session.current_task() is not None:
                continue
            idle = (now - session.last_activity).total_seconds()
            if idle > self.settings.agent_idle_timeout_seconds:
                await self.delete_session(session_id)

    def health(self) -> dict[str, Any]:
        try:
            resolve_pi_launch(self.settings)
            project_resources(self.settings)
            available = True
            reason = None
        except PiRpcUnavailable as exc:
            available = False
            reason = str(exc)
        return {
            "available": available,
            "reason": reason,
            "provider": self.settings.llm_provider,
            "model": self.settings.llm_model,
            "tool_policy": "extension-allowlist",
            "allowed_tools": list(ALLOWED_AGENT_TOOLS),
            "session_count": len(self.sessions),
            "max_sessions": self.settings.agent_max_sessions,
        }

    def _build_client(
        self,
        *,
        session_id: str,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        on_stderr: Callable[[str], Awaitable[None]],
        on_exit: Callable[[int | None, str], Awaitable[None]],
    ) -> Any:
        if self._client_factory is not None:
            return self._client_factory(
                settings=self.settings,
                session_id=session_id,
                on_event=on_event,
                on_stderr=on_stderr,
                on_exit=on_exit,
            )
        return PiRpcClient(
            settings=self.settings,
            session_id=session_id,
            on_event=on_event,
            on_stderr=on_stderr,
            on_exit=on_exit,
        )

    async def create_session(self) -> AgentSession:
        async with self._lock:
            if len(self.sessions) >= self.settings.agent_max_sessions:
                raise AgentUnavailable(
                    "Agent 会话数量已达到上限，请先关闭其他会话。"
                )
            session_id = _new_id("ags")
            session: AgentSession | None = None
            client: Any = None
            try:
                async def on_event(event: dict[str, Any]) -> None:
                    assert session is not None
                    await session.handle_rpc_event(event)

                async def on_stderr(text: str) -> None:
                    # Keep diagnostics out of the browser. Pi stderr is only
                    # surfaced as a generic error when the process exits.
                    return None

                async def on_exit(code: int | None, stderr: str) -> None:
                    assert session is not None
                    await session.handle_process_exit(code, stderr)

                client = self._build_client(
                    session_id=session_id,
                    on_event=on_event,
                    on_stderr=on_stderr,
                    on_exit=on_exit,
                )
                session = AgentSession(
                    settings=self.settings,
                    session_id=session_id,
                    client=client,
                )
                await client.start()
                session.status = "idle"
                session.emit(
                    "task_status",
                    {"status": "idle", "message": "Agent 会话已就绪"},
                )
                self.sessions[session_id] = session
                return session
            except Exception:
                if session is not None:
                    await session.close()
                elif client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass
                raise

    def get_session(self, session_id: str) -> AgentSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise AgentSessionNotFound(f"Agent 会话不存在: {session_id}")
        return session

    async def send_message(
        self,
        session_id: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> AgentTask:
        session = self.get_session(session_id)
        async with session._lock:
            task = session.start_task(message=message, context=context)
        prompt = build_agent_prompt(message, context)
        try:
            await session.client.prompt(prompt)
        except Exception as exc:
            session.emit(
                "error",
                {
                    "message": f"发送消息给 Pi Agent 失败: {exc}",
                    "code": "prompt_failed",
                },
                task_id=task.task_id,
            )
            session.finish_task(task, status="error", error=str(exc))
            raise AgentError(f"发送消息给 Pi Agent 失败: {exc}") from exc
        session._watchdog = asyncio.create_task(
            session.watchdog(task, self.settings.agent_timeout_seconds),
            name=f"agent-watchdog-{task.task_id}",
        )
        return task

    async def cancel(self, session_id: str) -> dict[str, Any]:
        return await self.get_session(session_id).cancel_current()

    async def delete_session(self, session_id: str) -> None:
        async with self._lock:
            session = self.sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    def list_sessions(self) -> list[dict[str, Any]]:
        return [session.snapshot() for session in self.sessions.values()]


__all__ = [
    "AgentError",
    "AgentSession",
    "AgentSessionBusy",
    "AgentSessionManager",
    "AgentSessionNotFound",
    "AgentTask",
    "AgentUnavailable",
    "PiRpcError",
    "build_agent_prompt",
]
