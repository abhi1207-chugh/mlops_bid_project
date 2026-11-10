"""Ingestion CLI: python -m pipeline.ingest

Idempotent and content-hashed per source text file: only changed files are re-embedded. Per-file
embeddings are cached under INDEX_DIR/cache; the FAISS index is rebuilt from cache (cheap). Writes
index_meta.json with per-document status and build time for freshness metrics (L1/D2).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict

import numpy as np

from common.config import get_settings
from common.logging import log, setup_logging
from pipeline.chunking import Chunk, chunk_document

logger = logging.getLogger("ingest")


def _sha(path: str, extra: str = "") -> str:
    h = hashlib.sha256(extra.encode())
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def ingest(force: bool = False) -> dict:
    s = get_settings()
    os.makedirs(os.path.join(s.index_dir, "cache"), exist_ok=True)
    with open(os.path.join(s.index_dir, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # several workers may start at once
        return _ingest_locked(s, force)


def _ingest_locked(s, force: bool) -> dict:
    manifest = json.load(open(os.path.join(s.corpus_dir, "manifest.json")))
    meta_path = os.path.join(s.index_dir, "index_meta.json")
    old = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    embedder = None
    all_chunks: list[Chunk] = []
    vectors: list[np.ndarray] = []
    files: dict[str, dict] = {}
    embedded = reused = 0
    by_file: dict[str, list[dict]] = {}
    for d in manifest["documents"]:
        by_file.setdefault(d["text"], []).append(d)

    for text_rel, docs in by_file.items():
        path = os.path.join(s.corpus_dir, text_rel)
        # the manifest is hashed in too: a status/date change must refresh chunk metadata
        digest = _sha(path, json.dumps(docs, sort_keys=True) + s.embedding_model)
        cache = os.path.join(s.index_dir, "cache", f"{digest}.npz")
        raw = open(path, encoding="utf-8").read()
        chunks = [c for d in docs for c in chunk_document(d, raw)]
        if os.path.exists(cache) and not force:
            vecs = np.load(cache)["v"]
            reused += 1
        else:
            if embedder is None:
                from pipeline.embeddings import LocalEmbeddings
                embedder = LocalEmbeddings(s.embedding_model)
            vecs = np.array(embedder.embed_documents([c.text for c in chunks]), dtype="float32")
            np.savez(cache, v=vecs)
            embedded += 1
        all_chunks += chunks
        vectors.append(vecs)
        files[text_rel] = {"sha256": digest, "chunks": len(chunks)}

    # rebuild FAISS from the cached vectors
    from langchain_community.vectorstores import FAISS
    if embedder is None:
        from pipeline.embeddings import LocalEmbeddings
        embedder = LocalEmbeddings(s.embedding_model)
    matrix = np.vstack(vectors)
    store = FAISS.from_embeddings(
        [(c.text, v.tolist()) for c, v in zip(all_chunks, matrix)], embedder,
        metadatas=[c.metadata() for c in all_chunks], ids=[c.chunk_id for c in all_chunks],
    )
    store.save_local(os.path.join(s.index_dir, "faiss"))
    with open(os.path.join(s.index_dir, "chunks.jsonl"), "w") as fh:
        for c in all_chunks:
            fh.write(json.dumps(asdict(c)) + "\n")
    meta = {
        "built_at": time.time(),
        "embedding_model": s.embedding_model,
        "chunks": len(all_chunks),
        "files": files,
        "documents": {d["doc_id"]: {"status": d["status"], "doc_type": d["doc_type"], "effective_date": d["effective_date"]}
                      for d in manifest["documents"]},
    }
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)
    log(logger, "ingest_done", chunks=len(all_chunks), files_embedded=embedded, files_reused=reused)
    return {"chunks": len(all_chunks), "files_embedded": embedded, "files_reused": reused}


def ensure_index() -> None:
    s = get_settings()
    if not os.path.exists(os.path.join(s.index_dir, "faiss", "index.faiss")):
        ingest()


if __name__ == "__main__":
    setup_logging()
    result = ingest(force="--force" in sys.argv)
    print(json.dumps(result))
