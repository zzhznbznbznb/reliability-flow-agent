"""Canonical content hashing for Process IR versions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.domain.process_ir import ProcessSpec


def _canonical_scope(scope: dict[str, Any]) -> dict[str, Any]:
    scope["nodes"] = sorted(
        scope.get("nodes", []), key=lambda item: item.get("id", "")
    )
    scope["edges"] = sorted(
        scope.get("edges", []), key=lambda item: item.get("id", "")
    )
    scope["end_node_ids"] = sorted(scope.get("end_node_ids", []))
    for node in scope["nodes"]:
        subflow = node.get("subflow")
        if isinstance(subflow, dict):
            _canonical_scope(subflow)
    return scope


def canonical_process_content(spec: ProcessSpec) -> dict[str, Any]:
    data = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    for key in ("process_id", "version", "content_hash", "created_at"):
        data.pop(key, None)

    if "status_catalog" in data:
        data["status_catalog"] = sorted(
            data["status_catalog"], key=lambda item: item.get("id", "")
        )
    _canonical_scope(data)
    return data


def compute_content_hash(spec: ProcessSpec) -> str:
    canonical = canonical_process_content(spec)
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def short_hash(content_hash: str) -> str:
    return content_hash.removeprefix("sha256:")[:12]
