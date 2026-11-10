import threading

from worker.main import worker_wsgi_app


def _call(app, path: str):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app({"PATH_INFO": path, "REQUEST_METHOD": "GET"}, start_response))
    return captured["status"], body


def test_worker_ready_endpoint_transitions_after_startup():
    ready = threading.Event()
    app = worker_wsgi_app(ready)
    assert _call(app, "/ready")[0].startswith("503")
    ready.set()
    status, body = _call(app, "/health")
    assert status.startswith("200")
    assert b'"worker_ready": true' in body
