from __future__ import annotations

from app.domain.reliability_ir import ReliabilityNodeConfig, ReliabilitySpec
from app.domain.reliability_validation import validate_reliability
from tests.helpers import document_from_spec, issue_codes, loop_process_dict, spec_from


def _spec(process, nodes, *, version=None, content_hash=None) -> ReliabilitySpec:
    return ReliabilitySpec.model_validate(
        {
            "process_version": version or process.version,
            "process_hash": content_hash or process.content_hash,
            "nodes": nodes,
        }
    )


def test_valid_reliability_configuration() -> None:
    process = document_from_spec()
    spec = _spec(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.05}],
    )
    result = validate_reliability(process, spec)
    assert result.valid is True
    assert result.participant_count == 1
    assert result.issues == []


def test_non_participating_task_is_valid_without_lambda() -> None:
    process = document_from_spec()
    spec = _spec(process, [{"node_id": "work", "participates": False}])
    result = validate_reliability(process, spec)
    assert result.valid is True
    assert result.participant_count == 0


def test_missing_task_configuration_is_an_error() -> None:
    process = document_from_spec()
    spec = _spec(process, [])
    result = validate_reliability(process, spec)
    assert result.valid is False
    assert "reliability_missing_config" in issue_codes(result.issues)


def test_unknown_node_configuration_is_an_error() -> None:
    process = document_from_spec()
    spec = _spec(
        process,
        [
            {"node_id": "work", "participates": False},
            {"node_id": "deleted_task", "participates": False},
        ],
    )
    result = validate_reliability(process, spec)
    assert result.valid is False
    assert "reliability_unknown_node" in issue_codes(result.issues)


def test_non_task_node_cannot_participate() -> None:
    process = document_from_spec()
    for node_id in ("start", "end"):
        spec = _spec(
            process,
            [
                {"node_id": "work", "participates": False},
                {"node_id": node_id, "participates": True, "lambda": 0.1},
            ],
        )
        result = validate_reliability(process, spec)
        assert result.valid is False
        assert "reliability_invalid_node_type" in issue_codes(result.issues)


def test_process_version_and_hash_mismatch_are_errors() -> None:
    process = document_from_spec()
    spec = _spec(
        process,
        [{"node_id": "work", "participates": False}],
        version=2,
        content_hash="sha256:" + "b" * 64,
    )
    result = validate_reliability(process, spec)
    assert result.valid is False
    assert {
        "reliability_process_version_mismatch",
        "reliability_process_hash_mismatch",
    } <= issue_codes(result.issues)


def test_missing_lambda_is_caught_even_if_schema_is_bypassed() -> None:
    process = document_from_spec()
    broken = ReliabilityNodeConfig.model_construct(
        node_id="work",
        participates=True,
        distribution="exponential",
        lambda_per_day=None,
        lambda_unit="per_day",
    )
    spec = ReliabilitySpec.model_construct(
        schema_version="reliability-ir/1.0",
        process_version=process.version,
        process_hash=process.content_hash,
        nodes=[broken],
    )
    result = validate_reliability(process, spec)
    assert result.valid is False
    assert "reliability_missing_lambda" in issue_codes(result.issues)


def test_invalid_lambda_is_caught_even_if_schema_is_bypassed() -> None:
    process = document_from_spec()
    broken = ReliabilityNodeConfig.model_construct(
        node_id="work",
        participates=True,
        distribution="exponential",
        lambda_per_day=-1.0,
        lambda_unit="per_day",
    )
    spec = ReliabilitySpec.model_construct(
        schema_version="reliability-ir/1.0",
        process_version=process.version,
        process_hash=process.content_hash,
        nodes=[broken],
    )
    result = validate_reliability(process, spec)
    assert result.valid is False
    assert "reliability_invalid_lambda" in issue_codes(result.issues)


def test_added_and_deleted_nodes_break_configuration_consistency() -> None:
    process = document_from_spec(spec_from(loop_process_dict()))
    stale_nodes = [
        {"node_id": "prepare", "participates": False},
        {"node_id": "removed_task", "participates": False},
    ]
    result = validate_reliability(process, _spec(process, stale_nodes))
    codes = issue_codes(result.issues)
    assert "reliability_unknown_node" in codes
    assert "reliability_missing_config" in codes
