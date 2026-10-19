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
