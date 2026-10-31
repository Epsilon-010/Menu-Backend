Slice 16 — Statistics: admin-only sales, products, tables, payment methods and kitchen/delivery times for a date range, with days cut in the business's own time zone.
Branch `feat/slice-16-stats` in Backend and Menu-Frontend. Delivery: one PR per repo (as in previous slices), work-unit commits. Runners: `uv run pytest`, `npm test`.

## Specs
- S1 (time zone, from L2 "Zona por tenant + rangos"): every tenant has an IANA time zone, `tenants.timezone`.
  - Migration adds the column; existing tenants get `America/Mexico_City` (assumption, L6).
  - `POST /auth/register` accepts an optional `timezone`; the register page sends the browser's
    (`Intl.DateTimeFormat().resolvedOptions().timeZone`); missing → `America/Mexico_City`.
  - `GET /tenant/settings` (admin) → `{timezone}`; `PATCH /tenant/settings {timezone}` (admin) → 200 `{timezone}`.
  - An unknown zone (register or PATCH) → 422 "Unknown time zone". Other roles → 403.
- S2 (range, from L2): `GET /stats?from=YYYY-MM-DD&to=YYYY-MM-DD` (admin only, other roles 403). Both days inclusive,
  as calendar days in the tenant's time zone. `to` before `from` → 422 "The end date must be on or after the start
  date"; more than 366 days → 422 "The range can be at most 366 days". The admin page offers "Today", "7 days"
  (today and the 6 days before), "30 days" and a custom from–to.
- S3 (sales, from L3 "Ambos, separados"): two figures, never mixed.
  - **Collected**: bills paid (with a payment method) whose payment time falls in the range; amount = what was
    charged (`paid_cents`), dated by the payment time. Average ticket = collected / paid bills (0 when none).
  - **Ordered, not collected yet**: dishes not cancelled, in orders sent in the range whose bill is still open,
    dated by when the order was sent.
  - Output: totals `{collected_cents, paid_bills, average_ticket_cents, pending_cents, pending_orders}` and
    `days: [{date, collected_cents, pending_cents}]` with one entry for every day of the range (zeros included).
  - By payment method: `[{method, bills, amount_cents}]` for cash, card and other (zeros included), from collected bills.
- S4 (products): dishes not cancelled in orders sent in the range, grouped by catalog item:
  `[{item_id, name, quantity, collected_cents, pending_cents}]`, collected = its bill is paid, pending = its bill is
  open; sorted by quantity, then amount; name = the most recent name ordered. (Assumption, L6: quantity and amount,
  ordered by quantity.)
- S5 (tables): orders sent in the range that are not fully cancelled, by table:
  `[{table_id, name, orders, collected_cents, pending_cents}]`, sorted by orders; deactivated tables included.
- S6 (times, from L4 "Promedio y mediana, por producto"): for dishes in orders sent in the range, never cancelled:
  - queue = from the dish entering the queue (`order_items.queued_at`: the order's send time, or when staff added it)
    until it went to preparing, or until it was ready when it skipped preparation (a drink: queued → ready is allowed);
    preparation = preparing → ready; delivery = ready → delivered. Each status is reached at most once (L8).
  - A dish counts in a stage only if it finished that stage. Order total = order sent → its last live dish delivered,
    only for completed orders.
  - Output: overall `{queue, preparation, delivery, order}` each `{average_seconds, median_seconds, count}` (null
    average/median when count is 0), plus per product `[{item_id, name, queue, preparation, delivery}]`.
  - The page shows durations as "12 min 30 s" (under a minute "45 s"; an hour or more "1 h 05 min").
  - New column `order_items.queued_at` (migration; existing rows backfilled with their order's `created_at`).
- S7 (page, from L5 "Gráficas propias en SVG + tablas"): `/admin/stats`, a link in the admin navigation. Total cards,
  a bar chart of sales per day drawn with SVG (collected and pending as two series, no new library), tables for
  products, tables, payment methods and times. Time zone setting reachable from the page.
- S8 (isolation): a tenant never sees another tenant's figures; table, guest, waiter and kitchen get 403 on `/stats`
  and `/tenant/settings`.
- S9 (from L10): "quita eso de la cuenta 0". A bill with nothing to charge (no orders, or every dish cancelled) is
  never paid: `POST /bills/{id}/payment` → 409 "This bill has nothing to charge; close the table instead" (bill stays
  open); `POST /bills/{id}/close` closes it without payment; the table cannot ask for it (409 "There is nothing to pay
  yet"). The stats ignore $0 bills paid before this rule. Waiter card shows "Close table" for $0; the menu hides "Ask
  for the bill" unless something is left to pay (or a request is open, to cancel it). "igual chequea que no se pueda
  mandar órdenes sin productos": already true — empty cart → 409 "The order is empty" (`test_ordering_api.py:201`).

## Tasks
- [x] T1 S1, S8 — Backend tenant time zone: column + migration `d81f0160ea55`, register, `/tenant/settings`. Route: inline. Commit `aa5eaa4`.
- [x] T2 S2-S6, S8 — Backend stats module + `order_items.queued_at` (migration `f7f7d880b795`). Route: inline. Commit `c768227`.
- [x] T3 S1, S7 — Frontend: register sends the zone, `/admin/stats` page with SVG chart, tables, zone setting. Route: inline. Frontend commit `dbc4358`.
- [x] T5 S9 — $0 bills closed, not paid (backend + waiter card + menu). Route: inline.
- [ ] T4 — Verify (independent verifier: T1/T2 touch migrations, item 1), docs, ROADMAP, CLAUDE.md. Route: delegated verifier.

## Log
- L1 (2026-10-30, user): "Arranca el Slice 16 — Estadísticas: rama feat/slice-16-stats desde main actualizado, en Backend
  y en Menu-Frontend. Antes de codificar, pregúntame de a una lo que el ROADMAP no define (por ejemplo: rangos de
  fechas y zona horaria, qué cuenta como venta, cómo mostrar los tiempos, gráficas o tablas)." ROADMAP: "Ventas por
  día, productos más vendidos, pedidos por mesa, ticket promedio, ventas por método de pago, tiempos promedio por
  platillo (en cola, preparación y entrega) y tiempo total por pedido."
- L2 (user): time zone and range → "Zona por tenant + rangos (Recommended)".
- L3 (user): what counts as a sale → "Ambos, separados".
- L4 (user): times → "Promedio y mediana, por producto (Recommended)".
- L5 (user): view → "Gráficas propias en SVG + tablas (Recommended)".
- L6 Assumptions announced to the user (correct if wrong): products by quantity and amount; tables include
  deactivated ones; existing tenants start at `America/Mexico_City`. Dishes added later by staff have no queue start
  today, hence `order_items.queued_at`. `tzdata` is already a transitive dependency (no new library).
- L7 (2026-10-30, user): "si hazlo" — the four assumptions of L6 accepted.
- L8 Evidence T1/T2: RED observed first for tenants (missing module) and stats domain (missing module); 23 stats unit
  tests, 12 stats API tests, 13 tenant settings API tests. Mutation checks: widening the query window survived until a
  "day before" case was added (now killed); `min`/`max` of ready was indistinguishable because a dish reaches each
  status once (`_TRANSITIONS`), so "last ready" was dropped and S6 rewritten. Found while doing it: a drink can go
  queued → ready, so its queue time ends at ready (unit test added). Days use UTC bounds (`day_bounds`), so a 25-hour
  clock-change day stays one local day. Full backend suite: 972 passed. Dev DB migrated to `f7f7d880b795`
  (54 dishes backfilled, 0 null). Probe on dev data via the proxy: totals, methods, products and the 422 message ok;
  one paid bill of $0 ("other") counts in the average ticket, as S3 says.
- L9 Evidence T3: 35 stats tests (logic, API, render); full frontend 345 passed, typecheck, lint, build ok. Palette
  slots 1/2 (#2a78d6, #eb6834) validated on white (CVD ΔE 24.7). Chrome headless at 1280 and 390 px: on the phone the
  scaled SVG shrank the labels and duration cells wrapped — fixed by drawing the chart at the measured container width
  (labels thinned to fit) and `whitespace-nowrap`; the tooltip covered the hovered bar — moved beside it.
- L10 (2026-10-31, user): "quita eos de la cuentna 0 igual chec que no se pued amandar ordenes sin prodcutos o asi
  actualzia el claude md y el roadmap ya hciue meger". Note: the Slice 16 branches had not been pushed yet; origin/main
  is still at the Slice 15 merge in both repos (told the user).
- L11 Evidence T5: RED 3 failing (pay $0, ask for $0 bill, old $0 bill in stats), GREEN after the change; a bill with
  something left still refuses close and is paid. Frontend helpers `hasSomethingToCharge`, `hasSomethingToPay` tested;
  347 frontend tests, typecheck, lint, build ok. The first verifier run was cut by the session end (no report).
