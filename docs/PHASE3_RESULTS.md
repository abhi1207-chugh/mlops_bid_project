# Phase 3 measurement protocol and results

## SLO declared before measurement

The API accepts a valid request in under 250 ms at p95. With the local stub at its default 1.5-second delay, a completed screening finding has a p95 target of 30 seconds. The service must keep route accuracy and groundedness at 1.0 on the committed evaluation set. A failed verification is an escalation, not a successful answer.

## Reproducible measurements

Run `make eval` to execute 20 cases, including B1, using v1 and v2 against the stub. The JSON output contains route accuracy, groundedness, context relevance, faithfulness, and hallucination rate. These are deterministic audit proxies: a finding is grounded and faithful only if independent verification passes; context relevance requires resolved citations; hallucination rate is one minus groundedness.

Run `make load` for a two-minute 20-user stub load test. The controlled `make scale-benchmark` target performs the one-worker and three-worker comparison with the same 20-user profile, 2-user/s ramp, and four-minute run duration. It waits for services/workers to become healthy and for Redis queues to drain between configurations. The Locust profile records both API acceptance and a `SCREENING / completed screening` measurement from submission through polling to a terminal result; report the latter for the complete-run SLO and scaling result. The controlled CSV outputs use the `artifacts/load-worker1-controlled_*.csv` and `artifacts/load-worker3-controlled_*.csv` prefixes. Retain those files and Grafana p50/p95, throughput, per-agent task-success, and worker-uptime panels for the report. The stub delay makes this comparison repeatable without provider spend.

## Historical measured scaling result — 10-Nov-2026

The earlier benchmark used the local stub, 20 Locust users, a 2-user/s ramp, and a two-minute duration. The API rate limit was raised to 100,000 requests/minute only for this isolated load run; the normal configured rate limit remains unchanged.

- One worker: 272 completed screenings, 2.29 completed screenings/s, p50 270 ms, p95 71 s, p99 76 s, and zero Locust failures. The complete-run 30-second p95 SLO was **not met** because a single FIFO worker accumulated a queue.
- Three workers: 830 completed screenings, 7.00 completed screenings/s, p50 270 ms, p95 530 ms, p99 16 s, and zero Locust failures. The complete-run p95 SLO was **met**.

Three workers increased completed-screening throughput by 3.06× and reduced p95 from 71 seconds to 530 ms in that earlier test. These are historical results from a different two-minute benchmark profile; do not combine them with the controlled four-minute results below. Raw evidence is retained in the original `artifacts/load-worker1_*.csv` and `artifacts/load-worker3_*.csv` files.

## Controlled measured scaling result — 12-Nov-2026

A new controlled comparison was run with the Stub provider, 20 Locust users, a 2-user/s ramp, a four-minute run duration, a 300-second per-screening timeout, one-second status polling, and a 360-second Locust stop timeout. The API rate limit was set to 100,000 requests/minute for this isolated benchmark only. The Makefile waited for healthy workers and drained the Redis queue/processing list before changing worker count and after the run.

The values below are taken from the controlled Locust `*_stats.csv` rows for `SCREENING / completed screening`, which measure submission-to-terminal-result latency rather than API acceptance:

| Metric | One worker | Three workers |
|---|---:|---:|
| Completed-screening measurements | 40 | 81 |
| Failures | 0 | 0 |
| Average completion latency | 161.33 s | 63.01 s |
| Median completion latency | 212.00 s | 70.00 s |
| Maximum completion latency | 214.93 s | 75.85 s |
| p95 completion latency | 215.00 s | 74.00 s |
| Completed-screening throughput | 0.0904/s | 0.2643/s |

On this controlled run, three workers delivered approximately **2.92×** the completed-screening throughput of one worker, a **60.9% reduction** in average completion latency, and a **65.6% reduction** in p95 completion latency. Both configurations recorded zero failures in the completed-screening measurement. The 30-second complete-run p95 SLO was **not met** by either configuration in this four-minute run (three-worker p95: 74 seconds).

The final three-worker Locust console screenshot showed 83 completed-screening events, while the extracted controlled `*_stats.csv` row reported 81. The comparison table uses the CSV row consistently; preserve both the CSVs and terminal output, and treat the two-count discrepancy as a reporting caveat rather than silently reconciling it. The final terminal check showed all three workers healthy and both Redis queue lengths at zero.

Controlled raw evidence is retained in:
- `artifacts/load-worker1-controlled_stats.csv`
- `artifacts/load-worker1-controlled_stats_history.csv`
- `artifacts/load-worker1-controlled_failures.csv`
- `artifacts/load-worker1-controlled_exceptions.csv`
- `artifacts/load-worker3-controlled_stats.csv`
- `artifacts/load-worker3-controlled_stats_history.csv`
- `artifacts/load-worker3-controlled_failures.csv`
- `artifacts/load-worker3-controlled_exceptions.csv`

## Deliberate change and expected comparison

Prompt v2 asks the classifier and verifier for shorter structured outputs and keeps the compliance contract compatible with v1. `make eval` runs v1 then v2 on the same 20 cases; compare the emitted reports. A variant only qualifies if groundedness and route accuracy do not decrease.

## Cache experiment

Retrieval cache entries contain only corpus passages keyed by tool arguments. A passage is added to the current run's retrieved set before it can be cited. The `screening_retrieval_cache_total` Grafana panel measures the effect. Run the evaluation twice without flushing Redis: the second pass should show cache hits. Record p95 duration and hit ratio in the course report; do not reuse final findings from cache.
