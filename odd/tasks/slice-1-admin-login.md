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
- S15: "el contador de intentos quiero que sea por usuairo que intenten entrar porfavor si es por ip muchas ips pueden entrar al usauor o intnetrar entrar que sea pro usuaoro porfavor" — login attempts are limited per account only; the per-IP counter is removed. Supersedes the IP part of S5.
- S16: "igual los jwt que esten en cookies o se setten ahi porfavor" — the access JWT travels in an httpOnly, Secure, SameSite=Strict cookie (path /api) and is no longer returned in the response body or kept in JS memory. Supersedes the in-memory part of S7.

## Tasks
- [x] T1 (S1, S2) tenants + staff modules: entities, ports, models, migration, seed command — inline — RED: import error; GREEN: 25 passed; migration up/down/up OK — Backend 182dcda
- [x] T2 (S3, S4, S5, S6, S12, S14) auth module: login/refresh/logout/me, JWT, Argon2, Redis rate limit, require_role — inline — RED: import error (unit); GREEN: 74 passed — Backend f699c6c
- [x] T3 (S7, S8, S9, S10, S11, S13) frontend: HTTP client with single-flight refresh, auth context, /login, protected /admin, logout — inline — no frontend test runner (exception): typecheck/lint/build OK — Menu-Frontend c6ed3e0
- [x] T4 (S11, S13) end-to-end check with docker compose + CLAUDE.md/ROADMAP/README updates — inline — API flow verified through the Vite proxy; pushed, CI green (Menu-Backend run 40421334883: backend, docker; Menu-Frontend run 40421338931: frontend, docker); merged to main (PR #1 slice 0, PR #2 slice 1 in both repos), CI green on main (Backend 0124ebf, Menu-Frontend 82b0a3e)
- [ ] T5 (S15) per-account-only login limiter — inline — branch feat/auth-cookie-session
- [ ] T6 (S16) access token cookie in backend and frontend — inline — branch feat/auth-cookie-session

## Log
- L1 (2026-10-26, user): "checa el proyecto y haz la sigueitne slide"
- L2 (2026-10-26, user decision): runtime deps `argon2-cffi` + `python-jose` (chosen over PyJWT/pwdlib).
- L3 (assumptions, documented defaults): user email is globally unique and stored lowercase (login has no tenant input); refresh tokens are 256-bit random values stored as SHA-256 hashes; refresh lifetime slides on each rotation (7d admin, 12h waiter/kitchen, 30d table); login rate limit counts failures per IP (20/15 min) and per account (5/15 min), configurable by env; `JWT_SECRET` is required configuration (no default in code).
- L4 (decision): auth module reuses staff/tenants through their application use cases (FindUserByEmail, GetUser, GetTenant), never their tables. JWT adapter lives in auth/infrastructure; shared only knows the AccessTokenDecoder port (app.state.access_tokens).
- L5 (evidence): docker compose rebuilt backend (new deps); seed created tenant 'La Taqueria Demo' / admin@demo.com in the dev DB; through http://localhost:5173 proxy: login 200 + refresh cookie, /me returns business name, refresh 200, logout 204, refresh after logout 401. Integration RED was not observed separately (tests and adapters written in the same step); unit RED observed.
- L6 (known limitation): per-IP login limit uses request.client.host; behind the Vite/nginx proxy every client shares the proxy IP. Trusted-proxy handling is pending.
- L7 (verification, independent verifier): one blocker B1 — parallel wrong-password logins bypassed the rate limit (30 parallel → 28×401, 2×429; limit 5/account) because the check and the increment were not atomic. Fixed: attempts counted with atomic INCR before the password check, given back on success (Backend ce1d2f9); recheck with the same probe → 5×401, 25×429; regression tests in tests/integration/modules/auth/test_rate_limiter.py; 77 passed. Also fixed advisories: Argon2 now runs in a worker thread; failed logout request still ends the local session (Menu-Frontend 66db36c). Open advisories: two tabs refreshing at the same instant revoke the family (spec'd reuse rule); per-account lockout can be triggered by anyone knowing the email; no absolute session cap (sliding refresh); access tokens of a deactivated user stay valid up to 15 min on require_role routes (deactivation is Slice 2); python-jose maintenance risk.
- L8 (native review): full-history candidate (99 files) failed with lens_context_budget_exceeded; reduced candidate 182dcda..fc7c429 (25 files, 1443 lines, lenses risk + resilience) granted by the user, approved and acknowledged (lineage review-9efded3b9b52576e, authority burned). No blockers; advisory follow-ups: per-IP budget is refunded on every successful login (DECR), so one valid credential lets an IP keep spraying other accounts; attempt-based per-account lockout is a DoS primitive; client IP from the peer; Redis down makes login fail; Argon2 thread-pool exhaustion under bursts; refresh not retry-safe on network loss; refresh_tokens table never pruned; no auth-failure logging.
- L9 (2026-10-26, user): "haz los ci y subelo" -> pushed feat/slice-1-admin-login in both repos; CI green on 8b38022 (backend) and 66db36c (frontend).
- L10 (2026-10-26, user): "ya hice merge checa y vee que mas hace falta para termianr esta slide y si ya no hae falta nada marcala como guardada o demas" -> PRs #1 and #2 merged in both repos, CI on main green; slice closed in ROADMAP.md and CLAUDE.md. Browser walkthrough (S11/S13) was not reported back by the user; covered at API level by tests and the proxy flow (L5).
- L11 (2026-10-26, user): "el contador de intentos quiero que sea por usuairo que intenten entrar porfavor si es por ip muchas ips pueden entrar al usauor o intnetrar entrar que sea pro usuaoro porfavor igual los jwt que esten en cookies o se setten ahi porfavor" -> slice reopened for T5/T6. Verified: the per-account limit (5/15 min) already existed next to the per-IP one; per-IP removed (also fixes the shared-proxy-IP and success-refund advisories). CSRF for cookie auth relies on SameSite=Strict (same-origin frontend). CLAUDE.md auth section updated accordingly.
