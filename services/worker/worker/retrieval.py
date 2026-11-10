"""Corpus access for the agent tools. Tracks every passage returned in a run so the verifier can check citations."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from common.config import get_settings


@lru_cache(maxsize=1)
def _load():
    from langchain_community.vectorstores import FAISS
    from pipeline.embeddings import LocalEmbeddings
    s = get_settings()
    emb = LocalEmbeddings(s.embedding_model)
    store = FAISS.load_local(os.path.join(s.index_dir, "faiss"), emb, allow_dangerous_deserialization=True)
    chunks = [json.loads(l) for l in open(os.path.join(s.index_dir, "chunks.jsonl"))]
    return store, {c["chunk_id"]: c for c in chunks}


def _norm_ref(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", x.lower())


class CorpusTools:
    """One instance per run. `retrieved` is the only source citations may resolve against (hard rule 2)."""

    def __init__(self, bid: dict) -> None:
        self.bid = bid
        self.retrieved: dict[str, dict] = {}
        self.calls = 0

    def _record(self, c: dict) -> dict:
        self.retrieved[c["chunk_id"]] = c
        return {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "clause_ref": c["clause_ref"], "page": c["page"],
                "doc_type": c["doc_type"], "status": c["status"], "date": c["date"], "text": c["text"]}

    def search_corpus(self, query: str, source_filter: str = "any", k: int = 4) -> list[dict]:
        self.calls += 1
        store, _ = _load()
        flt = None
        if source_filter in ("tender", "policy"):
            flt = {"doc_type": source_filter}
        hits = store.similarity_search_with_score(str(query)[:500], k=k, filter=flt, fetch_k=200)
        _, by_id = _load()
        out = [self._record(by_id[doc.metadata["chunk_id"]]) for doc, _score in hits]
        return out

    def get_clause(self, doc_id: str, clause_ref: str) -> list[dict]:
        self.calls += 1
        _, by_id = _load()
        want = _norm_ref(clause_ref)
        hits = [c for c in by_id.values() if c["doc_id"] == doc_id and _norm_ref(c["clause_ref"]) == want]
        if not hits:  # allow "Rule 173" to return its sub-rules too
            hits = [c for c in by_id.values() if c["doc_id"] == doc_id and _norm_ref(c["clause_ref"]).startswith(want)]
        return [self._record(c) for c in hits[:4]]

    def get_bid_field(self, field: str) -> dict:
        self.calls += 1
        if field not in self.bid:
            return {"field": field, "error": "no such field", "available": sorted(self.bid)}
        return {"field": field, "value": self.bid[field]}

    def call(self, tool: str, args: dict):
        if tool == "search_corpus":
            return self.search_corpus(args.get("query", ""), args.get("source_filter", "any"))
        if tool == "get_clause":
            return self.get_clause(str(args.get("doc_id", "")), str(args.get("clause_ref", "")))
        if tool == "get_bid_field":
            return self.get_bid_field(str(args.get("field", "")))
        raise ValueError(f"unknown tool {tool!r}")
