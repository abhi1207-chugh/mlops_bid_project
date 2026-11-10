# AGENTS.md: Bid Compliance Screening Service

Course project: UE24AM342AA5 ML System Design & AgentOps, Mini Project 06 (PESU).
Read `docs/PLAN.md` for the build order and `docs/corpus_confirmation.md` for the corpus and the demo case.

## What this system does
A multi-agent service that takes a bid summary, validates it, decides which mandatory tender conditions are met or unmet, and returns a routed finding with citations. A tender committee decides. The system never rejects or qualifies a bid on its own authority; its output is a screening finding.

Routes: `pass_to_technical_evaluation`, `seek_clarification`, `reject_with_cited_condition`, and `escalate_to_human` (used when the tender and the policy conflict, the bidder category is unclear, or the corpus cannot answer).

## Hard rules (do not break these)
1. **A run that did not complete or did not verify is never returned as a confident answer.** It escalates.
2. **Every citation must resolve to text actually retrieved in that run.** The verifier checks this before returning anything.
3. **No credentials, endpoints or model identifiers in the repo.** All come from env vars (`.env.example` documents them; the real `.env` is git-ignored). Model access goes through `LLMClient` in `services/common/llm.py` so the provider is swappable by config.
4. **A malformed request must not start an agent run.** Validate at the API boundary, quarantine rejects with field-level errors.
5. **Retrieval is a tool the agent chooses to call**, not a fixed pipeline stage. The loop is bounded by steps, tool calls and wall-clock time.
6. Nothing runs outside Docker. `docker compose up` from a clean clone must work.
7. Establish a working end-to-end path first. Add requirements after that. If the system does not start at the demo, the project gets zero.

## Architecture (planned)
- `api` (FastAPI): validates, quarantines, enqueues, returns `run_id` immediately. Status and result endpoints, feedback endpoint, `/health`, `/metrics`.
- `worker` (scalable with `--scale worker=3`): pulls runs from the Redis queue and executes the LangGraph agents.
- Agents in the worker:
  - **Classifier agent**: classifies the bidder (large enterprise, MSE, startup, consortium, foreign) and extracts the qualification entities. Unclear category means escalate.
  - **Compliance agent**: per mandatory condition, retrieves the tender clause, then looks for modifying provisions (policy orders, GFR), re-searches using what it read, produces findings, then routes.
  - **Verifier** (a separate node with its own prompt): checks every claim and citation against the retrieved passages. Failure means search again with a different strategy, or escalate.
- Agent tools: `search_corpus(query, source_filter)`, `get_clause(doc_id, clause_ref)`, `get_bid_field(field)`.
- `redis`: queue, cache, rate-limit counters.
- `stub-llm`: fixed responses after a realistic delay, used for Locust load tests.
- `prometheus`, `grafana`, `jaeger`: metrics, dashboard, traces.
- Retrieval: LangChain with FAISS, embeddings from sentence-transformers (`all-MiniLM-L6-v2`) run locally. Chunks carry metadata (`doc_id`, `page`, `clause_ref`, `doc_type` of `tender` or `policy`, `date`).
- Index is built by a CLI pipeline (`python -m pipeline.ingest`), idempotent, content-hashed per file so only changed documents are re-embedded.

## Conventions
- Python 3.11. Type hints. Pydantic v2 models for all external interfaces.
- Structured JSON logs. Every log line and span carries `correlation_id` (= `run_id`).
- Every LLM call records prompt version, prompt tokens, completion tokens and cost, per step.
- Prompts live in `prompts/<name>/vN.md`. The version used is recorded with every response.
- Tests in `tests/` (pytest). Evaluation scenarios in `eval/scenarios.jsonl`.

## The demo case (section 4.1): must be handled correctly
Tender: NIT Rourkela LTE NITR/PW/CIC-LTE/2026/390 (Supply of Network Switches). A DPIIT-recognised startup with 3-year average turnover Rs 40,00,000 against the tender's Rs 1,50,00,000 (Clause 5) and no past supply (Clause 6). The tender never mentions a startup relaxation. The correct result is **escalate_to_human** citing Clauses 5 and 6, the DoE OMs of 25-Jul-2016 and 20-Sep-2016, and GFR Rule 173(i). The EMD is not a conflict here: Clause 3 already exempts DPIIT startups. See `docs/corpus_confirmation.md` for the 12 test bidders (B1-B12).

Tender-version clarification: the corpus uses the **updated** NIT Rourkela tender issued 05-Nov-2026, which closed on 08-Nov-2026 at 10:00. The earlier/original tender version had a 26-Nov-2026 closing date; that is not the version used by this project. The updated tender is closed and satisfies the brief's closed-tender requirement. See `docs/corpus_confirmation.md` and `corpus/manifest.json`.

## Commands
- `cp .env.example .env` then fill in values
- `docker compose up --build`
- `make ingest` builds the index in the worker image
- `make test`
- `make eval` runs the evaluation batch
- `make load` runs Locust against the stub
