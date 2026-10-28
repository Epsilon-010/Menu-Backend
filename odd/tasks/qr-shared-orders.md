# QR shared orders (Slices 5, 6, 8 and 9)
Objective: table menu, a backend shared cart sent as one order per round, open/pay tables, and QR access for many phones.
Branch: `feat/qr-shared-orders` (Backend and Menu-Frontend). Delivery: single PR per repo. Runner: `uv run pytest`, `npm test`.

## Specs
- S1 (Slice 5). `/menu` shows the tenant's visible categories and available items with optimized images; cached in
  Redis per tenant and invalidated on every catalog change.
- S2 (Slice 6). "que puedan entrar x usuarios como ella puedan selccionar prodcutos y demas y que solo se generde una
  orden por mesa pero que muchas personas que entraron como mesa 5 puedan hacer la orden": one backend cart per table
  (tablet and phones share it); each line records who added it; anyone at the table can add, change or remove lines.
- S3. "que alguno de ellos la pueda mandar pidinedo una confirmacion al momento de mandarla o antes de manadarla" —
  decided "Confirma quien la manda": the sender sees the full summary and confirms with the cart `version`; a stale
  version gives 409 "The order changed, review it"; two simultaneous sends create one order; backend prices only.
- S4. "que se vea la orden generada oq ue se va genernado mientras los demas van añadiendo prodcutos y se les vaya
  mostrnado las ordenes generadas": everyone at the table sees the cart change live (SSE `cart.updated`, polling
  fallback) and the orders already sent with their status.
- S5. Decided "Nueva ronda": after sending, the cart is empty and the table can send another order on the same bill.
- S6 (Slice 8). Decided "Mesa abierta por mesero": waiter/admin opens a table (one open bill per table; the tablet's
  first order opens one too); paying (cash, card, other) closes it with the backend total; closing without payment only
  without orders. Closing discards the unsent cart.
- S7 (Slice 9). QR per table (`/q/<token>`, admin can show and regenerate it). `POST /auth/qr` gives a `guest` session
  only while the table has an open bill, else 409 "This table is not open yet; ask your waiter". "nadie pueda cceder
  depues de ir aunque haya abiero la app o la abra desde su casa y siga haciendo pedidos a nomreb de esa mesa depues de
  dias": closing the bill or regenerating the QR ends every guest session (refresh rejected, access floor, and every
  cart/order write re-checks the guest in the same transaction); guest sessions last at most 12 h.

## Tasks
- [ ] T1 (S1) inline — menu read endpoint, Redis cache + invalidation; frontend menu page.
- [ ] T2 (S2-S6) inline — `orders` module: bills, guests, carts, orders; use cases, routers, migration.
- [ ] T3 (S7) inline — QR token on tables, guest auth (login, refresh, /me, revocation).
- [ ] T4 (S4) inline — SSE table events.
- [ ] T5 (S2-S7) inline — frontend: shared cart, send confirmation, orders, `/q/:token`, waiter tables, admin QR.
- [ ] T6 — e2e probes on the dev stack; independent verifier (risk items 1, 2, 4).

## Log
- L1 (2026-10-27): "se me courre cambiar o agregar otra cosa a la logica de negocio, quiero que cambie un poco o se añada
  una forma mas de añadir pedidos me imagino ahora que si la empresa no quiere comprar un dispotivo para que ahi se tome
  le peidod pongan codgios qrs para que la gente entre como esa mesa pero no puedo controlar cuantos entran [...] y se
  mande una sola orende por mesa añade eso y haz los cambios correpondientes"
- L2 (2026-10-27): "implemantes ya lo que dije de las meses y el qr y lo proibaste apra que sirva y nadie pueda cceder
  depues de ir aunque haya abiero la app o la abra desde su casa y siga haciendo pedidos a nomreb de esa mesa depues de
  dias de haber uido o asi?" → "si ya has lo que te peid hazlo".
- L3: Bills, guests, carts and orders live in one `orders` module: paying a bill ends guests and discards the cart in
  the same transaction, and orders need the open bill; two modules would call each other. Slice 7 (kitchen screen) is
  not part of this feature: orders are stored `queued`.
- L4: The QR token is stored in plain text (unique), unlike the PIN: it is printed and stuck on the table anyway, the
  admin must be able to reprint it, and access is gated by the open bill, not by the token's secrecy.
