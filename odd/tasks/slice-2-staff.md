# Slice 2 — Staff: waiters and kitchen
Objective: the admin manages waiter/kitchen accounts and each one signs in to their own view.
Branch: `feat/slice-2-staff` in both repos, stacked on `feat/auth-cookie-session`. Delivery: ask-on-risk. Runner: `uv run pytest` (Backend), `npm run typecheck && npm run lint && npm run build` (Menu-Frontend).

## Specs
- S1 Staff CRUD in the admin panel (ROADMAP): "CRUD de personal en el panel admin: nombre, usuario, rol (`waiter` o `kitchen`), activo sí/no, restablecer contraseña."
  - No hard delete: deactivating is the "D" (assumption: orders will reference staff in later slices).
  - Only `waiter`/`kitchen` accounts are managed here; admins are not listed nor editable.
- S2 Login (ROADMAP): "Login del personal con el mismo flujo de tokens; refresh de 12 horas (un turno)."
  - User decision (L2): "entra mediante usuarios y contrseña los usuarios los hace y los dara el admin entrarn el elogin y pues alc rear guardara el tenant id para que lo logie o le muestre la info de si tenant"
  - Consequence: the username is unique across the platform; login receives only username (or the admin's email) + password; the tenant comes from the account.
  - Username: trimmed, lowercased, 3–40 chars of `a-z 0-9 . _ -`. Duplicate → 409.
- S3 Redirect (ROADMAP): "`waiter` → `/waiter`, `kitchen` → `/kitchen` (pantallas vacías por ahora, con el nombre del usuario y cerrar sesión)."
- S4 Revocation (ROADMAP): "Desactivar un usuario revoca sus sesiones." CLAUDE.md: "revoca de inmediato todas sus sesiones".
  - All refresh families of the user are revoked, and access tokens issued before the revocation are rejected (Redis marker for the access TTL).
  - Resetting a password also revokes the user's sessions (assumption).
- S5 Done when (ROADMAP, verbatim):
  - "Creo un mesero y un cocinero, entro con cada uno y llego a su vista."
  - "Un mesero o cocinero recibe 403 en endpoints de admin (tests por rol)."
  - "Desactivar al mesero cierra su sesión activa."
- S6 Isolation (CLAUDE.md): a tenant cannot see nor modify another tenant's staff; `table` gets 403 on admin operations.

## Tasks
- [x] T1 (S2, S4) Backend: username column + migration, login by username or email, session revocation (refresh families + access marker) — inline — RED: collection errors (missing modules); GREEN: 125 passed — see L4
- [x] T2 (S1, S4, S5, S6) Backend: staff use cases + `/api/v1/staff` admin router — inline — same commit as T1 (shared user domain and wiring) — see L4
- [x] T3 (S1, S3, S5) Frontend: login label, staff admin page, `/waiter` and `/kitchen` views — inline — typecheck/lint/build OK — Menu-Frontend 8d986a0 — see L5

## Log
- L1 (2026-10-26, user): "sigue con la siguiente slide checa el proyecto"
- L2 (2026-10-26, user): "entra mediante usuarios y contrseña los usuarios los hace y los dara el admin entrarn el elogin y pues alc rear guardara el tenant id para que lo logie o le muestre la info de si tenant"
- L3 (decision): access-token revocation check in Redis fails open (logged) so a Redis outage does not sign every device out; refresh revocation in Postgres still ends the session within the 15-minute access TTL.
- L4 (evidence, 2026-10-27): login body field renamed `email` -> `username` (takes the admin's email or a staff username); generic error "Invalid username or password"; `/auth/me` user gains `username` and `email` becomes nullable. Endpoints: `GET/POST /api/v1/staff`, `PATCH /api/v1/staff/{id}` (full_name, role, is_active), `PUT /api/v1/staff/{id}/password`. Deactivation, role change and password reset revoke every refresh family and mark `auth:revoked:{user_id}` in Redis; JWT `iat`/`exp` now carry sub-second precision for that comparison. Migration `c2f1caabe991` round-trips (downgrade deletes accounts without email). `uv run pytest`: 125 passed (78 at baseline). Incident: a mistaken `alembic downgrade -1` on the dev DB (still at the first revision) dropped all tables; the demo tenant/admin were re-seeded (`admin@demo.com`, new tenant id).
- L5 (evidence, 2026-10-27): E2E through the Vite proxy with curl: admin creates `demo.mesero` (waiter) and `demo.cocina` (kitchen); each signs in and `/me` shows its role and tenant; both get 403 on `GET`/`PATCH /staff`; deactivating `e2e.waiter` turns its live `/me` and refresh into 401 and blocks a new login. Independent verifier: S1-S6 PASS, no blockers; advisories: staff schemas ignore unknown fields (no `extra="forbid"`), staff router builds the auth refresh repository, revocation relies on one clock (single instance today), frontend `username` typed non-null. Native review (Gentle AI, Sonnet via `ANTHROPIC_MODEL`): Menu-Frontend `review-97050e829cee60fa` (base main, 4 lenses) approved and acknowledged; Backend `review-eb73ed83bc78ad25` (slice 2 commit only, 4 lenses) approved and acknowledged. Next: push `feat/slice-2-staff` in both repos and open PRs to `main` (they also carry `feat/auth-cookie-session`).
- L6 (2026-10-27, user): "ya le hice merge puedes revisar si si dime y deja todo listo para la sieguitne slide para abrir toro chat" -> PR #3 merged in Menu-Backend (de3f819) and Menu-Frontend (d901149); CI on `main` green in both. Full-range Gentle AI review of Backend from `main` (`review-495c92edd891d427`, 4 lenses) approved and acknowledged. Slice 2 closed in ROADMAP.md and CLAUDE.md.
