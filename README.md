# Bid Compliance Screening Service

Docker-only system that screens a bid against tender clauses and policy, then returns a cited finding for a tender committee. It never makes the committee's decision.

## Run from a clean clone

1. Install and start Docker Desktop.
2. `cp .env.example .env`
3. Set `GRAFANA_ADMIN_PASSWORD` in `.env`. Keep `LLM_PROVIDER=stub` for the free reproducible demo. Gemini additionally needs `LLM_API_KEY` and `LLM_MODEL`.
4. If ports conflict, set `API_PORT=8001` and `GRAFANA_PORT=3002` in `.env`.
5. Run `docker compose up --build`.
6. Open `http://localhost:8000/` (or configured API port) and select a sample bid.

The first worker start builds the local index. Check `http://localhost:8000/health` for Redis and index status.

## Commands

| Command | Purpose |
|---|---|
| `make test` | Run tests in Docker. |
| `make ingest` | Rebuild changed corpus embeddings. |
| `make eval` | Run 20 scenarios for prompt v1 and v2 using the stub. |
| `make load` | Run a two-minute Locust stub load test. |
| `docker compose up --scale worker=3` | Compare worker scaling. |

## Services

API/web: `http://localhost:8000` · Prometheus: `http://localhost:9090` · Grafana: `http://localhost:3000` · Jaeger: `http://localhost:16686`.

`POST /v1/screenings` validates and queues a bid, returning a `run_id`. Poll `GET /v1/screenings/{run_id}`. Invalid inputs are quarantined before agent work. Post committee feedback to `/v1/screenings/{run_id}/feedback` with `{"satisfactory":true,"reason":"..."}`.

The required B1 demo is a low-turnover DPIIT startup with no experience. It must escalate with clauses 5/6, both DoE orders, and GFR Rule 173(i). Failed, incomplete, or unverified work always escalates. See [runbook](docs/RUNBOOK.md), [measurement protocol](docs/PHASE3_RESULTS.md), and [report](docs/REPORT.md).

For LLMOps evidence and the exact L2--L6 evaluation/guardrail/cost/feedback methods, see [LLMOps notes](docs/LLMOPS.md). After a batch evaluation, compare prompt variants in `artifacts/eval-prompt-comparison.json`; feedback quality is available from `GET /v1/feedback/summary` and Grafana.

The corpus uses the updated NIT Rourkela tender, which closed on 08-Nov-2026. Its schedule and source details are recorded in `docs/corpus_confirmation.md`.
