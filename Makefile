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
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 -e PROMPT_VERSION=v1 worker python -m eval.run
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 -e PROMPT_VERSION=v2 worker python -m eval.run

load:
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 worker locust -f load/locustfile.py --headless -u 20 -r 2 -t 2m --host http://api:8000

# Produces comparable Locust CSV files from Docker-only workloads.  Start from a
# clean stack, then retain artifacts/load-worker{1,3}_*.csv as submission evidence.
scale-benchmark:
	# Keep Grafana/Jaeger out of this lifecycle so a dashboard port conflict cannot invalidate the load test.
	RATE_LIMIT_PER_MINUTE=100000 docker compose up -d --build --scale worker=1 redis stub-llm api worker
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 worker locust -f load/locustfile.py --headless -u 20 -r 2 -t 2m --csv=/artifacts/load-worker1 --csv-full-history --host http://api:8000
	docker compose up -d --scale worker=3 worker
	docker compose run --rm -e LLM_PROVIDER=stub -e LLM_BASE_URL=http://stub-llm:8080 worker locust -f load/locustfile.py --headless -u 20 -r 2 -t 2m --csv=/artifacts/load-worker3 --csv-full-history --host http://api:8000
