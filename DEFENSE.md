# DEFENSE.md

The design log for LivePay. Updated every phase. For each phase: decisions
made, tradeoffs/alternatives, what is simplified vs. real payroll, and likely
interview questions with good answers.

---

## Phase 0 — Scaffold

### What we built

Project skeleton: a FastAPI app with a `/health` endpoint, a Python 3.12
environment managed by `uv`, Postgres + Redis defined in Docker Compose,
a pytest suite, ruff linting/formatting, and a GitHub Actions CI pipeline.

### Decisions and why

- **`uv` for env + dependency management.** The machine had Python 3.11/3.13/3.14
  but not the required 3.12. `uv` installs a real 3.12 and pins it, so local,
  Docker, and CI all run the identical interpreter and dependency set (via the
  committed `uv.lock`). Reproducibility is the whole point of a lockfile.
- **Dependencies added per phase, not all up front.** Phase 0 only pulls in
  FastAPI + the test/lint toolchain. SQLAlchemy, Alembic, and Redis clients
  arrive in the phases that use them, so the git history honestly shows when
  and why each dependency appeared.
- **Typed Pydantic response model on `/health`.** Returning a `Health` model
  instead of a bare dict gives FastAPI an accurate OpenAPI schema and validates
  the outgoing shape. Cheap correctness.
- **Health = liveness only.** `/health` confirms the process is serving
  requests; it deliberately does **not** check Postgres/Redis yet. When those
  are wired in, a separate readiness concept can check dependencies. Mixing the
  two is a common mistake: a DB blip shouldn't make an orchestrator kill a
  perfectly healthy process.
- **Only Postgres + Redis are containerized.** The app runs on the host during
  early development for a faster edit/test loop. Healthchecks are defined on
  both services now so later phases can gate startup on `service_healthy`.
- **Pinned image versions** (`postgres:16-alpine`, `redis:7-alpine`) rather than
  `latest`, so the environment doesn't drift underneath us.
- **`.gitattributes` forces LF.** Avoids CRLF/LF churn between this Windows dev
  box and Linux CI.

### Tradeoffs / alternatives considered

- **`uv` vs. `pip` + `venv` vs. Poetry.** `uv` is fastest and handles the Python
  version install itself; the tradeoff is it's a newer tool an interviewer may
  not know. The lockfile story is the justification.
- **App not containerized yet.** Simpler and faster now; the cost is that "works
  on my machine" risk returns until we add an app Dockerfile (planned for the
  event-pipeline phase, where a separate worker process makes a container
  genuinely useful).
- **CI has no DB/Redis service containers yet.** No test needs them in Phase 0,
  so adding them would be dead config. They go in when the first integration
  test lands.

### Simplified vs. real payroll

Nothing payroll-specific exists yet. The one scaffold-level simplification:
secrets (`POSTGRES_PASSWORD`) are hardcoded dev values in compose and
`.env.example`. Real systems inject these from a secrets manager.

### Likely interview questions

- **Why `uv` over pip/Poetry?** Speed, built-in Python-version management, and a
  lockfile for reproducible installs across local/Docker/CI.
- **What's the difference between liveness and readiness, and which is
  `/health`?** Liveness = "is the process up"; readiness = "can it serve
  traffic (deps reachable)". `/health` is liveness; it intentionally doesn't
  probe Postgres/Redis so a transient DB issue doesn't get the process killed.
- **Why pin image tags and commit a lockfile?** Reproducibility — the same
  bytes everywhere, no silent drift from `latest` or floating version ranges.
- **Why not add all dependencies now?** Honest, reviewable history; each dep
  appears in the commit that needs it, and unused deps don't widen the attack
  surface or slow installs.
- **Why is the app not in Docker?** Faster dev loop early on; it gets
  containerized when the worker process makes it worthwhile.

---

## Phase 1 — Domain models + migrations

### What we built

Six SQLAlchemy 2 models (Employee, PayPeriod, Punch, PayCalculation,
Withdrawal, AuditLog), a config/session layer, an Alembic migration that
creates the schema, and DB-backed tests with a Postgres service in CI.

### Decisions and why

- **SQLAlchemy 2 typed models** (`Mapped[...]` / `mapped_column`). Static types
  flow into the ORM, so mypy/IDE catch column misuse.
- **Money as `Numeric`, never `Float`.** `hourly_rate`/`gross_pay`/etc. are
  `Numeric(p, 2)`, mapping to Python `Decimal`. Floats can't represent `0.10`
  exactly, so cents drift — unacceptable for payroll.
- **Timezone-aware timestamps** (`DateTime(timezone=True)`). Punches cross
  midnight and we compare instants; naive local times would be ambiguous around
  DST. Store UTC, interpret in the employee's zone at calculation time.
- **Deduction columns are nullable.** A `PayCalculation` exists after gross pay
  is known (Phase 2) but before deductions (Phase 3); null = "not computed yet,"
  distinct from `0`.
- **Idempotency key is `UNIQUE` on `punches`.** The database is the final
  guarantee that the same punch can't be inserted twice, even under a race —
  not just app-level checks.
- **CHECK constraints** (`hourly_rate >= 0`, `withdrawal.amount > 0`). Invariants
  belong in the DB so bad data can't exist regardless of which code writes it.
- **`punchkind` as a DB enum**; the migration's downgrade explicitly drops the
  enum type, because Postgres leaves it behind after the table is dropped.
- **Alembic URL comes from app settings**, not hardcoded in `alembic.ini`, so
  migrations and the app always share one source of truth.
- **Tests use a dedicated `livepay_test` DB with SAVEPOINT rollback** per test,
  so they are isolated and order-independent and never touch dev data.

### Tradeoffs / alternatives considered

- **Integer PKs vs. UUIDs.** Chose auto-increment ints for simplicity/readability.
  UUIDs would avoid ID enumeration and suit distributed inserts; noted as a
  future change if the event pipeline ever generates IDs client-side.
- **`create_all` in tests vs. running migrations in tests.** Used `create_all`
  for speed; the migration's correctness is proven separately by a full
  up/down/up cycle. A stricter setup would run `alembic upgrade head` in tests.
- **YTD amounts: derived vs. stored.** No YTD column yet — year-to-date CPP/EI
  will be summed from prior `PayCalculation` rows in Phase 3. Simpler and avoids
  a denormalized field that can drift; revisit if it becomes a performance issue.

### Environment gotchas (worth being able to explain)

- Dev box has a **native Postgres on 5432**, so compose maps the container to
  **5433** to avoid the clash. CI has no such conflict and uses 5432.
- The repo lives under **OneDrive**, which locked files in `.venv`; the project
  venv is kept **outside** OneDrive via `UV_PROJECT_ENVIRONMENT`.

### Likely interview questions

- **Why `Decimal`/`Numeric` for money?** Binary floats can't represent most
  decimal fractions exactly; errors accumulate. `Numeric` is exact base-10.
- **Where do you enforce idempotency and why there?** A `UNIQUE` DB constraint —
  the only place that holds under concurrent inserts; app checks alone have a
  check-then-insert race.
- **Why nullable deduction columns?** They model "not yet computed" vs. a real
  zero; the snapshot is written in two stages (gross, then deductions).
- **How are tests isolated?** Each runs in a transaction rolled back at the end
  (SAVEPOINT pattern) against a throwaway `livepay_test` database.
- **Why store UTC timestamps?** Unambiguous instants for midnight-crossing and
  DST; localize only when presenting or applying provincial rules.

---

## Phase 2 — Gross pay

### What we built

A pure-function engine (`livepay/payroll/gross.py`) that turns a list of punches
+ an hourly rate into regular hours, overtime hours, and gross dollars, plus a
list of anomalies. Ten unit tests cover every edge case.

### Decisions and why

- **Pipeline: punches → shifts → hours per local day → hours per work week →
  regular/overtime → dollars.** Splitting each shift across local calendar days
  is the key trick: it handles both midnight crossing and shifts that straddle
  the Sat/Sun work-week boundary with the same code.
- **Elapsed time is computed in UTC, boundaries in local time.** Hours paid =
  real elapsed time (correct across DST); day/week membership = local calendar
  (what "a work week" means). A 1:00–4:00 shift on spring-forward day is 2 paid
  hours, not 3.
- **The same-tzinfo subtraction trap.** Subtracting two aware datetimes that
  share one `tzinfo` object makes Python do naive wall-clock subtraction and
  ignore DST. We convert to UTC first (`_elapsed_hours`). A test (`test_dst_
  spring_forward...`) pins this.
- **Overtime is weekly (per Sun–Sat work week), not per pay period.** Ontario
  ESA s. 22: over 44 h in a *work week* at 1.5×. A test proves a 40h + 48h
  biweekly period yields 4h OT, which a per-period calc would miss.
- **Resilient punch pairing, never raises.** Missing clock-out → `open_shift`
  (zero hours); two clock-ins in a row → drop the first; clock-out with no
  clock-in → flagged and skipped. Bad data produces anomalies, not crashes.
- **Rounding.** Hours recorded to 0.01h, gross to the cent (`ROUND_HALF_UP`),
  computing gross from the recorded hours so stored values stay consistent.
  No earlier rounding — matches the "round only where required" rule.

### Tradeoffs / alternatives considered

- **Dropping the first of two consecutive clock-ins** vs. guessing an end time.
  We can't know when someone left, so inventing hours would be wrong; dropping
  + flagging is the safe, auditable choice.
- **Work week fixed to Sunday–Saturday.** ESA lets the employer define it; we
  use the statutory default. A real system would store it per employer.
- **Hours attributed by splitting at local midnight** vs. attributing a whole
  shift to its start day. Splitting is more correct for week-boundary OT and
  costs little.

### Simplified vs. real payroll

Hourly only (no salaried); no stat-holiday pay, no daily OT (Ontario has none),
no averaging agreements, no shift premiums. Single rate per employee.

### Likely interview questions

- **How do you handle a shift crossing midnight / a week boundary?** Split the
  shift into per-local-day segments; each day maps to a work week, so the hours
  land in the right week(s) automatically.
- **How is overtime computed and why per week?** Sum each Sun–Sat week; hours
  over 44 are overtime. ESA defines OT weekly, so a per-pay-period sum would be
  wrong when one week is light and the other heavy.
- **What happens on a missing clock-out?** It becomes an `open_shift` anomaly
  with zero counted hours; the calculation still completes.
- **Why compute elapsed time in UTC?** To avoid the same-tzinfo wall-clock
  subtraction bug and pay the true hours worked across DST.
- **Where could float have crept in and why didn't it?** Durations come from
  `timedelta`; everything downstream is `Decimal`, rounded only at the end.
