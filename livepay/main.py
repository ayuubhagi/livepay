"""FastAPI application entrypoint.

For Phase 0 this exposes a single health check. Later phases add the
punch-ingestion and wallet endpoints.
"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from livepay import __version__
from livepay.db import get_db
from livepay.pipeline import ensure_group, get_redis, publish_punch
from livepay.schemas import PunchAccepted, PunchIn, WalletBalance, WithdrawalIn, WithdrawalOut
from livepay.wallet import InsufficientFundsError, get_balance, withdraw

app = FastAPI(title="LivePay", version=__version__)

# FastAPI dependency alias (Annotated form avoids a call in argument defaults).
DbSession = Annotated[Session, Depends(get_db)]


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


@app.get("/wallet/{employee_id}", response_model=WalletBalance)
def read_wallet(employee_id: int, db: DbSession) -> WalletBalance:
    """Current-period available-to-withdraw balance for an employee."""
    return get_balance(db, employee_id)


@app.post("/withdrawals", status_code=201, response_model=WithdrawalOut)
def post_withdrawal(body: WithdrawalIn, db: DbSession) -> WithdrawalOut:
    """Withdraw against earned pay. 409 if the amount exceeds what's available."""
    try:
        record = withdraw(db, body.employee_id, body.amount, body.idempotency_key)
    except InsufficientFundsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"insufficient funds: available {exc.available}, requested {exc.requested}",
        ) from exc
    return WithdrawalOut(id=record.id, employee_id=record.employee_id, amount=record.amount)
