from __future__ import annotations

from fastapi.testclient import TestClient

from app.experiments.store import ExperimentStore
from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from tests.helpers import failure_process_dict


def _client(tmp_path) -> TestClient:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
        experiment_store=ExperimentStore(tmp_path / "experiments"),
    )
    return TestClient(app)


def test_experiment_is_persisted_and_queryable_by_result_id(tmp_path) -> None:
    with _client(tmp_path) as client:
        process = client.post(
            "/api/processes", json=failure_process_dict()
        ).json()["process"]
        reliability = client.put(
            f"/api/processes/{process['process_id']}/reliability",
            json={
                "process_version": process["version"],
                "process_hash": process["content_hash"],
                "nodes": [
                    {"node_id": "inspect", "participates": True, "lambda": 0.0},
                    {"node_id": "repair", "participates": False},
                ],
            },
        )
        assert reliability.status_code == 200, reliability.text

        response = client.post(
            f"/api/processes/{process['process_id']}/experiments",
            json={
                "entity_count": 3,
                "simulation_end": 10,
                "random_seed": 7,
                "failure_policy": "require_failure_exit",
                "evaluation_targets": {"overall_reliability_min": 1.0},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["result_id"].startswith("exp_")
        assert body["simulation"]["process_id"] == process["process_id"]
        assert body["evaluation"]["overall"]["entity_count"] == 3

        listed = client.get("/api/experiments")
        assert listed.status_code == 200
        summaries = listed.json()["experiments"]
        assert summaries[0]["result_id"] == body["result_id"]
        assert summaries[0]["process_id"] == process["process_id"]

        fetched = client.get(f"/api/experiments/{body['result_id']}")
        assert fetched.status_code == 200
        record = fetched.json()["experiment"]
        assert record["result_id"] == body["result_id"]
        assert record["process_version"] == process["version"]
        assert record["reliability_revision"] == reliability.json()["reliability"]["revision"]


def test_experiment_requires_bound_reliability(tmp_path) -> None:
    with _client(tmp_path) as client:
        process = client.post(
            "/api/processes", json=failure_process_dict()
        ).json()["process"]
        response = client.post(
            f"/api/processes/{process['process_id']}/experiments",
            json={
                "entity_count": 3,
                "simulation_end": 10,
                "random_seed": 7,
                "failure_policy": "require_failure_exit",
            },
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "reliability_not_bound"
