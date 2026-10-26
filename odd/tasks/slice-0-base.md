# Slice 0 — Project base
Objective: working skeleton (backend, frontend, Docker, CI) before the first feature.
Branch: `feat/slice-0-base` in `Backend` and `Menu-Frontend` (two separate repos). Delivery: single-pr per repo. Runner: `uv run pytest` (backend), `tsc --noEmit` + `npm run lint` + `npm run build` (frontend).

## Specs
- S1: "Backend con `uv init`, estructura hexagonal (`modules/`, `shared/`) y FastAPI."
- S2: "`docker-compose.yml` con postgres, redis, backend y frontend; `.env.example`." — lives in the `Backend` repo, frontend built from `../Menu-Frontend` (decision L2).
- S3: "Alembic configurado leyendo la URL de las settings."
- S4: "Frontend React + Vite + TS + Tailwind con React Router."
- S5: "pytest configurado con BD de prueba (migraciones de Alembic) y carpetas `tests/unit` y `tests/integration`."
- S6: "Workflow de GitHub Actions `.github/workflows/ci.yml` con jobs de backend, frontend y docker." — one workflow per repo (decision L2).
- Done when:
  - S7: "`docker compose up -d --build` levanta los 4 servicios sin errores."
  - S8: "`GET /api/v1/health` responde 200 e informa conexión a Postgres y Redis."
  - S9: "`uv run pytest` pasa con al menos el test del health."
  - S10: "El frontend abre en el navegador y muestra una página inicial."
  - S11: "Al hacer push de la rama y abrir un pull request, la CI corre en GitHub y queda en verde." — push/PR is a user decision.
- S12: "los id se autogenrar y son uuid usan la libreria que ya existe e igual modificalo en el proyecot y demas" — primary keys are auto-generated UUIDs (stdlib `uuid`), provided by a shared mixin and documented in CLAUDE.md.

## Tasks
- [ ] T1 (S1, S3, S5, S8, S9) backend skeleton, settings, health, Alembic, pytest, Dockerfile — inline
- [ ] T2 (S4, S10) frontend Tailwind + Router + strict + home page + Dockerfile — inline
- [ ] T3 (S2, S6, S7, S11) docker-compose, `.env.example`, CI workflows in both repos — inline
- [ ] T4 (S12) UUID primary key mixin + CLAUDE.md convention — inline

## Log
- L1 (2026-10-26, user): "revisa el claude.md para entender el proeycto y el entrono que se usara y el roadmap para las slices que me entregaras, hazlas usanado las herrameitnas de egram odd y demas"
- L2 (2026-10-26, user decision): two separate repos ("Dos repos separados"): `Backend` → Epsilon-010/Menu-Backend, `Menu-Frontend` → Epsilon-010/Menu-Frontend. Each repo has its own CI; the 4-service docker-compose lives in the backend repo and builds `../Menu-Frontend`. Folder kept as `Backend` (rename to `Menu-Backend` was blocked by Windows file lock).
- L3: Postgres driver chosen: `asyncpg` (async SQLAlchemy + Alembic async env); psycopg v3 async was rejected because it does not run on the default Windows Proactor event loop. Async tests use the AnyIO pytest plugin bundled with FastAPI (no extra test lib).
- L4 (2026-10-26, user): "lops id se autogenrar y son uuid usan la libreria que ya existe e igual modificalo en el proyecot y demas" → stdlib `uuid.uuid4` in Python (domain can create ids without the DB) plus Postgres `gen_random_uuid()` server default. Per-tenant order sequence numbers stay integers (display number, not the id).
