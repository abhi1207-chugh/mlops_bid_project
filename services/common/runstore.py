"""Run state in Redis (shared by api and workers) plus a durable JSON copy per finished run (F8)."""
from __future__ import annotations

import json
import os
import time
import uuid

import redis

from common.config import get_settings
from common.models import Finding, RunRecord


class RunStore:
    def __init__(self, client: redis.Redis | None = None) -> None:
        self.s = get_settings()
        self.r = client or redis.Redis.from_url(self.s.redis_url, decode_responses=True, socket_timeout=30, socket_connect_timeout=5)

    @staticmethod
    def _key(run_id: str) -> str:
        return f"run:{run_id}"

    def create(self, bid: dict, flags: list[str]) -> RunRecord:
        now = time.time()
        rec = RunRecord(run_id=str(uuid.uuid4()), status="queued", created_at=now, updated_at=now, bid=bid, flags=flags)
        self.save(rec)
        return rec

    def enqueue(self, run_id: str) -> None:
        self.r.lpush(self.s.queue_key, run_id)

    def set_trace_context(self, run_id: str, carrier: dict[str, str]) -> None:
        self.r.set(f"trace:{run_id}", json.dumps(carrier), ex=86400)

    def get_trace_context(self, run_id: str) -> dict[str, str] | None:
        raw = self.r.get(f"trace:{run_id}")
        return json.loads(raw) if raw else None

    def save(self, rec: RunRecord) -> None:
        rec.updated_at = time.time()
        self.r.set(self._key(rec.run_id), rec.model_dump_json())

    def get(self, run_id: str) -> RunRecord | None:
        raw = self.r.get(self._key(run_id))
        return RunRecord.model_validate_json(raw) if raw else None

    def finish(self, rec: RunRecord, finding: Finding) -> None:
        rec.finding = finding
        rec.status = "escalated" if finding.route == "escalate_to_human" else "done"
        self.save(rec)
        try:  # durable copy for run reconstruction by run_id
            os.makedirs(self.s.run_store_dir, exist_ok=True)
            with open(os.path.join(self.s.run_store_dir, f"{rec.run_id}.json"), "w") as fh:
                fh.write(rec.model_dump_json(indent=2))
        except OSError:
            pass

    def save_feedback(self, run_id: str, feedback: dict) -> None:
        """Append-only feedback, deliberately kept separate from the screening record."""
        key = f"feedback:{run_id}"
        self.r.rpush(key, json.dumps(feedback))
        self.r.expire(key, 60 * 60 * 24 * 90)

    def feedback(self, run_id: str) -> list[dict]:
        return [json.loads(item) for item in self.r.lrange(f"feedback:{run_id}", 0, -1)]

    def recover_processing(self, stale_after: int = 120) -> int:
        """Requeue expired processing entries; only reclaim records whose heartbeat is stale."""
        recovered = 0
        for run_id in self.r.lrange(self.s.processing_key, 0, -1):
            rec = self.get(run_id)
            if rec is None or rec.status != "running" or time.time() - rec.updated_at < stale_after:
                continue
            rec.status = "queued"
            self.save(rec)
            self.r.lrem(self.s.processing_key, 1, run_id)
            self.r.lpush(self.s.queue_key, run_id)
            recovered += 1
        return recovered

    def ping(self) -> bool:
        return bool(self.r.ping())


def quarantine(payload: object, errors: list[dict]) -> str:
    """Store a rejected request with its field-level errors. Never starts an agent run."""
    s = get_settings()
    qid = str(uuid.uuid4())
    os.makedirs(s.quarantine_dir, exist_ok=True)
    body = {"quarantine_id": qid, "received_at": time.time(), "errors": errors, "payload": payload}
    with open(os.path.join(s.quarantine_dir, f"{qid}.json"), "w") as fh:
        json.dump(body, fh, default=str, indent=2)
    return qid
