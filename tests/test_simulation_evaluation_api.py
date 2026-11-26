from __future__ import annotations

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
    response = client.post("/api/processes", json=data or failure_process_dict())
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


def _failure_nodes(lam: float) -> list[dict]:
    return [
        {"node_id": "inspect", "participates": True, "lambda": lam},
        {"node_id": "repair", "participates": False},
    ]


def _evaluate(client: TestClient, process_id: str, **overrides):
    payload = {
        "entity_count": 3,
        "simulation_end": 10,
        "random_seed": 7,
        "failure_policy": "require_failure_exit",
    }
    payload.update(overrides)
    return client.post(
        f"/api/processes/{process_id}/simulate/evaluate", json=payload
    )


def test_simulation_evaluation_runs_real_runtime_and_returns_both_results(
    client: TestClient,
) -> None:
    process = _create_process(client)
    reliability = _save_reliability(client, process, _failure_nodes(lam=1e9))

    response = _evaluate(
        client,
        process["process_id"],
        evaluation_targets={
            "overall_reliability_min": 1.0,
            "end_availability_min": 1.0,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == {"simulation", "evaluation", "explanation"}
    assert body["simulation"]["total_failure_count"] == 3
    assert body["simulation"]["completed_count"] == 3
    assert body["evaluation"]["overall"]["ever_failed_entity_count"] == 3
    assert body["evaluation"]["overall"]["overall_reliability"] == 0.0
    assert body["evaluation"]["process_binding"]["process_id"] == process["process_id"]
    assert (
        body["evaluation"]["reliability_binding"]["reliability_id"]
        == reliability["reliability_id"]
    )
    assert body["evaluation"]["target_status"] == "not_achieved"
    assert isinstance(body["explanation"], str)
    assert "整体可靠性" in body["explanation"]


def test_simulation_evaluation_targets_can_be_achieved(client: TestClient) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes(lam=0.0))

    response = _evaluate(
        client,
        process["process_id"],
        evaluation_targets={
            "overall_reliability_min": 1.0,
            "end_availability_min": 1.0,
        },
    )
    assert response.status_code == 200, response.text
    evaluation = response.json()["evaluation"]
    assert evaluation["overall"]["overall_reliability"] == 1.0
    assert evaluation["overall"]["end_availability"] == 1.0
    assert evaluation["target_status"] == "achieved"
    targets = {item["metric"]: item for item in evaluation["targets"]}
    assert targets["overall_reliability"]["status"] == "achieved"
    assert targets["end_availability"]["status"] == "achieved"


def test_simulation_evaluation_supports_lambda_zero_without_failure_exit(
    client: TestClient,
) -> None:
    process = _create_process(client, minimal_process_dict())
    _save_reliability(
        client,
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.0}],
    )

    response = _evaluate(
        client,
        process["process_id"],
        evaluation_targets={"overall_reliability_min": 1.0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["simulation"]["total_failure_count"] == 0
    assert body["evaluation"]["overall"]["overall_reliability"] == 1.0
    assert body["evaluation"]["target_status"] == "achieved"


def test_simulation_evaluation_returns_not_configured_targets(
    client: TestClient,
) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes(lam=0.0))

    response = _evaluate(client, process["process_id"])
    assert response.status_code == 200, response.text
    evaluation = response.json()["evaluation"]
    assert evaluation["target_status"] == "not_configured"
    assert all(item["status"] == "not_configured" for item in evaluation["targets"])


def test_simulation_evaluation_requires_bound_reliability(
    client: TestClient,
) -> None:
    process = _create_process(client)

    response = _evaluate(client, process["process_id"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "reliability_not_bound"


def test_simulation_evaluation_rejects_invalid_targets(
    client: TestClient,
) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes(lam=0.0))

    response = _evaluate(
        client,
        process["process_id"],
        evaluation_targets={"overall_reliability_min": 1.5},
    )
    assert response.status_code == 422
    assert response.json()["issues"][0]["code"] == "schema_invalid"


def test_simulation_failure_does_not_return_fake_evaluation(
    client: TestClient,
) -> None:
    process = _create_process(client, minimal_process_dict())
    _save_reliability(
        client,
        process,
        [{"node_id": "work", "participates": True, "lambda": 0.1}],
    )

    response = _evaluate(client, process["process_id"])
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "simulation_invalid"
    assert "evaluation" not in body
    assert "explanation" not in body


def test_evaluation_failure_is_reported_and_not_masked(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _create_process(client)
    _save_reliability(client, process, _failure_nodes(lam=0.0))

    def broken_evaluation(*args, **kwargs):
        raise RuntimeError("evaluation exploded")

    monkeypatch.setattr(
        "app.analysis.service.evaluate_simulation", broken_evaluation
    )

    response = _evaluate(client, process["process_id"])
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "evaluation_failed"
    assert "evaluation exploded" in detail["error"]
    assert "evaluation" not in response.json()
