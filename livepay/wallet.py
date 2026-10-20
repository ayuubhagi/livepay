"""Wallet: earned-pay balance and safe on-demand withdrawals.

available = earned_net * (1 - safety_buffer) - already_withdrawn

`earned_net` is the net pay of the latest pay snapshot for the current period.
Until the deductions engine (Phase 3) runs, `net_pay` is null and treated as 0,
so nothing is withdrawable against unverified pay.

Overdraw safety: `withdraw` takes a row lock (`SELECT ... FOR UPDATE`) on the
employee's pay-period row, so concurrent withdrawals are serialized — the second
request only reads the balance after the first has committed, and can't overdraw.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from livepay.config import settings
from livepay.models import AuditLog, PayCalculation, PayPeriod, Withdrawal
from livepay.payroll.periods import period_bounds
from livepay.schemas import WalletBalance

_CENTS = Decimal("0.01")


class InsufficientFundsError(Exception):
    """Raised when a withdrawal exceeds the available balance."""

    def __init__(self, available: Decimal, requested: Decimal):
        self.available = available
        self.requested = requested
        super().__init__(f"requested {requested} exceeds available {available}")


def compute_available(earned_net: Decimal, buffer: Decimal, withdrawn: Decimal) -> Decimal:
    """Pure balance formula, floored at zero and rounded down to the cent."""
    raw = earned_net * (Decimal(1) - buffer) - withdrawn
    available = max(Decimal(0), raw)
    # Round DOWN: never offer a fraction of a cent more than is really available.
    return available.quantize(_CENTS, rounding=ROUND_DOWN)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _latest_net(db: Session, employee_id: int, pay_period_id: int) -> Decimal:
    net = db.execute(
        select(PayCalculation.net_pay)
        .where(
            PayCalculation.employee_id == employee_id,
            PayCalculation.pay_period_id == pay_period_id,
        )
        .order_by(PayCalculation.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return net if net is not None else Decimal(0)


def _withdrawn(db: Session, employee_id: int, pay_period_id: int) -> Decimal:
    total = db.execute(
        select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
            Withdrawal.employee_id == employee_id,
            Withdrawal.pay_period_id == pay_period_id,
        )
    ).scalar_one()
    return Decimal(total)


def get_balance(db: Session, employee_id: int, now: datetime | None = None) -> WalletBalance:
    """Read-only current-period balance (no lock)."""
    now = now or datetime.now(_tz())
    start, _end = period_bounds(now.astimezone(_tz()).date())
    period = db.execute(
        select(PayPeriod).where(PayPeriod.employee_id == employee_id, PayPeriod.start_date == start)
    ).scalar_one_or_none()

    buffer = settings.wallet_safety_buffer
    if period is None:
        return WalletBalance(
            employee_id=employee_id,
            pay_period_start=start,
            earned_net=Decimal("0.00"),
            safety_buffer=buffer,
            withdrawn=Decimal("0.00"),
            available=Decimal("0.00"),
        )

    earned_net = _latest_net(db, employee_id, period.id)
    withdrawn = _withdrawn(db, employee_id, period.id)
    return WalletBalance(
        employee_id=employee_id,
        pay_period_start=start,
        earned_net=earned_net,
        safety_buffer=buffer,
        withdrawn=withdrawn,
        available=compute_available(earned_net, buffer, withdrawn),
    )


def withdraw(
    db: Session,
    employee_id: int,
    amount: Decimal,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> Withdrawal:
    """Withdraw `amount` from the current period, never overdrawing.

    Serializes concurrent callers via a row lock on the pay-period row.
    """
    now = now or datetime.now(_tz())
    start, _end = period_bounds(now.astimezone(_tz()).date())

    # Idempotent replay: same key -> return the existing withdrawal.
    if idempotency_key is not None:
        existing = db.execute(
            select(Withdrawal).where(Withdrawal.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    # Lock the period row; concurrent withdrawals block here until we commit.
    period = db.execute(
        select(PayPeriod)
        .where(PayPeriod.employee_id == employee_id, PayPeriod.start_date == start)
        .with_for_update()
    ).scalar_one_or_none()

    if period is None:
        db.rollback()
        raise InsufficientFundsError(available=Decimal("0.00"), requested=amount)

    earned_net = _latest_net(db, employee_id, period.id)
    withdrawn = _withdrawn(db, employee_id, period.id)
    available = compute_available(earned_net, settings.wallet_safety_buffer, withdrawn)

    if amount > available:
        db.rollback()
        raise InsufficientFundsError(available=available, requested=amount)

    record = Withdrawal(
        employee_id=employee_id,
        pay_period_id=period.id,
        amount=amount,
        idempotency_key=idempotency_key,
    )
    db.add(record)
    db.flush()
    db.add(
        AuditLog(
            employee_id=employee_id,
            event_type="withdrawal",
            detail={
                "withdrawal_id": record.id,
                "amount": str(amount),
                "available_before": str(available),
                "pay_period_start": start.isoformat(),
            },
        )
    )
    db.commit()
    return record
