"""Stub-backed load profile. Start Compose with LLM_PROVIDER=stub before running `make load`."""
from __future__ import annotations

import json
from pathlib import Path

from locust import HttpUser, between, task

SAMPLES = json.loads(Path("/app/eval/bidders.json").read_text())


class ScreeningUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def submit_compliant_bid(self) -> None:
        bid = next(item["bid"] for item in SAMPLES if item["id"] == "B2")
        with self.client.post("/v1/screenings", json=bid, name="POST /v1/screenings", catch_response=True) as response:
            if response.status_code != 202:
                response.failure(f"unexpected status {response.status_code}")
