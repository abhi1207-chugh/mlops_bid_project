# Public Procurement Bid Compliance Screening Service

Multi-agent service that screens a bid summary against a tender's mandatory conditions and the policy relaxations that can override them, then returns a cited finding. It never rejects a bid on its own authority; a tender committee decides. See `CLAUDE.md` for the rules and design, and `docs/PLAN.md` for the build order.

## Status
Phase 1 end-to-end path is built: validation and quarantine, API and Redis queue, ingestion (245 chunks, content-hashed), LLM client (stub and gemini providers), classifier / compliance / verifier agents, and a web client at `/`.
The local deterministic `stub` provider follows the same clause-retrieval loop and returns grounded demo routes without an API key. The configured provider path was also exercised for B1 (verified escalation with the required tender and policy citations) and B2 (verified pass to technical evaluation). Set `LLM_PROVIDER=gemini`, `LLM_API_KEY`, and `LLM_MODEL` in `.env` to use Gemini.
Not yet built: Phase 2 and later (circuit breaker, injection guard, rate limiting, OpenTelemetry, metrics dashboards, evaluation, feedback). A run whose worker dies mid-run stays `running` (no reaper yet).

## Run
```bash
cp .env.example .env        # set GRAFANA_ADMIN_PASSWORD; the default LLM_PROVIDER=stub needs no key
docker compose up --build
curl http://localhost:8000/health   # web client at http://localhost:8000/ (set API_PORT / GRAFANA_PORT in .env if those ports are taken)
```

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |
| Jaeger | http://localhost:16686 |

Scale workers: `docker compose up --scale worker=3`.

## Layout
```
contracts/       data contracts (JSON Schema)
corpus/          raw PDFs and extracted text (tender, DoE/DPE orders, GFR Ch.6)
docs/            plan, corpus confirmation, runbook, incident log, report
eval/            evaluation scenarios and runner
load/            Locust files
observability/   Prometheus and Grafana config
pipeline/        ingestion CLI (parse, chunk, embed, index)
prompts/         versioned prompts
services/        api, worker, stub_llm, common
tests/
```

## Corpus
See `docs/corpus_confirmation.md`.
