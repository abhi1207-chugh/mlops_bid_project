# Phase 3 measurement protocol and results

## SLO declared before measurement

The API accepts a valid request in under 250 ms at p95. With the local stub at its default 1.5-second delay, a completed screening finding has a p95 target of 30 seconds. The service must keep route accuracy and groundedness at 1.0 on the committed evaluation set. A failed verification is an escalation, not a successful answer.

## Reproducible measurements

Run `make eval` to execute 20 cases, including B1, using v1 and v2 against the stub. The JSON output contains route accuracy, groundedness, context relevance, faithfulness, and hallucination rate. These are deterministic audit proxies: a finding is grounded and faithful only if independent verification passes; context relevance requires resolved citations; hallucination rate is one minus groundedness.

Run `make load` for a two-minute 20-user stub load test. `make scale-benchmark` performs the required one-worker and three-worker comparison and saves the Docker-generated Locust CSV files as `artifacts/load-worker1_*.csv` and `artifacts/load-worker3_*.csv`. The Locust profile records both API acceptance and a `SCREENING / completed screening` measurement from submission through polling to a terminal result; report the latter for the complete-run SLO and scaling result. Retain those files and Grafana p50/p95, throughput, per-agent task-success, and worker-uptime panels for the report. The stub delay makes this comparison repeatable without provider spend.

## Measured scaling result — 10-Nov-2026

The benchmark used the local stub, 20 Locust users, a 2-user/s ramp, and a two-minute duration. The API rate limit was raised to 100,000 requests/minute only for this isolated load run; the normal configured rate limit remains unchanged.

- One worker: 272 completed screenings, 2.29 completed screenings/s, p50 270 ms, p95 71 s, p99 76 s, and zero Locust failures. The complete-run 30-second p95 SLO was **not met** because a single FIFO worker accumulated a queue.
- Three workers: 830 completed screenings, 7.00 completed screenings/s, p50 270 ms, p95 530 ms, p99 16 s, and zero Locust failures. The complete-run p95 SLO was **met**.

Three workers increased completed-screening throughput by 3.06× and reduced p95 from 71 seconds to 530 ms. The identified bottleneck is the single worker's serial screening/LLM loop, rather than API acceptance. Raw evidence is retained in `artifacts/load-worker1_*.csv` and `artifacts/load-worker3_*.csv`.

## Deliberate change and expected comparison

Prompt v2 asks the classifier and verifier for shorter structured outputs and keeps the compliance contract compatible with v1. `make eval` runs v1 then v2 on the same 20 cases; compare the emitted reports. A variant only qualifies if groundedness and route accuracy do not decrease.

## Cache experiment

Retrieval cache entries contain only corpus passages keyed by tool arguments. A passage is added to the current run's retrieved set before it can be cited. The `screening_retrieval_cache_total` Grafana panel measures the effect. Run the evaluation twice without flushing Redis: the second pass should show cache hits. Record p95 duration and hit ratio in the course report; do not reuse final findings from cache.
