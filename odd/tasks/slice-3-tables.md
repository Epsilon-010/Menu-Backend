# Slice 3 — Tables and device login
Objective: the admin creates tables and each tablet signs in as its table.
Branch: `feat/slice-3-tables` in both repos, from `main`. Delivery: ask-on-risk. Runner: `uv run pytest` (Backend), `npm run typecheck && npm run lint && npm run build` (Menu-Frontend).

## Specs
- S1 Tables CRUD (ROADMAP): "CRUD de mesas en el panel admin (nombre/número, activa sí/no)."
  - Name: trimmed, 1-60 chars, unique per tenant (case-insensitive). Duplicate -> 409 (assumption).
  - No hard delete: deactivating is the "D" (assumption: orders and bills reference tables in later slices).
- S2 Device credentials (ROADMAP): "Al crear una mesa se generan credenciales de dispositivo (código de mesa + PIN) que el admin ve una sola vez y puede regenerar (regenerar revoca las sesiones de esa mesa)."
  - Design accepted by the user (L2): table code of 6 characters without ambiguous ones (no 0/O/1/I/L), generated, unique across the platform (login receives no tenant; the tenant comes from the table), fixed and always visible to the admin.
  - PIN: 6 generated digits, returned only in the create and regenerate responses, stored as an Argon2 hash. Regenerating changes only the PIN.
- S3 Login (ROADMAP): "Login de mesa con rol `table` y `table_id` en el token; refresh de 30 días."
  - `POST /api/v1/auth/table-login` with `{code, pin}`; same cookies as staff login; generic error "Invalid table code or PIN"; rate limit per table code; inactive tables cannot sign in.
  - Refresh tokens of a table store `table_id` (and no `user_id`); `/auth/me` returns `table` instead of `user` for the `table` role.
- S4 Redirect (ROADMAP): "Tras el login, redirige a `/menu` mostrando el nombre de la mesa."
- S5 Done when (ROADMAP, verbatim):
  - "Creo la \"Mesa 4\", entro con sus credenciales desde otra pestaña y veo `/menu` como Mesa 4."
  - "Un token `table` recibe 403 en cualquier endpoint de admin, mesero o cocina (con test)."
  - "Desactivar la mesa o regenerar su PIN cierra la sesión del dispositivo."
- S6 Tenant isolation (CLAUDE.md + L2): every new table carries `tenant_id` (FK + index); every query over tenant data filters by the tenant taken from the token. The only platform-wide lookup is the pre-auth search by table code (same as the existing username/email login lookup), isolated in one repository method so a future Postgres RLS policy can route it. A tenant cannot see nor modify another tenant's tables; `table`, `waiter` and `kitchen` get 403 on table management.

## Tasks
- [x] T1 (S1, S2, S3, S5, S6) Backend: `tables` module + migration, table login, table sessions in `refresh_tokens`, `/me` for tables — inline (no Writer trigger: one dependent unit) — RED: collection error (no `app.modules.tables`), 12 API tests failing; GREEN: 162 passed — see L4
- [ ] T2 (S1, S2, S4, S5) Frontend: tables admin panel, "Table" login tab, `/menu` showing the table name — inline
- [ ] T3 (S1-S6) Independent verification — delegated (Risk items 1: `refresh_tokens` schema change; 2: authentication)

## Log
- L1 (2026-10-27, user): "sigue con la sigueitne slide"
- L2 (2026-10-27, user): "si el codgio + pin pero recuerda que siempre deben de llevar el tenatn id para qeu no muesyre informacion de alguien mas porque estoy pensando a la bd ponerle un RLS en base a  ese tenat sigue con la slide"
- L3 (2026-10-27, user): "el tenatn_id no debe de ser un nombre debe de ser un uuid" — verified: `tenants.id` is a UUID (`UUIDPrimaryKey`); `tables.tenant_id` and `refresh_tokens.tenant_id` are UUID FKs taken from the token; the tenant name is only a display field.
- L4 (evidence, 2026-10-27): endpoints `GET/POST /api/v1/tables`, `PATCH /api/v1/tables/{id}` (name, is_active), `POST /api/v1/tables/{id}/pin` (new PIN, same code), admin only; `POST /api/v1/auth/table-login` `{code, pin}`, limiter key `table:{CODE}`. `/auth/me` gains `table` (null for staff; `user` is null for tables). Migration `370b69df3ba3`: table `tables` (unique `code`, unique index `(tenant_id, lower(name))`), `refresh_tokens.table_id` FK + index, `user_id` nullable, CHECK `ck_refresh_tokens_subject` (exactly one). Round-trip downgrade/upgrade run on the test DB only (downgrade deletes table sessions); dev DB upgraded. `uv run pytest`: 162 passed (125 at baseline). Known gap: two concurrent creates with the same name hit the unique index and return 500 instead of 409 (same as staff usernames).
