"""Worker: pulls runs from the Redis queue and executes the agents."""
from __future__ import annotations

import logging
import json
import threading
import time
from wsgiref.simple_server import WSGIRequestHandler, make_server

import redis

from prometheus_client import Counter, Gauge, Histogram, make_wsgi_app

from common.config import get_settings
from common.llm import get_llm_client
from common.logging import correlation_id, log, setup_logging
from common.runstore import RunStore
from common.tracing import extract_context, setup_tracing, span
from worker.agents import run_screening

logger = logging.getLogger("worker")
RUNS = Counter("screening_runs_total", "Finished runs", ["route"])
DURATION = Histogram("screening_run_seconds", "Run wall-clock seconds")
AGENT_STEPS = Histogram("screening_agent_steps", "LLM calls per completed run")
TOOL_CALLS = Histogram("screening_tool_calls", "Tool calls per completed run")
VERIFICATIONS = Counter("screening_verifications_total", "Verification outcomes", ["outcome"])
AGENT_CALLS = Counter("screening_agent_calls_total", "Successful LLM calls", ["agent"])
AGENT_TASKS = Counter("screening_agent_tasks_total", "Agent task outcomes", ["agent", "outcome"])
STEP_DURATION = Histogram("screening_agent_step_seconds", "Latency for each completed LLM step", ["agent"])
RETRIES = Counter("screening_verification_retries_total", "Verifier-driven compliance retries")
RUN_ERRORS = Counter("screening_run_errors_total", "Runs escalated because of an operational error", ["reason"])
CACHE = Counter("screening_retrieval_cache_total", "Retrieval cache outcomes", ["outcome"])
LLM_TOKENS = Counter("screening_llm_tokens_total", "LLM tokens by step and type", ["step", "type"])
LLM_COST = Counter("screening_llm_cost_total", "Recorded LLM cost by step", ["step"])
QUEUE_DEPTH = Gauge("screening_queue_depth", "Queued screening jobs")
PROCESSING_DEPTH = Gauge("screening_processing_depth", "Screening jobs claimed by workers")
WORKER_READY = Gauge("screening_worker_ready", "Whether this worker is ready to process jobs")
WORKER_HEARTBEATS = Counter("screening_worker_heartbeats_total", "Run lease renewals")


class QuietHandler(WSGIRequestHandler):
    """Prometheus handles scrape logs; avoid noisy non-structured WSGI access output."""

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def worker_wsgi_app(ready: threading.Event):
    metrics_app = make_wsgi_app()

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path in {"/health", "/ready"}:
            is_ready = ready.is_set()
            status = "200 OK" if is_ready else "503 Service Unavailable"
            payload = json.dumps({"status": "ready" if is_ready else "starting", "worker_ready": is_ready}).encode()
            start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
            return [payload]
        return metrics_app(environ, start_response)

    return app


def start_worker_http(ready: threading.Event) -> None:
    server = make_server("", 9100, worker_wsgi_app(ready), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True, name="worker-observability").start()


def update_queue_metrics(store: RunStore) -> None:
    try:
        QUEUE_DEPTH.set(store.r.llen(get_settings().queue_key))
        PROCESSING_DEPTH.set(store.r.llen(get_settings().processing_key))
    except redis.RedisError:
        pass


def process(store: RunStore, llm, run_id: str) -> None:
    rec = store.get(run_id)
    if rec is None:
        log(logger, "run_missing", logging.WARNING, run_id=run_id)
        return
    token = correlation_id.set(run_id)
    heartbeat_stop = threading.Event()

    def renew_lease() -> None:
        while not heartbeat_stop.wait(10):
            try:
                if not store.heartbeat(run_id):
                    return
                WORKER_HEARTBEATS.inc()
            except redis.RedisError:
                log(logger, "heartbeat_failed", logging.WARNING, run_id=run_id)

    try:
        rec.status = "running"
        store.save(rec)
        threading.Thread(target=renew_lease, daemon=True, name=f"run-heartbeat-{run_id[:8]}").start()
        t0 = time.perf_counter()
        with span("worker.process_run", parent=extract_context(store.get_trace_context(run_id)), run_id=run_id):
            finding, trace = run_screening(run_id, rec.bid, rec.flags, llm)
        heartbeat_stop.set()
        rec.trace = trace
        store.finish(rec, finding)
        DURATION.observe(time.perf_counter() - t0)
        RUNS.labels(finding.route).inc()
        AGENT_STEPS.observe(finding.steps)
        TOOL_CALLS.observe(finding.tool_calls)
        VERIFICATIONS.labels("passed" if finding.verification and finding.verification.passed else "not_passed").inc()
        if finding.verification and finding.verification.attempts > 1:
            RETRIES.inc(finding.verification.attempts - 1)
        if finding.escalation_reason in {"run_incomplete", "llm_unavailable", "run_error", "verification_failed"}:
            RUN_ERRORS.labels(finding.escalation_reason).inc()
        for usage in finding.usage:
            AGENT_CALLS.labels(usage.step).inc()
            STEP_DURATION.labels(usage.step).observe(usage.latency_ms / 1000)
            LLM_TOKENS.labels(usage.step, "prompt").inc(usage.prompt_tokens)
            LLM_TOKENS.labels(usage.step, "completion").inc(usage.completion_tokens)
            LLM_COST.labels(usage.step).inc(usage.cost)
        cache_hits = sum(1 for item in trace if item.get("kind") == "cache_hit")
        cache_misses = sum(1 for item in trace if item.get("kind") == "cache_miss")
        if cache_hits:
            CACHE.labels("hit").inc(cache_hits)
        if cache_misses:
            CACHE.labels("miss").inc(cache_misses)
        # A task success is deliberately stricter than a transport-successful LLM call.
        # It lets the dashboard expose the rate at which each independent role completed
        # its responsibility without needing to infer it from routes.
        classifier_ok = any(item.get("kind") == "classified" and item.get("category") in {
            "large_enterprise", "mse", "startup"
        } for item in trace) and finding.escalation_reason != "bidder_category_unclear"
        compliance_ok = bool(any(u.step == "compliance" for u in finding.usage)) and finding.escalation_reason not in {
            "run_incomplete", "llm_unavailable", "run_error", "verification_failed"
        }
        verifier_ok = bool(finding.verification and finding.verification.passed)
        for agent, ok in (("classifier", classifier_ok), ("compliance", compliance_ok), ("verifier", verifier_ok)):
            AGENT_TASKS.labels(agent, "success" if ok else "failure").inc()
        log(logger, "run_finished", route=finding.route, steps=finding.steps, tool_calls=finding.tool_calls)
    finally:
        heartbeat_stop.set()
        correlation_id.reset(token)


def main() -> None:
    setup_logging()
    setup_tracing("bid-compliance-worker")
    s = get_settings()
    ready = threading.Event()
    start_worker_http(ready)  # metrics plus readiness on one per-replica scrape endpoint
    from pipeline.ingest import ensure_index
    from worker.retrieval import warm_corpus
    ensure_index()  # idempotent; locked so scaled workers do not race
    warm_corpus()  # avoid spending the first agent tool-call deadline on model/FAISS initialization
    store, llm = RunStore(), get_llm_client()
    WORKER_READY.set(1)
    ready.set()
    log(logger, "worker_ready")
    while True:
        try:
            recovered = store.recover_processing()
            if recovered:
                log(logger, "stale_runs_requeued", count=recovered)
            run_id = store.r.blmove(s.queue_key, s.processing_key, 5, "RIGHT", "LEFT")
        except redis.RedisError as exc:
            log(logger, "queue_error", logging.WARNING, error=type(exc).__name__)
            time.sleep(2)
            continue
        if not run_id:
            update_queue_metrics(store)
            continue
        try:
            process(store, llm, run_id)
        except Exception:  # noqa: BLE001 - store failure; leave in processing list for inspection
            logger.exception("process_failed")
            continue
        store.r.lrem(s.processing_key, 1, run_id)
        update_queue_metrics(store)


if __name__ == "__main__":
    main()
