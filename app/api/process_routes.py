"""Process IR HTTP API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field

from app.agent.domain_rules import validate_process_with_domain
from app.api.deps import get_process_store
from app.diagram.svg import render_process_svg
from app.domain.process_ir import ProcessDocument, ProcessSpec, StrictModel
from app.domain.validation import ValidationResult
from app.domain.versioning import compute_content_hash
from app.processes.store import (
    ProcessNotFound,
    ProcessStore,
    VersionConflict,
)

router = APIRouter(prefix="/api/processes", tags=["processes"])


class ProcessUpdateRequest(StrictModel):
    base_version: int = Field(ge=1)
    process: ProcessSpec


def _document_payload(document: ProcessDocument) -> dict[str, Any]:
    return document.model_dump(mode="json", by_alias=True)


def _invalid_detail(result: ValidationResult) -> dict[str, Any]:
    return {
        "valid": False,
        "content_hash": result.content_hash,
        "issues": [issue.model_dump(mode="json") for issue in result.issues],
    }


def _ensure_valid(spec: ProcessSpec) -> ValidationResult:
    result = validate_process_with_domain(spec)
    if not result.valid:
        raise HTTPException(status_code=400, detail=_invalid_detail(result))
    return result


@router.post("/validate")
def validate_process_spec(spec: ProcessSpec) -> ValidationResult:
    return validate_process_with_domain(spec)


@router.post("/preview.svg")
def preview_diagram(spec: ProcessSpec) -> Response:
    content_hash = compute_content_hash(spec)
    svg = render_process_svg(spec, content_hash=content_hash)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "X-Content-Hash": content_hash,
            "Cache-Control": "no-store",
        },
    )


@router.get("")
def list_processes(
    store: ProcessStore = Depends(get_process_store),
) -> dict[str, Any]:
    return {"processes": store.list_processes()}


@router.post("", status_code=201)
def create_process(
    spec: ProcessSpec,
    store: ProcessStore = Depends(get_process_store),
) -> dict[str, Any]:
    result = _ensure_valid(spec)
    document = store.create(spec)
    return {
        "process": _document_payload(document),
        "created": True,
        "warnings": [
            issue.model_dump(mode="json") for issue in result.warnings
        ],
    }


@router.get("/{process_id}")
def get_process(
    process_id: str,
    version: int | None = None,
    store: ProcessStore = Depends(get_process_store),
) -> dict[str, Any]:
    document = store.get(process_id, version)
    return {"process": _document_payload(document)}


@router.put("/{process_id}")
def update_process(
    process_id: str,
    body: ProcessUpdateRequest,
    store: ProcessStore = Depends(get_process_store),
) -> dict[str, Any]:
    result = _ensure_valid(body.process)
    document, created = store.update(process_id, body.process, body.base_version)
    return {
        "process": _document_payload(document),
        "created": created,
        "warnings": [
            issue.model_dump(mode="json") for issue in result.warnings
        ],
    }


@router.get("/{process_id}/versions")
def list_versions(
    process_id: str,
    store: ProcessStore = Depends(get_process_store),
) -> dict[str, Any]:
    return {"versions": store.version_summaries(process_id)}


@router.get("/{process_id}/diagram.svg")
def process_diagram(
    process_id: str,
    request: Request,
    version: int | None = None,
    store: ProcessStore = Depends(get_process_store),
) -> Response:
    document = store.get(process_id, version)
    svg = render_process_svg(
        document,
        version=document.version,
        content_hash=document.content_hash,
    )
    etag = f'"{document.content_hash}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "ETag": etag,
            "Cache-Control": "no-cache",
            "X-Content-Hash": document.content_hash,
        },
    )


__all__ = [
    "ProcessNotFound",
    "VersionConflict",
    "router",
]
