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
- S4. "con lo de mesero si una orden aparece en preparacion o asi se le cobra todo"
  - Assumption (not confirmed by the user): the payment is still allowed, but the waiter sees how many dishes are
    not delivered on the table card and a warning in the payment dialog. Blocking the payment in the API would
    reverse the Slice 7 decision "cuenta cobrada = nada cambia" and is left as a question for the user.
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
- Open question for the user (S4): block the payment while dishes are not delivered, or keep the warning.
