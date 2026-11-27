"""Process IR schema.

This module describes business process structure only. Reliability parameters
such as lambda, participation flags or reliability distributions must never be
added here; they belong to the separate Reliability IR.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "process-ir/1.0"
ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
ATTRIBUTE_PATTERN = r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$"
PROCESS_ID_PATTERN = r"^proc_[a-f0-9]{12}$"
CONTENT_HASH_PATTERN = r"^sha256:[a-f0-9]{64}$"

NodeType = Literal["start", "task", "decision", "end", "subprocess"]
EdgeKind = Literal["normal", "conditional", "default", "failure"]
ConditionOp = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "exists",
    "is_null",
    "and",
    "or",
    "not",
]
EffectOp = Literal["set_attribute", "increment_counter", "set_state", "set_status"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class StatusDefinition(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    counts_as_available: bool = True


class Condition(StrictModel):
    op: ConditionOp
    field: str | None = Field(default=None, max_length=128)
    value: Any = None
    conditions: list["Condition"] | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "Condition":
        fields = self.model_fields_set
        if self.op in {"and", "or", "not"}:
            if self.field is not None or self.value is not None:
                raise ValueError("逻辑条件不能同时设置 field 或 value")
            if not self.conditions:
                raise ValueError("逻辑条件必须包含 conditions")
            if self.op == "not" and len(self.conditions) != 1:
                raise ValueError("not 条件只能包含一个子条件")
            return self

        if self.conditions:
            raise ValueError("比较条件不能包含 conditions")
        if self.field is None or not self.field:
            raise ValueError("比较条件必须设置 field")

        if self.op in {"exists", "is_null"}:
            if self.value is not None:
                raise ValueError(f"{self.op} 条件不应设置 value")
            return self

        if "value" not in fields:
            raise ValueError(f"{self.op} 条件必须设置 value")

        if self.op in {"in", "not_in"} and not isinstance(self.value, list):
            raise ValueError(f"{self.op} 条件的 value 必须是数组")
        if self.op in {"gt", "gte", "lt", "lte"}:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError(f"{self.op} 条件的 value 必须是数字")
        return self


class Effect(StrictModel):
    op: EffectOp
    name: str | None = Field(default=None, pattern=ATTRIBUTE_PATTERN)
    value: Any = None
    by: float = Field(default=1.0, ge=-1_000_000, le=1_000_000)

    @model_validator(mode="after")
    def _validate_shape(self) -> "Effect":
        fields = self.model_fields_set
        if self.op == "set_status":
            if self.name is not None:
                raise ValueError("set_status 不应设置 name")
            if self.value is None or not isinstance(self.value, str):
                raise ValueError("set_status 必须设置字符串 value")
            return self

        if self.op in {"set_attribute", "increment_counter", "set_state"}:
            if self.name is None:
                raise ValueError(f"{self.op} 必须设置 name")

        if self.op == "set_attribute":
            if "value" not in fields:
                raise ValueError("set_attribute 必须设置 value")
        elif self.op == "increment_counter":
            if self.value is not None:
                raise ValueError("increment_counter 不应设置 value")
        elif self.op == "set_state":
            if self.name not in {"currently_failed", "current_status"}:
                raise ValueError(
                    "set_state 的 name 只能是 currently_failed 或 current_status"
                )
            if "value" not in fields:
                raise ValueError("set_state 必须设置 value")
            if self.name == "currently_failed" and not isinstance(self.value, bool):
                raise ValueError("currently_failed 必须是布尔值")
            if self.name == "current_status" and not isinstance(self.value, str):
                raise ValueError("current_status 必须是字符串")
        return self


class NodeOutcome(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    weight: float = Field(gt=0)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def _validate_attribute_names(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if not re.fullmatch(ATTRIBUTE_PATTERN, key):
                raise ValueError(f"非法属性名: {key}")
        return value


class NodePosition(StrictModel):
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)


class ProcessNode(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: NodeType
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    position: NodePosition | None = None
    duration: float | None = Field(default=None, ge=0)
    status_on_enter: str | None = Field(default=None, pattern=ID_PATTERN)
    status_on_complete: str | None = Field(default=None, pattern=ID_PATTERN)
    on_enter: list[Effect] = Field(default_factory=list)
    on_complete: list[Effect] = Field(default_factory=list)
    outcomes: list[NodeOutcome] = Field(default_factory=list)
    subflow: "ProcessSubflow | None" = None

    @model_validator(mode="after")
    def _validate_subflow_shape(self) -> "ProcessNode":
        if self.type == "subprocess":
            if self.subflow is None:
                raise ValueError("subprocess 节点必须包含 subflow")
            if self.duration is not None:
                raise ValueError("subprocess 节点不能设置 duration")
            if self.outcomes:
                raise ValueError("subprocess 节点不能设置 outcomes")
        elif self.subflow is not None:
            raise ValueError("只有 subprocess 节点可以设置 subflow")
        return self


class ProcessEdge(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)

    id: str = Field(pattern=ID_PATTERN)
    source: str = Field(alias="from", pattern=ID_PATTERN)
    target: str = Field(alias="to", pattern=ID_PATTERN)
    kind: EdgeKind = "normal"
    label: str = Field(default="", max_length=200)
    priority: int = Field(default=0, ge=-1000, le=1000)
    condition: Condition | None = None
    subflow_exit: str | None = Field(default=None, pattern=ID_PATTERN)


class ProcessGuards(StrictModel):
    max_node_visits: int = Field(default=10000, ge=1, le=1_000_000)


class ProcessSubflow(StrictModel):
    start_node_id: str = Field(default="", max_length=64)
    end_node_ids: list[str] = Field(default_factory=list)
    nodes: list[ProcessNode] = Field(default_factory=list)
    edges: list[ProcessEdge] = Field(default_factory=list)
    guards: ProcessGuards = Field(default_factory=ProcessGuards)


class ProcessSpec(StrictModel):
    schema_version: Literal["process-ir/1.0", "process-ir/1.1"] = SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status_catalog: list[StatusDefinition] = Field(default_factory=list)
    start_node_id: str = Field(default="", max_length=64)
    end_node_ids: list[str] = Field(default_factory=list)
    nodes: list[ProcessNode] = Field(default_factory=list)
    edges: list[ProcessEdge] = Field(default_factory=list)
    guards: ProcessGuards = Field(default_factory=ProcessGuards)


class ProcessDocument(ProcessSpec):
    process_id: str = Field(pattern=PROCESS_ID_PATTERN)
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    created_at: datetime


Condition.model_rebuild()
ProcessNode.model_rebuild()
ProcessSubflow.model_rebuild()


def is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
