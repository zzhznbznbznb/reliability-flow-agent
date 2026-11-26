"""Evaluation result data models.

N/A semantics are represented with ``None`` for optional numeric metrics. They
must never be replaced with invented zero values.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.domain.process_ir import StrictModel

EVALUATION_SCHEMA_VERSION = "evaluation/1.0"
DEFAULT_SMALL_SAMPLE_THRESHOLD = 30

TargetStatus = Literal[
    "achieved",
    "not_achieved",
    "unevaluable",
    "not_configured",
]
EndStateClassification = Literal["good", "bad", "unknown"]
WarningSeverity = Literal["info", "warning"]
WarningScope = Literal["system", "node", "entity", "experiment"]


class EvaluationConfig(StrictModel):
    small_sample_threshold: int = Field(
        default=DEFAULT_SMALL_SAMPLE_THRESHOLD, ge=1
    )


class EvaluationTargets(StrictModel):
    overall_reliability_min: float | None = Field(default=None, ge=0, le=1)
    end_availability_min: float | None = Field(default=None, ge=0, le=1)


class EvaluationWarning(StrictModel):
    code: str
    severity: WarningSeverity = "warning"
    scope: WarningScope
    message: str
    node_id: str | None = None
    entity_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ProcessBinding(StrictModel):
    process_id: str
    version: int = Field(ge=1)
    content_hash: str
    name: str


class ReliabilityBinding(StrictModel):
    reliability_id: str
    revision: int = Field(ge=1)
    hash: str
    process_version: int = Field(ge=1)
    process_hash: str


class PerEntityNodeMetrics(StrictModel):
    entity_id: str
    node_id: str
    planned_duration: float | None = None
    visit_count: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    actual_elapsed_time: float | None = Field(default=None, ge=0)
    actual_elapsed_complete: bool
    actual_elapsed_time_unit: Literal["day"] = "day"
    reliability_exposure_time: float = Field(ge=0)
    reliability_exposure_time_unit: Literal["day"] = "day"
    theoretical_reliability: float | None = Field(default=None, ge=0, le=1)


class NodeMetrics(StrictModel):
    node_id: str
    node_name: str
    lambda_per_day: float = Field(alias="lambda", ge=0)
    lambda_unit: Literal["per_day"] = "per_day"
    planned_duration: float | None = None
    visit_count: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    total_actual_elapsed_time: float | None = Field(default=None, ge=0)
    actual_elapsed_complete: bool
    actual_elapsed_time_unit: Literal["device_day"] = "device_day"
    total_reliability_exposure_time: float = Field(ge=0)
    reliability_exposure_time_unit: Literal["device_day"] = "device_day"
    unique_exposed_entity_count: int = Field(ge=0)
    node_is_small_sample: bool
    empirical_failure_frequency: float | None = Field(default=None, ge=0, le=1)
    mean_entity_theoretical_reliability: float | None = Field(
        default=None, ge=0, le=1
    )
    joint_theoretical_no_failure_probability: float | None = Field(
        default=None, ge=0, le=1
    )
    per_entity_metrics: list[PerEntityNodeMetrics] = Field(default_factory=list)

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        populate_by_name=True,
    )


class EntityMetrics(StrictModel):
    entity_id: str
    final_node_id: str
    final_status: str | None = None
    end_state_classification: EndStateClassification
    failure_count: int = Field(ge=0)
    repair_count: int = Field(ge=0)
    ever_failed: bool
    currently_failed: bool
    repair_in_progress: bool
    completed: bool
    stopped: bool
    stopped_reason: str | None = None
    node_metrics: list[PerEntityNodeMetrics] = Field(default_factory=list)


class OverallMetrics(StrictModel):
    entity_count: int = Field(ge=1)
    ever_failed_entity_count: int = Field(ge=0)
    overall_reliability: float = Field(ge=0, le=1)
    good_end_count: int = Field(ge=0)
    bad_end_count: int = Field(ge=0)
    unknown_end_count: int = Field(ge=0)
    availability_evaluable: bool
    end_availability: float | None = Field(default=None, ge=0, le=1)
    observed_good_end_fraction: float = Field(ge=0, le=1)
    total_failure_count: int = Field(ge=0)
    runtime_failure_counter_total: int = Field(ge=0)
    failure_counter_consistent: bool
    total_repair_count: int = Field(ge=0)
    repair_completed_count: int = Field(ge=0)
    repair_pending_count: int = Field(ge=0)
    repair_in_progress_count: int = Field(ge=0)
    currently_failed_entity_count: int = Field(ge=0)
    completed_entity_count: int = Field(ge=0)
    stopped_entity_count: int = Field(ge=0)
    unfinished_entity_count: int = Field(ge=0)
    mean_failure_count_per_entity: float = Field(ge=0)
    mean_repair_count_per_entity: float = Field(ge=0)
    status_distribution: dict[str, int] = Field(default_factory=dict)


class TargetResult(StrictModel):
    metric: Literal["overall_reliability", "end_availability"]
    configured: bool
    actual: float | None = None
    target: float | None = None
    met: bool | None = None
    gap: float | None = None
    status: TargetStatus
    reason: str | None = None


class EvaluationResult(StrictModel):
    schema_version: Literal["evaluation/1.0"] = EVALUATION_SCHEMA_VERSION
    process_binding: ProcessBinding
    reliability_binding: ReliabilityBinding
    sample_size: int = Field(ge=1)
    small_sample_threshold: int = Field(ge=1)
    is_small_sample: bool
    overall: OverallMetrics
    nodes: list[NodeMetrics] = Field(default_factory=list)
    entities: list[EntityMetrics] = Field(default_factory=list)
    targets: list[TargetResult] = Field(default_factory=list)
    target_status: TargetStatus
    warnings: list[EvaluationWarning] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


__all__ = [
    "DEFAULT_SMALL_SAMPLE_THRESHOLD",
    "EVALUATION_SCHEMA_VERSION",
    "EndStateClassification",
    "EntityMetrics",
    "EvaluationConfig",
    "EvaluationResult",
    "EvaluationTargets",
    "EvaluationWarning",
    "NodeMetrics",
    "OverallMetrics",
    "PerEntityNodeMetrics",
    "ProcessBinding",
    "ReliabilityBinding",
    "TargetResult",
    "TargetStatus",
]
