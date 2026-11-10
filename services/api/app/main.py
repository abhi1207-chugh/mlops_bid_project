"""API: validate, quarantine, enqueue, return run_id at once (F1, F2, D1, A4)."""
from __future__ import annotations

import json
import logging
import os
import time

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import Counter, Gauge, make_asgi_app

from common.config import get_settings
from common.contract import validate_bid
from common.logging import correlation_id, log, setup_logging
from common.runstore import RunStore, quarantine

setup_logging()
logger = logging.getLogger("api")
app = FastAPI(title="Bid Compliance Screening", version="0.1.0")
app.mount("/metrics", make_asgi_app())

SUBMITTED = Counter("screenings_submitted_total", "Accepted screening requests")
QUARANTINED = Counter("screenings_quarantined_total", "Requests rejected by validation")
RATE_LIMITED = Counter("screenings_rate_limited_total", "Requests rejected by client rate limiting")
INDEX_AGE = Gauge("index_age_seconds", "Seconds since the corpus index was built")
STATIC = os.path.join(os.path.dirname(__file__), "static")

_store: RunStore | None = None


def store() -> RunStore:
    global _store
    if _store is None:
        _store = RunStore()
    return _store


def index_meta() -> dict | None:
    try:
        with open(os.path.join(get_settings().index_dir, "index_meta.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def rate_limit(client_key: str) -> int:
    """Fixed-window, Redis-backed limiter shared by API replicas."""
    window = int(time.time() // 60)
    key = f"rate:{client_key}:{window}"
    pipe = store().r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 120)
    count, _ = pipe.execute()
    return int(count)


@app.get("/")
def web_client() -> FileResponse:
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/health")
def health() -> JSONResponse:
    redis_ok = True
    try:
        store().ping()
    except redis.RedisError:
        redis_ok = False
    meta = index_meta()
    age = None
    if meta:
        age = round(time.time() - meta["built_at"], 1)
        INDEX_AGE.set(age)
    body = {"status": "ok" if redis_ok else "degraded", "redis": redis_ok,
            "index": {"built": bool(meta), "age_seconds": age, "chunks": (meta or {}).get("chunks")}}
    return JSONResponse(body, status_code=200 if redis_ok else 503)


@app.get("/v1/samples")
def samples() -> list:
    path = os.getenv("SAMPLES_PATH", "/app/eval/bidders.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except OSError:
        return []


@app.post("/v1/screenings", status_code=202)
async def submit_screening(request: Request) -> JSONResponse:
    # Parse manually: FastAPI's own body validation would skip quarantine.
    try:
        payload = json.loads(await request.body())
    except ValueError:
        payload = None
        errors = [{"field": "(body)", "message": "body is not valid JSON", "type": "json_invalid"}]
        model = None
    else:
        model, errors = validate_bid(payload)
    if model is None:
        qid = quarantine(payload, errors)
        QUARANTINED.inc()
        log(logger, "request_quarantined", quarantine_id=qid, error_fields=[e["field"] for e in errors])
        return JSONResponse({"status": "quarantined", "quarantine_id": qid, "errors": errors}, status_code=422)
    try:
        client_key = request.client.host if request.client else "unknown"
        if rate_limit(client_key) > get_settings().rate_limit_per_minute:
            RATE_LIMITED.inc()
            return JSONResponse({"detail": "rate limit exceeded; retry in the next minute"}, status_code=429,
                                headers={"Retry-After": "60"})
        rec = store().create(model.model_dump(), model.flags())
        store().enqueue(rec.run_id)
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="queue unavailable; request not accepted")
    SUBMITTED.inc()
    token = correlation_id.set(rec.run_id)
    log(logger, "run_enqueued", tender_id=model.tender_id, flags=rec.flags)
    correlation_id.reset(token)
    return JSONResponse({"run_id": rec.run_id, "status": "queued", "flags": rec.flags}, status_code=202)


@app.get("/v1/screenings/{run_id}")
def get_screening(run_id: str) -> dict:
    try:
        rec = store().get(run_id)
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="store unavailable")
    if rec is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return {"run_id": rec.run_id, "status": rec.status, "flags": rec.flags,
            "finding": rec.finding.model_dump() if rec.finding else None}


@app.get("/v1/screenings/{run_id}/trace")
def get_trace(run_id: str) -> dict:
    rec = store().get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return {"run_id": run_id, "status": rec.status, "bid": rec.bid, "trace": rec.trace,
            "usage": [u.model_dump() for u in rec.finding.usage] if rec.finding else []}


@app.post("/v1/screenings/{run_id}/feedback")
def feedback(run_id: str) -> dict:
    # Phase 3 (L6): persist satisfactory yes/no with a reason.
    raise HTTPException(status_code=501, detail="not implemented")
