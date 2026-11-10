# Runbook

## Redis unavailable

Symptom: `/health` reports `redis: false` or submissions return 503.

Check: `docker compose ps redis` and `docker compose logs redis`.

Recovery: restart Redis, then restart the API and worker. Requests that were not accepted must be submitted again.

## LLM unavailable or circuit open

Symptom: findings escalate with `llm_unavailable`.

Check: worker logs for `llm_call_failed` or `LLMCircuitOpen`.

Recovery: restore provider connectivity. The circuit closes automatically after `CIRCUIT_BREAKER_RESET_SECONDS`; resubmit any escalated bid if the committee needs a fresh screening.

## Run stuck in processing

Symptom: a run remains `running` after the worker stops.

Check: `docker compose logs worker` and the `/v1/screenings/{run_id}` endpoint.

Recovery: workers requeue stale processing entries after 120 seconds. Restart the worker if none is running.

## Missing or stale index

Symptom: `/health` reports no built index or retrieval fails.

Check: `/health` index metadata.

Recovery: run `make ingest`, then restart workers.

## Jaeger trace missing

Symptom: no trace appears after a screening run.

Check: `docker compose ps jaeger`, `docker compose logs api worker`, and `OTEL_EXPORTER_OTLP_ENDPOINT` in `.env`.

Recovery: set the endpoint to `jaeger:4317`, restart API and worker, submit a new bid, then search Jaeger for `bid-compliance-api` or `bid-compliance-worker`.
