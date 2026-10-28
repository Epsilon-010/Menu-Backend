# Self sign-up and staff code + PIN

Objective: a business owner signs up alone (email + password, then the business name) and lands in the admin panel;
staff members are created with only a name and sign in with a generated code + PIN. Branch `feat/self-signup-staff-pin`
in Backend and Menu-Frontend (stacked on `feat/slice-7-kitchen`). Delivery: ask-on-risk. Runner: `uv run pytest`,
`npm test`.

## Specs

- **S1** Sign-up. User words (L1): "un usuario entrara como admin se registrara ya sea usaruio y contrañsea cuante y
  demas ... antes la persona debe de poder registrar su necoio de comida con nombre o asi solo que pida el nombre y
  datos que no genrern firccion de moemtn solo el nombre para cerar el registro". `POST /api/v1/auth/register`
  `{id?, email, password, business_name}` creates the tenant and its admin in **one transaction** and signs in
  (same cookies as login, `201 {expires_in, role: "admin"}`). Validation as today: email format, password 8-128,
  business name 1-120. Email taken: 409 "Email already in use". Rate limited per client IP (namespace `signup:`).
  The admin's `full_name` is "Admin" (no extra field: no friction). Idempotent: `id` is the tenant id chosen by the
  client; repeating the same sign-up (same id, email, password and business name) signs in to the account already created; the same
  id with other data: 409 "That id is already used by something else".
- **S2** Sign-up UI: `/register`, two steps in one form (step 1 email + password, step 2 business name), then
  redirect to `/admin`. Link from `/login`. Errors shown inline.
- **S3** After sign-up the admin panel is the one that exists today (staff, tables, catalog...), scoped to the new
  tenant. "el panel ya parecera como esta de meseros y demas y apartir de eso se crear el tenant que se usara o se
  asociara a ese rergiteos de negocio".
- **S4** Staff create with only a name. User words: "la parte de registo de mesero solo que pida el nombre y genere
  un pin para ese mesero y el admin se lo proporcionara". `POST /api/v1/staff` `{id?, full_name, role}` (role
  `waiter` | `kitchen`; decision L2 applies to both) generates a **staff code** (6 characters, alphabet
  `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, unique across the platform) and a **PIN** (6 digits, Argon2). Response `201`
  `{id, code, full_name, role, is_active, pin}`; the PIN is shown only once. Replay of the same id: 409 "This staff
  member was already created; generate a new PIN to see the credentials"; id of something else: 409 "That id is
  already used by something else".
- **S5** No collisions by name. User words: "como se puede hacer o asi para que la bd no cunfa por ejemplo si hay
  alguien llamado agustin quiuevedo en un locla y en toro igual y se registra con ese n0mbre que no lo bote porque
  este agaradno el pin de alguien mas". Names may repeat within a tenant and across tenants; the login identifier is
  the code, never the name.
- **S6** Staff login: code + PIN through the existing `POST /api/v1/auth/login` (`username` = code, any case;
  `password` = PIN), same rate limiting (`staff:<code>`), same generic error. Login page tabs: Admin (email +
  password), Staff (code + PIN), Table (code + PIN).
- **S7** `POST /api/v1/staff/{id}/pin` regenerates the PIN (code stays), returns `{..., pin}` and ends every session
  of the member. Replaces `PUT /staff/{id}/password` (removed). Staff list/update responses carry `code` instead of
  `username`.
- **S8** Existing staff accounts (dev data, e.g. `demo.mesero`) keep their login identifier as their code and their
  old password until the admin generates a new PIN. No data migration.
- **S9** Tenant isolation and roles: a tenant never sees/edits another's staff; `table`/`guest`/`waiter`/`kitchen`
  get 403 on staff admin endpoints; sign-up needs no session.

## Tasks

| ID | Specs | Route | Status | Commit |
|----|-------|-------|--------|--------|
| T1 | S1, S4-S9 backend | delegated (writer reason: parallel units, backend + frontend, disjoint repos) | done (L6) | d545148, 25a9842, adf863c, 5e519cf, L6 fix |
| T2 | S2, S3, S4, S6, S7 frontend | delegated (same parallel launch) | done (RED/GREEN: register.test.ts, staff/api.test.ts) | Menu-Frontend f12d46f, 387f5ca |
| T3 | all | inline: docs (CLAUDE.md, ROADMAP.md), e2e check, risk/verify | done (L7) | c6757ca, Menu-Frontend ce2fe59 |

## Log

- **L1** (2026-10-28, user, verbatim): "sigue con la sigeuite slice chec ael repo, pero antes queiro que el flujo
  cambie un poco un usuario entrara como admin se registrara ya sea usaruio y contrañsea cuante y demas dene de poder
  registrace una vez dentor de le muestra el panel que ya tenemos solo que antes la persona debe de poder registrar su
  necoio de comida con nombre o asi solo que pida el nombre y datos que no genrern firccion de moemtn solo el nombre
  para cerar el registro una vez eso el panel ya parecera como esta de meseros y demas y apartir de eso se crear el
  tenant que se usara o se asociara a ese rergiteos de negocio todo lo que ya tenemso meseros mesas y todo cambia es
  aparte del flujo quier qeu loc ambie y ya lo codes ahora la parte de registo de mesero solo que pida el nombre y
  genere un pin para ese mesero y el admin se lo proporcionara pero hay que ver como se puede hacer o asi para que la
  bd no cunfa por ejemplo si hay alguien llamado agustin quiuevedo en un locla y en toro igual y se registra con ese
  n0mbre que no lo bote porque este agaradno el pin de alguien mas"
- **L2** (2026-10-28, user answer): staff login = "Código + PIN (Recommended)" — generated unique code + 6-digit PIN,
  same as tables, for waiters and kitchen.
- **L3** (parent decision, from L1 "datos que no generen fricción"): sign-up is one atomic request (no account
  without a business, no token without tenant); the admin name defaults to "Admin". The code lives in the existing
  globally-unique `users.username` column (stored lowercase, shown uppercase), so login and tokens do not change.
- **L4** Next after this feature: Slice 8 remainder ("Pedir la cuenta" from the table).
- **L5** (2026-10-28, T2 frontend): /register two-step form (draft id keyed on email+password), login tabs Admin/Staff/Table, staff panel name+role only with code+PIN shown once and inline New PIN confirm; reset-password UI removed. Staff tab enforces no code/PIN length so S8 legacy usernames and passwords still sign in. typecheck, lint, 137 tests and build green.
- **L5** (2026-10-28, T1 evidence) Commits: `d545148` feat(staff) code + PIN create / `POST /staff/{id}/pin`
  (replaces `PUT /staff/{id}/password`); `25a9842` feat(auth) `POST /auth/register`; `adf863c` test(staff) code
  collision savepoint + concurrent replays. RED observed first for the unit tests of each rule (import errors, then
  assertions) and for the register API tests (20 failing before the route). Race tests fail when their lock is
  removed (email lock 3/3, staff-create lock 1/1). Results: `uv run pytest tests/unit -q` 278 passed;
  `uv run pytest tests/integration/modules/staff tests/integration/modules/auth tests/integration/shared -q` 132
  passed; full suite (with `test_unique_races.py` ignored, it fails at import) 549 passed, 2 failed. Pending, outside
  T1's edit surface: (1) `tests/integration/modules/tables/test_tables_api.py::test_a_table_token_gets_403_on_every_admin_endpoint`
  still calls the removed `PUT /staff/{id}/password` (now 404): use `tablet.post(f"{STAFF_URL}/{waiter}/pin")`;
  (2) `tests/integration/modules/test_create_replay_races.py::test_concurrent_staff_replays_all_get_the_same_member`
  uses the old `CreateStaffMember` signature and replay semantics: drop it (replaced by
  `tests/integration/modules/staff/test_seed_and_repositories.py::test_concurrent_staff_replays_create_one_member_and_say_so`)
  or port it; (3) `tests/integration/modules/test_unique_races.py` imports the removed `UsernameNotAvailable`: use
  `StaffCodeTaken` and a valid code (e.g. `"K7M2QX"`) instead of `"juan.taco"`. The other modules' tests keep using
  `create_member(admin, username, role)`, which now creates through the API and turns the member into a legacy
  account (S8 path) so their chosen username + `STAFF_PASSWORD` still sign in; migrating them to `add_member` +
  code/PIN is optional. `/auth/me` keeps `user.username` (the code in lowercase) unchanged.
- **L6** (2026-10-28, parent) Out-of-surface tests moved to the new contract (`5e519cf`); full suite 556 passed.
  Independent verifier: S1-S9 pass, baseline differential clean (admin/table login, refresh, logout unchanged). Blocker
  B1: a replay with the same id/email/password but another business name returned 201 and dropped the new name.
  Fix: S1 replay now also requires the same business name (409 "That id is already used by something else"
  otherwise; RED observed in `test_the_same_id_with_other_credentials_is_refused[fields2]`, then GREEN); the frontend
  draft key includes the business name, so a corrected name is a new sign-up. Advisories kept: every sign-up attempt
  counts toward the per-IP limit (5 per 15 min; Docker Desktop shares one IP in dev), 429 text says "login attempts",
  sign-up reveals whether an email is registered (by spec), StaffPanel replay 409 reloads the whole list.
- **L7** (2026-10-28, parent) Native review: Menu-Frontend `review-8fdf49dd9aab6e56` (base 56b61f0, risk + reliability)
  approved and acknowledged; Backend `review-c4bec167e5a1bee6` (base 6afcab2, risk + resilience + reliability) approved
  and acknowledged; advisories: sign-up retries consume the per-IP limit, register_business.py:90-96 warning. E2E over
  the dev proxy (:5173): sign-up 201 -> /auth/me admin of the new tenant; three "Agustin Quevedo" members got distinct
  codes and each signed in only with its own PIN; code A + PIN B 401; New PIN kept the code, ended the old session and
  the old PIN; waiter 403 on /staff; legacy `demo.mesero` still signs in. Headless Chrome rendered /register (step 1)
  and /login (Admin, Staff, Table tabs). CLAUDE.md and ROADMAP.md updated. Next: Slice 8 "Pedir la cuenta".
