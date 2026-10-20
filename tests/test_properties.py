"""Property-based tests (Hypothesis) for the gross pay engine.

Properties proven here (tax-independent):
* determinism — recomputing the same punches gives the same result;
* order-independence — the order punches arrive in doesn't change the result;
* invariants — hours and gross are never negative, and regular + overtime
  always equals total hours worked (conservation).

Net-pay properties (net >= 0, net <= gross) are added once the deductions
engine exists (Phase 3).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from livepay.models import PunchKind
from livepay.payroll.gross import (
    calculate_gross,
    pair_punches,
    split_regular_overtime,
    weekly_hours,
)

RATE = Decimal("20.00")


@dataclass
class P:
    kind: PunchKind
    event_time: datetime


# Whole-hour UTC timestamps across 2026: keeps hour totals exact integers so the
# conservation property isn't defeated by Decimal's finite context precision.
_BASE = datetime(2026, 1, 1, tzinfo=UTC)
event_times = st.integers(min_value=0, max_value=365 * 24).map(lambda h: _BASE + timedelta(hours=h))

punches_strategy = st.lists(
    st.builds(
        P,
        kind=st.sampled_from([PunchKind.IN, PunchKind.OUT]),
        event_time=event_times,
    ),
    max_size=12,
)


def _summary(result):
    return (result.regular_hours, result.overtime_hours, result.gross_pay)


@given(punches=punches_strategy)
def test_calculation_is_deterministic(punches):
    assert _summary(calculate_gross(punches, RATE)) == _summary(calculate_gross(punches, RATE))


@given(punches=punches_strategy, data=st.data())
def test_punch_order_does_not_change_result(punches, data):
    shuffled = data.draw(st.permutations(punches))
    assert _summary(calculate_gross(punches, RATE)) == _summary(calculate_gross(shuffled, RATE))


@given(punches=punches_strategy, rate=st.decimals(min_value=0, max_value=1000, places=2))
def test_hours_and_gross_never_negative(punches, rate):
    result = calculate_gross(punches, rate)
    assert result.regular_hours >= 0
    assert result.overtime_hours >= 0
    assert result.gross_pay >= 0


@given(punches=punches_strategy)
def test_regular_plus_overtime_conserves_total_hours(punches):
    shifts, _ = pair_punches(punches)
    weeks = weekly_hours(shifts)
    regular, overtime = split_regular_overtime(weeks)
    assert regular + overtime == sum(weeks.values(), Decimal(0))
    assert overtime >= 0
