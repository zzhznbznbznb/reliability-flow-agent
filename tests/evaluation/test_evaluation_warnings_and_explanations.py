from __future__ import annotations

from app.evaluation.evaluator import compute_reliability_hash, evaluate_simulation
from app.evaluation.explanations import (
    build_explanation,
    explain_node,
    explain_warnings,
)
from tests.evaluation.helpers import (
    STATUS_CATALOG,
    completed_entity,
    entity,
    ev,
    make_process,
    make_reliability,
    make_result,
    sample,
)
from tests.helpers import reliability_document_from_process


def test_reliability_hash_normalizes_zero_and_null_forms() -> None:
    process = make_process(status_catalog=STATUS_CATALOG)
    zero_int = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0}],
    )
    zero_float = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.0}],
    )
    missing_lambda = reliability_document_from_process(
        process, [{"node_id": "work", "participates": False}]
    )
    null_lambda = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": False, "lambda": None}],
    )
    assert compute_reliability_hash(zero_int) == compute_reliability_hash(
        zero_float
    )
    assert compute_reliability_hash(missing_lambda) == compute_reliability_hash(
        null_lambda
    )
    assert compute_reliability_hash(zero_int) != compute_reliability_hash(
        missing_lambda
    )


def test_reliability_hash_ignores_record_identity_and_revision() -> None:
    process = make_process(status_catalog=STATUS_CATALOG)
    first = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.1}],
        revision=1,
        reliability_id="rel_000000000000",
    )
    second = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.1}],
        revision=9,
        reliability_id="rel_111111111111",
    )
    assert compute_reliability_hash(first) == compute_reliability_hash(second)
    assert compute_reliability_hash(first).startswith("sha256:")
    assert len(compute_reliability_hash(first)) == len("sha256:") + 64


def test_reliability_hash_changes_with_semantic_configuration() -> None:
    process = make_process(status_catalog=STATUS_CATALOG)
    first = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.1}],
    )
    second = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.2}],
    )
    third = reliability_document_from_process(
        process,
        [{"node_id": "work", "participates": False}],
    )
    assert compute_reliability_hash(first) != compute_reliability_hash(second)
    assert compute_reliability_hash(first) != compute_reliability_hash(third)


def test_binding_mismatch_and_entity_count_mismatch_warn() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    entity_one = completed_entity("e1", seq_base=0)
    result = make_result(
        process, reliability, [entity_one], [], entity_count=5
    )
    mutated_process = process.model_copy(
        update={"content_hash": "sha256:" + "a" * 64}
    )
    evaluation = evaluate_simulation(mutated_process, reliability, result)
    codes = {warning.code for warning in evaluation.warnings}
    assert "process_binding_mismatch" in codes
    assert "entity_count_mismatch" in codes


def test_event_sequence_anomaly_produces_warning_and_null_actual() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    broken = entity(
        "e1",
        status="operational",
        node_visits={"work": 1},
        history=[
            ev(0, 1, "node_completed", "e1", "work", {"elapsed": 1.0}),
        ],
    )
    samples = [sample("e1", lam=0.1, exposure=1.0)]
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [broken], samples),
    )
    node = evaluation.nodes[0]
    assert node.total_actual_elapsed_time is None
    assert node.actual_elapsed_complete is False
    assert "event_sequence_invalid" in {
        warning.code for warning in evaluation.warnings
    }
    assert "actual_elapsed_incomplete" in {
        warning.code for warning in evaluation.warnings
    }


def test_explanations_are_deterministic_and_respect_na() -> None:
    process = make_process(status_catalog=STATUS_CATALOG, status_on_enter="operational")
    reliability = make_reliability(process, lam=0.1)
    unknown = completed_entity("e1", seq_base=0, status=None)
    evaluation = evaluate_simulation(
        process,
        reliability,
        make_result(process, reliability, [unknown], []),
    )
    overall_text = build_explanation(evaluation)
    node_text = explain_node(evaluation, "work")
    assert "R_e" in overall_text
    assert "A_e" in overall_text
    assert "N/A" in overall_text
    assert "N/A" in node_text
    assert "联合" in node_text
    assert "因果" in overall_text
    assert build_explanation(evaluation) == overall_text
    warning_text = "\n".join(explain_warnings(evaluation))
    assert warning_text
    assert "未知" in warning_text or "状态" in warning_text
