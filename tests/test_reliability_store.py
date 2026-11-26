from __future__ import annotations

import json

from app.domain.reliability_ir import ReliabilitySpec
from app.reliability.store import ReliabilityStore
from tests.helpers import document_from_spec


def _spec(process, nodes) -> ReliabilitySpec:
    return ReliabilitySpec.model_validate(
        {
            "process_version": process.version,
            "process_hash": process.content_hash,
            "nodes": nodes,
        }
    )


def test_save_and_load_reliability_revision(tmp_path) -> None:
    process = document_from_spec()
    store = ReliabilityStore(tmp_path / "reliability")
    spec = _spec(
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.02}],
    )

    document, created = store.save(process, spec)
    assert created is True
    assert document.process_id == process.process_id
    assert document.process_version == process.version
    assert document.process_hash == process.content_hash
    assert document.revision == 1

    loaded = store.get(process.process_id, process.version, process.content_hash)
    assert loaded is not None
    assert loaded.reliability_id == document.reliability_id
    assert loaded.nodes[0].lambda_per_day == 0.02


def test_identical_save_does_not_create_a_revision(tmp_path) -> None:
    process = document_from_spec()
    store = ReliabilityStore(tmp_path / "reliability")
    spec = _spec(process, [{"node_id": "work", "participates": False}])

    first, created = store.save(process, spec)
    second, created_again = store.save(process, spec)
    assert created is True
    assert created_again is False
    assert first.reliability_id == second.reliability_id
    assert len(store.list_revisions(process.process_id)) == 1


def test_changed_configuration_creates_new_revision(tmp_path) -> None:
    process = document_from_spec()
    store = ReliabilityStore(tmp_path / "reliability")
    store.save(process, _spec(process, [{"node_id": "work", "participates": False}]))
    second, created = store.save(
        process,
        _spec(process, [{"node_id": "work", "participates": True, "lambda": 0}]),
    )
    assert created is True
    assert second.revision == 2
    assert [item.revision for item in store.list_revisions(process.process_id)] == [2, 1]


def test_new_process_version_does_not_reuse_old_binding(tmp_path) -> None:
    store = ReliabilityStore(tmp_path / "reliability")
    v1 = document_from_spec()
    store.save(v1, _spec(v1, [{"node_id": "work", "participates": False}]))

    v2 = document_from_spec(version=2, content_hash="sha256:" + "c" * 64)
    assert store.get(v2.process_id, v2.version, v2.content_hash) is None

    second, created = store.save(v2, _spec(v2, [{"node_id": "work", "participates": False}]))
    assert created is True
    assert second.revision == 2
    assert second.process_version == 2
    assert store.get(v1.process_id, 1, v1.content_hash).revision == 1


def test_reliability_file_is_separate_from_process_files(tmp_path) -> None:
    process = document_from_spec()
    root = tmp_path / "reliability"
    store = ReliabilityStore(root)
    store.save(process, _spec(process, [{"node_id": "work", "participates": False}]))
    files = list(root.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["store_schema_version"] == "reliability-store/1.0"
    assert payload["revisions"][0]["process_hash"] == process.content_hash
    assert "nodes" in payload["revisions"][0]
    assert "duration" not in payload["revisions"][0]
