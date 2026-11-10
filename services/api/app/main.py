"""API: validate, quarantine, enqueue, return run_id at once (F1, F2, D1, A4)."""
from __future__ import annotations

import json
import logging
import os
import time
import hashlib

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import REGISTRY, Counter, Gauge, make_asgi_app

from common.config import get_settings
from common.contract import validate_bid
from common.logging import correlation_id, log, setup_logging
from common.models import FeedbackRequest
from common.runstore import RunStore, quarantine
from common.tracing import inject_context, setup_tracing, span

setup_logging()
setup_tracing("bid-compliance-api")
logger = logging.getLogger("api")
app = FastAPI(title="Bid Compliance Screening", version="0.1.0")
app.mount("/metrics", make_asgi_app())

def _metric(metric_type, name: str, documentation: str, labels: list[str] | None = None):
    """Return an existing process metric when an ASGI module is re-imported.

    Uvicorn reloads and test clients can import this module more than once in one
    interpreter. Prometheus metrics are process-global, so registering a second
    collector would make the API fail before it can serve a health response.
    """
    try:
        return metric_type(name, documentation, labels or [])
    except ValueError:
        collector_name = name.removesuffix("_total") if metric_type is Counter else name
        return REGISTRY._names_to_collectors[collector_name]


SUBMITTED = _metric(Counter, "screenings_submitted_total", "Accepted screening requests")
QUARANTINED = _metric(Counter, "screenings_quarantined_total", "Requests rejected by validation")
RATE_LIMITED = _metric(Counter, "screenings_rate_limited_total", "Requests rejected by client rate limiting")
FEEDBACK = _metric(Counter, "screening_feedback_total", "Committee feedback", ["satisfactory"])
AUTO_SCORES = _metric(Counter, "screening_auto_scores_total", "Sampled deterministic auto-scores", ["outcome"])
AUTO_QUALITY = _metric(Counter, "screening_auto_quality_total", "Sampled automatic quality metric values", ["metric", "outcome"])
INDEX_AGE = _metric(Gauge, "index_age_seconds", "Seconds since the corpus index was built")
INDEX_CHUNKS = _metric(Gauge, "index_chunks", "Corpus chunks in the active index")
INDEX_BUILT_AT = _metric(Gauge, "index_built_timestamp_seconds", "Unix timestamp of the active index build")
QUEUE_DEPTH = _metric(Gauge, "screening_queue_depth", "Queued screening jobs")
PROCESSING_DEPTH = _metric(Gauge, "screening_processing_depth", "Screening jobs claimed by workers")
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
        INDEX_CHUNKS.set(meta.get("chunks", 0))
        INDEX_BUILT_AT.set(meta["built_at"])
    queue_depth = processing_depth = None
    if redis_ok:
        try:
            queue_depth = store().r.llen(get_settings().queue_key)
            processing_depth = store().r.llen(get_settings().processing_key)
            QUEUE_DEPTH.set(queue_depth)
            PROCESSING_DEPTH.set(processing_depth)
        except redis.RedisError:
            redis_ok = False
    body = {"status": "ok" if redis_ok else "degraded", "redis": redis_ok,
            "index": {"built": bool(meta), "age_seconds": age, "chunks": (meta or {}).get("chunks")},
            "queue": {"queued": queue_depth, "processing": processing_depth}}
    return JSONResponse(body, status_code=200 if redis_ok else 503)


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness requires both the shared queue/store and a usable local corpus index."""
    response = health()
    body = json.loads(response.body)
    is_ready = response.status_code == 200 and body["index"]["built"]
    body["status"] = "ready" if is_ready else "not_ready"
    return JSONResponse(body, status_code=200 if is_ready else 503)


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
        with span("api.submit_screening", tender_id=model.tender_id):
            rec = store().create(model.model_dump(), model.flags())
            with span("queue.enqueue", run_id=rec.run_id):
                store().set_trace_context(rec.run_id, inject_context())
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


@app.post("/v1/screenings/{run_id}/feedback", status_code=201)
def feedback(run_id: str, body: FeedbackRequest) -> dict:
    """Record committee feedback and sample a transparent, non-LLM quality score."""
    rec = store().get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    sampled = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < get_settings().auto_score_sample_rate
    auto_score = None
    if sampled:
        verified = bool(rec.finding and rec.finding.verification and rec.finding.verification.passed)
        cited = bool(rec.finding and rec.finding.citations)
        grounded = verified and cited
        metrics = {"groundedness": float(grounded), "context_relevance": float(cited),
                   "faithfulness": float(grounded), "hallucination_rate": float(not grounded)}
        auto_score = {"method": "deterministic_verified_citation_check", "metrics": metrics,
                      "verification_passed": verified, "has_resolved_citations": cited}
        AUTO_SCORES.labels("grounded" if grounded else "needs_review").inc()
        for metric, value in metrics.items():
            AUTO_QUALITY.labels(metric, "positive" if value else "negative").inc(value)
    entry = {"received_at": time.time(), "satisfactory": body.satisfactory, "reason": body.reason,
             "auto_score": auto_score}
    store().save_feedback(run_id, entry)
    FEEDBACK.labels(str(body.satisfactory).lower()).inc()
    return {"run_id": run_id, "recorded": True, "sampled_for_auto_score": sampled, "auto_score": auto_score}


@app.get("/v1/feedback/summary")
def feedback_summary() -> dict:
    """Quality roll-up for L6; source entries remain append-only per run."""
    try:
        return store().feedback_summary()
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="feedback store unavailable")
