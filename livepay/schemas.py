"""Request/response schemas for the HTTP API."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from livepay.models import PunchKind


class PunchIn(BaseModel):
    employee_id: int
    kind: PunchKind
    event_time: datetime
    idempotency_key: str = Field(min_length=1, max_length=64)


class PunchAccepted(BaseModel):
    stream_id: str
    idempotency_key: str


class WithdrawalIn(BaseModel):
    employee_id: int
    amount: Decimal = Field(gt=0)
    idempotency_key: str | None = Field(default=None, max_length=64)


class WithdrawalOut(BaseModel):
    id: int
    employee_id: int
    amount: Decimal
    status: str = "completed"


class WalletBalance(BaseModel):
    employee_id: int
    pay_period_start: date
    earned_net: Decimal
    safety_buffer: Decimal
    withdrawn: Decimal
    available: Decimal
