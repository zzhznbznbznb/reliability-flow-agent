"""Canonical content hashing for Process IR versions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.domain.process_ir import ProcessSpec


def canonical_process_content(spec: ProcessSpec) -> dict[str, Any]:
    data = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    for key in ("process_id", "version", "content_hash", "created_at"):
        data.pop(key, None)

    if "status_catalog" in data:
        data["status_catalog"] = sorted(
            data["status_catalog"], key=lambda item: item.get("id", "")
        )
    data["nodes"] = sorted(data.get("nodes", []), key=lambda item: item.get("id", ""))
    data["edges"] = sorted(data.get("edges", []), key=lambda item: item.get("id", ""))
    data["end_node_ids"] = sorted(data.get("end_node_ids", []))
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
