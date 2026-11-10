# Build Plan

Order matters. Finish each phase so that `docker compose up` still works before starting the next. Requirement IDs refer to the project brief (F = functional, A = agent, L = LLMOps, D = platform).

## Phase 0: Setup (done)
- [x] Corpus chosen and confirmed (`docs/corpus_confirmation.md`)
- [x] Repo skeleton, Compose stack, config, CLAUDE.md

## Phase 1: Working end-to-end path (target: week 2). Nothing else counts without this.
- [x] **Data contract + validation** (F1, F2, D1): `contracts/bid_summary.schema.json`, Pydantic model, schema/range/category/cross-field checks, quarantine store with field-level errors
- [x] **API + queue** (A4): `POST /v1/screenings` returns `run_id` at once; `GET /v1/screenings/{id}` for status and result; worker consumes from Redis
- [x] **Ingestion** (D2, L1): parse PDFs (OCR'd text already in `corpus/text/`), chunk with clause-aware metadata, embed locally, FAISS index, per-file hash for incremental re-embedding, freshness metrics
- [x] **LLM client** with provider interface and stub support
- [x] **Agents** (A1, A2, A3, F3-F7): classifier agent, compliance agent with three tools, verifier, bounded loop, escalation
- [x] **Web client** (A8): one HTML page, submit, poll, show recommendation, citations, escalation path
- [x] Demo items 1, 2, 5, 10 working (verified 08-Nov-2026: Compose path and B1/B2/B9 API runs; B1 used the configured provider and returned a verified escalation with Clauses 3, 5, 6, both DoE OMs and GFR Rule 173(i))

## Phase 2: Robustness and safety
- [x] Timeouts, retry with exponential backoff, circuit breaker, fallback path (A5): demo item 8
- [x] Prompt injection defence, output filter (cannot issue a determination), toxicity check (L4): demo item 7
- [x] Verification failure -> re-search -> escalate path demonstrable (A3): demo item 6
- [x] Structured logs, correlation ID, OpenTelemetry to Jaeger, run reconstruction by `run_id` (D5, F8): demo item 3
- [x] Rate limiting per client (D7)

## Phase 3: Measurement
- [x] Per-step token and cost tracking (L5)
- [x] Prometheus metrics + Grafana dashboard: p50/p95, error rate, throughput, availability, per-agent success rate, steps/tool calls per run, retry rate (A6, D5)
- [x] Declare the p95 SLO **before** measuring (D6); Locust against stub; `--scale worker=3` comparison (A7): demo item 9
- [x] Caching and measured effect (D7)
- [x] Evaluation set, at least 20 scenarios, including 4.1 (L3); metrics: groundedness, context relevance, faithfulness, hallucination rate; one deliberate change and before/after
- [x] Two prompt variants compared on the same set (L2)
- [x] Feedback endpoint + sampled auto-scoring (L6)

## Phase 4: Documentation
- [x] README that a stranger can follow to run the system
- [x] Runbook for the two most likely failures + incident log with at least one real entry (D8). Log real failures **as they happen during development**.
- [x] Report: scope, agent design (topology, tools, verification, loop limits), architecture diagram with deployment boundaries, rejected alternatives, before/after eval, SLO/results/bottleneck/cost per 100 runs, what did not work

## Demo checklist (10 items)
1 compose up from clean clone | 2 valid request with citations | 3 one run traced end to end | 4 malformed request quarantined, no agent started | 5 corpus cannot answer -> escalation | 6 verifier catches unsupported answer | 7 injection attempt blocked | 8 circuit breaker opens, degradation | 9 Locust results + scale effect | 10 the 4.1 case

## Prioritisation notes
Completing all 22 requirements is not expected. Cut from the end of Phase 3 first (L6, L2), and write down what was cut and why. That reasoning is assessed.

## Suggested split for a team of 2-3
- A: API, validation, queue, web client, Compose
- B: ingestion, retrieval, agents, verification
- C: observability, evaluation, load testing, report
