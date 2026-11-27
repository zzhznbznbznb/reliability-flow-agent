"""JSON-backed experiment result storage.

An experiment is one real Runtime + Evaluation run. It stores the exact
Process IR version/hash, Reliability revision/hash, simulation inputs and both
result artifacts so a result can be reopened later without recomputing it.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from app.domain.process_ir import ProcessDocument, StrictModel
from app.domain.reliability_ir import ReliabilityDocument
from app.evaluation.models import (
    EvaluationResult,
    EvaluationTargets,
)
from app.simulation.config import ProjectParameters, SimulationConfig
from app.simulation.models import SimulationResult

EXPERIMENT_SCHEMA_VERSION = "experiment/1.0"
RESULT_ID_PATTERN = r"^exp_[a-f0-9]{12}$"


class ExperimentNotFound(Exception):
    def __init__(self, result_id: str) -> None:
        super().__init__(f"实验结果不存在: {result_id}")
        self.result_id = result_id


class ExperimentRecord(StrictModel):
    schema_version: Literal["experiment/1.0"] = EXPERIMENT_SCHEMA_VERSION
    result_id: str = Field(pattern=RESULT_ID_PATTERN)
    created_at: datetime
    process_id: str
    process_version: int = Field(ge=1)
    process_hash: str
    process_name: str
    reliability_id: str
    reliability_revision: int = Field(ge=1)
    reliability_hash: str
    simulation_config: dict[str, Any]
    project: ProjectParameters | None = None
    evaluation_targets: dict[str, Any] | None = None
    simulation: SimulationResult
    evaluation: EvaluationResult
    explanation: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, result_id: str) -> Path:
        if not re.fullmatch(RESULT_ID_PATTERN, result_id):
            raise ExperimentNotFound(result_id)
        return self.root / f"{result_id}.json"

    def save(
        self,
        *,
        process: ProcessDocument,
        reliability: ReliabilityDocument,
        simulation_config: SimulationConfig,
        evaluation_targets: EvaluationTargets | None,
        simulation: SimulationResult,
        evaluation: EvaluationResult,
        explanation: str,
    ) -> ExperimentRecord:
        with self._lock:
            result_id = f"exp_{uuid.uuid4().hex[:12]}"
            record = ExperimentRecord.model_validate(
                {
                    "result_id": result_id,
                    "created_at": _utc_now(),
                    "process_id": process.process_id,
                    "process_version": process.version,
                    "process_hash": process.content_hash,
                    "process_name": process.name,
                    "reliability_id": reliability.reliability_id,
                    "reliability_revision": reliability.revision,
                    "reliability_hash": evaluation.reliability_binding.hash,
                    "simulation_config": simulation_config.model_dump(
                        mode="json", by_alias=True
                    ),
                    "project": (
                        simulation_config.project.model_dump(
                            mode="json", by_alias=True
                        )
                        if simulation_config.project is not None
                        else None
                    ),
                    "evaluation_targets": (
                        evaluation_targets.model_dump(mode="json", by_alias=True)
                        if evaluation_targets is not None
                        else None
                    ),
                    "simulation": simulation.model_dump(mode="json", by_alias=True),
                    "evaluation": evaluation.model_dump(mode="json", by_alias=True),
                    "explanation": explanation,
                }
            )
            self._write(record)
            return record

    def _write(self, record: ExperimentRecord) -> None:
        path = self._path(record.result_id)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        payload = json.dumps(
            record.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def get(self, result_id: str) -> ExperimentRecord:
        with self._lock:
            path = self._path(result_id)
            if not path.is_file():
                raise ExperimentNotFound(result_id)
            return ExperimentRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            )

    def list_summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            summaries: list[dict[str, Any]] = []
            for path in sorted(self.root.glob("exp_*.json")):
                if not path.is_file():
                    continue
                try:
                    record = ExperimentRecord.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                except Exception:
                    continue
                overall = record.evaluation.overall
                summaries.append(
                    {
                        "result_id": record.result_id,
                        "created_at": record.created_at.isoformat(),
                        "process_id": record.process_id,
                        "process_name": record.process_name,
                        "project_name": (
                            record.project.name
                            if record.project is not None
                            else None
                        ),
                        "process_version": record.process_version,
                        "process_hash": record.process_hash,
                        "reliability_revision": record.reliability_revision,
                        "entity_count": record.simulation.entity_count,
                        "simulation_start": record.simulation.simulation_start,
                        "simulation_end": record.simulation.simulation_end,
                        "simulation_duration": record.simulation.simulation_duration,
                        "simulation_unit": record.simulation.simulation_unit,
                        "simulation_total_time": (
                            record.project.simulation_total_time
                            if record.project is not None
                            else None
                        ),
                        "random_seed": record.simulation.random_seed,
                        "target_status": record.evaluation.target_status,
                        "overall_reliability": overall.overall_reliability,
                        "end_availability": overall.end_availability,
                    }
                )
            summaries.sort(key=lambda item: item["created_at"], reverse=True)
            return summaries


__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "ExperimentNotFound",
    "ExperimentRecord",
    "ExperimentStore",
    "RESULT_ID_PATTERN",
]
