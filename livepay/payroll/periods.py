"""Biweekly pay-period boundaries.

Periods are fixed 14-day blocks counted from a configured anchor Sunday, so they
always align to Sunday–Saturday work weeks. A punch is assigned to the period
whose local-date range contains the punch's local date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from livepay.config import settings

PERIOD_DAYS = 14


def period_bounds(local_day: date) -> tuple[date, date]:
    """Return (start_date, end_date) of the biweekly period containing `local_day`."""
    anchor = settings.pay_period_anchor
    # Floor division handles dates before the anchor correctly (negative index).
    index = (local_day - anchor).days // PERIOD_DAYS
    start = anchor + timedelta(days=index * PERIOD_DAYS)
    end = start + timedelta(days=PERIOD_DAYS - 1)
    return start, end


def period_utc_range(start: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC [lo, hi) instants for a period starting on local date `start`.

    `hi` is the start of the next period (exclusive), so a half-open range can
    be used to query punches by `event_time`.
    """
    local_start = datetime(start.year, start.month, start.day, tzinfo=tz)
    local_end = local_start + timedelta(days=PERIOD_DAYS)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)
