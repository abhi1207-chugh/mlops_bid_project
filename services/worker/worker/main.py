"""Worker: pulls runs from the Redis queue and executes the agents."""
from __future__ import annotations

import logging
import time

import redis

from prometheus_client import Counter, Histogram, start_http_server

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
RETRIES = Counter("screening_verification_retries_total", "Verifier-driven compliance retries")
RUN_ERRORS = Counter("screening_run_errors_total", "Runs escalated because of an operational error", ["reason"])
CACHE = Counter("screening_retrieval_cache_total", "Retrieval cache outcomes", ["outcome"])
LLM_TOKENS = Counter("screening_llm_tokens_total", "LLM tokens by step and type", ["step", "type"])
LLM_COST = Counter("screening_llm_cost_total", "Recorded LLM cost by step", ["step"])


def process(store: RunStore, llm, run_id: str) -> None:
    rec = store.get(run_id)
    if rec is None:
        log(logger, "run_missing", logging.WARNING, run_id=run_id)
        return
    token = correlation_id.set(run_id)
    try:
        rec.status = "running"
        store.save(rec)
        t0 = time.perf_counter()
        with span("worker.process_run", parent=extract_context(store.get_trace_context(run_id)), run_id=run_id):
            finding, trace = run_screening(run_id, rec.bid, rec.flags, llm)
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
            LLM_TOKENS.labels(usage.step, "prompt").inc(usage.prompt_tokens)
            LLM_TOKENS.labels(usage.step, "completion").inc(usage.completion_tokens)
            LLM_COST.labels(usage.step).inc(usage.cost)
        cache_hits = sum(1 for item in trace if item.get("kind") == "cache_hit")
        cache_misses = sum(1 for item in trace if item.get("kind") == "cache_miss")
        if cache_hits:
            CACHE.labels("hit").inc(cache_hits)
        if cache_misses:
            CACHE.labels("miss").inc(cache_misses)
        log(logger, "run_finished", route=finding.route, steps=finding.steps, tool_calls=finding.tool_calls)
    finally:
        correlation_id.reset(token)


def main() -> None:
    setup_logging()
    setup_tracing("bid-compliance-worker")
    s = get_settings()
    start_http_server(9100)  # per-replica metrics, scraped via DNS service discovery
    from pipeline.ingest import ensure_index
    ensure_index()  # idempotent; locked so scaled workers do not race
    store, llm = RunStore(), get_llm_client()
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
            continue
        try:
            process(store, llm, run_id)
        except Exception:  # noqa: BLE001 - store failure; leave in processing list for inspection
            logger.exception("process_failed")
            continue
        store.r.lrem(s.processing_key, 1, run_id)


if __name__ == "__main__":
    main()
