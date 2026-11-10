# Staff flows: kitchen, waiter and menu screens

Objective: fix what the user found testing the kitchen, waiter and table screens, and check the whole order flow.
Branches: `feat/staff-flows` in Backend (from `feat/menu-sections`) and Menu-Frontend (from `feat/menu-sections`).
Delivery: one PR per repo, backend first. Runners: `uv run pytest` (backend), `npm test` from PowerShell (frontend).

## Specs

- S1. "en la parte de cocina que se vean las ordenes ya termiandas en otra seccion o asi abajo"
  - `GET /api/v1/kitchen/orders/finished` (admin, kitchen): orders of open bills with no dish queued or preparing,
    the one finished last first, at most 30, never with prices. They leave when the bill is paid.
  - The kitchen screen lists them under the queue as "Terminadas".
- S2. "los botones de listo y todo eso en las rodenes de cocina se ven todos superpuestos mejora el disñeo en esa pantalla"
  - Each dish still to cook carries its own buttons (start, ready, reject); nothing is selected first. Buttons wrap,
    never overlap, at 390, 820 and 1280 px.
- S3. "en el menu lo de la sesion de salir y asi se ve superpuestos con el menus que se enseña"
  - The top bar is in the page flow (sticky or not, per the theme), never floating over the content.
- S4. "con lo de mesero si una orden aparece en preparacion o asi se le cobra todo"; then (L6) "si dejal con aviso
  pero puede que se cobre solo lo que ya cobro tipo asi de que solo lo que ya esta marcado como entregado o asi se
  cobra"; then (L7) "siemrpe que las personas teremine de comer se pagara al final elije tu la merjor opcion y haz el
  flujo de cobro".
  - The bill is paid once, at the end. `POST /bills/{id}/payment` accepts `only_delivered` (boolean, default false):
    true cancels every dish not delivered (queued, preparing or ready) with reason "Not delivered when the bill was
    paid" and the cashier's role, in the same transaction, then charges the rest and closes the bill. A refused
    payment (stale total, nothing to charge) cancels nothing. Without it the payment charges every dish, as before.
  - The payment dialog lists each dish, marks the ones not delivered, lets the waiter choose "Solo lo entregado"
    (default when something was delivered and something was not) or "Toda la cuenta", shows the total, the method
    and, for cash, the change.
- S5. "cuando le doy canecelar desde mesero aparece un enesajeque lo canbcelo cocina"
  - `order_items.cancelled_by` stores the role that cancelled (kitchen, waiter, admin); every order response
    carries `cancelled_by`. Only kitchen cancellations read "Rechazado por la cocina" and raise the waiter alert;
    the rest read "Cancelado".
- S6. "mejora el disñeo de todo se ve muy IA y muy feo" / "los flujos checalos bien ... desde cobrar ordenar marcar lsito y entrwagado"
  - Waiter screen in two views (deliveries, tables), free tables as compact tiles, neutral delivered notes.
  - The order, cook, cancel, deliver and pay flow is exercised end to end.

## Tasks

- [x] T1 (S1, S5) backend, inline. RED observed (finished list test failed on the old code), then 139 focused and
  1330 full-suite tests passed. Migration `a41c7e9d2b60` (nullable column; downgrade drops it).
- [x] T2 (S1-S6) frontend, inline. 499 Vitest tests, typecheck, lint and build pass.
- [x] T3 (S6) end to end on a separate database (`menu_staffflows`) with the new API on port 8021 and Vite on 5174:
  20 of 20 checks pass; Chrome headless captures at 390, 820 and 1280 px report no horizontal scroll, no clipped
  and no overlapping buttons on kitchen, waiter and menu.
- [x] T4 (S4) payment flow: backend `only_delivered` and the frontend payment dialog, inline.

## Log

- L1 (2026-11-10, user): "en la parte de cocina que se vean las ordenes ya termiandas en otra seccion o asi abajo,
  igual los botones de listo y todo eso en las rodenes de cocina se ven todos superpuestos mejora el disñeo en esa
  pantalla iguan el el menu lo de la sesion de salir y asi se ve superpuestos con el menus que se enseña que no se vea
  asi mejorarlo o acomada las cosas de una mejro manera iguan con lo de mesero si una orden aparece en preparacion o
  asi se le cobra todo, y cuando le doy canecelar desde mesero aparece un enesajeque lo canbcelo cocina igual mejora
  el disñeo de todo se ve muy IA y muy feo, igual los flujos checalos bien y todo porfavbor desde cobrar ordenar
  marcar lsito y entrwagado y demas"
- L2: the dev database is at `de3bacf10d81` and the compose backend runs the main checkout, so nothing of this
  branch was applied to the dev database; the end to end run used its own database.
- L3: Vitest fails on every file when started from Git Bash (drive letter case); it runs from PowerShell.
- L4: dishes cancelled before the migration have `cancelled_by` null and read "Cancelado".
- L5: commits Backend `3e7698b`, Menu-Frontend `37a4366`. Native review of the backend commit approved and
  acknowledged (`review-5211d89c8b1b99c1`, lenses risk and reliability); its one advisory: no test proves the cap of
  30 finished orders. Frontend assessed `under_budget`, not reviewed. No independent verifier was run.
- L6 (2026-11-10, user): "si dejal con aviso pero puede que se cobre solo lo que ya cobro tipo asi de que solo lo que ya
  esta marcado como entregado o asi se cobra op se amrca como cobrado con su metodo?"
- L7 (2026-11-10, user): "supongamos que al siempre al gffinal se pide la cuenta lo manejaremos asi siemrpe que las
  personas teremine de comer se pagara al final elije tu la merjor opcion y haz el flujo de cobro". Decision: no
  partial payments and the table never stays open after paying; one payment that may leave out what never arrived.
- L8: T4 evidence. RED: 3 of the new payment tests failed on the old code. GREEN: 175 focused tests. End to end on a
  separate database: a table with one delivered dish and three pending paid $70.00 with `only_delivered`; the three
  were cancelled by the waiter, the kitchen and delivery queues emptied, the table was free and `/stats` reported
  the $70.00 as collected. A delivered-only payment sent with the whole total was refused and cancelled nothing.
- L9: commits Backend `15e7939` (payment, plus a unit test for the cap of 30 finished orders, the advisory of L5)
  and Menu-Frontend `0655767`. Full backend suite: 1335 passed. Native review of the whole backend branch against
  `main` (33 files, 1690 lines) approved with no findings and acknowledged (`review-8daaf40f3de9d386`). An earlier
  attempt on the previous candidate (`review-8e8fc99b2a62fbe6`) stopped at `review status` with `operation_timeout`
  twice; it did not happen again. Frontend commits assessed `under_budget`, not reviewed.
