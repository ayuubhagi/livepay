"""Event pipeline: punches flow through a Redis Stream to a worker.

    POST /punches --> XADD (Redis Stream) --> worker (consumer group)
                  --> persist punch (idempotent) --> recalculate period
                  --> write pay snapshot + audit log --> XACK

Idempotency has two layers: the client-supplied `idempotency_key` is UNIQUE in
the DB, and the insert uses ON CONFLICT DO NOTHING, so replaying the same punch
never double-counts hours even if the stream delivers it more than once.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from livepay.config import settings
from livepay.models import AuditLog, Employee, PayCalculation, PayPeriod, Punch, PunchKind
from livepay.payroll.gross import calculate_gross
from livepay.payroll.periods import period_bounds, period_utc_range

STREAM_KEY = "livepay:punches"
GROUP = "workers"


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Process-wide Redis client (strings decoded)."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def ensure_group(r: redis.Redis) -> None:
    """Create the consumer group (and stream) if it doesn't exist yet."""
    try:
        r.xgroup_create(STREAM_KEY, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def publish_punch(r: redis.Redis, payload: dict) -> str:
    """Append a punch to the stream; returns the stream message id."""
    return r.xadd(STREAM_KEY, {"data": json.dumps(payload)})


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _get_or_create_period(db: Session, employee_id: int, start, end) -> PayPeriod:
    period = db.execute(
        select(PayPeriod).where(
            PayPeriod.employee_id == employee_id, PayPeriod.start_date == start
        )
    ).scalar_one_or_none()
    if period is None:
        period = PayPeriod(employee_id=employee_id, start_date=start, end_date=end)
        db.add(period)
        db.flush()
    return period


def process_punch(db: Session, payload: dict) -> dict:
    """Persist one punch and recalculate its pay period. Idempotent."""
    event_time = datetime.fromisoformat(payload["event_time"])
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    employee_id = payload["employee_id"]

    # Idempotent insert: a replayed punch (same key) inserts nothing.
    insert_stmt = (
        pg_insert(Punch)
        .values(
            employee_id=employee_id,
            kind=PunchKind(payload["kind"]),
            event_time=event_time,
            idempotency_key=payload["idempotency_key"],
            source="api",
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Punch.id)
    )
    punch_id = db.execute(insert_stmt).scalar_one_or_none()

    if punch_id is None:
        db.add(
            AuditLog(
                employee_id=employee_id,
                event_type="punch_duplicate_ignored",
                detail={"idempotency_key": payload["idempotency_key"]},
            )
        )
        db.commit()
        return {"status": "duplicate"}

    tz = _tz()
    local_day = event_time.astimezone(tz).date()
    start, end = period_bounds(local_day)
    period = _get_or_create_period(db, employee_id, start, end)

    lo, hi = period_utc_range(start, tz)
    punches = (
        db.execute(
            select(Punch)
            .where(
                Punch.employee_id == employee_id,
                Punch.event_time >= lo,
                Punch.event_time < hi,
            )
            .order_by(Punch.event_time)
        )
        .scalars()
        .all()
    )

    employee = db.get(Employee, employee_id)
    result = calculate_gross(list(punches), employee.hourly_rate, tz)

    # Append a new snapshot each recalculation (auditable history). Deduction
    # and net columns stay null until the tax engine (Phase 3) fills them.
    snapshot = PayCalculation(
        employee_id=employee_id,
        pay_period_id=period.id,
        regular_hours=result.regular_hours,
        overtime_hours=result.overtime_hours,
        gross_pay=result.gross_pay,
    )
    db.add(snapshot)
    db.flush()

    db.add(
        AuditLog(
            employee_id=employee_id,
            event_type="punch_processed",
            detail={
                "punch_id": punch_id,
                "idempotency_key": payload["idempotency_key"],
                "pay_period_start": start.isoformat(),
                "snapshot_id": snapshot.id,
                "regular_hours": str(result.regular_hours),
                "overtime_hours": str(result.overtime_hours),
                "gross_pay": str(result.gross_pay),
                "anomalies": [a.kind for a in result.anomalies],
            },
        )
    )
    db.commit()
    return {
        "status": "processed",
        "punch_id": punch_id,
        "snapshot_id": snapshot.id,
        "gross_pay": str(result.gross_pay),
    }


def consume_once(
    r: redis.Redis,
    session_factory,
    consumer: str = "worker-1",
    count: int = 10,
    block: int | None = None,
) -> list[dict]:
    """Read and process one batch of pending punches; ACK each. Returns results."""
    response = r.xreadgroup(GROUP, consumer, {STREAM_KEY: ">"}, count=count, block=block)
    results: list[dict] = []
    for _stream, messages in response or []:
        for message_id, fields in messages:
            payload = json.loads(fields["data"])
            with session_factory() as db:
                results.append(process_punch(db, payload))
            r.xack(STREAM_KEY, GROUP, message_id)
    return results
