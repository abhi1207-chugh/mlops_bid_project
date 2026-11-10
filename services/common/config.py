"""Environment-driven settings. Nothing here is hardcoded to a provider, endpoint or model (hard rule 3)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _f(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    redis_url: str = field(default_factory=lambda: _f("REDIS_URL", "redis://redis:6379/0"))
    quarantine_dir: str = field(default_factory=lambda: _f("QUARANTINE_DIR", "/data/quarantine"))
    run_store_dir: str = field(default_factory=lambda: _f("RUN_STORE_DIR", "/data/runs"))
    index_dir: str = field(default_factory=lambda: _f("INDEX_DIR", "/data/index"))
    corpus_dir: str = field(default_factory=lambda: _f("CORPUS_DIR", "/app/corpus"))
    embedding_model: str = field(default_factory=lambda: _f("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
    prompts_dir: str = field(default_factory=lambda: _f("PROMPTS_DIR", "/app/prompts"))
    max_steps: int = field(default_factory=lambda: int(_f("AGENT_MAX_STEPS", "8")))
    max_tool_calls: int = field(default_factory=lambda: int(_f("AGENT_MAX_TOOL_CALLS", "12")))
    max_seconds: float = field(default_factory=lambda: float(_f("AGENT_MAX_SECONDS", "60")))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_f("RATE_LIMIT_PER_MINUTE", "10")))
    circuit_breaker_failure_threshold: int = field(default_factory=lambda: int(_f("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")))
    circuit_breaker_reset_seconds: float = field(default_factory=lambda: float(_f("CIRCUIT_BREAKER_RESET_SECONDS", "30")))
    retrieval_cache_seconds: int = field(default_factory=lambda: int(_f("RETRIEVAL_CACHE_SECONDS", "3600")))
    auto_score_sample_rate: float = field(default_factory=lambda: float(_f("AUTO_SCORE_SAMPLE_RATE", "0.20")))
    tool_timeout_seconds: float = field(default_factory=lambda: float(_f("TOOL_TIMEOUT_SECONDS", "5")))
    prompt_version: str = field(default_factory=lambda: _f("PROMPT_VERSION", "v1"))
    queue_key: str = "runs:queue"
    processing_key: str = "runs:processing"


def get_settings() -> Settings:
    return Settings()
