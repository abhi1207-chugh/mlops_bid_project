# Incident Log

## Docker Desktop paused

- Impact: Dockerized tests could not connect to the daemon.
- Cause: Docker Desktop was manually paused.
- Resolution: resumed Docker Desktop and reran the suite.
- Prevention: check Docker Desktop before the demo.

## Host ports already occupied

- Impact: the API and Grafana could not bind to ports 8000 and 3000.
- Cause: unrelated local projects were using those ports.
- Resolution: used `API_PORT=8001` and an alternate Grafana port.
- Prevention: set demonstration ports in `.env` before starting Compose.

## Stub citation parser selected prompt examples

- Impact: the end-to-end stub evaluation produced verifier escalations because citations used placeholder chunk IDs.
- Cause: the stub parsed example JSON embedded in the compliance prompt before parsing actual tool output.
- Resolution: changed the stub to parse `TOOL_RESULT` JSON first.
- Prevention: keep prompt examples separate from executable stub parsing and retain an end-to-end stub evaluation check.
