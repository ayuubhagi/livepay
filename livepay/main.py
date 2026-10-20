"""FastAPI application entrypoint.

For Phase 0 this exposes a single health check. Later phases add the
punch-ingestion and wallet endpoints.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from livepay import __version__
from livepay.pipeline import ensure_group, get_redis, publish_punch
from livepay.schemas import PunchAccepted, PunchIn

app = FastAPI(title="LivePay", version=__version__)


class Health(BaseModel):
    """Response schema for the health check."""

    status: str
    version: str


@app.get("/health", response_model=Health)
def health() -> Health:
    """Liveness probe. Returns 200 with a static body when the app is up.

    This checks only that the process is serving requests; it does not yet
    verify Postgres or Redis connectivity (added when those are wired in).
    """
    return Health(status="ok", version=__version__)


@app.post("/punches", status_code=202, response_model=PunchAccepted)
def post_punch(punch: PunchIn) -> PunchAccepted:
    """Accept a punch and enqueue it on the Redis Stream for the worker.

    Returns 202 Accepted: the punch is queued, not yet persisted. The worker
    performs the idempotent insert and recalculation.
    """
    r = get_redis()
    ensure_group(r)
    payload = {
        "employee_id": punch.employee_id,
        "kind": punch.kind.value,
        "event_time": punch.event_time.isoformat(),
        "idempotency_key": punch.idempotency_key,
    }
    stream_id = publish_punch(r, payload)
    return PunchAccepted(stream_id=stream_id, idempotency_key=punch.idempotency_key)
