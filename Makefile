.PHONY: up down ingest test eval load scale-benchmark

up:
	docker compose up --build

down:
	docker compose down

ingest:
	docker compose run --rm worker python -m pipeline.ingest

test:
	docker compose run --rm worker pytest -q tests

eval:
	STUB_DELAY_MS=$${EVAL_STUB_DELAY_MS:-0} LLM_PROVIDER=stub LLM_BASE_URL=http://stub-llm:8080 PROMPT_VERSION=v1 docker compose up -d --force-recreate --scale worker=1 stub-llm worker
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 -e PROMPT_VERSION=v1 -e EVAL_OUTPUT_PATH=/artifacts/eval-v1.json worker python -m eval.run
	STUB_DELAY_MS=$${EVAL_STUB_DELAY_MS:-0} LLM_PROVIDER=stub LLM_BASE_URL=http://stub-llm:8080 PROMPT_VERSION=v2 docker compose up -d --force-recreate --scale worker=1 stub-llm worker
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 -e PROMPT_VERSION=v2 -e EVAL_OUTPUT_PATH=/artifacts/eval-v2.json worker python -m eval.run
	docker compose run --rm -e EVAL_COMPARISON_PATH=/artifacts/eval-prompt-comparison.json worker python -m eval.compare

load:
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 worker locust -f load/locustfile.py --headless -u 20 -r 2 -t 2m --host http://api:8000

# Produces comparable Locust CSV files from Docker-only workloads.  Start from a
# clean stack, then retain artifacts/load-worker{1,3}_*.csv as submission evidence.

scale-benchmark:
	# Start one worker with the stub provider
	LLM_PROVIDER=stub LLM_BASE_URL=http://stub-llm:8080 RATE_LIMIT_PER_MINUTE=100000 docker compose up -d --build --force-recreate --scale worker=1 redis stub-llm api worker

	# Run one-worker benchmark
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 worker locust -f load/locustfile.py --headless -u 20 -r 2 -t 2m --csv=/artifacts/load-worker1 --csv-full-history --host http://api:8000

	# Restart all workers with the stub provider and scale to three
	LLM_PROVIDER=stub LLM_BASE_URL=http://stub-llm:8080 RATE_LIMIT_PER_MINUTE=100000 docker compose up -d --force-recreate --scale worker=3 worker

	# Run three-worker benchmark
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 worker locust -f load/locustfile.py --headless -u 20 -r 2 -t 2m --csv=/artifacts/load-worker3 --csv-full-history --host http://api:8000
