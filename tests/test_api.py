from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.processes.store import ProcessStore

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _example() -> dict:
    return json.loads(
        (EXAMPLES / "equipment_support_flow.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(process_store=ProcessStore(tmp_path / "processes"))
    with TestClient(app) as test_client:
        yield test_client


def test_process_crud_versions_and_diagram(client: TestClient) -> None:
    created = client.post("/api/processes", json=_example())
    assert created.status_code == 201
    body = created.json()
    process = body["process"]
    process_id = process["process_id"]
    assert process["version"] == 1
    assert process["content_hash"].startswith("sha256:")
    assert process["edges"][0]["from"] == "start"

    listed = client.get("/api/processes")
    assert listed.status_code == 200
    assert listed.json()["processes"][0]["process_id"] == process_id

    fetched = client.get(f"/api/processes/{process_id}")
    assert fetched.status_code == 200
    assert fetched.json()["process"]["name"] == "设备支援流程"

    updated_data = deepcopy(_example())
    updated_data["name"] = "设备支援流程 v2"
    updated_data["nodes"][1]["position"] = {"x": 260, "y": 260}
    updated = client.put(
        f"/api/processes/{process_id}",
        json={"base_version": 1, "process": updated_data},
    )
    assert updated.status_code == 200
    assert updated.json()["created"] is True
    assert updated.json()["process"]["version"] == 2

    history = client.get(f"/api/processes/{process_id}/versions")
    assert history.status_code == 200
    assert [item["version"] for item in history.json()["versions"]] == [2, 1]

    old = client.get(f"/api/processes/{process_id}?version=1")
    assert old.status_code == 200
    assert old.json()["process"]["name"] == "设备支援流程"

    diagram = client.get(f"/api/processes/{process_id}/diagram.svg")
    assert diagram.status_code == 200
    assert diagram.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in diagram.text
    etag = diagram.headers["etag"]
    not_modified = client.get(
        f"/api/processes/{process_id}/diagram.svg",
        headers={"If-None-Match": etag},
    )
    assert not_modified.status_code == 304


def test_version_conflict_is_reported(client: TestClient) -> None:
    process = client.post("/api/processes", json=_example()).json()["process"]
    process_id = process["process_id"]
    updated = deepcopy(_example())
    updated["name"] = "v2"
    assert (
        client.put(
            f"/api/processes/{process_id}",
            json={"base_version": 1, "process": updated},
        ).status_code
        == 200
    )
    conflict = client.put(
        f"/api/processes/{process_id}",
        json={"base_version": 1, "process": updated},
    )
    assert conflict.status_code == 409
    assert conflict.json()["current_version"] == 2


def test_invalid_process_is_rejected_with_issue_details(client: TestClient) -> None:
    data = _example()
    data["end_node_ids"] = []
    response = client.post("/api/processes", json=data)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["valid"] is False
    assert any(issue["code"] == "missing_end_reference" for issue in detail["issues"])


def test_schema_rejects_reliability_parameters(client: TestClient) -> None:
    data = _example()
    data["nodes"][1]["lambda"] = 0.02
    response = client.post("/api/processes", json=data)
    assert response.status_code == 422
    assert response.json()["valid"] is False
    assert response.json()["issues"][0]["code"] == "schema_invalid"


def test_validate_and_preview_endpoints(client: TestClient) -> None:
    validation = client.post("/api/processes/validate", json=_example())
    assert validation.status_code == 200
    assert validation.json()["valid"] is True

    preview = client.post("/api/processes/preview.svg", json=_example())
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/svg+xml")
    assert preview.headers["x-content-hash"].startswith("sha256:")
    assert "<svg" in preview.text


def test_missing_process_returns_404(client: TestClient) -> None:
    response = client.get("/api/processes/proc_000000000000")
    assert response.status_code == 404
    assert response.json()["process_id"] == "proc_000000000000"


def test_built_frontend_is_served_when_available(client: TestClient) -> None:
    index = Path(__file__).resolve().parent.parent / "web" / "index.html"
    if not index.is_file():
        pytest.skip("frontend has not been built")
    response = client.get("/")
    assert response.status_code == 200
    assert "Reliability Flow Agent" in response.text
