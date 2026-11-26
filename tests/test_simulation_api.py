from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from tests.helpers import failure_process_dict, minimal_process_dict


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
    )
    with TestClient(app) as test_client:
        yield test_client


def _create_process(client: TestClient, data: dict | None = None) -> dict:
    response = client.post(
        "/api/processes", json=data or failure_process_dict()
    )
    assert response.status_code == 201, response.text
    return response.json()["process"]


def _save_reliability(client: TestClient, process: dict, nodes: list[dict]) -> dict:
    response = client.put(
        f"/api/processes/{process['process_id']}/reliability",
        json={
            "process_version": process["version"],
            "process_hash": process["content_hash"],
            "nodes": nodes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["reliability"]


def _failure_nodes(lam: float = 1e9) -> list[dict]:
    return [
        {"node_id": "inspect", "participates": True, "lambda": lam},
        {"node_id": "repair", "participates": False},
    ]


def _simulate(client: TestClient, process_id: str, **overrides):
    payload = {
        "entity_count": 2,
        "simulation_end": 10,
        "random_seed": 5,
        "failure_policy": "require_failure_exit",
    }
    payload.update(overrides)
    return client.post(
        f"/api/processes/{process_id}/simulate", json=payload
    )


def test_simulation_api_runs_real_events_and_repairs(client: TestClient) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes())
    response = _simulate(client, process["process_id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entity_count"] == 2
    assert body["completed_count"] == 2
    assert body["total_failure_count"] == 2
    assert body["reliability_sample_count"] == 2
    assert body["event_count"] == len(body["events"])
    assert body["reliability_samples"][0]["lambda"] == 1e9
    assert body["reliability_samples"][0]["exposure_time"] == 1.0
    entity = body["entities"][0]
    assert entity["failure_count"] == 1
    assert entity["repair_count"] == 1
    assert entity["ever_failed"] is True
    assert entity["currently_failed"] is False
    types = {event["event_type"] for event in body["events"]}
    assert {"reliability_sample", "reliability_failure", "repair_started"} <= types


def test_simulation_api_is_reproducible_with_same_seed(client: TestClient) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes(lam=0.4))
    first = _simulate(client, process["process_id"], entity_count=5)
    second = _simulate(client, process["process_id"], entity_count=5)
    assert first.status_code == 200
    assert first.json() == second.json()


def test_simulation_requires_bound_reliability(client: TestClient) -> None:
    process = _create_process(client)
    response = _simulate(client, process["process_id"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "reliability_not_bound"


def test_simulation_rejects_missing_failure_exit(client: TestClient) -> None:
    process = _create_process(client, minimal_process_dict())
    _save_reliability(
        client,
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.1}],
    )
    response = _simulate(client, process["process_id"])
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "simulation_invalid"
    assert {issue["code"] for issue in detail["issues"]} == {
        "missing_failure_exit"
    }


def test_simulation_enforces_request_and_safety_limits(client: TestClient) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes())
    zero_entities = _simulate(client, process["process_id"], entity_count=0)
    assert zero_entities.status_code == 422

    too_many = _simulate(
        client, process["process_id"], entity_count=10001
    )
    assert too_many.status_code == 400
    assert {
        issue["code"] for issue in too_many.json()["detail"]["issues"]
    } == {"max_entities_exceeded"}

    too_long = _simulate(
        client, process["process_id"], simulation_end=400000
    )
    assert too_long.status_code == 400
    assert {
        issue["code"] for issue in too_long.json()["detail"]["issues"]
    } == {"max_simulation_days_exceeded"}


def test_simulation_uses_version_bound_reliability(client: TestClient) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes())
    updated_data = deepcopy(failure_process_dict())
    updated_data["name"] = "故障维修流程 v2"
    updated = client.put(
        f"/api/processes/{process['process_id']}",
        json={"base_version": 1, "process": updated_data},
    )
    assert updated.status_code == 200
    assert updated.json()["process"]["version"] == 2

    stale = _simulate(client, process["process_id"])
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "reliability_not_bound"

    historical = _simulate(
        client, process["process_id"], process_version=1
    )
    assert historical.status_code == 200
    assert historical.json()["process_version"] == 1


def test_simulation_unknown_process_and_version_return_404(
    client: TestClient,
) -> None:
    missing = _simulate(client, "proc_000000000000")
    assert missing.status_code == 404

    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes())
    missing_version = _simulate(
        client, process["process_id"], process_version=99
    )
    assert missing_version.status_code == 404
