from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.domain.process_ir import ProcessDocument, ProcessSpec
from app.domain.reliability_ir import ReliabilityDocument
from app.domain.versioning import compute_content_hash


def minimal_process_dict() -> dict[str, Any]:
    return {
        "schema_version": "process-ir/1.0",
        "name": "最小流程",
        "description": "",
        "status_catalog": [],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {
                "id": "work",
                "type": "task",
                "name": "工作",
                "duration": 1,
                "position": {"x": 200, "y": 120},
            },
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {
                "id": "e_start_work",
                "from": "start",
                "to": "work",
                "kind": "normal",
            },
            {
                "id": "e_work_end",
                "from": "work",
                "to": "end",
                "kind": "normal",
            },
        ],
        "guards": {"max_node_visits": 10000},
    }


def minimal_spec() -> ProcessSpec:
    return ProcessSpec.model_validate(minimal_process_dict())


def spec_from(data: dict[str, Any]) -> ProcessSpec:
    return ProcessSpec.model_validate(deepcopy(data))


def loop_process_dict() -> dict[str, Any]:
    return {
        "schema_version": "process-ir/1.0",
        "name": "带循环流程",
        "status_catalog": [],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {"id": "prepare", "type": "task", "name": "准备", "duration": 0.5},
            {"id": "check", "type": "decision", "name": "检查"},
            {
                "id": "rework",
                "type": "task",
                "name": "返工",
                "duration": 0.4,
                "outcomes": [
                    {
                        "id": "fixed",
                        "name": "修复",
                        "weight": 1,
                        "attributes": {"quality_ok": True},
                    }
                ],
            },
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_prepare", "from": "start", "to": "prepare", "kind": "normal"},
            {"id": "e_prepare_check", "from": "prepare", "to": "check", "kind": "normal"},
            {
                "id": "e_check_end",
                "from": "check",
                "to": "end",
                "kind": "conditional",
                "label": "合格",
                "condition": {
                    "op": "eq",
                    "field": "attributes.quality_ok",
                    "value": True,
                },
            },
            {"id": "e_check_rework", "from": "check", "to": "rework", "kind": "default"},
            {"id": "e_rework_check", "from": "rework", "to": "check", "kind": "normal"},
        ],
        "guards": {"max_node_visits": 10000},
    }


def branching_process_dict() -> dict[str, Any]:
    return {
        "schema_version": "process-ir/1.0",
        "name": "分支流程",
        "status_catalog": [],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {
                "id": "prepare",
                "type": "task",
                "name": "准备",
                "duration": 1,
                "outcomes": [
                    {
                        "id": "slow",
                        "name": "慢路线",
                        "weight": 0.5,
                        "attributes": {"route_slow": True},
                    },
                    {
                        "id": "fast",
                        "name": "快路线",
                        "weight": 0.5,
                        "attributes": {"route_slow": False},
                    },
                ],
            },
            {"id": "route", "type": "decision", "name": "路线判断"},
            {"id": "slow_task", "type": "task", "name": "慢任务", "duration": 5},
            {"id": "fast_task", "type": "task", "name": "快任务", "duration": 0.5},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_prepare", "from": "start", "to": "prepare", "kind": "normal"},
            {"id": "e_prepare_route", "from": "prepare", "to": "route", "kind": "normal"},
            {
                "id": "e_route_slow",
                "from": "route",
                "to": "slow_task",
                "kind": "conditional",
                "priority": 10,
                "condition": {
                    "op": "eq",
                    "field": "attributes.route_slow",
                    "value": True,
                },
            },
            {
                "id": "e_route_fast",
                "from": "route",
                "to": "fast_task",
                "kind": "conditional",
                "priority": 10,
                "condition": {
                    "op": "eq",
                    "field": "attributes.route_slow",
                    "value": False,
                },
            },
            {"id": "e_route_default", "from": "route", "to": "fast_task", "kind": "default"},
            {"id": "e_slow_end", "from": "slow_task", "to": "end", "kind": "normal"},
            {"id": "e_fast_end", "from": "fast_task", "to": "end", "kind": "normal"},
        ],
        "guards": {"max_node_visits": 10000},
    }


def failure_process_dict() -> dict[str, Any]:
    return {
        "schema_version": "process-ir/1.0",
        "name": "故障维修流程",
        "status_catalog": [
            {"id": "operational", "name": "可运行", "counts_as_available": True},
            {"id": "under_repair", "name": "维修中", "counts_as_available": False},
        ],
        "start_node_id": "start",
        "end_node_ids": ["end"],
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {
                "id": "inspect",
                "type": "task",
                "name": "检测",
                "duration": 1,
                "status_on_enter": "operational",
                "outcomes": [
                    {
                        "id": "ok",
                        "name": "检测完成",
                        "weight": 1,
                        "attributes": {"inspection_passed": True},
                    }
                ],
            },
            {
                "id": "repair",
                "type": "task",
                "name": "维修",
                "duration": 0.5,
                "status_on_enter": "under_repair",
                "status_on_complete": "operational",
                "on_complete": [
                    {
                        "op": "set_state",
                        "name": "currently_failed",
                        "value": False,
                    }
                ],
            },
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"id": "e_start_inspect", "from": "start", "to": "inspect", "kind": "normal"},
            {"id": "e_inspect_end", "from": "inspect", "to": "end", "kind": "normal"},
            {"id": "e_inspect_repair", "from": "inspect", "to": "repair", "kind": "failure"},
            {"id": "e_repair_end", "from": "repair", "to": "end", "kind": "normal"},
        ],
        "guards": {"max_node_visits": 10000},
    }


def issue_codes(issues: list) -> set[str]:
    return {issue.code for issue in issues}


def document_from_spec(
    spec: ProcessSpec | None = None,
    *,
    version: int = 1,
    content_hash: str | None = None,
) -> ProcessDocument:
    source = spec or minimal_spec()
    return ProcessDocument.model_validate(
        {
            **source.model_dump(mode="python", by_alias=True),
            "process_id": "proc_000000000000",
            "version": version,
            "content_hash": content_hash or compute_content_hash(source),
            "created_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
        }
    )


def reliability_document_from_process(
    process: ProcessDocument,
    nodes: list[dict[str, Any]],
    *,
    revision: int = 1,
    reliability_id: str = "rel_000000000000",
    process_version: int | None = None,
    process_hash: str | None = None,
) -> ReliabilityDocument:
    return ReliabilityDocument.model_validate(
        {
            "process_id": process.process_id,
            "process_version": process_version or process.version,
            "process_hash": process_hash or process.content_hash,
            "reliability_id": reliability_id,
            "revision": revision,
            "created_at": datetime(2026, 11, 20, tzinfo=timezone.utc),
            "nodes": nodes,
        }
    )


def non_participating_reliability(process: ProcessDocument) -> ReliabilityDocument:
    return reliability_document_from_process(
        process,
        [
            {"node_id": node.id, "participates": False}
            for node in process.nodes
            if node.type == "task"
        ],
    )
