
"""Corpus access for the agent tools. Tracks every passage returned in a run so the verifier can check citations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from functools import lru_cache
from queue import Queue

import redis

from common.config import get_settings


@lru_cache(maxsize=1)
def _load():
    from langchain_community.vectorstores import FAISS
    from pipeline.embeddings import LocalEmbeddings

    s = get_settings()
    emb = LocalEmbeddings(s.embedding_model)

    store = FAISS.load_local(
        os.path.join(s.index_dir, "faiss"),
        emb,
        allow_dangerous_deserialization=True
    )

    with open(os.path.join(s.index_dir, "chunks.jsonl")) as f:
        chunks = [json.loads(line) for line in f]

    return store, {c["chunk_id"]: c for c in chunks}


def _norm_ref(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", x.lower())


class CorpusTools:
    """One instance per run. Retrieved passages are the only source citations may resolve against."""

    def __init__(self, bid: dict) -> None:
        self.bid = bid
        self.retrieved: dict[str, dict] = {}
        self.calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_events: list[str] = []

        s = get_settings()

        try:
            self.cache = redis.Redis.from_url(
                s.redis_url,
                decode_responses=True,
                socket_timeout=1,
                socket_connect_timeout=1
            )
            self.cache_ttl = s.retrieval_cache_seconds

        except redis.RedisError:
            self.cache = None
            self.cache_ttl = 0

    def _record(self, c: dict) -> dict:
        self.retrieved[c["chunk_id"]] = c

        return {
            "chunk_id": c["chunk_id"],
            "doc_id": c["doc_id"],
            "clause_ref": c["clause_ref"],
            "page": c["page"],
            "doc_type": c["doc_type"],
            "status": c["status"],
            "date": c["date"],
            "text": c["text"]
        }

    def _cache_key(self, operation: str, args: dict) -> str:
        raw = json.dumps(
            [operation, args],
            sort_keys=True,
            separators=(",", ":")
        )

        return "retrieval:" + hashlib.sha256(raw.encode()).hexdigest()

    def _cached(self, operation: str, args: dict, compute) -> list[dict]:
        key = self._cache_key(operation, args)

        if self.cache:
            try:
                raw = self.cache.get(key)

                if raw:
                    self.cache_hits += 1
                    self.cache_events.append("hit")
                    return json.loads(raw)

            except (redis.RedisError, ValueError):
                pass

        self.cache_misses += 1
        self.cache_events.append("miss")

        value = compute()

        if self.cache and self.cache_ttl:
            try:
                self.cache.set(
                    key,
                    json.dumps(value),
                    ex=self.cache_ttl
                )

            except redis.RedisError:
                pass

        return value

    def search_corpus(
        self,
        query: str,
        source_filter: str = "any",
        k: int = 4
    ) -> list[dict]:

        self.calls += 1
        clean = str(query)[:500]

        def compute() -> list[dict]:
            store, _ = _load()

            flt = (
                {"doc_type": source_filter}
                if source_filter in ("tender", "policy")
                else None
            )

            hits = store.similarity_search_with_score(
                clean,
                k=k,
                filter=flt,
                fetch_k=200
            )

            _, by_id = _load()

            return [
                by_id[doc.metadata["chunk_id"]]
                for doc, _score in hits
            ]

        passages = self._cached(
            "search",
            {
                "query": clean,
                "source_filter": source_filter,
                "k": k
            },
            compute
        )

        return [self._record(c) for c in passages]

    def get_clause(
        self,
        doc_id: str,
        clause_ref: str
    ) -> list[dict]:

        self.calls += 1

        def compute() -> list[dict]:
            _, by_id = _load()

            want = _norm_ref(clause_ref)

            hits = [
                c for c in by_id.values()
                if c["doc_id"] == doc_id
                and _norm_ref(c["clause_ref"]) == want
            ]

            if not hits:
                hits = [
                    c for c in by_id.values()
                    if c["doc_id"] == doc_id
                    and _norm_ref(c["clause_ref"]).startswith(want)
                ]

            return hits[:4]

        passages = self._cached(
            "clause",
            {
                "doc_id": doc_id,
                "clause_ref": clause_ref
            },
            compute
        )

        return [self._record(c) for c in passages]

    def get_bid_field(self, field: str) -> dict:
        self.calls += 1

        if field not in self.bid:
            return {
                "field": field,
                "error": "no such field",
                "available": sorted(self.bid)
            }

        return {
            "field": field,
            "value": self.bid[field]
        }

    def _execute_tool(self, tool: str, args: dict):
        """Dispatch a supported tool."""

        if tool == "search_corpus":
            return self.search_corpus(
                args.get("query", ""),
                args.get("source_filter", "any")
            )

        if tool == "get_clause":
            return self.get_clause(
                str(args.get("doc_id", "")),
                str(args.get("clause_ref", ""))
            )

        if tool == "get_bid_field":
            return self.get_bid_field(
                str(args.get("field", ""))
            )

        raise ValueError(f"unknown tool {tool!r}")

    def call(self, tool: str, args: dict):
        """Execute a tool with a configurable wall-clock timeout."""

        timeout = get_settings().tool_timeout_seconds

        result_queue: Queue[tuple[bool, object]] = Queue(maxsize=1)

        def run_tool():
            try:
                result = self._execute_tool(tool, args)
                result_queue.put((True, result))

            except Exception as exc:
                result_queue.put((False, exc))

        thread = threading.Thread(
            target=run_tool,
            daemon=True,
            name=f"tool-{tool}"
        )

        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError(
                f"Tool '{tool}' exceeded its "
                f"{timeout}-second timeout"
            )

        success, result = result_queue.get_nowait()

        if not success:
            if isinstance(result, BaseException):
                raise result
            raise RuntimeError(
                f"Tool '{tool}' failed with an unexpected result"
            )

      
