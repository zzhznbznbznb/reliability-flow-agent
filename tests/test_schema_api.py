from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore
from app.experiments.store import ExperimentStore


def test_schema_endpoints_expose_real_pydantic_schemas(tmp_path) -> None:
    app = create_app(
        process_store=ProcessStore(tmp_path / "processes"),
        reliability_store=ReliabilityStore(tmp_path / "reliability"),
        experiment_store=ExperimentStore(tmp_path / "experiments"),
    )
    with TestClient(app) as client:
        process = client.get("/api/schemas/process-ir")
        reliability = client.get("/api/schemas/reliability-ir")

    assert process.status_code == 200
    assert reliability.status_code == 200
    process_schema = process.json()
    reliability_schema = reliability.json()
    assert "nodes" in process_schema["properties"]
    assert "edges" in process_schema["properties"]
    assert "process_version" in reliability_schema["properties"]
    assert "nodes" in reliability_schema["properties"]
