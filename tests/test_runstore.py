import time

import fakeredis

from common.runstore import RunStore


def test_stale_processing_run_is_requeued(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://unused")
    store = RunStore(fakeredis.FakeRedis(decode_responses=True))
    rec = store.create({"tender_id": "T"}, [])
    rec.status = "running"
    rec.updated_at = time.time() - 500
    store.r.set(store._key(rec.run_id), rec.model_dump_json())
    store.r.lpush(store.s.processing_key, rec.run_id)
    assert store.recover_processing(stale_after=120) == 1
    assert store.r.llen(store.s.processing_key) == 0
    assert store.r.lrange(store.s.queue_key, 0, -1) == [rec.run_id]
    assert store.get(rec.run_id).status == "queued"
