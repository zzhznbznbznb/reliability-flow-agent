"""Reliability IR schema.

Reliability IR is stored and validated independently from Process IR. It only
describes node-level reliability configuration and is bound to an exact Process
IR version through process_id, process_version and process_hash.

The supported failure model is the exponential distribution:

    R(t) = exp(-lambda * t)

``lambda`` is expressed in the simulation time unit (hour/day/month/year). The
time axis of the runtime is expressed in the same unit for every node. The user
configures lambda only; R is derived, never stored.

A reliability configuration can describe three kinds of modules:

* ``activity``: legacy/ordinary task configuration. New models do not put a
  failure rate on ordinary tasks; they only carry their duration in Process IR.
* ``stage``: a nested subprocess that represents a storage or duty stage. The
  configured lambda is sampled on the stage's operating task.
* ``test``: a test/detection module. It carries a detection rate ``Ft`` and an
  optional test time. It never carries lambda.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.domain.process_ir import (
    CONTENT_HASH_PATTERN,
    ID_PATTERN,
    PROCESS_ID_PATTERN,
    StrictModel,
)

RELIABILITY_SCHEMA_VERSION = "reliability-ir/1.1"
RELIABILITY_ID_PATTERN = r"^rel_[a-f0-9]{12}$"
LAMBDA_UNIT = "per_day"

Distribution = Literal["exponential"]
LambdaUnit = Literal["per_hour", "per_day", "per_month", "per_year"]
ModuleType = Literal["activity", "stage", "test"]

LAMBDA_UNIT_LABELS: dict[str, str] = {
    "per_hour": "每小时",
    "per_day": "每天",
    "per_month": "每月",
    "per_year": "每年",
}


def lambda_unit_for_simulation_unit(simulation_unit: str) -> str:
    """Map a simulation unit to the matching lambda unit."""

    return {
        "hour": "per_hour",
        "day": "per_day",
        "month": "per_month",
        "year": "per_year",
    }.get(simulation_unit, "per_day")


class ReliabilityNodeConfig(StrictModel):
    """Reliability configuration for one task or stage node.

    ``participates=False`` means the node executes normally but is never sampled
    for random failures. A previously configured lambda may be retained on a
    non-participating node so that history is not silently discarded.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        allow_inf_nan=False,
    )

    node_id: str = Field(pattern=ID_PATTERN)
    module_type: ModuleType = "activity"
    participates: bool = False
    distribution: Distribution = "exponential"
    lambda_per_day: float | None = Field(
        default=None,
        alias="lambda",
        ge=0,
        description=(
            "Failure rate expressed in the configured lambda_unit. The field "
            "name is kept for backward compatibility; the unit is authoritative."
        ),
    )
    lambda_unit: LambdaUnit = LAMBDA_UNIT
    detection_rate: float | None = Field(default=None, ge=0, le=1)
    test_time: float | None = Field(default=None, gt=0)
    stage_task_id: str | None = Field(default=None, pattern=ID_PATTERN)

    @field_validator("lambda_per_day", mode="before")
    @classmethod
    def _validate_lambda(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("lambda 必须是数字")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("lambda 必须是有限数字")
        if numeric < 0:
            raise ValueError("lambda 必须大于或等于 0")
        return numeric

    @field_validator("detection_rate", mode="before")
    @classmethod
    def _validate_detection_rate(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("故障检测率 Ft 必须是数字")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("故障检测率 Ft 必须是有限数字")
        if numeric < 0 or numeric > 1:
            raise ValueError("故障检测率 Ft 必须在 0 到 1 之间")
        return numeric

    @field_validator("test_time", mode="before")
    @classmethod
    def _validate_test_time(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("测试时间必须是数字")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("测试时间必须是有限数字")
        if numeric <= 0:
            raise ValueError("测试时间必须大于 0")
        return numeric

    @model_validator(mode="after")
    def _require_lambda_when_participating(self) -> "ReliabilityNodeConfig":
        if self.module_type == "test":
            if self.lambda_per_day is not None:
                raise ValueError("测试模块不能配置故障率 lambda")
            if self.detection_rate is None:
                raise ValueError("测试模块必须配置故障检测率 Ft")
            if self.participates:
                raise ValueError("测试模块不参与独立的指数故障抽样")
            return self
        if self.module_type == "stage" and not self.participates:
            raise ValueError("阶段模块必须参与指数故障抽样")
        if self.participates and self.lambda_per_day is None:
            raise ValueError("参与可靠性计算的节点必须填写 lambda")
        return self


class ReliabilitySpec(StrictModel):
    """Independent reliability payload bound to a Process IR version."""

    schema_version: Literal["reliability-ir/1.0", "reliability-ir/1.1"] = (
        RELIABILITY_SCHEMA_VERSION
    )
    process_version: int = Field(ge=1)
    process_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    nodes: list[ReliabilityNodeConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_node_ids(self) -> "ReliabilitySpec":
        node_ids = [node.node_id for node in self.nodes]
        duplicates = sorted(
            {node_id for node_id in node_ids if node_ids.count(node_id) > 1}
        )
        if duplicates:
            raise ValueError(f"可靠性配置节点重复: {', '.join(duplicates)}")
        return self


class ReliabilityDocument(ReliabilitySpec):
    """Persisted Reliability IR revision."""

    process_id: str = Field(pattern=PROCESS_ID_PATTERN)
    reliability_id: str = Field(pattern=RELIABILITY_ID_PATTERN)
    revision: int = Field(ge=1)
    created_at: datetime


__all__ = [
    "LAMBDA_UNIT",
    "LAMBDA_UNIT_LABELS",
    "RELIABILITY_ID_PATTERN",
    "RELIABILITY_SCHEMA_VERSION",
    "LambdaUnit",
    "ModuleType",
    "ReliabilityDocument",
    "ReliabilityNodeConfig",
    "ReliabilitySpec",
    "lambda_unit_for_simulation_unit",
]
