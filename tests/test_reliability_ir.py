from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.process_ir import ProcessSpec
from app.domain.reliability_ir import (
    ReliabilityDocument,
    ReliabilityNodeConfig,
    ReliabilitySpec,
)
from tests.helpers import document_from_spec, minimal_process_dict


def _hash() -> str:
    return "sha256:" + "a" * 64


def _config(**overrides):
    data = {"node_id": "work", "participates": True, "lambda": 0.02}
    data.update(overrides)
    return ReliabilityNodeConfig.model_validate(data)


def test_reliability_node_schema_defaults_to_exponential_per_day() -> None:
    config = _config()
    payload = config.model_dump(mode="json", by_alias=True)
    assert payload == {
        "node_id": "work",
        "module_type": "activity",
        "participates": True,
        "distribution": "exponential",
        "lambda": 0.02,
        "lambda_unit": "per_day",
        "detection_rate": None,
        "test_time": None,
        "stage_task_id": None,
    }


def test_participating_node_requires_lambda() -> None:
    with pytest.raises(ValidationError):
        ReliabilityNodeConfig.model_validate(
            {"node_id": "work", "participates": True}
        )


def test_non_participating_node_does_not_require_lambda() -> None:
    config = ReliabilityNodeConfig.model_validate(
        {"node_id": "work", "participates": False}
    )
    assert config.lambda_per_day is None


def test_non_participating_node_may_retain_lambda() -> None:
    config = ReliabilityNodeConfig.model_validate(
        {"node_id": "work", "participates": False, "lambda": 0.3}
    )
    assert config.lambda_per_day == 0.3


def test_zero_lambda_is_valid() -> None:
    assert _config(**{"lambda": 0}).lambda_per_day == 0.0


@pytest.mark.parametrize("value", [-1, -0.0001])
def test_negative_lambda_is_invalid(value: float) -> None:
    with pytest.raises(ValidationError):
        _config(**{"lambda": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_lambda_is_invalid(value: float) -> None:
    with pytest.raises(ValidationError):
        _config(**{"lambda": value})


def test_boolean_lambda_is_invalid() -> None:
    with pytest.raises(ValidationError):
        _config(**{"lambda": True})


def test_only_exponential_distribution_is_supported() -> None:
    with pytest.raises(ValidationError):
        _config(distribution="weibull")


def test_supported_lambda_units_are_validated() -> None:
    for unit in ("per_hour", "per_day", "per_month", "per_year"):
        assert _config(lambda_unit=unit).lambda_unit == unit
    with pytest.raises(ValidationError):
        _config(lambda_unit="per_second")


def test_unknown_reliability_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _config(duration=2.0)


def test_duplicate_node_config_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReliabilitySpec.model_validate(
            {
                "process_version": 1,
                "process_hash": _hash(),
                "nodes": [
                    {"node_id": "work", "participates": False},
                    {"node_id": "work", "participates": True, "lambda": 0.1},
                ],
            }
        )


def test_reliability_document_requires_process_binding() -> None:
    document = ReliabilityDocument.model_validate(
        {
            "process_id": "proc_000000000000",
            "process_version": 3,
            "process_hash": _hash(),
            "reliability_id": "rel_000000000000",
            "revision": 2,
            "nodes": [{"node_id": "work", "participates": False}],
            "created_at": "2026-11-20T00:00:00Z",
        }
    )
    assert document.process_version == 3
    assert document.process_hash == _hash()


def test_process_and_reliability_fields_are_isolated() -> None:
    process_dict = minimal_process_dict()
    process_dict["nodes"][1]["participates"] = True
    with pytest.raises(ValidationError):
        ProcessSpec.model_validate(process_dict)

    process = ProcessSpec.model_validate(minimal_process_dict())
    dumped = process.model_dump(mode="json")
    serialized = str(dumped)
    assert "participates" not in serialized
    assert "lambda" not in serialized
    assert "distribution" not in serialized


def test_document_helper_binds_hash_to_process_content() -> None:
    document = document_from_spec()
    assert document.content_hash.startswith("sha256:")
    config_spec = ReliabilitySpec.model_validate(
        {
            "process_version": document.version,
            "process_hash": document.content_hash,
            "nodes": [{"node_id": "work", "participates": False}],
        }
    )
    assert config_spec.process_hash == document.content_hash
