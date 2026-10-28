# Slice 7 — Kitchen and partial deliveries in real time
Objective: orders go from the table straight to the kitchen; the kitchen releases dishes partially and waiters deliver what is ready, everything grouped by order. Branch `feat/slice-7-kitchen` in Backend and Menu-Frontend.
Delivery strategy: `single-pr` per repo (project convention: one PR per slice), native review per commit range. Test runners: `uv run pytest` (Backend), `npm test` + `npm run typecheck` + `npm run lint` + `npm run build` (Menu-Frontend).

## Specs

S1 — Kitchen screen (ROADMAP, verbatim): "**Pantalla de cocina** (`/kitchen`): tarjetas de orden (comandas) en orden de llegada (FIFO como sugerencia, sin obligarlo) con número de orden, mesa, tiempo de espera y sus platillos (cantidad, modificadores, notas, estado), sin precios." "Dentro de cada tarjeta: marcar uno o varios platillos de esa orden como **En preparación** o **Listo**; **Rechazar** (con motivo) un platillo aún no empezado." "Cocina puede trabajar varias órdenes a la vez y adelantar cualquiera." "La tarjeta sale de la pantalla de cocina cuando ya no le quedan platillos pendientes."

S2 — Waiter delivery queue (verbatim): "**Vista de meseros** (`/waiter`): cola de entrega con **tarjetas de orden** que tienen al menos un platillo listo, ordenadas FIFO por el platillo listo más antiguo. Cada tarjeta separa visualmente **Listos para llevar**, **Entregados** y **Pendientes en cocina**, con contador (p. ej. "Mesa 1 · Orden #12 · 2 de 5 entregados"). Botón **Entregar** por platillo y **Entregar todos los listos** de la orden. Filtros por estado y mesa. El mesero no confirma nada."

S3 — State machine (verbatim): "Máquina de estados de `OrderItem` en el dominio y estado de `Order` derivado (`queued` → `in_progress` → `partially_delivered` → `completed`), solo con el rol permitido; historial de quién y cuándo por platillo."
- Allowed transitions (from CLAUDE.md permission matrix): `queued → preparing` (admin, kitchen); `queued|preparing → ready` (admin, kitchen); `ready → delivered` (admin, waiter); `queued → cancelled` with a reason (admin, waiter, kitchen). Anything else is invalid (e.g. `queued → delivered`).
- Assumption: `queued → ready` directly is allowed (drinks need no preparation); ROADMAP lists both buttons without ordering them.

S4 — Atomicity (verbatim): "Transiciones atómicas condicionadas al estado esperado; marcar varios platillos de una orden es todo-o-nada."

S5 — Events (verbatim): "Eventos por Redis Streams (`orders:{tenant_id}`) entregados por SSE filtrados por tenant y rol; al reconectar se recupera el estado desde la API; polling de respaldo."

S6 — Alerts (verbatim): "Aviso sonoro opcional (cocina: pedido nuevo; meseros: platillo listo); resaltar pedidos con espera mayor al umbral configurable."

S7 — Rejections (verbatim): "Si cocina rechaza un platillo, se avisa a los meseros y a la mesa con el motivo."

S8 — Table (verbatim): "La tablet de la mesa ve el estado de cada platillo de sus pedidos."

S9 — Done when (verbatim): "Llegan las órdenes 1, 2 y 3; cocina adelanta la 2 y marca listos 2 de sus 4 platillos; al mesero le aparece la tarjeta de la orden 2 con 2 listos y 2 pendientes; los entrega y la orden queda en `partially_delivered`; cuando cocina libera y el mesero entrega el resto, la orden pasa sola a `completed` y desaparece de ambas vistas." "La mesa ve cada platillo cambiar de estado sin recargar."

S10 — Required tests (verbatim): "transición inválida rechazada (p. ej. `queued` → `delivered`); el estado del pedido se deriva correctamente en todos los casos (incluye cancelados); dos cocineros marcando el mismo platillo a la vez no generan doble transición; marcar varios platillos donde uno está en estado inválido no cambia ninguno; no se pueden marcar en una misma acción platillos de órdenes distintas; la cocina no ve precios; un mesero no ve pedidos de otro tenant; una mesa no recibe eventos de otra mesa."

S11 — API contract (design decision for this slice; both repos build against it):
- `StaffOrderOut` (no prices, for every staff queue): `{id, number, table_id, table_name, sent_by, created_at, status, items: [{id, name, quantity, note, added_by, status, cancel_reason, ready_at, updated_at}]}`.
- `GET /api/v1/kitchen/orders` — roles admin, kitchen. Orders with at least one item `queued` or `preparing`, sorted by `number` ascending; all their items included.
- `GET /api/v1/deliveries` — roles admin, waiter. Orders with at least one item `ready`, sorted by their oldest item `ready_at`.
- `POST /api/v1/orders/{order_id}/items/status` — roles admin, waiter, kitchen. Body `{item_ids: [uuid] (1..50, unique), status: "preparing"|"ready"|"delivered"|"cancelled", reason?: string 1..200}` (`extra="forbid"`; `reason` required for `cancelled` and rejected otherwise → 422). Response 200 `StaffOrderOut`. Errors (RFC 9457): order not in tenant → 404 "Order not found"; an item id not in this order → 422 "All dishes must belong to this order"; role not allowed for the target → 403 "Your role cannot mark dishes as <status>"; any item not in an allowed source state → 409 "Some dishes already changed; reload the order" and nothing changes.
- `GET /api/v1/orders/settings` (admin, waiter, kitchen) → `{late_order_minutes}`; `PATCH /api/v1/orders/settings` (admin) body `{late_order_minutes: 1..240}`; default 15.
- Existing `OrderItemOut` (table and bills responses) gains `cancel_reason: string | null`.
- Events on `orders:{tenant_id}`: existing `order.created` plus new `order.updated` (fields `kind`, `table_id`, `order_id`) after each committed status change. `GET /api/v1/staff/events` (admin, waiter, kitchen) is SSE with event names `order.created`, `order.updated`, `bill.opened`, `bill.closed` and data `{order_id?, table_id}`; never cart events, never prices. `GET /api/v1/table/events` also forwards `order.updated` for its own table only.

## Tasks
| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 | S3, S4, S5, S6 (setting), S7, S10, S11 | delegated (backend writer; parallel with T2, Writer trigger a) | pending | |
| T2 | S1, S2, S6, S7, S8, S9, S11 | delegated (frontend writer; parallel with T1) | pending | |
| T3 | S9 | inline: browser e2e of the "Done when" scenario, docs (ROADMAP, CLAUDE.md) | pending | |
| T4 | all | independent verifier (Risk items 1 migration, 4 concurrency) + native review | pending | |

Risk: item 1 (new migration: columns, history table, check constraint) and item 4 (concurrent conditional updates).

## Log
- L1 (2026-10-28, user, verbatim): "Después sigue con el Slice 7 (pantalla de cocina en tiempo real) cuando te lo pida." — then: "si arraca con esa slide y borra el de ana el perfil y pon el admin y pass admin123 ya no menciones o pongas algo de ana no pongas nobre de muejres guardalo en tu memoria para todas las seciones o incluso para el web ya no lo hagas ya cuantas veces te dije"
- L2: Prep done: neutral sample names (Backend 3d55415, Menu-Frontend b48dd54); dev admin login `admin` / `admin123`. Explorer map: no item transitions, history, kitchen/delivery listings, staff SSE or price-free schema exist; `OrderStatus` is derived by `derive_order_status`; table names come through the `Tables` port.
