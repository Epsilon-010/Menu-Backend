Slice 17 — Admin accounts: an admin creates and (de)activates other admins of their business; every admin can change their own password; a new admin must replace their temporary password first.
Branch `feat/slice-17-admin-accounts` in Backend (from `main`) and Menu-Frontend (from `feat/slice-16-stats`, whose PR is not merged yet). Delivery: one PR per repo, work-unit commits. Runners: `uv run pytest`, `npm test`.

## Specs
- S1 (roadmap): "El admin crea otros admins de su tenant; cambio de contraseña para todos los usuarios."
- S2 (create, from L2 "Temp password"): `POST /admins {id?, full_name, email}` (admin only) → 201
  `{id, email, full_name, is_active, must_change_password: true, temporary_password}`. The temporary password is
  generated (12 characters from the staff-code alphabet), shown only in that response and stored as a hash.
  - Invalid email → 422 "Invalid email"; name empty or over 120 → 422 "Full name must have 1 to 120 characters";
    email already used anywhere → 409 "Email already in use" (same wording as sign-up).
  - Idempotent: repeating the same `id` in the tenant → 409 "This admin was already created" (the password cannot be
    shown twice); an id used by something else → 409 "That id is already used by something else".
- S3 (list): `GET /admins` (admin only) → the tenant's admins ordered by name:
  `[{id, email, full_name, is_active, must_change_password}]`.
- S4 (manage, from L4 "Deactivate/reactivate"): `PATCH /admins/{id} {full_name?, is_active?}` (admin only) → 200 the
  admin. Deactivating ends every session of that admin right away (`session_version`, like staff).
  - Deactivating yourself → 409 "You cannot deactivate your own account", so the business always keeps an active admin.
  - Unknown id, another tenant's account, or a waiter/cook id → 404 "Admin not found".
  - Concurrent deactivations are serialized per tenant and the caller must still be an active admin, so two admins can
    never deactivate each other at the same time (the losing request → 403 "Not allowed").
- S5 (change password, from L3 "Admins only"): `POST /auth/password {current_password, new_password}`; only admins
  (waiter/kitchen/table/guest → 403; they keep the admin-managed PIN).
  - Wrong current password → 400 "The current password is incorrect"; failures count in the login limiter under
    `password:<user id>` → 429 like login when exceeded.
  - New password outside 8–128 → 422 "Password must have 8 to 128 characters"; equal to the current one → 422
    "The new password must be different from the current one".
  - Success → 200 `SessionResponse`: hash replaced, `must_change_password` false, every session of the admin ends
    (other devices signed out) and the caller gets fresh session cookies.
- S6 (forced change, from L2): login, refresh and register responses and `GET /auth/me` (`user`) include
  `must_change_password`. While it is true the access token carries it and every role-checked route answers 403
  "Change your temporary password first"; `/auth/password`, `/auth/me`, `/auth/refresh`, `/auth/logout` keep working.
  The frontend sends that admin to the change-password screen and nowhere else.
- S7 (frontend): `/admin/admins` "Admins" page linked in the admin navigation: list (with "You" on your own row and a
  "Temporary password" tag), create form (name + email, keeps its id until success), the temporary password shown once
  like the staff PIN, Deactivate/Reactivate (not on your own row). `/admin/account` "Change password" form (current,
  new, repeat; mismatch blocked in the browser). Forced screen for `must_change_password`.
- S8 (isolation): one tenant never sees or changes another tenant's admins; waiter/kitchen/table get 403 on `/admins`.

## Tasks
- [ ] T1 (S1-S6, S8) Backend: `must_change_password` column + migration, admin use cases and `/admins` router, change
  password, token claim and 403 gate, tests. Route: inline (no writer reason: one unit, sequential).
- [ ] T2 (S6-S7) Frontend: api, Admins page, account page, forced redirect, tests. Route: inline.
- [ ] T3 Verify: independent verifier (Risk item 2: auth) + native review per repo.

## Log
- L1 (2026-10-31, user): "haz la sigueitne slcie"
- L2 (2026-10-31, user, new admin credentials): "Temp password (Recommended)" — system generates a temporary password
  shown once; the new admin must change it on first login.
- L3 (2026-10-31, user, who changes passwords): "Admins only (Recommended)" — every admin changes their own password
  (asks for the current one); waiters/cooks keep the admin-managed PIN.
- L4 (2026-10-31, user, managing other admins): "Deactivate/reactivate (Recommended)" — list, deactivate or reactivate
  (sessions revoked at once); nobody can deactivate themselves.
- L6 T1 evidence: RED 24 failed (`test_admins_api.py`, no `/admins` nor `/auth/password`); GREEN 25 integration +
  18 unit (`test_admin_use_cases.py`). Migration `548bab5f5d29` (adds `users.must_change_password`, constant default:
  no table rewrite; downgrade drops it). The session body gained `must_change_password` (9 exact asserts updated in
  auth/register/QR/tables tests); `FakeAccessTokens` and the user/credential fakes learned the new members.
- L7 T2 evidence: `npm test` 364 passed (new: admins api, account api, password rules, forced-screen render),
  typecheck, lint and build clean. The forced screen lives in `RequireRole`, so every role-guarded page shows it.
- L5 Assumptions: `PATCH` also renames; a new password must differ from the current one; the self-registered owner and
  existing admins start with `must_change_password = false`. Frontend branch starts from `feat/slice-16-stats`.
