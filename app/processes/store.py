"""JSON-backed, versioned Process IR storage."""

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
    ProcessSpec,
    StrictModel,
)
from app.domain.versioning import compute_content_hash

STORE_SCHEMA_VERSION = "process-store/1.0"


class ProcessStoreError(Exception):
    """Base error for process storage."""


class ProcessNotFound(ProcessStoreError):
    def __init__(self, process_id: str) -> None:
        super().__init__(f"流程不存在: {process_id}")
        self.process_id = process_id


class ProcessVersionNotFound(ProcessNotFound):
    def __init__(self, process_id: str, version: int) -> None:
        super().__init__(f"流程 {process_id} 不存在版本 {version}")
        self.version = version


class VersionConflict(ProcessStoreError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"版本冲突: 基于版本 {expected}，当前最新版本为 {actual}")
        self.expected = expected
        self.actual = actual


class ProcessStoreFile(StrictModel):
    store_schema_version: Literal["process-store/1.0"] = STORE_SCHEMA_VERSION
    process_id: str = Field(pattern=PROCESS_ID_PATTERN)
    versions: list[ProcessDocument] = Field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iter_nodes(nodes):
    for node in nodes:
        yield node
        if node.subflow is not None:
            yield from _iter_nodes(node.subflow.nodes)


def _iter_edges(edges, nodes):
    yield from edges
    for node in nodes:
        if node.subflow is not None:
            yield from _iter_edges(node.subflow.edges, node.subflow.nodes)


def _scope_counts(document: ProcessDocument) -> dict[str, int]:
    nodes = list(_iter_nodes(document.nodes))
    edges = list(_iter_edges(document.edges, document.nodes))
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "top_level_node_count": len(document.nodes),
        "top_level_edge_count": len(document.edges),
        "subprocess_count": sum(
            1 for node in nodes if node.type == "subprocess"
        ),
    }


class ProcessStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, process_id: str) -> Path:
        if not re.fullmatch(PROCESS_ID_PATTERN, process_id):
            raise ProcessNotFound(process_id)
        return self.root / f"{process_id}.json"

    def _read(self, process_id: str) -> ProcessStoreFile:
        path = self._path(process_id)
        if not path.is_file():
            raise ProcessNotFound(process_id)
        store_file = ProcessStoreFile.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if store_file.process_id != process_id:
            raise ProcessStoreError("流程文件内容与文件名不一致")
        if not store_file.versions:
            raise ProcessStoreError("流程文件不包含任何版本")
        return store_file

    def _write(self, store_file: ProcessStoreFile) -> None:
        path = self._path(store_file.process_id)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        payload = json.dumps(
            store_file.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def create(self, spec: ProcessSpec) -> ProcessDocument:
        with self._lock:
            process_id = f"proc_{uuid.uuid4().hex[:12]}"
            document = ProcessDocument.model_validate(
                {
                    **spec.model_dump(mode="python", by_alias=True),
                    "process_id": process_id,
                    "version": 1,
                    "content_hash": compute_content_hash(spec),
                    "created_at": _utc_now(),
                }
            )
            self._write(
                ProcessStoreFile(process_id=process_id, versions=[document])
            )
            return document

    def update(
        self, process_id: str, spec: ProcessSpec, base_version: int
    ) -> tuple[ProcessDocument, bool]:
        with self._lock:
            store_file = self._read(process_id)
            latest = store_file.versions[-1]
            if latest.version != base_version:
                raise VersionConflict(base_version, latest.version)
            content_hash = compute_content_hash(spec)
            if content_hash == latest.content_hash:
                return latest, False

            document = ProcessDocument.model_validate(
                {
                    **spec.model_dump(mode="python", by_alias=True),
                    "process_id": process_id,
                    "version": latest.version + 1,
                    "content_hash": content_hash,
                    "created_at": _utc_now(),
                }
            )
            store_file.versions.append(document)
            self._write(store_file)
            return document, True

    def get(self, process_id: str, version: int | None = None) -> ProcessDocument:
        with self._lock:
            store_file = self._read(process_id)
            if version is None:
                return store_file.versions[-1]
            for document in store_file.versions:
                if document.version == version:
                    return document
            raise ProcessVersionNotFound(process_id, version)

    def version_summaries(self, process_id: str) -> list[dict[str, Any]]:
        with self._lock:
            store_file = self._read(process_id)
            summaries = [
                {
                    "version": document.version,
                    "content_hash": document.content_hash,
                    "created_at": document.created_at.isoformat(),
                    "name": document.name,
                    **_scope_counts(document),
                }
                for document in store_file.versions
            ]
            summaries.sort(key=lambda item: item["version"], reverse=True)
            return summaries

    def list_processes(self) -> list[dict[str, Any]]:
        with self._lock:
            summaries: list[dict[str, Any]] = []
            for path in sorted(self.root.glob("proc_*.json")):
                if not path.is_file():
                    continue
                process_id = path.stem
                store_file = self._read(process_id)
                latest = store_file.versions[-1]
                summaries.append(
                    {
                        "process_id": process_id,
                        "name": latest.name,
                        "latest_version": latest.version,
                        "content_hash": latest.content_hash,
                        "created_at": latest.created_at.isoformat(),
                        **_scope_counts(latest),
                        "version_count": len(store_file.versions),
                    }
                )
            summaries.sort(
                key=lambda item: (item["created_at"], item["process_id"]),
                reverse=True,
            )
            return summaries
