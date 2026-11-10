# LLMOps evidence (L2--L6)

## L2: versioned prompts and comparison

Prompts are immutable files in `prompts/<agent>/vN.md`. `load_prompt` returns the
version identifier and every `UsageRecord`, persisted `Finding`, structured log, and
trace records it. `make eval` runs the same fixed 20 scenarios against `v1` and `v2`,
writes `artifacts/eval-v1.json` and `artifacts/eval-v2.json`, then writes the numeric
comparison to `artifacts/eval-prompt-comparison.json`.

The deliberate v2 change is shorter, more explicit structured-output wording for the
classifier and verifier. The candidate is selected only when route accuracy and
faithfulness do not decrease. With the deterministic stub, the expected baseline and
candidate results are both route accuracy, groundedness, context relevance, and
faithfulness of 1.0 (hallucination rate 0.0), so the measured delta is 0.0. A provider
evaluation must use the generated comparison artefact rather than assume the stub
result transfers to that provider.

## L3: fixed evaluation and equivalent metrics

`eval/scenarios.py` constructs 20 immutable cases from the committed bidders, including
B1 (the required startup-policy conflict). Every model-run case has `expected_route`
and `expected_support` as `(doc_id, clause_ref)` pairs. Invalid B11/B12 requests are
also in the batch, but excluded from retrieval-quality denominators because safety rules
prevent them reaching a model.

The evaluator is a deterministic equivalent to a groundedness evaluator:

- **Groundedness:** independent verifier passed.
- **Context relevance:** at least one cited passage is in the case's expected support.
- **Faithfulness:** verifier passed and each condition with evidence has a citation.
- **Hallucination rate:** `1 - faithfulness` over evaluated model findings.

The v1/v2 artefacts are the before/after report for one deliberate prompt change.

## L4: guardrails

Validation scans every string that is later serialised into a model prompt, not only
`remarks`, for prompt-injection and abusive/threatening text. Invalid requests are
quarantined and never queued. The complete final structured model output (including
citation quotes) is checked for toxicity and unauthorised autonomous determinations.
Unsafe or unverified output is escalated rather than returned as a screening finding.

## L5: usage and cost

Each LLM call records prompt tokens, completion tokens, configured cost, latency, step,
prompt version, and run ID. The worker persists the usage on the finding and exports
`screening_llm_tokens_total` and `screening_llm_cost_total{step}`. Grafana displays
cost per 100 runs and the highest-cost step. Stub cost is intentionally zero; for a
provider run set the documented per-1K token prices in the environment and use:

`100 * sum(increase(screening_llm_cost_total[1h])) / sum(increase(screening_runs_total[1h]))`

The `topk(1, sum(increase(screening_llm_cost_total[1h])) by (step))` panel identifies
the largest cost driver.

## L6: feedback and live quality

`POST /v1/screenings/{run_id}/feedback` stores satisfactory/unsatisfactory feedback and
a required reason as append-only Redis records. `GET /v1/feedback/summary` aggregates
the persisted records. A configurable sample of live runs is automatically scored with
the same four deterministic quality metrics used by evaluation. Prometheus records the
sampled dimensions and Grafana charts feedback and sampled quality over time.
