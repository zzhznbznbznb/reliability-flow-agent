from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from tests.helpers import minimal_process_dict


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
    )
    with TestClient(app) as test_client:
        yield test_client


def _create_process(client: TestClient) -> dict:
    response = client.post("/api/processes", json=minimal_process_dict())
    assert response.status_code == 201
    return response.json()["process"]


def _payload(process: dict, nodes: list[dict]) -> dict:
    return {
        "process_version": process["version"],
        "process_hash": process["content_hash"],
        "nodes": nodes,
    }


def _full_nodes(**overrides) -> list[dict]:
    node = {"node_id": "work", "participates": True, "lambda": 0.02}
    node.update(overrides)
    return [node]


def test_get_reliability_before_save_reports_missing(client: TestClient) -> None:
    process = _create_process(client)
    response = client.get(f"/api/processes/{process['process_id']}/reliability")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "missing"
    assert body["reliability"] is None
    assert body["process"]["version"] == 1


def test_save_and_reload_reliability_configuration(client: TestClient) -> None:
    process = _create_process(client)
    response = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json=_payload(process, _full_nodes()),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    document = body["reliability"]
    assert document["process_version"] == 1
    assert document["process_hash"] == process["content_hash"]
    assert document["nodes"][0]["lambda"] == 0.02
    assert document["nodes"][0]["lambda_unit"] == "per_day"
    assert document["nodes"][0]["distribution"] == "exponential"

    fetched = client.get(f"/api/processes/{process['process_id']}/reliability")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["status"] == "bound"
    assert fetched_body["reliability"]["reliability_id"] == document["reliability_id"]
    assert fetched_body["reliability"]["nodes"][0]["participates"] is True


def test_missing_task_configuration_is_rejected(client: TestClient) -> None:
    process = _create_process(client)
    response = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json=_payload(process, []),
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["valid"] is False
    assert any(
        issue["code"] == "reliability_missing_config" for issue in detail["issues"]
    )


def test_non_task_and_unknown_nodes_are_rejected(client: TestClient) -> None:
    process = _create_process(client)
    non_task = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json=_payload(
            process,
            [
                {"node_id": "work", "participates": False},
                {"node_id": "start", "participates": True, "lambda": 0.1},
            ],
        ),
    )
    assert non_task.status_code == 400
    assert any(
        issue["code"] == "reliability_invalid_node_type"
        for issue in non_task.json()["detail"]["issues"]
    )

    unknown = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json=_payload(
            process,
            [
                {"node_id": "work", "participates": False},
                {"node_id": "ghost", "participates": False},
            ],
        ),
    )
    assert unknown.status_code == 400
    assert any(
        issue["code"] == "reliability_unknown_node"
        for issue in unknown.json()["detail"]["issues"]
    )


def test_lambda_zero_is_accepted_and_negative_is_schema_error(
    client: TestClient,
) -> None:
    process = _create_process(client)
    zero = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json=_payload(process, _full_nodes(**{"lambda": 0})),
    )
    assert zero.status_code == 200
    assert zero.json()["reliability"]["nodes"][0]["lambda"] == 0

    negative = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json=_payload(process, _full_nodes(**{"lambda": -0.1})),
    )
    assert negative.status_code == 422
    assert negative.json()["issues"][0]["code"] == "schema_invalid"


def test_non_finite_lambda_json_is_rejected(client: TestClient) -> None:
    process = _create_process(client)
    for token in ("NaN", "Infinity", "-Infinity"):
        body = (
            '{"process_version":1,"process_hash":"%s","nodes":'
            '[{"node_id":"work","participates":true,"lambda":%s}]}'
            % (process["content_hash"], token)
        )
        response = client.put(
            f"/api/processes/{process['process_id']}/reliability",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["issues"][0]["code"] == "schema_invalid"


def test_validate_endpoint_checks_binding_and_participation(
    client: TestClient,
) -> None:
    process = _create_process(client)
    valid = client.post(
        f"/api/processes/{process['process_id']}/reliability/validate",
        json=_payload(process, _full_nodes()),
    )
    assert valid.status_code == 200
    assert valid.json()["valid"] is True
    assert valid.json()["participant_count"] == 1

    invalid = client.post(
        f"/api/processes/{process['process_id']}/reliability/validate",
        json={
            **_payload(process, _full_nodes()),
            "process_hash": "sha256:" + "b" * 64,
        },
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert any(
        issue["code"] == "reliability_process_hash_mismatch"
        for issue in invalid.json()["issues"]
    )


def test_new_process_version_marks_old_reliability_stale(
    client: TestClient,
) -> None:
    process = _create_process(client)
    process_id = process["process_id"]
    saved = client.put(
        f"/api/processes/{process_id}/reliability",
        json=_payload(process, _full_nodes()),
    )
    assert saved.status_code == 200
    old_reliability_id = saved.json()["reliability"]["reliability_id"]

    updated_data = deepcopy(minimal_process_dict())
    updated_data["name"] = "最小流程 v2"
    updated = client.put(
        f"/api/processes/{process_id}",
        json={"base_version": 1, "process": updated_data},
    )
    assert updated.status_code == 200
    v2 = updated.json()["process"]
    assert v2["version"] == 2

    latest = client.get(f"/api/processes/{process_id}/reliability")
    assert latest.status_code == 200
    body = latest.json()
    assert body["status"] == "stale"
    assert body["reliability"] is None
    assert len(body["stale_revisions"]) == 1
    assert body["stale_revisions"][0]["reliability_id"] == old_reliability_id

    old = client.get(f"/api/processes/{process_id}/reliability?version=1")
    assert old.status_code == 200
    assert old.json()["status"] == "bound"
    assert old.json()["reliability"]["reliability_id"] == old_reliability_id

    history = client.get(f"/api/processes/{process_id}/reliability/history")
    assert history.status_code == 200
    revisions = history.json()["revisions"]
    assert len(revisions) == 1
    assert revisions[0]["process_version"] == 1
    assert revisions[0]["current"] is False


def test_cannot_save_reliability_against_old_process_version(
    client: TestClient,
) -> None:
    process = _create_process(client)
    process_id = process["process_id"]
    updated_data = deepcopy(minimal_process_dict())
    updated_data["name"] = "v2"
    v2 = client.put(
        f"/api/processes/{process_id}",
        json={"base_version": 1, "process": updated_data},
    ).json()["process"]

    conflict = client.put(
        f"/api/processes/{process_id}/reliability",
        json=_payload(process, _full_nodes()),
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["code"] == "reliability_binding_conflict"
    assert detail["current_version"] == 2

    saved = client.put(
        f"/api/processes/{process_id}/reliability",
        json={**_payload(v2, _full_nodes()), "process_version": 2},
    )
    assert saved.status_code == 200
    assert saved.json()["reliability"]["process_version"] == 2


def test_reliability_requires_existing_process(client: TestClient) -> None:
    response = client.get("/api/processes/proc_000000000000/reliability")
    assert response.status_code == 404


def test_empty_nodes_payload_is_not_silently_accepted(client: TestClient) -> None:
    process = _create_process(client)
    response = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json=_payload(process, []),
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]["issues"][0]["code"]
        == "reliability_missing_config"
    )
