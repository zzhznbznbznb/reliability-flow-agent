"""JSON Schema endpoints used by Pi extension tools.

These are read-only descriptions of the existing Pydantic models. They do not
create a second schema source and do not change IR semantics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.domain.process_ir import ProcessSpec
from app.domain.reliability_ir import ReliabilitySpec

router = APIRouter(prefix="/api/schemas", tags=["schemas"])


@router.get("/process-ir")
def process_ir_schema() -> dict[str, Any]:
    return ProcessSpec.model_json_schema()


@router.get("/reliability-ir")
def reliability_ir_schema() -> dict[str, Any]:
    return ReliabilitySpec.model_json_schema()


__all__ = ["router"]
