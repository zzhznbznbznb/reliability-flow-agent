"""Backend-owned validation for Agent Process IR candidates.

The Pi extension calls the public validation endpoint, but the Agent host never
trusts the model or extension response. Every candidate is re-parsed and
re-validated here before it can become a canvas proposal.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.agent.domain_rules import validate_process_with_domain
from app.agent.requirements import CoverageResult, RequirementAnalysis
from app.domain.process_ir import ProcessSpec


def _schema_issues(error: ValidationError) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in error.errors():
        location = ".".join(str(part) for part in item.get("loc", ()))
        issues.append(
            {
                "severity": "error",
                "code": "schema_invalid",
                "message": f"{location}: {item.get('msg', '数据不合法')}",
                "node_id": None,
                "edge_id": None,
                "field": location or None,
            }
        )
    return issues


def validate_candidate(
    raw: Any,
) -> tuple[dict[str, Any], ProcessSpec | None]:
    if not isinstance(raw, dict):
        return (
            {
                "valid": False,
                "schema_valid": False,
                "content_hash": None,
                "issues": [
                    {
                        "severity": "error",
                        "code": "schema_invalid",
                        "message": "Process IR 候选必须是 JSON 对象",
                        "field": "spec",
                    }
                ],
            },
            None,
        )
    try:
        spec = ProcessSpec.model_validate(raw)
    except ValidationError as error:
        return (
            {
                "valid": False,
                "schema_valid": False,
                "content_hash": None,
                "issues": _schema_issues(error),
            },
            None,
        )

    result = validate_process_with_domain(spec)
    payload = result.model_dump(mode="json")
    payload["schema_valid"] = True
    return payload, spec


def apply_coverage(
    validation: dict[str, Any],
    analysis: RequirementAnalysis | None,
    spec: ProcessSpec | None,
) -> tuple[dict[str, Any], CoverageResult | None]:
    if analysis is None or spec is None:
        return validation, None

    from app.agent.requirements import evaluate_requirement_coverage

    coverage = evaluate_requirement_coverage(analysis, spec)
    issues = list(validation.get("issues") or [])
    issues.extend(issue.model_dump(mode="json") for issue in coverage.issues)
    merged = dict(validation)
    merged["issues"] = issues
    merged["coverage"] = coverage.model_dump(mode="json")
    if not coverage.covered:
        merged["valid"] = False
    return merged, coverage


__all__ = [
    "apply_coverage",
    "validate_candidate",
]
