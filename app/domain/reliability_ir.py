"""Reliability IR schema.

Reliability IR is stored and validated independently from Process IR. It only
describes node-level reliability configuration and is bound to an exact Process
IR version through process_id, process_version and process_hash.

The first version supports the exponential distribution only:

    R(t) = exp(-lambda * t)

where lambda is the failure rate per natural day and t is exposure time in
natural days. The user configures lambda only; R is derived, never stored.
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

RELIABILITY_SCHEMA_VERSION = "reliability-ir/1.0"
RELIABILITY_ID_PATTERN = r"^rel_[a-f0-9]{12}$"
LAMBDA_UNIT = "per_day"

Distribution = Literal["exponential"]
LambdaUnit = Literal["per_day"]


class ReliabilityNodeConfig(StrictModel):
    """Reliability configuration for one task node.

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
    participates: bool = False
    distribution: Distribution = "exponential"
    lambda_per_day: float | None = Field(default=None, alias="lambda", ge=0)
    lambda_unit: LambdaUnit = LAMBDA_UNIT

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

    @model_validator(mode="after")
    def _require_lambda_when_participating(self) -> "ReliabilityNodeConfig":
        if self.participates and self.lambda_per_day is None:
            raise ValueError("参与可靠性计算的节点必须填写 lambda")
        return self


class ReliabilitySpec(StrictModel):
    """Independent reliability payload bound to a Process IR version."""

    schema_version: Literal["reliability-ir/1.0"] = RELIABILITY_SCHEMA_VERSION
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
    "RELIABILITY_ID_PATTERN",
    "RELIABILITY_SCHEMA_VERSION",
    "ReliabilityDocument",
    "ReliabilityNodeConfig",
    "ReliabilitySpec",
]
