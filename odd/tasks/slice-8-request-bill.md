# Slice 8 (rest) — Request the bill from the table
Objective: a table (tablet or QR guest) asks for the bill once per visit and can cancel it; waiters see it on the table card and in a banner. Branch `feat/slice-8-request-bill` in Backend and Menu-Frontend.
Delivery strategy: `single-pr` per repo. Test runners: `uv run pytest` (Backend), `npm test` + `npm run typecheck` + `npm run lint` + `npm run build` (Menu-Frontend).

## Specs

S1 — ROADMAP (verbatim): "La tablet puede mostrar "Pedir la cuenta" para avisar al mesero (evento en tiempo real)." Applies to the tablet and to QR guests (same permissions as `table`).

S2 — Once, cancellable (user decision, L2): "Pedirla una sola vez: el aviso queda hasta que el mesero cobra o lo atiende" + "con cancelación". Asking again while requested returns the same request (no second alert); the diner can cancel it; the waiter/admin can dismiss it ("lo atiende"); paying or closing the bill ends it.
- Assumption: asking needs an open bill with at least one order; otherwise 409 "There is nothing to pay yet".

S3 — Waiter view (user decision, L3): "Las dos": badge "Bill requested" on the table card AND a banner visible from the waiter screen; the existing waiter sound plays; tapping the banner goes to the table.

S4 — API contract:
- `GET /table/bill-request` → `{requested_at: datetime | null}` (diner).
- `POST /table/bill-request` → 200 `{requested_at}`; idempotent while requested.
- `DELETE /table/bill-request` → 204; idempotent (nothing requested is fine).
- `DELETE /bills/{bill_id}/request` → 204 (admin, waiter); idempotent; 404 for unknown or closed bills.
- `BillOut` gains `bill_requested_at: datetime | null` (staff `/bills/tables` and `/bills/{id}`).
- Events `bill.requested` and `bill.request_cleared` on the table channel (data `{}`, like every table event) and to staff (`STAFF_KINDS`, data `{table_id}`).

S5 — Isolation: another tenant's bill is 404 for dismissal; kitchen cannot dismiss (403); a guest of a past visit gets 401; the table only hears its own table.

## Tasks
- T1 (S1, S2, S4, S5) backend: column + migration, use cases, routes, events, tests — inline — done `96cb2e5` (RED 10 failed → GREEN 10 passed; full suite 567 passed)
- T2 (S3, S4) frontend: table button, waiter badge + banner + sound — inline — done Menu-Frontend `7959160` (RED 6 failed → GREEN; typecheck, lint, 143 tests, build ok)
- T3 docs: ROADMAP slice 8 done, CLAUDE.md "Estado actual" — inline — done

## Log
L1 (2026-10-28, user, verbatim pasted handoff): "Lo siguiente: terminar el Slice 8 con "Pedir la cuenta" desde la mesa, en una rama feat/slice-8-request-bill creada desde main en los dos repos." "Qué preguntarte antes de codificar: si el aviso se puede repetir o cancelar, y si al mesero le aparece en la tarjeta de la mesa o como notificación aparte."
L2 (2026-10-28, user): "si hazlo asi" — to the recommendation "la 1 con cancelación" (ask once; cancellable).
L3 (2026-10-28, user): "si las 3" — badge on the card and banner, banner light and linking to the table.
L4: branches created from `main` (Backend 74c9c0d, Menu-Frontend 221ff4b). CI of main not checked (`gh` has no session).
L5: T1 and T2 inline (no writer trigger: the frontend depends on the backend contract). Tables that asked for the bill move to the top of the waiter's list; the banner is sticky on the waiter screen (deliveries + tables are one screen, `ServiceBoard`).
L6: e2e HTTP against the Docker stack (Mesa 5, demo.mesero): ask without orders 409 "There is nothing to pay yet"; after one order ask 200; waiter sees `bill_requested_at`; dismiss 204; ask again and cancel 204. Dev data: Mesa 5 now has an open bill with one order.
L7: Gentle AI assess per commit: Backend medium/under_budget, Menu-Frontend medium/under_budget (no review due). Risk: item 1 (migration adding `bills.bill_requested_at`) → independent verifier launched.
L8: independent verifier PASS S1-S5, no blockers (orders suite 100 passed; migration down/up on `menu_test`; race probes: concurrent asks give one event, a dismiss waiting on a payment gets 404 and the bill stays paid). Advisory 1 fixed: paying or closing clears `bill_requested_at` (RED → GREEN in `test_paying_ends_the_request...`). Advisory 2: spec wording corrected (table events carry `{}`). Advisory 3 accepted: the kitchen hears the two events without prices and ignores them.
