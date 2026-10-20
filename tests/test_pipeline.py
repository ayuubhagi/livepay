"""Integration tests for the punch event pipeline (Redis Stream + worker)."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from livepay import pipeline
from livepay.models import AuditLog, Employee, PayCalculation, Punch, PunchKind


def _employee(db) -> int:
    emp = Employee(first_name="Grace", last_name="Hopper", hourly_rate=Decimal("30.00"))
    db.add(emp)
    db.commit()
    return emp.id


def _payload(employee_id, kind, dt, key) -> dict:
    return {
        "employee_id": employee_id,
        "kind": kind.value,
        "event_time": dt.isoformat(),
        "idempotency_key": key,
    }


def test_punch_flows_to_snapshot_and_audit(committed_db, session_factory, redis_client):
    emp_id = _employee(committed_db)
    pipeline.ensure_group(redis_client)

    # An 8-hour shift on a Monday.
    pipeline.publish_punch(
        redis_client, _payload(emp_id, PunchKind.IN, datetime(2026, 1, 5, 14, tzinfo=UTC), "in-1")
    )
    pipeline.publish_punch(
        redis_client, _payload(emp_id, PunchKind.OUT, datetime(2026, 1, 5, 22, tzinfo=UTC), "out-1")
    )

    results = pipeline.consume_once(redis_client, session_factory, count=10)

    assert [r["status"] for r in results] == ["processed", "processed"]

    with session_factory() as db:
        punches = db.execute(select(func.count()).select_from(Punch)).scalar()
        assert punches == 2
        latest = db.execute(
            select(PayCalculation).order_by(PayCalculation.id.desc())
        ).scalars().first()
        assert latest.regular_hours == Decimal("8.00")
        assert latest.gross_pay == Decimal("240.00")  # 8h * $30
        assert latest.net_pay is None  # deductions not computed yet (Phase 3)
        audit_types = db.execute(select(AuditLog.event_type)).scalars().all()
        assert "punch_processed" in audit_types


def test_duplicate_punch_is_not_double_counted(committed_db, session_factory, redis_client):
    emp_id = _employee(committed_db)
    pipeline.ensure_group(redis_client)

    payload = _payload(emp_id, PunchKind.IN, datetime(2026, 1, 5, 14, tzinfo=UTC), "dup-key")
    pipeline.publish_punch(redis_client, payload)
    pipeline.publish_punch(redis_client, payload)  # same idempotency key

    results = pipeline.consume_once(redis_client, session_factory, count=10)

    assert sorted(r["status"] for r in results) == ["duplicate", "processed"]
    with session_factory() as db:
        punches = db.execute(select(func.count()).select_from(Punch)).scalar()
        assert punches == 1


def test_post_punches_endpoint_enqueues(committed_db, session_factory, redis_client, monkeypatch):
    from fastapi.testclient import TestClient

    from livepay import main
    from livepay.main import app

    # Point the endpoint's Redis client at the isolated test db. Patch the name
    # bound in `livepay.main`, since that's where the endpoint looks it up.
    monkeypatch.setattr(main, "get_redis", lambda: redis_client)
    emp_id = _employee(committed_db)

    client = TestClient(app)
    response = client.post(
        "/punches",
        json={
            "employee_id": emp_id,
            "kind": "in",
            "event_time": "2026-01-05T14:00:00+00:00",
            "idempotency_key": "api-1",
        },
    )

    assert response.status_code == 202
    assert response.json()["idempotency_key"] == "api-1"

    results = pipeline.consume_once(redis_client, session_factory, count=10)
    assert results[0]["status"] == "processed"
