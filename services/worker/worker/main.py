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
from worker.agents import run_screening

logger = logging.getLogger("worker")
RUNS = Counter("screening_runs_total", "Finished runs", ["route"])
DURATION = Histogram("screening_run_seconds", "Run wall-clock seconds")


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
        finding, trace = run_screening(run_id, rec.bid, rec.flags, llm)
        rec.trace = trace
        store.finish(rec, finding)
        DURATION.observe(time.perf_counter() - t0)
        RUNS.labels(finding.route).inc()
        log(logger, "run_finished", route=finding.route, steps=finding.steps, tool_calls=finding.tool_calls)
    finally:
        correlation_id.reset(token)


def main() -> None:
    setup_logging()
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
