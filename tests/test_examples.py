from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.process_ir import ProcessSpec
from app.domain.validation import validate_process

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize(
    "filename",
    [
        "equipment_support_flow.json",
        "manufacturing_flow.json",
        "reliability_maintenance_flow.json",
    ],
)
def test_example_flows_are_valid(filename: str) -> None:
    data = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    spec = ProcessSpec.model_validate(data)
    result = validate_process(spec)
    assert result.valid is True, [issue.model_dump() for issue in result.errors]
