"""Structured requirement analysis for long natural-language requests.

The LLM extracts an explicit requirement graph first. The backend then checks the
generated Process IR against that graph so clauses cannot be silently dropped or
invented. This module performs no keyword matching and no language inference.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, model_validator

from app.domain.process_ir import (
    ID_PATTERN,
    ProcessSpec,
    StrictModel,
)

StepKind = Literal["start", "task", "decision", "end", "subprocess"]
BranchKind = Literal["normal", "conditional", "default", "failure"]


class RequirementStep(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    kind: StepKind
    parent_id: str | None = Field(default=None, pattern=ID_PATTERN)
    description: str = Field(default="", max_length=2000)
    duration: float | None = Field(default=None, ge=0)


class RequirementBranch(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    from_step: str = Field(pattern=ID_PATTERN)
    to_step: str = Field(pattern=ID_PATTERN)
    kind: BranchKind = "normal"
    condition: str | None = Field(default=None, max_length=500)
    loop: bool = False
    exit_step_id: str | None = Field(default=None, pattern=ID_PATTERN)


class RequirementAmbiguity(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    question: str = Field(min_length=1, max_length=500)
    blocks_generation: bool = True
    options: list[str] = Field(default_factory=list, max_length=10)


class RequirementAnalysis(StrictModel):
    summary: str = Field(default="", max_length=5000)
    steps: list[RequirementStep] = Field(default_factory=list, max_length=500)
    branches: list[RequirementBranch] = Field(default_factory=list, max_length=1000)
    ambiguities: list[RequirementAmbiguity] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def _validate_references(self) -> "RequirementAnalysis":
        step_ids = [step.id for step in self.steps]
        duplicates = sorted(
            {step_id for step_id in step_ids if step_ids.count(step_id) > 1}
        )
        if duplicates:
            raise ValueError(f"需求分析步骤 ID 重复: {', '.join(duplicates)}")
        branch_ids = [branch.id for branch in self.branches]
        duplicate_branches = sorted(
            {
                branch_id
                for branch_id in branch_ids
                if branch_ids.count(branch_id) > 1
            }
        )
        if duplicate_branches:
            raise ValueError(
                f"需求分析连接 ID 重复: {', '.join(duplicate_branches)}"
            )
        known = set(step_ids)
        step_map = {step.id: step for step in self.steps}
        for step in self.steps:
            if step.parent_id is None:
                continue
            parent = step_map.get(step.parent_id)
            if parent is None:
                raise ValueError(
                    f"步骤 {step.id} 引用了未知父步骤 {step.parent_id}"
                )
            if parent.kind != "subprocess":
                raise ValueError(
                    f"步骤 {step.id} 的父步骤 {parent.id} 不是 subprocess"
                )
            seen = {step.id}
            current = parent
            depth = 0
            while current.parent_id is not None:
                if current.id in seen:
                    raise ValueError(
                        f"步骤父子关系存在循环引用: {step.id}"
                    )
                seen.add(current.id)
                current = step_map[current.parent_id]
                depth += 1
                if depth > 32:
                    raise ValueError("步骤父子层级过深或存在循环引用")
        for branch in self.branches:
            if branch.from_step not in known:
                raise ValueError(
                    f"连接 {branch.id} 引用了未知起点 {branch.from_step}"
                )
            if branch.to_step not in known:
                raise ValueError(
                    f"连接 {branch.id} 引用了未知终点 {branch.to_step}"
                )
            source = step_map[branch.from_step]
            target = step_map[branch.to_step]
            if branch.exit_step_id is not None:
                if branch.exit_step_id not in known:
                    raise ValueError(
                        f"连接 {branch.id} 引用了未知出口 {branch.exit_step_id}"
                    )
                if source.kind != "subprocess":
                    raise ValueError(
                        f"连接 {branch.id} 不是子流程父连接，不能设置 exit_step_id"
                    )
                exit_step = step_map[branch.exit_step_id]
                if exit_step.parent_id != source.id:
                    raise ValueError(
                        f"连接 {branch.id} 的 exit_step_id 不属于子流程 {source.id}"
                    )
            if source.kind == "subprocess":
                if target.parent_id != source.parent_id:
                    raise ValueError(
                        f"子流程父连接 {branch.id} 的终点必须与子流程同一层级"
                    )
            elif source.parent_id != target.parent_id:
                raise ValueError(
                    f"连接 {branch.id} 跨越了父子流程层级"
                )
        return self

    @property
    def blocking_ambiguities(self) -> list[RequirementAmbiguity]:
        return [item for item in self.ambiguities if item.blocks_generation]


class CoverageIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    step_id: str | None = None
    branch_id: str | None = None
    node_id: str | None = None


class RequirementAnalysisIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    step_id: str | None = None
    branch_id: str | None = None


class RequirementAnalysisResult(StrictModel):
    valid: bool
    issues: list[RequirementAnalysisIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[RequirementAnalysisIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


def _nodes_in_cycles(
    node_ids: list[str], branches: list[RequirementBranch]
) -> set[str]:
    """Return nodes that lie on at least one cycle in the local scope.

    A legal continuous-loop subprocess can never reach an end node by design.
    Those nodes are structurally valid; only non-cyclic dead ends are errors.
    """

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for branch in branches:
        adjacency.setdefault(branch.from_step, []).append(branch.to_step)
    in_cycle: set[str] = set()
    for start in node_ids:
        stack = list(adjacency.get(start, []))
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == start:
                in_cycle.add(start)
                break
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, []))
    return in_cycle


def validate_requirement_analysis(
    analysis: RequirementAnalysis,
) -> RequirementAnalysisResult:
    """Validate a hierarchical requirement analysis as an IR blueprint."""

    issues: list[RequirementAnalysisIssue] = []
    step_map = {step.id: step for step in analysis.steps}
    children_by_parent: dict[str | None, list[RequirementStep]] = {}
    for step in analysis.steps:
        children_by_parent.setdefault(step.parent_id, []).append(step)

    def error(
        code: str,
        message: str,
        *,
        step_id: str | None = None,
        branch_id: str | None = None,
    ) -> None:
        issues.append(
            RequirementAnalysisIssue(
                severity="error",
                code=code,
                message=message,
                step_id=step_id,
                branch_id=branch_id,
            )
        )

    def warning(
        code: str,
        message: str,
        *,
        step_id: str | None = None,
        branch_id: str | None = None,
    ) -> None:
        issues.append(
            RequirementAnalysisIssue(
                severity="warning",
                code=code,
                message=message,
                step_id=step_id,
                branch_id=branch_id,
            )
        )

    def validate_scope(parent_id: str | None, depth: int) -> None:
        if depth > 8:
            error(
                "requirement_max_nesting_depth",
                "嵌套层级超过上限 8 层",
                step_id=parent_id,
            )
            return
        steps = children_by_parent.get(parent_id, [])
        starts = [step for step in steps if step.kind == "start"]
        ends = [step for step in steps if step.kind == "end"]
        if len(starts) != 1:
            error(
                "requirement_start_count",
                (
                    f"作用域 {parent_id or 'root'} 必须且只能有 1 个 start 节点，"
                    f"当前有 {len(starts)} 个"
                ),
                step_id=parent_id,
            )
        if not ends:
            error(
                "requirement_end_missing",
                f"作用域 {parent_id or 'root'} 至少需要 1 个 end 节点",
                step_id=parent_id,
            )

        scope_steps = set(step.id for step in steps)
        scope_branches = [
            branch
            for branch in analysis.branches
            if branch.from_step in scope_steps and branch.to_step in scope_steps
        ]
        outgoing: dict[str, list[RequirementBranch]] = {
            step.id: [] for step in steps
        }
        incoming: dict[str, list[RequirementBranch]] = {
            step.id: [] for step in steps
        }
        for branch in scope_branches:
            outgoing[branch.from_step].append(branch)
            incoming[branch.to_step].append(branch)

        for step in steps:
            branches = outgoing[step.id]
            kinds = [branch.kind for branch in branches]

            if step.kind in {"start", "end", "decision", "subprocess"}:
                if step.duration is not None:
                    error(
                        "requirement_decision_has_duration"
                        if step.kind == "decision"
                        else "requirement_non_task_has_duration",
                        (
                            f"节点 {step.id}（{step.name}）是 {step.kind}，"
                            "不应设置 duration；只有 task 才需要 duration，"
                            "请将非 task 节点的 duration 设为 null"
                        ),
                        step_id=step.id,
                    )

            if step.kind == "task" and step.duration is None:
                warning(
                    "requirement_task_missing_duration",
                    (
                        f"task 节点 {step.id}（{step.name}）尚未配置 duration，"
                        "结构建模阶段允许留空，仿真前必须补充"
                    ),
                    step_id=step.id,
                )

            if step.kind == "start":
                if incoming[step.id]:
                    error(
                        "requirement_start_has_incoming",
                        f"start 节点 {step.id} 不应有入边",
                        step_id=step.id,
                    )
                if len(branches) != 1 or kinds[0] != "normal":
                    error(
                        "requirement_start_invalid_exit",
                        f"start 节点 {step.id} 必须且只能有一条 normal 出边",
                        step_id=step.id,
                    )

            if step.kind == "end" and branches:
                error(
                    "requirement_end_has_outgoing",
                    f"end 节点 {step.id} 不应有出边",
                    step_id=step.id,
                )

            if step.kind == "decision":
                if len(branches) < 2:
                    error(
                        "requirement_decision_too_few_branches",
                        f"decision 节点 {step.id} 至少需要 2 条分支",
                        step_id=step.id,
                    )
                if any(kind not in {"conditional", "default"} for kind in kinds):
                    error(
                        "requirement_decision_invalid_branch_kind",
                        f"decision 节点 {step.id} 的分支类型只能是 conditional/default",
                        step_id=step.id,
                    )
                if "conditional" not in kinds:
                    error(
                        "requirement_decision_without_condition",
                        f"decision 节点 {step.id} 缺少 conditional 分支",
                        step_id=step.id,
                    )
                if "default" not in kinds:
                    error(
                        "requirement_decision_without_default",
                        f"decision 节点 {step.id} 缺少 default 兜底分支",
                        step_id=step.id,
                    )

            if step.kind == "task":
                if not branches:
                    error(
                        "requirement_task_missing_exit",
                        f"task 节点 {step.id} 没有出边",
                        step_id=step.id,
                    )
                elif len(branches) == 1:
                    if kinds[0] != "normal":
                        error(
                            "requirement_task_invalid_single_exit",
                            f"task 节点 {step.id} 只有一条出边时必须为 normal",
                            step_id=step.id,
                        )
                elif "conditional" in kinds:
                    if "default" not in kinds:
                        error(
                            "requirement_task_missing_default",
                            f"task 节点 {step.id} 存在 conditional 分支时必须提供 default 分支",
                            step_id=step.id,
                        )
                    if any(kind in {"normal", "failure"} for kind in kinds):
                        error(
                            "requirement_task_invalid_branch_mix",
                            f"task 节点 {step.id} 的 conditional 分支不能再与 normal/failure 混用",
                            step_id=step.id,
                        )
                elif set(kinds) != {"normal", "failure"}:
                    error(
                        "requirement_task_ambiguous_branching",
                        f"task 节点 {step.id} 的分支组合不明确",
                        step_id=step.id,
                    )

            if step.kind == "subprocess":
                child_steps = children_by_parent.get(step.id, [])
                child_starts = [
                    item for item in child_steps if item.kind == "start"
                ]
                child_ends = [
                    item for item in child_steps if item.kind == "end"
                ]
                if not child_starts:
                    error(
                        "requirement_subprocess_missing_start",
                        f"subprocess 节点 {step.id} 缺少内部 start 节点",
                        step_id=step.id,
                    )
                if not child_ends:
                    error(
                        "requirement_subprocess_missing_end",
                        f"subprocess 节点 {step.id} 缺少内部 end 节点",
                        step_id=step.id,
                    )
                if not branches:
                    error(
                        "requirement_subprocess_missing_parent_exit",
                        f"subprocess 节点 {step.id} 缺少父流程出口分支",
                        step_id=step.id,
                    )
                for branch in branches:
                    if branch.kind not in {"normal", "failure"}:
                        error(
                            "requirement_subprocess_invalid_parent_exit",
                            f"subprocess 父连接 {branch.id} 的类型必须为 normal/failure",
                            branch_id=branch.id,
                        )
                    if branch.exit_step_id is None:
                        if len(child_ends) > 1:
                            error(
                                "requirement_subprocess_exit_required",
                                (
                                    f"subflow {step.id} 有多个内部 end 节点，"
                                    f"父连接 {branch.id} 必须指定 exit_step_id"
                                ),
                                branch_id=branch.id,
                            )
                    else:
                        exit_step = step_map.get(branch.exit_step_id)
                        if exit_step is None or exit_step.parent_id != step.id:
                            error(
                                "requirement_subprocess_unknown_exit",
                                f"连接 {branch.id} 的 exit_step_id 不属于子流程 {step.id}",
                                branch_id=branch.id,
                            )
                        elif exit_step.kind != "end":
                            error(
                                "requirement_subprocess_exit_not_end",
                                f"连接 {branch.id} 的 exit_step_id 必须是 end 节点",
                                branch_id=branch.id,
                            )
                mapped_exits = {
                    branch.exit_step_id
                    for branch in branches
                    if branch.exit_step_id is not None
                }
                if len(child_ends) > 1:
                    for end_step in child_ends:
                        if end_step.id not in mapped_exits:
                            error(
                                "requirement_subprocess_exit_not_mapped",
                                f"subflow {step.id} 的内部 end 节点 {end_step.id} 没有父连接映射",
                                step_id=end_step.id,
                            )
                validate_scope(step.id, depth + 1)

            for kind in ("normal", "failure", "default"):
                if kinds.count(kind) > 1 and step.kind != "subprocess":
                    error(
                        "requirement_duplicate_branch_kind",
                        f"节点 {step.id} 存在多条 {kind} 分支",
                        step_id=step.id,
                    )

        for branch in scope_branches:
            if branch.kind == "conditional":
                if not branch.condition:
                    error(
                        "requirement_conditional_without_condition",
                        f"conditional 分支 {branch.id} 缺少 condition 说明",
                        branch_id=branch.id,
                    )
            elif branch.condition:
                warning(
                    "requirement_branch_condition_not_allowed",
                    f"{branch.kind} 分支 {branch.id} 不应带 condition",
                    branch_id=branch.id,
                )

        if starts:
            reachable = {starts[0].id}
            queue = [starts[0].id]
            while queue:
                current = queue.pop()
                for branch in outgoing.get(current, []):
                    if branch.to_step not in reachable:
                        reachable.add(branch.to_step)
                        queue.append(branch.to_step)
            for step in steps:
                if step.id not in reachable:
                    error(
                        "requirement_unreachable_step",
                        f"节点 {step.id}（{step.name}）无法从 start 到达",
                        step_id=step.id,
                    )
            reverse: dict[str, list[str]] = {step.id: [] for step in steps}
            for branch in scope_branches:
                reverse[branch.to_step].append(branch.from_step)
            can_reach_end = {step.id for step in ends}
            queue = list(can_reach_end)
            while queue:
                current = queue.pop()
                for previous in reverse.get(current, []):
                    if previous not in can_reach_end:
                        can_reach_end.add(previous)
                        queue.append(previous)
            cycle_nodes = _nodes_in_cycles(
                [step.id for step in steps], scope_branches
            )
            for step in steps:
                if step.id not in can_reach_end:
                    if step.id in cycle_nodes:
                        warning(
                            "requirement_continuous_loop",
                            (
                                f"节点 {step.id}（{step.name}）处于持续循环中，"
                                "按设计不会到达 end，视为合法的持续循环"
                            ),
                            step_id=step.id,
                        )
                    else:
                        error(
                            "requirement_cannot_reach_end",
                            f"节点 {step.id}（{step.name}）无法到达任何 end 节点",
                            step_id=step.id,
                        )

    validate_scope(None, 0)
    return RequirementAnalysisResult(
        valid=not any(issue.severity == "error" for issue in issues),
        issues=issues,
    )


class CoverageResult(StrictModel):
    covered: bool
    step_count: int = Field(ge=0)
    covered_step_count: int = Field(ge=0)
    branch_count: int = Field(ge=0)
    covered_branch_count: int = Field(ge=0)
    issues: list[CoverageIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[CoverageIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


def evaluate_requirement_coverage(
    analysis: RequirementAnalysis,
    spec: ProcessSpec,
) -> CoverageResult:
    issues: list[CoverageIssue] = []
    step_map = {step.id: step for step in analysis.steps}
    children_by_parent: dict[str | None, list[RequirementStep]] = {}
    for step in analysis.steps:
        children_by_parent.setdefault(step.parent_id, []).append(step)

    step_to_node: dict[str, object] = {}
    scope_by_parent: dict[str | None, object] = {None: spec}

    def map_scope(parent_id: str | None, scope) -> None:
        nodes = scope.nodes or []
        by_id = {node.id: node for node in nodes}
        by_name: dict[str, str] = {}
        for node in nodes:
            by_name.setdefault(node.name, node.id)
        for step in children_by_parent.get(parent_id, []):
            node = by_id.get(step.id)
            if node is None:
                fallback_id = by_name.get(step.name)
                if fallback_id is not None:
                    node = by_id[fallback_id]
            if node is None:
                issues.append(
                    CoverageIssue(
                        severity="error",
                        code="requirement_step_missing",
                        message=f"步骤 {step.id}（{step.name}）在流程中找不到对应节点",
                        step_id=step.id,
                    )
                )
                continue
            step_to_node[step.id] = node
            if node.type != step.kind:
                issues.append(
                    CoverageIssue(
                        severity="error",
                        code="requirement_step_kind_mismatch",
                        message=(
                            f"步骤 {step.id} 的类型是 {step.kind}，"
                            f"但对应节点 {node.id} 的类型是 {node.type}"
                        ),
                        step_id=step.id,
                        node_id=node.id,
                    )
                )
            if (
                step.kind == "task"
                and step.duration is not None
                and node.duration is not None
                and not math.isclose(
                    float(step.duration), float(node.duration), abs_tol=1e-9
                )
            ):
                issues.append(
                    CoverageIssue(
                        severity="warning",
                        code="requirement_duration_mismatch",
                        message=(
                            f"步骤 {step.id} 的时长是 {step.duration}，"
                            f"与节点时长 {node.duration} 不一致"
                        ),
                        step_id=step.id,
                        node_id=node.id,
                    )
                )
            if step.kind == "subprocess":
                if node.subflow is None:
                    issues.append(
                        CoverageIssue(
                            severity="error",
                            code="requirement_subprocess_missing_subflow",
                            message=f"节点 {node.id} 是 subprocess 但缺少 subflow",
                            step_id=step.id,
                            node_id=node.id,
                        )
                    )
                else:
                    scope_by_parent[step.id] = node.subflow
                    map_scope(step.id, node.subflow)

    map_scope(None, spec)

    covered_branches = 0
    for branch in analysis.branches:
        source_step = step_map[branch.from_step]
        target_step = step_map[branch.to_step]
        source_node = step_to_node.get(branch.from_step)
        target_node = step_to_node.get(branch.to_step)
        if source_node is None or target_node is None:
            issues.append(
                CoverageIssue(
                    severity="error",
                    code="requirement_branch_unresolved",
                    message=f"连接 {branch.id} 的起点或终点无法映射到节点",
                    branch_id=branch.id,
                )
            )
            continue
        parent_id = source_step.parent_id
        scope = scope_by_parent.get(parent_id)
        if scope is None:
            issues.append(
                CoverageIssue(
                    severity="error",
                    code="requirement_branch_scope_missing",
                    message=f"连接 {branch.id} 找不到所在作用域",
                    branch_id=branch.id,
                )
            )
            continue
        candidates = [
            edge
            for edge in scope.edges or []
            if edge.source == source_node.id and edge.target == target_node.id
        ]
        if source_step.kind == "subprocess":
            exit_node_id = (
                step_to_node.get(branch.exit_step_id).id
                if branch.exit_step_id and step_to_node.get(branch.exit_step_id)
                else None
            )
            if exit_node_id is not None:
                candidates = [
                    edge
                    for edge in candidates
                    if edge.subflow_exit in {exit_node_id, None}
                ]
            if not candidates:
                issues.append(
                    CoverageIssue(
                        severity="error",
                        code="requirement_branch_missing",
                        message=(
                            f"连接 {branch.id}（{branch.from_step} → "
                            f"{branch.to_step}）在对应作用域中找不到匹配的子流程出口边"
                        ),
                        branch_id=branch.id,
                    )
                )
                continue
            matched = candidates[0]
            if (
                exit_node_id is not None
                and matched.subflow_exit not in {None, exit_node_id}
            ):
                issues.append(
                    CoverageIssue(
                        severity="error",
                        code="requirement_subflow_exit_mismatch",
                        message=(
                            f"连接 {branch.id} 期望出口 {exit_node_id}，"
                            f"但匹配到的边出口是 {matched.subflow_exit}"
                        ),
                        branch_id=branch.id,
                        node_id=source_node.id,
                    )
                )
        else:
            if not candidates:
                issues.append(
                    CoverageIssue(
                        severity="error",
                        code="requirement_branch_missing",
                        message=(
                            f"连接 {branch.id}（{branch.from_step} → "
                            f"{branch.to_step}）在对应作用域中找不到匹配的边"
                        ),
                        branch_id=branch.id,
                    )
                )
                continue
            matched = candidates[0]
        covered_branches += 1
        if matched.kind != branch.kind:
            issues.append(
                CoverageIssue(
                    severity="warning",
                    code="requirement_branch_kind_mismatch",
                    message=(
                        f"连接 {branch.id} 的类型是 {branch.kind}，"
                        f"匹配边 {matched.id} 的类型是 {matched.kind}"
                    ),
                    branch_id=branch.id,
                    node_id=source_node.id,
                )
            )

    analyzed_node_ids = {
        node.id for node in step_to_node.values() if node is not None
    }

    def check_extra_nodes(scope) -> None:
        for node in scope.nodes or []:
            if (
                node.type in {"task", "decision", "subprocess"}
                and node.id not in analyzed_node_ids
            ):
                issues.append(
                    CoverageIssue(
                        severity="error",
                        code="requirement_node_not_analyzed",
                        message=(
                            f"节点 {node.id}（{node.name}）在需求分析中没有对应步骤，"
                            "可能属于未声明的多余活动"
                        ),
                        node_id=node.id,
                    )
                )
            if node.subflow is not None:
                check_extra_nodes(node.subflow)

    check_extra_nodes(spec)

    for ambiguity in analysis.blocking_ambiguities:
        issues.append(
            CoverageIssue(
                severity="error",
                code="requirement_ambiguity_unresolved",
                message=f"存在未澄清的阻塞问题 {ambiguity.id}: {ambiguity.question}",
            )
        )

    error_count = sum(1 for issue in issues if issue.severity == "error")
    return CoverageResult(
        covered=error_count == 0,
        step_count=len(analysis.steps),
        covered_step_count=len(step_to_node),
        branch_count=len(analysis.branches),
        covered_branch_count=covered_branches,
        issues=issues,
    )


__all__ = [
    "BranchKind",
    "CoverageIssue",
    "CoverageResult",
    "RequirementAmbiguity",
    "RequirementAnalysis",
    "RequirementAnalysisIssue",
    "RequirementAnalysisResult",
    "RequirementBranch",
    "RequirementStep",
    "StepKind",
    "evaluate_requirement_coverage",
    "validate_requirement_analysis",
]
