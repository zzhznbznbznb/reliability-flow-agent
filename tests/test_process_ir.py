from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.domain.process_ir import Condition, ProcessSpec
from app.domain.versioning import compute_content_hash
from tests.helpers import minimal_process_dict, minimal_spec, spec_from


def test_minimal_spec_is_valid_at_schema_level() -> None:
    spec = minimal_spec()
    assert spec.schema_version == "process-ir/1.0"
    assert spec.start_node_id == "start"
    assert spec.nodes[1].duration == 1
    assert spec.edges[0].source == "start"
    assert spec.edges[0].target == "work"


def test_edge_alias_is_serialized_as_from_and_to() -> None:
    dumped = minimal_spec().model_dump(by_alias=True, mode="json")
    assert dumped["edges"][0]["from"] == "start"
    assert dumped["edges"][0]["to"] == "work"
    assert "source" not in dumped["edges"][0]


def test_reliability_fields_are_rejected_from_process_ir() -> None:
    data = minimal_process_dict()
    data["nodes"][1]["lambda"] = 0.02
    with pytest.raises(ValidationError):
        ProcessSpec.model_validate(data)

    data = minimal_process_dict()
    data["reliability"] = {"participates": True}
    with pytest.raises(ValidationError):
        ProcessSpec.model_validate(data)


def test_content_hash_is_independent_of_node_and_edge_order() -> None:
    first = minimal_process_dict()
    second = deepcopy(first)
    second["nodes"] = list(reversed(second["nodes"]))
    second["edges"] = list(reversed(second["edges"]))
    assert compute_content_hash(spec_from(first)) == compute_content_hash(spec_from(second))


def test_content_hash_changes_when_position_changes() -> None:
    first = minimal_process_dict()
    second = deepcopy(first)
    second["nodes"][1]["position"] = {"x": 400, "y": 120}
    assert compute_content_hash(spec_from(first)) != compute_content_hash(spec_from(second))


def test_condition_shape_is_strict() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate({"op": "and", "field": "attributes.x"})
    with pytest.raises(ValidationError):
        Condition.model_validate({"op": "in", "field": "attributes.x", "value": 1})
    with pytest.raises(ValidationError):
        Condition.model_validate({"op": "gt", "field": "attributes.x", "value": True})

    condition = Condition.model_validate(
        {"op": "eq", "field": "attributes.x", "value": True}
    )
    assert condition.field == "attributes.x"
