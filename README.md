# LivePay

A small continuous payroll engine for Ontario that recalculates an employee's
gross and net pay on every clock-in/clock-out event and shows how much earned
pay they could withdraw right now.

> ⚠️ **Learning project — not a real payroll product.**
> LivePay was built to learn continuous payroll calculation and on-demand pay,
> inspired by Dayforce's continuous calculation and Dayforce Wallet. It is
> **not** tax advice, it is **not** certified, and it must not be used to pay
> real people. Tax logic targets **Ontario only** and uses the CRA T4127
> Payroll Deductions Formulas (2026 edition). Always verify against the CRA
> Payroll Deductions Online Calculator (PDOC).

## Status

🚧 Under construction. Built in phases; see `DEFENSE.md` for the design log.

- [x] Phase 0 — Scaffold (FastAPI, Postgres + Redis via Docker, pytest, ruff, CI)
- [ ] Phase 1 — Domain models + migrations
- [ ] Phase 2 — Gross pay (overtime, midnight-crossing, missing clock-outs)
- [ ] Phase 3 — Deductions (CPP/CPP2, EI, federal + Ontario tax)
- [ ] Phase 4 — PDOC verification tests
- [ ] Phase 5 — Event pipeline (Redis Streams, worker, idempotency)
- [ ] Phase 6 — Wallet (available balance, withdrawals, locking)
- [ ] Phase 7 — Property-based tests (Hypothesis)
- [ ] Phase 8 — README polish + architecture diagram
- [ ] Phase 9 — Optional React dashboard

## Stack

Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy 2 + Alembic · Redis Streams ·
pytest + Hypothesis · ruff · Docker Compose · GitHub Actions.

## Quick start (Phase 0)

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker Desktop.

```bash
# 1. Start Postgres + Redis
docker compose up -d

# 2. Create the Python 3.12 environment and install deps
uv sync

# 3. Run the API
uv run uvicorn livepay.main:app --reload

# 4. Check it's alive
curl http://localhost:8000/health
# -> {"status":"ok"}
```

## Development

```bash
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pytest            # tests
```

## What's simplified vs. real payroll

Tracked in detail in `DEFENSE.md`. In short: Ontario only, no vacation pay,
no benefits/taxable allowances, salaried-vs-hourly limited to hourly, and tax
figures are verified against PDOC rather than CRA-certified.
