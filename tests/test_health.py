from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "reliability-flow-agent"
    assert body["version"] == "0.3.0"
    assert body["phase"] == "4B"


def test_meta_endpoint_describes_offline_first_llm_contract() -> None:
    response = client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["offline_capable"] is True
    assert body["llm"]["provider"] == "opencode-go"
    assert body["llm"]["model"] == "deepseek-v4.1-flash"
    assert body["llm"]["required_for_simulation"] is False


def test_meta_endpoint_never_exposes_credentials() -> None:
    response = client.get("/api/meta")
    text = response.text.lower()
    assert "api_key" not in text
    assert "authorization" not in text
    assert "bearer" not in text
    assert "secret" not in text
