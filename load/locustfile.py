"""Stub-backed load profile. Start Compose with LLM_PROVIDER=stub before running `make load`."""
from __future__ import annotations

import json
import time
from pathlib import Path

from locust import HttpUser, between, task

SAMPLES = json.loads(Path("/app/eval/bidders.json").read_text())


class ScreeningUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def submit_compliant_bid(self) -> None:
        bid = next(item["bid"] for item in SAMPLES if item["id"] == "B2")
        started = time.perf_counter()
        with self.client.post("/v1/screenings", json=bid, name="POST /v1/screenings", catch_response=True) as response:
            if response.status_code != 202:
                response.failure(f"unexpected status {response.status_code}")
                return
            run_id = response.json().get("run_id")
            if not run_id:
                response.failure("accepted response had no run_id")
                return
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            with self.client.get(f"/v1/screenings/{run_id}", name="GET /v1/screenings/{id}", catch_response=True) as poll:
                if poll.status_code != 200:
                    poll.failure(f"unexpected status {poll.status_code}")
                    self._record_completion(started, len(poll.content), RuntimeError("status poll failed"))
                    return
                status = poll.json().get("status")
                if status in {"done", "escalated", "failed"}:
                    self._record_completion(started, len(poll.content), None)
                    return
            time.sleep(0.25)
        self._record_completion(started, 0, TimeoutError("screening did not finish within 90 seconds"))

    def _record_completion(self, started: float, response_length: int, exception: Exception | None) -> None:
        """Record submission-to-terminal-result latency, rather than only API acceptance."""
        self.environment.events.request.fire(
            request_type="SCREENING",
            name="completed screening",
            response_time=(time.perf_counter() - started) * 1000,
            response_length=response_length,
            exception=exception,
        )
