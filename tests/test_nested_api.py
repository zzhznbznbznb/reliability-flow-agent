from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from tests.helpers import project_payload

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "examples" / "equipment_support_nested_flow.json"


def _iter_nodes(nodes):
    for node in nodes:
        yield node
        subflow = (
            node.subflow if hasattr(node, "subflow") else node.get("subflow")
        )
        if subflow is not None:
            children = (
                subflow.nodes
                if hasattr(subflow, "nodes")
                else subflow.get("nodes")
            )
            yield from _iter_nodes(children)


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
    )
    with TestClient(app) as test_client:
        yield test_client


def test_nested_process_save_reload_simulate_and_experiment(client: TestClient) -> None:
    spec = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    created = client.post("/api/processes", json=spec)
    assert created.status_code == 201, created.text
    process = created.json()["process"]
    process_id = process["process_id"]
    assert process["schema_version"] == "process-ir/1.1"

    versions = client.get(f"/api/processes/{process_id}/versions").json()["versions"]
    assert versions[0]["node_count"] == 28
    assert versions[0]["edge_count"] == 29
    assert versions[0]["subprocess_count"] == 2

    loaded = client.get(f"/api/processes/{process_id}").json()["process"]
    node_map = {node["id"]: node for node in loaded["nodes"]}
    assert node_map["n_storage"]["type"] == "subprocess"
    assert node_map["n_duty"]["type"] == "subprocess"
    assert {
        node["id"] for node in node_map["n_storage"]["subflow"]["nodes"]
    } == {"s_start", "s_store", "s_inspect", "s_dec", "s_repair", "s_done"}
    assert {
        node["id"] for node in node_map["n_duty"]["subflow"]["nodes"]
    } == {"d_start", "d_duty", "d_inspect", "d_dec", "d_repair", "d_done"}

    reliability_nodes = []
    for node in _iter_nodes(node_map.values()):
        if node["type"] != "task":
            continue
        is_test = node["id"] in {
            "s_inspect",
            "d_inspect",
            "n_first_test",
            "n_second_test",
        }
        reliability_nodes.append(
            {
                "node_id": node["id"],
                "module_type": "test" if is_test else "activity",
                "participates": False,
                "lambda_unit": "per_day",
                **(
                    {"detection_rate": 1.0, "test_time": 1.0}
                    if is_test
                    else {}
                ),
            }
        )
    reliability_nodes.extend(
        [
            {
                "node_id": "n_storage",
                "module_type": "stage",
                "participates": True,
                "lambda": 0.0,
                "lambda_unit": "per_day",
                "stage_task_id": "s_store",
            },
            {
                "node_id": "n_duty",
                "module_type": "stage",
                "participates": True,
                "lambda": 0.0,
                "lambda_unit": "per_day",
                "stage_task_id": "d_duty",
            },
        ]
    )
    saved = client.put(
        f"/api/processes/{process_id}/reliability",
        json={
            "process_version": process["version"],
            "process_hash": process["content_hash"],
            "nodes": reliability_nodes,
        },
    )
    assert saved.status_code == 200, saved.text

    simulation = client.post(
        f"/api/processes/{process_id}/simulate",
        json={
            "entity_count": 1,
            "simulation_end": 500,
            "random_seed": 0,
        },
    )
    assert simulation.status_code == 200, simulation.text
    simulation_body = simulation.json()
    assert simulation_body["runtime_semantic_version"] == "stepwise-detection/1.0"
    assert simulation_body["entities"][0]["completed"] is True
    assert any(
        sample["node_id"] == "n_storage"
        and sample["scope_path"] == ["n_storage"]
        for sample in simulation_body["reliability_samples"]
    )

    experiment = client.post(
        f"/api/processes/{process_id}/experiments",
        json={
            "entity_count": 1,
            "simulation_end": 500,
            "random_seed": 0,
            "project": project_payload(
                missile_count=1, simulation_total_time=500
            ),
        },
    )
    assert experiment.status_code == 200, experiment.text
    experiment_body = experiment.json()
    node_metrics = {
        node["node_id"]: node for node in experiment_body["evaluation"]["nodes"]
    }
    assert "n_storage" in node_metrics
    assert "n_duty" in node_metrics
    tests = {
        test["node_id"] for test in experiment_body["evaluation"]["tests"]
    }
    assert {"s_inspect", "d_inspect", "n_first_test", "n_second_test"} <= tests

    record = client.get(
        f"/api/experiments/{experiment_body['result_id']}"
    )
    assert record.status_code == 200
    assert record.json()["experiment"]["simulation"]["process_version"] == 1
