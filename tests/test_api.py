import fakeredis
import pytest
from fastapi.testclient import TestClient

from common.runstore import RunStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QUARANTINE_DIR", str(tmp_path / "q"))
    from app import main
    main._store = RunStore(fakeredis.FakeRedis(decode_responses=True))
    return TestClient(main.app), main


def test_malformed_request_quarantined_and_no_run_started(client, tmp_path):
    c, main = client
    r = c.post("/v1/screenings", json={"tender_id": "T", "bidder_name": "x", "bidder_category_claimed": "banana",
                                      "avg_annual_turnover_inr": -1, "emd_paid_inr": 0, "documents_submitted": []})
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} >= {"bidder_category_claimed", "avg_annual_turnover_inr"}
    assert main.store().r.llen("runs:queue") == 0
    assert len(list((tmp_path / "q").glob("*.json"))) == 1


def test_not_json_quarantined(client):
    c, main = client
    assert c.post("/v1/screenings", content=b"{nope").status_code == 422
    assert main.store().r.llen("runs:queue") == 0


def test_valid_request_returns_run_id_at_once(client):
    import json
    c, main = client
    bid = next(b for b in json.load(open("/app/eval/bidders.json")) if b["id"] == "B2")["bid"]
    r = c.post("/v1/screenings", json=bid)
    assert r.status_code == 202
    rid = r.json()["run_id"]
    assert main.store().r.llen("runs:queue") == 1
    assert c.get(f"/v1/screenings/{rid}").json()["status"] == "queued"
    assert c.get("/v1/screenings/nope").status_code == 404


def test_injection_is_quarantined_and_never_queued(client, tmp_path):
    import json
    c, main = client
    bid = next(b for b in json.load(open("/app/eval/bidders.json")) if b["id"] == "B11")["bid"]
    r = c.post("/v1/screenings", json=bid)
    assert r.status_code == 422
    assert r.json()["errors"][0]["type"] == "prompt_injection"
    assert main.store().r.llen("runs:queue") == 0
    assert len(list((tmp_path / "q").glob("*.json"))) == 1


def test_rate_limit_rejects_without_creating_another_run(client, monkeypatch):
    import json
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    c, main = client
    bid = next(b for b in json.load(open("/app/eval/bidders.json")) if b["id"] == "B2")["bid"]
    assert c.post("/v1/screenings", json=bid).status_code == 202
    limited = c.post("/v1/screenings", json=bid)
    assert limited.status_code == 429
    assert main.store().r.llen("runs:queue") == 1
