import httpx
import pytest

from common.llm import HttpLLMClient, LLMCircuitOpen, LLMError


def test_circuit_breaker_opens_after_configured_provider_failures(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_BASE_URL", "http://stub.invalid")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "2")
    client = HttpLLMClient()

    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("down")

    client._call_stub = unavailable
    with pytest.raises(LLMError):
        client.generate("x", prompt_version="v1", step="test", run_id="r1")
    with pytest.raises(LLMError):
        client.generate("x", prompt_version="v1", step="test", run_id="r2")
    with pytest.raises(LLMCircuitOpen):
        client.generate("x", prompt_version="v1", step="test", run_id="r3")
