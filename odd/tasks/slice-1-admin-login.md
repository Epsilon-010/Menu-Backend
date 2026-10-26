# Slice 1 — Admin login with rotating tokens
Objective: an admin signs in to their tenant with email and password; the session survives with secure refresh rotation.
Branch: `feat/slice-1-admin-login` in `Backend` and `Menu-Frontend` (from `feat/slice-0-base`, main not merged yet). Delivery: single-pr per repo. Runner: `uv run pytest` (backend), `npm run typecheck` + `npm run lint` + `npm run build` (frontend).

## Specs
Backend:
- S1: "Modelos y migraciones: `tenants`, `users` (con `role` y `tenant_id`; en este slice solo se usa `admin`), `refresh_tokens` (hash, `family_id`, expiración, revocado/rotado)."
- S2: "Comando de seed que crea un tenant y su admin inicial."
- S3: "`POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`."
- S4: "Access JWT (15 min) con `tenant_id` y `role`; refresh opaco en cookie httpOnly; rotación y detección de reutilización (revoca la familia)."
- S5: "Hash Argon2, rate limiting del login con Redis, error genérico."
- S6: "Dependencia `require_role(...)` y contexto de tenant desde el token."

Frontend:
- S7: "Página `/login`, cliente HTTP con refresh automático ante 401, access token en memoria."
- S8: "Rutas protegidas por rol: `/admin` solo para `admin`; redirige a `/login` sin sesión."
- S9: "Al recargar la página, la sesión se recupera con `/auth/refresh`."
- S10: "Botón de cerrar sesión."

Done when:
- S11: "Con el admin del seed puedo iniciar sesión y ver `/admin` con el nombre de mi negocio."
- S12: "Credenciales incorrectas → error genérico; muchos intentos → bloqueo temporal."
- S13: "Recargar la página no cierra la sesión; tras el logout no puedo volver a `/admin`."
- S14: "Tests: rotación emite un refresh nuevo e invalida el anterior; reutilizar un refresh rotado revoca toda la familia; un token de un tenant no accede a datos de otro."

## Tasks
- [ ] T1 (S1, S2) tenants + staff modules: entities, ports, models, migration, seed command — inline
- [ ] T2 (S3, S4, S5, S6, S12, S14) auth module: login/refresh/logout/me, JWT, Argon2, Redis rate limit, require_role — inline
- [ ] T3 (S7, S8, S9, S10, S11, S13) frontend: HTTP client with single-flight refresh, auth context, /login, protected /admin, logout — inline
- [ ] T4 (S11, S13) end-to-end check with docker compose + CLAUDE.md/ROADMAP/README updates — inline

## Log
- L1 (2026-10-26, user): "checa el proyecto y haz la sigueitne slide"
- L2 (2026-10-26, user decision): runtime deps `argon2-cffi` + `python-jose` (chosen over PyJWT/pwdlib).
- L3 (assumptions, documented defaults): user email is globally unique and stored lowercase (login has no tenant input); refresh tokens are 256-bit random values stored as SHA-256 hashes; refresh lifetime slides on each rotation (7d admin, 12h waiter/kitchen, 30d table); login rate limit counts failures per IP (20/15 min) and per account (5/15 min), configurable by env; `JWT_SECRET` is required configuration (no default in code).
