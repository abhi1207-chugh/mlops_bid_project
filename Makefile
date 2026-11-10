.PHONY: up down ingest test eval load

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
