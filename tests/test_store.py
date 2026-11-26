from __future__ import annotations

import pytest

from app.processes.store import (
    ProcessNotFound,
    ProcessStore,
    ProcessVersionNotFound,
    VersionConflict,
)
from tests.helpers import minimal_process_dict, spec_from


def test_create_update_and_history(tmp_path) -> None:
    store = ProcessStore(tmp_path)
    first = store.create(spec_from(minimal_process_dict()))
    assert first.version == 1
    assert first.process_id.startswith("proc_")

    updated_data = minimal_process_dict()
    updated_data["name"] = "修改后的流程"
    updated_data["nodes"][1]["position"] = {"x": 500, "y": 200}
    second, created = store.update(first.process_id, spec_from(updated_data), 1)
    assert created is True
    assert second.version == 2
    assert second.content_hash != first.content_hash

    original = store.get(first.process_id, 1)
    latest = store.get(first.process_id)
    assert original.name == "最小流程"
    assert latest.name == "修改后的流程"
    assert latest.version == 2

    summaries = store.version_summaries(first.process_id)
    assert [summary["version"] for summary in summaries] == [2, 1]

    reloaded = ProcessStore(tmp_path)
    assert reloaded.get(first.process_id).name == "修改后的流程"


def test_unchanged_content_does_not_create_new_version(tmp_path) -> None:
    store = ProcessStore(tmp_path)
    first = store.create(spec_from(minimal_process_dict()))
    second, created = store.update(first.process_id, spec_from(minimal_process_dict()), 1)
    assert created is False
    assert second.version == 1
    assert len(store.version_summaries(first.process_id)) == 1


def test_version_conflict_is_reported(tmp_path) -> None:
    store = ProcessStore(tmp_path)
    first = store.create(spec_from(minimal_process_dict()))
    data = minimal_process_dict()
    data["name"] = "第二版"
    store.update(first.process_id, spec_from(data), 1)
    with pytest.raises(VersionConflict):
        store.update(first.process_id, spec_from(minimal_process_dict()), 1)


def test_missing_process_and_version(tmp_path) -> None:
    store = ProcessStore(tmp_path)
    with pytest.raises(ProcessNotFound):
        store.get("proc_000000000000")
    first = store.create(spec_from(minimal_process_dict()))
    with pytest.raises(ProcessVersionNotFound):
        store.get(first.process_id, 99)


def test_list_processes(tmp_path) -> None:
    store = ProcessStore(tmp_path)
    store.create(spec_from(minimal_process_dict()))
    items = store.list_processes()
    assert len(items) == 1
    assert items[0]["latest_version"] == 1
    assert items[0]["node_count"] == 3
    assert items[0]["edge_count"] == 2
