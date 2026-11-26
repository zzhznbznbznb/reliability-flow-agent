"""Reliability IR HTTP API.

Reliability configuration is always saved against the latest saved Process IR
version and its exact content hash. Older revisions remain readable for
historical experiments but never bind automatically to a new process version.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_process_store, get_reliability_store
from app.domain.process_ir import ProcessDocument
from app.domain.reliability_ir import (
    ReliabilityDocument,
    ReliabilitySpec,
)
from app.domain.reliability_validation import (
    ReliabilityValidationResult,
    validate_reliability,
)
from app.processes.store import ProcessStore
from app.reliability.store import (
    ReliabilityStore,
    revision_summary,
)

router = APIRouter(prefix="/api/processes", tags=["reliability"])


def _document_payload(document: ReliabilityDocument) -> dict[str, Any]:
    return document.model_dump(mode="json", by_alias=True, exclude_none=True)


def _validation_payload(result: ReliabilityValidationResult) -> dict[str, Any]:
    return {
        "valid": result.valid,
        "issues": [issue.model_dump(mode="json") for issue in result.issues],
        "process_id": result.process_id,
        "process_version": result.process_version,
        "process_hash": result.process_hash,
        "participant_count": result.participant_count,
    }


def _binding_conflict(
    process: ProcessDocument, spec: ReliabilitySpec
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "reliability_binding_conflict",
            "message": "可靠性配置只能保存到最新 Process IR 版本",
            "requested_version": spec.process_version,
            "requested_hash": spec.process_hash,
            "current_version": process.version,
            "current_hash": process.content_hash,
        },
    )


@router.post("/{process_id}/reliability/validate")
def validate_reliability_config(
    process_id: str,
    spec: ReliabilitySpec,
    process_store: ProcessStore = Depends(get_process_store),
) -> dict[str, Any]:
    document = process_store.get(process_id, spec.process_version)
    result = validate_reliability(document, spec)
    return _validation_payload(result)


@router.get("/{process_id}/reliability")
def get_reliability(
    process_id: str,
    version: int | None = None,
    process_store: ProcessStore = Depends(get_process_store),
    reliability_store: ReliabilityStore = Depends(get_reliability_store),
) -> dict[str, Any]:
    document = process_store.get(process_id, version)
    revision = reliability_store.get(
        process_id, document.version, document.content_hash
    )
    revisions = reliability_store.list_revisions(process_id)
    stale = [
        revision_summary(item)
        for item in revisions
        if item.process_version != document.version
        or item.process_hash != document.content_hash
    ]
    status = "bound" if revision is not None else ("stale" if revisions else "missing")
    return {
        "process": {
            "process_id": document.process_id,
            "version": document.version,
            "content_hash": document.content_hash,
        },
        "reliability": _document_payload(revision) if revision else None,
        "status": status,
        "stale_revisions": stale,
        "revision_count": len(revisions),
    }


@router.get("/{process_id}/reliability/history")
def list_reliability_history(
    process_id: str,
    process_store: ProcessStore = Depends(get_process_store),
    reliability_store: ReliabilityStore = Depends(get_reliability_store),
) -> dict[str, Any]:
    latest = process_store.get(process_id)
    revisions = reliability_store.list_revisions(process_id)
    return {
        "process_id": process_id,
        "current_process_version": latest.version,
        "current_process_hash": latest.content_hash,
        "revisions": [
            {
                **revision_summary(revision),
                "current": (
                    revision.process_version == latest.version
                    and revision.process_hash == latest.content_hash
                ),
            }
            for revision in revisions
        ],
    }


@router.put("/{process_id}/reliability")
def save_reliability(
    process_id: str,
    spec: ReliabilitySpec,
    process_store: ProcessStore = Depends(get_process_store),
    reliability_store: ReliabilityStore = Depends(get_reliability_store),
) -> dict[str, Any]:
    latest = process_store.get(process_id)
    if (
        spec.process_version != latest.version
        or spec.process_hash != latest.content_hash
    ):
        raise _binding_conflict(latest, spec)

    result = validate_reliability(latest, spec)
    if not result.valid:
        raise HTTPException(status_code=400, detail=_validation_payload(result))

    document, created = reliability_store.save(latest, spec)
    return {
        "reliability": _document_payload(document),
        "created": created,
        "validation": _validation_payload(result),
    }


__all__ = ["router"]
