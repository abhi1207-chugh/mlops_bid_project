# LLMOps evidence (L2–L6)

## L2: versioned prompts and controlled comparison

Prompts are versioned files in `prompts/<agent>/vN.md`. `load_prompt` resolves an
agent-specific override (for example, `COMPLIANCE_PROMPT_VERSION=v2`) and records
the version used by each agent in the persisted finding and trace.

The L3 experiment is paired on the same fixed 20-scenario dataset using the local
stub provider. It deliberately changes only the compliance prompt:

| Agent | Before | After |
|---|---|---|
| Classifier | v1 | v1 |
| Compliance | v1 | v2 |
| Verifier | v1 | v1 |

This isolates the effect of the compliance prompt change. `make eval` writes
`artifacts/eval-v1.json`, `artifacts/eval-v2.json`, and
`artifacts/eval-prompt-comparison.json`. The comparison checks that case IDs and
ordering match, reports deltas for route accuracy and all four L3 quality metrics,
and only declares a single winner when it is no worse on every compared metric.

**Run the experiment before recording scores.** The previously committed v1-only
evaluation used an older scenario set and is not a valid before/after result for the
current L3 benchmark. Do not reuse its figures as current experiment results.

## L3: fixed evidence-backed evaluation

`eval/scenarios.py` creates 20 valid, in-scope retrieval scenarios. Each has an
expected route and one or more supporting evidence entries containing the document
ID, clause/paragraph reference, and supporting passage text copied from the
repository corpus. B1 is the required section 4.1 startup-policy conflict. The
remaining cases exercise large-enterprise threshold boundaries, incomplete turnover
evidence, mandatory-document omissions, MSE exemption/trader handling, and startup
DPIIT evidence.

Malformed/quarantined and unsupported-category requests are not included in the
retrieval-quality denominator: they must not reach the LLM or retrieval system and
are handled by the contract/guardrail path. In-scope timeouts and failed runs remain
in the denominator as unsuccessful findings.

Run both prompt variants and the comparison from the command line:

```bash
make test
make eval
```

The evaluator is a deterministic equivalent to a groundedness evaluator, using the
independent citation verifier and scenario-labelled corpus evidence:

- **Groundedness:** number of findings with `verification.passed=true`, divided by
  all 20 in-scope scenarios.
- **Context relevance:** number of unique cited document/clause references that
  match the scenario's labelled supporting passages, divided by all unique cited
  document/clause references.
- **Faithfulness:** number of scenarios with a passed verifier and citations on
  every evidence-bearing condition, divided by all 20 in-scope scenarios.
- **Hallucination rate:** `1 - faithfulness`.

The JSON reports include the numerator/denominator counts, definitions, expected
support passages, expected/actual routes, findings, and prompt versions observed.
The generated paired comparison reports the v1 value, v2 value, absolute delta,
percentage-point change, and which version is better for each metric. Hallucination
rate is lower-is-better. Scores are intentionally not pre-filled; they must come from
the completed run of `make eval`.

## L4: guardrails

Validation scans every string that is later serialised into a model prompt, not only
`remarks`, for prompt-injection and abusive/threatening text. Invalid requests are
quarantined and never queued. The complete final structured model output (including
citation quotes) is checked for toxicity and unauthorised autonomous determinations.
Unsafe or unverified output is escalated rather than returned as a screening finding.

## L5: usage and cost

Each LLM call records prompt tokens, completion tokens, configured cost, latency, step,
prompt version, and run ID. The worker persists usage on the finding and exports
`screening_llm_tokens_total` and `screening_llm_cost_total{step}`. Grafana displays
cost per 100 runs and the highest-cost step. Stub cost is intentionally zero; for a
provider run set the documented per-1K token prices in the environment and use:

`100 * sum(increase(screening_llm_cost_total[1h])) / sum(increase(screening_runs_total[1h]))`

The `topk(1, sum(increase(screening_llm_cost_total[1h])) by (step))` panel identifies
the largest cost driver.

## L6: feedback and live quality

`POST /v1/screenings/{run_id}/feedback` stores satisfactory/unsatisfactory feedback and
a required reason as append-only Redis records. `GET /v1/feedback/summary` aggregates
the persisted records. A configurable sample of live runs is automatically scored
with the deterministic quality metrics used by evaluation. Prometheus records sampled
dimensions and Grafana charts feedback and sampled quality over time.
