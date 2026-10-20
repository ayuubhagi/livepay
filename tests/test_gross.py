"""Unit tests for gross pay: overtime, midnight/week-boundary shifts, bad data."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from livepay.models import PunchKind
from livepay.payroll.gross import calculate_gross

TZ = ZoneInfo("America/Toronto")
RATE = Decimal("25.00")


@dataclass
class P:
    """Minimal punch stand-in for the calculator (duck-types PunchLike)."""

    kind: PunchKind
    event_time: datetime


def tor(year, month, day, hour, minute=0) -> datetime:
    """A timezone-aware America/Toronto timestamp."""
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def shift(in_dt, out_dt) -> list[P]:
    return [P(PunchKind.IN, in_dt), P(PunchKind.OUT, out_dt)]


def test_single_shift_no_overtime():
    punches = shift(tor(2026, 1, 5, 9), tor(2026, 1, 5, 17))  # 8h Monday
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("8.00")
    assert result.overtime_hours == Decimal("0.00")
    assert result.gross_pay == Decimal("200.00")
    assert result.anomalies == []


def test_weekly_overtime_over_44():
    # Mon–Fri, 10h/day = 50h in one work week.
    punches = []
    for day in range(5, 10):  # Jan 5..9 (Mon..Fri)
        punches += shift(tor(2026, 1, day, 8), tor(2026, 1, day, 18))
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("44.00")
    assert result.overtime_hours == Decimal("6.00")
    # 44*25 + 6*25*1.5 = 1100 + 225
    assert result.gross_pay == Decimal("1325.00")


def test_overtime_is_per_week_not_per_pay_period():
    # Week 1 (Jan 4–10): 40h. Week 2 (Jan 11–17): 48h. Total 88h.
    # Per-week overtime = 4h (only week 2 exceeds 44). Per-period (88h vs 88h
    # threshold) would wrongly give 0h overtime.
    punches = []
    for day in range(5, 10):  # 5 days x 8h = 40h, week 1
        punches += shift(tor(2026, 1, day, 9), tor(2026, 1, day, 17))
    for day in range(12, 18):  # 6 days x 8h = 48h, week 2
        punches += shift(tor(2026, 1, day, 9), tor(2026, 1, day, 17))
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("84.00")
    assert result.overtime_hours == Decimal("4.00")
    assert result.gross_pay == Decimal("2250.00")
    assert len(result.weekly_hours) == 2


def test_midnight_crossing_single_week():
    # Mon 22:00 -> Tue 06:00 = 8h, both days in the same work week.
    punches = shift(tor(2026, 1, 5, 22), tor(2026, 1, 6, 6))
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("8.00")
    assert result.gross_pay == Decimal("200.00")
    assert len(result.weekly_hours) == 1


def test_shift_crosses_work_week_boundary():
    # Sat Jan 10 22:00 -> Sun Jan 11 02:00: 2h in week 1, 2h in week 2.
    punches = shift(tor(2026, 1, 10, 22), tor(2026, 1, 11, 2))
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("4.00")
    assert result.overtime_hours == Decimal("0.00")
    assert len(result.weekly_hours) == 2
    assert all(h == Decimal("2") for h in result.weekly_hours.values())


def test_missing_clock_out_does_not_crash():
    punches = [P(PunchKind.IN, tor(2026, 1, 5, 9))]  # never clocked out
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("0.00")
    assert result.gross_pay == Decimal("0.00")
    assert [a.kind for a in result.anomalies] == ["open_shift"]


def test_clock_out_without_clock_in():
    punches = [P(PunchKind.OUT, tor(2026, 1, 5, 17))]
    result = calculate_gross(punches, RATE, TZ)

    assert result.gross_pay == Decimal("0.00")
    assert [a.kind for a in result.anomalies] == ["clock_out_without_clock_in"]


def test_two_clock_ins_in_a_row_drops_the_first():
    # IN 09:00, IN 10:00, OUT 12:00 -> only the 10:00–12:00 shift counts (2h).
    punches = [
        P(PunchKind.IN, tor(2026, 1, 5, 9)),
        P(PunchKind.IN, tor(2026, 1, 5, 10)),
        P(PunchKind.OUT, tor(2026, 1, 5, 12)),
    ]
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("2.00")
    assert "missing_clock_out" in [a.kind for a in result.anomalies]


def test_dst_spring_forward_pays_real_elapsed_hours():
    # 2026 DST begins Sun Mar 8, 02:00 -> 03:00. A 01:00–04:00 shift is only
    # 2 real hours because the 02:00 hour does not exist locally.
    punches = shift(tor(2026, 3, 8, 1), tor(2026, 3, 8, 4))
    result = calculate_gross(punches, RATE, TZ)

    assert result.regular_hours == Decimal("2.00")
    assert result.gross_pay == Decimal("50.00")


def test_fractional_hours_round_to_cents():
    # 7h20m = 7.333..h -> recorded 7.33h; 7.33 * 30 = 219.90.
    punches = shift(tor(2026, 1, 5, 9), tor(2026, 1, 5, 16, 20))
    result = calculate_gross(punches, Decimal("30.00"), TZ)

    assert result.regular_hours == Decimal("7.33")
    assert result.gross_pay == Decimal("219.90")
