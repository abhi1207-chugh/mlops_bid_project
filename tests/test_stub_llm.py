from fastapi.testclient import TestClient

from stub_llm.main import app


def test_stub_llm_exposes_prometheus_metrics():
    """Keep the configured Prometheus target from silently becoming unhealthy."""
    client = TestClient(app)
    response = client.get("/metrics/")
    assert response.status_code == 200
    assert "stub_llm_requests_total" in response.text

