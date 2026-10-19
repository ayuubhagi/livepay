"""FastAPI application entrypoint.

For Phase 0 this exposes a single health check. Later phases add the
punch-ingestion and wallet endpoints.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from livepay import __version__

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
