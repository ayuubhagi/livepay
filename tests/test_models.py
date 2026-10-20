"""Schema-level tests: defaults, constraints, and relationships work as declared."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from livepay.models import Employee, PayPeriod, Punch, PunchKind


def _make_employee(**overrides) -> Employee:
    data = {"first_name": "Ada", "last_name": "Lovelace", "hourly_rate": Decimal("25.00")}
    data.update(overrides)
    return Employee(**data)


def test_employee_defaults(db_session):
    emp = _make_employee()
    db_session.add(emp)
    db_session.flush()

    assert emp.id is not None
    assert emp.province == "ON"
    assert emp.federal_claim_code == 1
    assert emp.ontario_claim_code == 1


def test_negative_hourly_rate_rejected(db_session):
    db_session.add(_make_employee(hourly_rate=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_idempotency_key_rejected(db_session):
    emp = _make_employee()
    db_session.add(emp)
    db_session.flush()

    now = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    db_session.add(
        Punch(employee_id=emp.id, kind=PunchKind.IN, event_time=now, idempotency_key="k1")
    )
    db_session.flush()
    db_session.add(
        Punch(employee_id=emp.id, kind=PunchKind.OUT, event_time=now, idempotency_key="k1")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_pay_period_relationship(db_session):
    emp = _make_employee()
    db_session.add(emp)
    db_session.flush()

    period = PayPeriod(
        employee_id=emp.id,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 18),
    )
    db_session.add(period)
    db_session.flush()

    assert period in emp.pay_periods
