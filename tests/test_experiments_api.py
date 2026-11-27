from __future__ import annotations

from fastapi.testclient import TestClient

from app.experiments.store import ExperimentStore
from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from tests.helpers import failure_process_dict, project_payload


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
                "project": project_payload(
                    missile_count=3, simulation_total_time=10
                ),
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


def test_project_total_time_controls_runtime_and_is_persisted(tmp_path) -> None:
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
                "entity_count": 2,
                "random_seed": 11,
                "project": project_payload(
                    missile_count=2, simulation_total_time=12.5
                ),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["simulation"]["simulation_duration"] == 12.5
        assert body["simulation"]["simulation_end"] == 12.5
        assert body["simulation"]["simulation_unit"] == "day"
        assert body["simulation"]["project"]["simulation_total_time"] == 12.5

        stored = client.get(f"/api/experiments/{body['result_id']}").json()[
            "experiment"
        ]
        assert stored["project"]["simulation_total_time"] == 12.5
        assert stored["simulation_config"]["simulation_duration"] == 12.5
        summary = client.get("/api/experiments").json()["experiments"][0]
        assert summary["simulation_total_time"] == 12.5
        assert summary["simulation_duration"] == 12.5
        assert summary["simulation_unit"] == "day"


def test_project_total_time_must_match_runtime_duration(tmp_path) -> None:
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
                "entity_count": 2,
                "simulation_duration": 10,
                "random_seed": 11,
                "project": project_payload(
                    missile_count=2, simulation_total_time=12
                ),
            },
        )
    assert response.status_code == 422
    assert "simulation_total_time" in response.text
