"""Gross pay calculation from punch events.

Pure functions, no database or network. The pipeline is:

    punches -> shifts -> hours per local day -> hours per work week
            -> split into regular/overtime -> gross dollars

Design notes
------------
* Hours are computed from the *absolute* elapsed time between punches (UTC
  instants), so a shift that crosses midnight or a DST change is still paid the
  real number of hours worked.
* Day and work-week boundaries are evaluated in the employee's **local** time
  zone (Ontario -> America/Toronto), because "a work week" is a local-calendar
  concept. We therefore split each shift's hours across the local days it spans.
* Overtime is weekly, not per pay period: each work week's hours over the
  threshold are paid at the overtime multiplier. A biweekly period is two work
  weeks evaluated independently.

Constants below are Ontario Employment Standards Act, 2000 values (s. 22 —
overtime after 44 hours in a work week at 1.5x the regular rate). They are
employment-standards figures, not CRA tax constants; the tax constants live in
`livepay/tax/constants_2026.py`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from livepay.models import PunchKind

DEFAULT_TZ = ZoneInfo("America/Toronto")

# Ontario ESA, 2000 s. 22(1): overtime after 44 h in a work week at 1.5x.
OVERTIME_WEEKLY_THRESHOLD = Decimal("44")
OVERTIME_MULTIPLIER = Decimal("1.5")

# ESA default work week absent an employer-defined one: Sunday–Saturday.
# Python's date.weekday(): Monday=0 .. Sunday=6.
WEEK_START_WEEKDAY = 6  # Sunday

_HOUR = Decimal(3600)
_CENTS = Decimal("0.01")
_HUNDREDTH_HOUR = Decimal("0.01")


class PunchLike(Protocol):
    """Anything with a punch direction and an aware timestamp."""

    kind: PunchKind
    event_time: datetime


def _elapsed_hours(start: datetime, end: datetime) -> Decimal:
    """True elapsed hours between two instants.

    Converts to UTC first: subtracting two aware datetimes that share the same
    tzinfo makes Python ignore the zone (wall-clock subtraction), which is wrong
    across a DST change. In UTC the subtraction reflects real elapsed time.
    """
    delta = end.astimezone(UTC) - start.astimezone(UTC)
    return Decimal(delta.total_seconds()) / _HOUR


@dataclass(frozen=True)
class Shift:
    start: datetime
    end: datetime

    @property
    def hours(self) -> Decimal:
        return _elapsed_hours(self.start, self.end)


@dataclass(frozen=True)
class Anomaly:
    kind: str
    at: datetime
    detail: str


@dataclass
class GrossResult:
    regular_hours: Decimal
    overtime_hours: Decimal
    gross_pay: Decimal
    shifts: list[Shift] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    weekly_hours: dict[date, Decimal] = field(default_factory=dict)


def pair_punches(punches: list[PunchLike]) -> tuple[list[Shift], list[Anomaly]]:
    """Pair each clock-in with the next clock-out, in time order.

    Resilient to bad sequences (never raises):
    * a clock-in with no following clock-out -> `open_shift` anomaly, no hours;
    * two clock-ins in a row -> the earlier one is dropped (`missing_clock_out`);
    * a clock-out with no open clock-in -> `clock_out_without_clock_in` anomaly;
    * a clock-out at or before its clock-in -> `non_positive_shift` anomaly.
    """
    ordered = sorted(punches, key=lambda p: p.event_time)
    shifts: list[Shift] = []
    anomalies: list[Anomaly] = []
    open_in: PunchLike | None = None

    for punch in ordered:
        if punch.kind == PunchKind.IN:
            if open_in is not None:
                anomalies.append(
                    Anomaly(
                        "missing_clock_out",
                        open_in.event_time,
                        "clock-in with no clock-out before next clock-in",
                    )
                )
            open_in = punch
        else:  # PunchKind.OUT
            if open_in is None:
                anomalies.append(
                    Anomaly(
                        "clock_out_without_clock_in",
                        punch.event_time,
                        "clock-out with no open clock-in",
                    )
                )
                continue
            if punch.event_time <= open_in.event_time:
                anomalies.append(
                    Anomaly(
                        "non_positive_shift", punch.event_time, "clock-out at or before clock-in"
                    )
                )
                open_in = None
                continue
            shifts.append(Shift(open_in.event_time, punch.event_time))
            open_in = None

    if open_in is not None:
        anomalies.append(Anomaly("open_shift", open_in.event_time, "clock-in with no clock-out"))

    return shifts, anomalies


def hours_by_local_day(shift: Shift, tz: ZoneInfo = DEFAULT_TZ) -> dict[date, Decimal]:
    """Split a shift's hours across the local calendar days it spans."""
    start = shift.start.astimezone(tz)
    end = shift.end.astimezone(tz)
    result: dict[date, Decimal] = defaultdict(Decimal)

    cursor = start
    while cursor < end:
        next_midnight = (cursor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        segment_end = min(end, next_midnight)
        result[cursor.date()] += _elapsed_hours(cursor, segment_end)
        cursor = segment_end

    return dict(result)


def _week_start(day: date) -> date:
    """The work-week start date (most recent Sunday on or before `day`)."""
    offset = (day.weekday() - WEEK_START_WEEKDAY) % 7
    return day - timedelta(days=offset)


def weekly_hours(shifts: list[Shift], tz: ZoneInfo = DEFAULT_TZ) -> dict[date, Decimal]:
    """Total hours per work week (keyed by the week's start date)."""
    totals: dict[date, Decimal] = defaultdict(Decimal)
    for shift in shifts:
        for day, hours in hours_by_local_day(shift, tz).items():
            totals[_week_start(day)] += hours
    return dict(totals)


def split_regular_overtime(
    weekly_totals: dict[date, Decimal],
    threshold: Decimal = OVERTIME_WEEKLY_THRESHOLD,
) -> tuple[Decimal, Decimal]:
    """Split weekly totals into (regular, overtime) hours, per week."""
    regular = Decimal(0)
    overtime = Decimal(0)
    for hours in weekly_totals.values():
        if hours > threshold:
            regular += threshold
            overtime += hours - threshold
        else:
            regular += hours
    return regular, overtime


def compute_gross(
    regular_hours: Decimal,
    overtime_hours: Decimal,
    hourly_rate: Decimal,
    multiplier: Decimal = OVERTIME_MULTIPLIER,
) -> Decimal:
    """Gross dollars from hours and rate, rounded to the cent."""
    gross = hourly_rate * regular_hours + hourly_rate * multiplier * overtime_hours
    return gross.quantize(_CENTS, rounding=ROUND_HALF_UP)


def calculate_gross(
    punches: list[PunchLike],
    hourly_rate: Decimal,
    tz: ZoneInfo = DEFAULT_TZ,
) -> GrossResult:
    """End-to-end: punches + rate -> regular/overtime hours and gross pay."""
    shifts, anomalies = pair_punches(punches)
    weeks = weekly_hours(shifts, tz)
    regular, overtime = split_regular_overtime(weeks)

    # Record hours to the hundredth of an hour; compute pay from those figures
    # so stored hours and stored gross stay internally consistent.
    regular = regular.quantize(_HUNDREDTH_HOUR, rounding=ROUND_HALF_UP)
    overtime = overtime.quantize(_HUNDREDTH_HOUR, rounding=ROUND_HALF_UP)
    gross = compute_gross(regular, overtime, hourly_rate)

    return GrossResult(
        regular_hours=regular,
        overtime_hours=overtime,
        gross_pay=gross,
        shifts=shifts,
        anomalies=anomalies,
        weekly_hours=weeks,
    )
