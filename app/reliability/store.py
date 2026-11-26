"""JSON-backed, revisioned Reliability IR storage.

Reliability IR files are independent from Process IR files. Every revision is
bound to an exact process_id, process_version and process_hash. New Process IR
versions never inherit old Reliability IR revisions automatically.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from app.domain.process_ir import (
    PROCESS_ID_PATTERN,
    ProcessDocument,
    StrictModel,
)
from app.domain.reliability_ir import (
    ReliabilityDocument,
    ReliabilityNodeConfig,
    ReliabilitySpec,
)

RELIABILITY_STORE_SCHEMA_VERSION = "reliability-store/1.0"


class ReliabilityStoreError(Exception):
    """Base error for reliability storage."""


class ReliabilityStoreFile(StrictModel):
    store_schema_version: Literal["reliability-store/1.0"] = (
        RELIABILITY_STORE_SCHEMA_VERSION
    )
    process_id: str = Field(pattern=PROCESS_ID_PATTERN)
    revisions: list[ReliabilityDocument] = Field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _node_payload(nodes: list[ReliabilityNodeConfig]) -> list[dict[str, Any]]:
    return [
        node.model_dump(mode="json", by_alias=True, exclude_none=True)
        for node in nodes
    ]


class ReliabilityStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, process_id: str) -> Path:
        if not re.fullmatch(PROCESS_ID_PATTERN, process_id):
            raise ReliabilityStoreError(f"非法流程 ID: {process_id}")
        return self.root / f"{process_id}.reliability.json"

    def _read(self, process_id: str) -> ReliabilityStoreFile | None:
        path = self._path(process_id)
        if not path.is_file():
            return None
        store_file = ReliabilityStoreFile.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if store_file.process_id != process_id:
            raise ReliabilityStoreError("可靠性文件内容与文件名不一致")
        return store_file

    def _write(self, store_file: ReliabilityStoreFile) -> None:
        path = self._path(store_file.process_id)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        payload = json.dumps(
            store_file.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def save(
        self,
        process: ProcessDocument,
        spec: ReliabilitySpec,
    ) -> tuple[ReliabilityDocument, bool]:
        with self._lock:
            store_file = self._read(process.process_id)
            if store_file is None:
                store_file = ReliabilityStoreFile(process_id=process.process_id)

            for revision in reversed(store_file.revisions):
                if (
                    revision.process_version == process.version
                    and revision.process_hash == process.content_hash
                    and _node_payload(revision.nodes) == _node_payload(spec.nodes)
                ):
                    return revision, False

            next_revision = (
                max((revision.revision for revision in store_file.revisions), default=0)
                + 1
            )
            document = ReliabilityDocument.model_validate(
                {
                    **spec.model_dump(mode="python", by_alias=True),
                    "process_id": process.process_id,
                    "process_version": process.version,
                    "process_hash": process.content_hash,
                    "reliability_id": f"rel_{uuid.uuid4().hex[:12]}",
                    "revision": next_revision,
                    "created_at": _utc_now(),
                }
            )
            store_file.revisions.append(document)
            self._write(store_file)
            return document, True

    def get(
        self,
        process_id: str,
        process_version: int,
        process_hash: str,
    ) -> ReliabilityDocument | None:
        with self._lock:
            store_file = self._read(process_id)
            if store_file is None:
                return None
            matches = [
                revision
                for revision in store_file.revisions
                if revision.process_version == process_version
                and revision.process_hash == process_hash
            ]
            if not matches:
                return None
            return max(matches, key=lambda revision: revision.revision)

    def list_revisions(self, process_id: str) -> list[ReliabilityDocument]:
        with self._lock:
            store_file = self._read(process_id)
            if store_file is None:
                return []
            revisions = sorted(
                store_file.revisions,
                key=lambda revision: revision.revision,
                reverse=True,
            )
            return revisions


def revision_summary(document: ReliabilityDocument) -> dict[str, Any]:
    return {
        "reliability_id": document.reliability_id,
        "process_version": document.process_version,
        "process_hash": document.process_hash,
        "revision": document.revision,
        "created_at": document.created_at.isoformat(),
        "node_count": len(document.nodes),
        "participant_count": sum(
            1 for node in document.nodes if node.participates
        ),
    }


__all__ = [
    "RELIABILITY_STORE_SCHEMA_VERSION",
    "ReliabilityStore",
    "ReliabilityStoreError",
    "ReliabilityStoreFile",
    "revision_summary",
]
