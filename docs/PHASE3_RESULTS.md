# Phase 3 measurement protocol and results

## SLO declared before measurement

The API accepts a valid request in under 250 ms at p95. With the local stub at its default 1.5-second delay, a completed screening finding has a p95 target of 30 seconds. The service must keep route accuracy and groundedness at 1.0 on the committed evaluation set. A failed verification is an escalation, not a successful answer.

## Reproducible measurements

Run `make eval` to execute 20 cases, including B1, using v1 and v2 against the stub. The JSON output contains route accuracy, groundedness, context relevance, faithfulness, and hallucination rate. These are deterministic audit proxies: a finding is grounded and faithful only if independent verification passes; context relevance requires resolved citations; hallucination rate is one minus groundedness.

Run `make load` for a two-minute 20-user stub load test. Compare workers with `docker compose up -d --scale worker=1` and `docker compose up -d --scale worker=3`, then retain Locust CSV output and the Grafana p95/throughput panels for the report. The stub delay makes this comparison repeatable without provider spend.

## Deliberate change and expected comparison

Prompt v2 asks the classifier and verifier for shorter structured outputs and keeps the compliance contract compatible with v1. `make eval` runs v1 then v2 on the same 20 cases; compare the emitted reports. A variant only qualifies if groundedness and route accuracy do not decrease.

## Cache experiment

Retrieval cache entries contain only corpus passages keyed by tool arguments. A passage is added to the current run's retrieved set before it can be cited. The `screening_retrieval_cache_total` Grafana panel measures the effect. Run the evaluation twice without flushing Redis: the second pass should show cache hits. Record p95 duration and hit ratio in the course report; do not reuse final findings from cache.
