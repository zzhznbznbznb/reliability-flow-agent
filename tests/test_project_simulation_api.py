from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.process_ir import ProcessDocument
from app.experiments.store import ExperimentStore
from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from tests.helpers import equipment_reliability_nodes, project_payload

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "examples" / "equipment_support_reliability_flow.json"


def _client(tmp_path) -> TestClient:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
        experiment_store=ExperimentStore(tmp_path / "experiments"),
    )
    return TestClient(app)


def _create_process(client: TestClient) -> dict:
    spec = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    response = client.post("/api/processes", json=spec)
    assert response.status_code == 201, response.text
    return response.json()["process"]


def _save_reliability(
    client: TestClient,
    process: dict,
    *,
    lambda1: float,
    lambda2: float,
    ft: float,
) -> dict:
    nodes = equipment_reliability_nodes(
        ProcessDocument.model_validate(process),
        lambda1=lambda1,
        lambda2=lambda2,
        detection_rate=ft,
    )
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


def test_formal_experiment_requires_complete_project_parameters(tmp_path) -> None:
    with _client(tmp_path) as client:
        process = _create_process(client)
        _save_reliability(client, process, lambda1=0.0, lambda2=0.0, ft=1.0)
        response = client.post(
            f"/api/processes/{process['process_id']}/experiments",
            json={
                "entity_count": 2,
                "simulation_end": 30,
                "random_seed": 1,
            },
        )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "missing_project_parameters"
    fields = {issue["field"] for issue in detail["issues"]}
    assert fields == {
        "name",
        "description",
        "reliability_target",
        "readiness_target",
        "simulation_unit",
        "missile_count",
        "simulation_total_time",
    }


def test_experiment_persists_project_and_reports_stage_detection_metrics(
    tmp_path,
) -> None:
    with _client(tmp_path) as client:
        process = _create_process(client)
        _save_reliability(client, process, lambda1=0.002, lambda2=0.002, ft=0.7)
        response = client.post(
            f"/api/processes/{process['process_id']}/experiments",
            json={
                "entity_count": 8,
                "simulation_end": 120,
                "random_seed": 2026,
                "project": project_payload(
                    missile_count=8,
                    reliability_target=0.5,
                    readiness_target=0.5,
                    simulation_total_time=120,
                ),
                "evaluation_targets": {
                    "overall_reliability_min": 0.5,
                    "readiness_min": 0.5,
                },
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["simulation"]["project"]["name"] == "测试项目"
        assert body["simulation"]["project"]["missile_count"] == 8
        assert body["simulation"]["simulation_unit"] == "day"
        assert body["simulation"]["entity_count"] == 8
        evaluation = body["evaluation"]
        assert evaluation["overall"]["readiness"] is not None
        assert (
            evaluation["overall"]["total_available_time"]
            + evaluation["overall"]["total_unavailable_time"]
            == 8 * 120
        )
        nodes = {node["node_id"]: node for node in evaluation["nodes"]}
        assert nodes["n_storage"]["module_type"] == "stage"
        assert nodes["n_duty"]["module_type"] == "stage"
        assert "n_storage" in nodes and "n_duty" in nodes
        tests = {test["node_id"]: test for test in evaluation["tests"]}
        assert {"s_inspect", "n_first_test", "n_second_test", "d_inspect"} <= set(
            tests
        )
        assert tests["s_inspect"]["detection_rate"] == 0.7
        assert tests["s_inspect"]["test_count"] > 0
        targets = {target["metric"]: target for target in evaluation["targets"]}
        assert targets["readiness"]["configured"] is True
        assert targets["readiness"]["status"] in {"achieved", "not_achieved"}

        record = client.get(f"/api/experiments/{body['result_id']}")
        assert record.status_code == 200
        stored = record.json()["experiment"]
        assert stored["project"]["name"] == "测试项目"
        listed = client.get("/api/experiments").json()["experiments"]
        assert listed[0]["project_name"] == "测试项目"


def test_formal_experiment_rejects_missing_stage_and_detection_parameters(
    tmp_path,
) -> None:
    with _client(tmp_path) as client:
        process = _create_process(client)
        document = ProcessDocument.model_validate(process)

        def iter_nodes(nodes):
            for node in nodes:
                yield node
                if node.subflow is not None:
                    yield from iter_nodes(node.subflow.nodes)

        nodes = [
            {
                "node_id": node.id,
                "module_type": "activity",
                "participates": False,
                "lambda_unit": "per_day",
            }
            for node in iter_nodes(document.nodes)
            if node.type == "task"
        ]
        saved = client.put(
            f"/api/processes/{process['process_id']}/reliability",
            json={
                "process_version": process["version"],
                "process_hash": process["content_hash"],
                "nodes": nodes,
            },
        )
        assert saved.status_code == 200, saved.text
        response = client.post(
            f"/api/processes/{process['process_id']}/experiments",
            json={
                "entity_count": 2,
                "simulation_end": 30,
                "random_seed": 1,
                "project": project_payload(missile_count=2),
            },
        )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "simulation_parameters_missing"
    codes = {issue["code"] for issue in detail["issues"]}
    assert "missing_stage_reliability" in codes
    assert "missing_test_detection_module" in codes


def test_formal_experiment_rejects_lambda_on_ordinary_activity(tmp_path) -> None:
    with _client(tmp_path) as client:
        process = _create_process(client)
        document = ProcessDocument.model_validate(process)
        nodes = equipment_reliability_nodes(
            document, lambda1=0.0, lambda2=0.0, detection_rate=1.0
        )
        for node in nodes:
            if node["node_id"] == "n_transport":
                node.update(
                    {
                        "module_type": "activity",
                        "participates": True,
                        "lambda": 0.1,
                    }
                )
        saved = client.put(
            f"/api/processes/{process['process_id']}/reliability",
            json={
                "process_version": process["version"],
                "process_hash": process["content_hash"],
                "nodes": nodes,
            },
        )
        assert saved.status_code == 200, saved.text
        response = client.post(
            f"/api/processes/{process['process_id']}/experiments",
            json={
                "entity_count": 1,
                "simulation_end": 30,
                "random_seed": 1,
                "project": project_payload(missile_count=1),
            },
        )
    assert response.status_code == 400
    detail = response.json()["detail"]
    codes = {issue["code"] for issue in detail["issues"]}
    assert "activity_lambda_not_allowed" in codes
