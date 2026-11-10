"""Provider-agnostic LLM interface (swappable by config; see .env.example).

Provider, endpoint, key and model come from env vars only (hard rule 3). Every call has a timeout and a
bounded retry with exponential backoff. A process-local circuit breaker stops repeated failed calls and
lets the agent return its safe escalation path.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from common.logging import log

logger = logging.getLogger("llm")


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost: float
    latency_ms: float


class LLMError(RuntimeError):
    """The model call failed after retries. Callers must escalate, never answer confidently (hard rule 1)."""


class LLMCircuitOpen(LLMError):
    """The provider has recently failed repeatedly; do not add avoidable load."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int, reset_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_until = 0.0

    def allow(self) -> bool:
        return time.monotonic() >= self.opened_until

    def record_success(self) -> None:
        self.failures = 0
        self.opened_until = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_until = time.monotonic() + self.reset_seconds


class LLMClient(Protocol):
    def generate(self, prompt: str, *, prompt_version: str, step: str, run_id: str) -> LLMResult: ...


class HttpLLMClient:
    def __init__(self, provider: str | None = None) -> None:
        self.provider = (provider or os.getenv("LLM_PROVIDER", "stub")).lower()
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "3"))
        self.price_prompt = float(os.getenv("LLM_PRICE_PROMPT_PER_1K", "0"))
        self.price_completion = float(os.getenv("LLM_PRICE_COMPLETION_PER_1K", "0"))
        self.breaker = CircuitBreaker(int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
                                      float(os.getenv("CIRCUIT_BREAKER_RESET_SECONDS", "30")))
        if self.provider not in ("stub", "gemini"):
            raise ValueError(f"unknown LLM_PROVIDER {self.provider!r} (expected stub | gemini)")
        if self.provider == "gemini" and not (self.api_key and self.model):
            raise ValueError("LLM_PROVIDER=gemini requires LLM_API_KEY and LLM_MODEL")
        self._http = httpx.Client(timeout=self.timeout)

    # -- provider calls -------------------------------------------------------------------------
    def _call_stub(self, prompt: str, step: str, run_id: str) -> tuple[str, int, int]:
        r = self._http.post(f"{self.base_url}/v1/generate", json={"prompt": prompt, "step": step, "run_id": run_id})
        r.raise_for_status()
        d = r.json()
        return d["text"], int(d["usage"]["prompt_tokens"]), int(d["usage"]["completion_tokens"])

    def _call_gemini(self, prompt: str, step: str, run_id: str) -> tuple[str, int, int]:
        base = self.base_url or "https://generativelanguage.googleapis.com"
        r = self._http.post(
            f"{base}/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
        )
        r.raise_for_status()
        d = r.json()
        text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"] if not p.get("thought"))
        u = d.get("usageMetadata", {})
        return text, int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0))

    # -- public ---------------------------------------------------------------------------------
    def generate(self, prompt: str, *, prompt_version: str, step: str, run_id: str) -> LLMResult:
        if not self.breaker.allow():
            raise LLMCircuitOpen("LLM circuit breaker is open after repeated provider failures")
        call = self._call_stub if self.provider == "stub" else self._call_gemini
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            t0 = time.perf_counter()
            try:
                text, pt, ct = call(prompt, step, run_id)
                latency = (time.perf_counter() - t0) * 1000
                cost = pt / 1000 * self.price_prompt + ct / 1000 * self.price_completion
                log(logger, "llm_call", step=step, prompt_version=prompt_version, prompt_tokens=pt,
                    completion_tokens=ct, cost=cost, latency_ms=round(latency, 1), attempt=attempt)
                self.breaker.record_success()
                return LLMResult(text=text, prompt_tokens=pt, completion_tokens=ct, cost=cost, latency_ms=latency)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                log(logger, "llm_call_failed", logging.WARNING, step=step, attempt=attempt, error=type(exc).__name__, http_status=status)
                if attempt < self.max_retries:
                    delay = min(0.5 * 2**attempt, 8)
                    if status in (429, 503):  # rate limit / overload: back off much longer, honour Retry-After
                        delay = min(5 * 2**attempt, 40)
                        try:
                            delay = max(delay, float(exc.response.headers.get("retry-after", 0)))
                        except (AttributeError, ValueError):
                            pass
                    time.sleep(delay)
        self.breaker.record_failure()
        raise LLMError(f"{step}: LLM call failed after {self.max_retries + 1} attempts: {type(last).__name__}")


def get_llm_client() -> LLMClient:
    return HttpLLMClient()
