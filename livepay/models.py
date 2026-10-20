"""SQLAlchemy ORM models — the LivePay domain.

Entities: Employee, Punch, PayPeriod, PayCalculation, Withdrawal, AuditLog.

Money is always stored as Numeric (-> Python Decimal), never float. Timestamps
are timezone-aware. Deduction columns on PayCalculation are nullable because
they are filled in by the deductions engine (Phase 3), after gross pay exists.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from livepay.db import Base


class PunchKind(enum.StrEnum):
    """Direction of a punch event."""

    IN = "in"
    OUT = "out"


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    # Pay rate in dollars/hour. Numeric(10, 2) -> Decimal, exact to the cent.
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    province: Mapped[str] = mapped_column(String(2), default="ON")
    # TD1 claim codes drive the tax tables used in Phase 3 (code 1 = basic
    # personal amount). The code is an employee input; the dollar amounts it
    # maps to are CRA constants defined later from T4127.
    federal_claim_code: Mapped[int] = mapped_column(default=1)
    ontario_claim_code: Mapped[int] = mapped_column(default=1)
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    punches: Mapped[list[Punch]] = relationship(back_populates="employee")
    pay_periods: Mapped[list[PayPeriod]] = relationship(back_populates="employee")
    calculations: Mapped[list[PayCalculation]] = relationship(back_populates="employee")
    withdrawals: Mapped[list[Withdrawal]] = relationship(back_populates="employee")

    __table_args__ = (CheckConstraint("hourly_rate >= 0", name="ck_employee_rate_nonneg"),)


class PayPeriod(Base):
    __tablename__ = "pay_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    employee: Mapped[Employee] = relationship(back_populates="pay_periods")
    calculations: Mapped[list[PayCalculation]] = relationship(back_populates="pay_period")

    __table_args__ = (
        # One pay period per employee per start date (biweekly cadence).
        UniqueConstraint("employee_id", "start_date", name="uq_period_employee_start"),
    )


class Punch(Base):
    __tablename__ = "punches"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    kind: Mapped[PunchKind] = mapped_column()
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Client-supplied key: sending the same punch twice must not double-count.
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    employee: Mapped[Employee] = relationship(back_populates="punches")


class PayCalculation(Base):
    """A pay snapshot: the result of recalculating one period at a point in time."""

    __tablename__ = "pay_calculations"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    pay_period_id: Mapped[int] = mapped_column(ForeignKey("pay_periods.id"))

    regular_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    gross_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    # Filled in by the deductions engine (Phase 3); null until then.
    cpp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cpp2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ei: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    federal_tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    provincial_tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_deductions: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    net_pay: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    employee: Mapped[Employee] = relationship(back_populates="calculations")
    pay_period: Mapped[PayPeriod] = relationship(back_populates="calculations")


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    pay_period_id: Mapped[int] = mapped_column(ForeignKey("pay_periods.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    employee: Mapped[Employee] = relationship(back_populates="withdrawals")

    __table_args__ = (CheckConstraint("amount > 0", name="ck_withdrawal_amount_positive"),)


class AuditLog(Base):
    """Append-only record of what happened and why, for traceability."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
