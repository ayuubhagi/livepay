"""Wallet tests: balance math, withdrawals, idempotency, and overdraw safety."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from livepay.models import Employee, PayCalculation, PayPeriod, Withdrawal
from livepay.payroll.periods import period_bounds
from livepay.wallet import (
    InsufficientFundsError,
    compute_available,
    get_balance,
    withdraw,
)

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 1, 5, 12, tzinfo=TZ)


def _seed(db, net_pay: str) -> int:
    """Create an employee with a pay period and a snapshot carrying net_pay."""
    emp = Employee(first_name="Alan", last_name="Turing", hourly_rate=Decimal("30.00"))
    db.add(emp)
    db.flush()
    start, end = period_bounds(NOW.astimezone(TZ).date())
    period = PayPeriod(employee_id=emp.id, start_date=start, end_date=end)
    db.add(period)
    db.flush()
    db.add(
        PayCalculation(
            employee_id=emp.id,
            pay_period_id=period.id,
            regular_hours=Decimal("0"),
            overtime_hours=Decimal("0"),
            gross_pay=Decimal(net_pay),
            net_pay=Decimal(net_pay),
        )
    )
    db.commit()
    return emp.id


def test_compute_available_formula():
    # 1000 net, 25% buffer, nothing withdrawn -> 750 available.
    assert compute_available(Decimal("1000"), Decimal("0.25"), Decimal("0")) == Decimal("750.00")
    assert compute_available(Decimal("1000"), Decimal("0.25"), Decimal("300")) == Decimal("450.00")
    # Never negative.
    assert compute_available(Decimal("1000"), Decimal("0.25"), Decimal("900")) == Decimal("0.00")


def test_withdraw_happy_path(committed_db, session_factory):
    emp_id = _seed(committed_db, "1000.00")  # available 750
    with session_factory() as db:
        record = withdraw(db, emp_id, Decimal("500.00"), now=NOW)
        assert record.amount == Decimal("500.00")
    with session_factory() as db:
        balance = get_balance(db, emp_id, now=NOW)
        assert balance.available == Decimal("250.00")
        assert balance.withdrawn == Decimal("500.00")


def test_withdraw_insufficient_raises(committed_db, session_factory):
    emp_id = _seed(committed_db, "1000.00")  # available 750
    with session_factory() as db:
        with pytest.raises(InsufficientFundsError):
            withdraw(db, emp_id, Decimal("800.00"), now=NOW)


def test_withdraw_is_idempotent(committed_db, session_factory):
    emp_id = _seed(committed_db, "1000.00")
    with session_factory() as db:
        first = withdraw(db, emp_id, Decimal("100.00"), idempotency_key="w1", now=NOW)
    with session_factory() as db:
        second = withdraw(db, emp_id, Decimal("100.00"), idempotency_key="w1", now=NOW)
        assert second.id == first.id
    with session_factory() as db:
        count = db.execute(select(func.count()).select_from(Withdrawal)).scalar()
        assert count == 1


def test_concurrent_withdrawals_cannot_overdraw(committed_db, session_factory):
    # Available is 750. Two simultaneous 500 withdrawals must not both succeed.
    emp_id = _seed(committed_db, "1000.00")
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()  # release both threads at once to maximize contention
        with session_factory() as db:
            try:
                record = withdraw(db, emp_id, Decimal("500.00"), now=NOW)
                return ("ok", record.amount)
            except InsufficientFundsError:
                return ("insufficient", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [f.result() for f in [pool.submit(attempt), pool.submit(attempt)]]

    statuses = sorted(status for status, _ in outcomes)
    assert statuses == ["insufficient", "ok"]  # exactly one succeeded

    with session_factory() as db:
        total = db.execute(select(func.coalesce(func.sum(Withdrawal.amount), 0))).scalar_one()
        assert Decimal(total) == Decimal("500.00")  # never overdrew past 750
