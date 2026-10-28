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
- [x] T1 (S1) inline — menu endpoint + generation-keyed Redis cache invalidated after every catalog write. RED: 404;
  GREEN `1c50fef` (5 tests incl. the stale-write race).
- [x] T2 (S2-S6) inline — `orders` module (bills, guests, carts, orders), table lock per visit, migration
  `32b04396f6b8`. GREEN `441ff45` (13 API tests: shared cart, stale version 409, 4 concurrent sends → 1 order,
  idempotent add/send, backend prices, unavailable items, isolation, roles, open/pay/close).
- [x] T3 (S7) inline — QR token on tables, `guest` role, `POST /auth/qr`, refresh and /me for guests, 12 h cap, new
  QR / deactivation / payment end guests; migration `709cd38442c8` (down/up OK). GREEN `5984ae8` (13 API + 4 unit
  tests). Mutation check: removing the in-transaction guest check fails 5 tests (Redis-less, reopened table, 12 h,
  forged claims).
- [x] T4 (S4) inline — SSE `GET /table/events` from the tenant stream, filtered by table; guest stream ends on
  `bill.closed`; 5-minute streams. GREEN `98d1219` (4 tests). Full suite 352 passed.
- [x] T5 (S1-S7) delegated (context backstop) — frontend: menu, shared cart (SSE + 5 s polling fallback), send
  confirmation with 409 review, orders, `/q/:token`, visit-ended screen, waiter tables board, admin QR link.
  Menu-Frontend `b9ecc8d`: typecheck, lint, 84 tests, build OK; SSE checked unbuffered through the Vite proxy.
- [x] T6 — independent verifier: S1-S6 PASS, S7 FAIL with B1 (old-QR scan racing a new QR) and B2 (deadlock: tables
  row locked before the visit lock). One correction `4d9ef74` (visit lock first, QR re-checked under it, plus advisories
  A1/A2), recheck: both FIXED. E2E on the dev stack through Vite: 20/20 (scratch script, not committed).
- [x] T7 — native review per slice (the whole branch exceeded the lens budget): `86b3aa7..441ff45` approved
  (review-687761e0b8bc78fb), `441ff45..5984ae8` approved (review-37509f8fbe983483), `5984ae8..c8df73c` approved
  (review-5467c7dc109ded61); its findings fixed in `803685d` (events read after a concrete stream id, one warning per
  Redis outage, line replays scoped to the visit). `c8df73c..803685d` assessed medium / under budget.

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
- L5: Unit tests cover tables' new QR use cases; the ordering use cases are covered by API tests against Postgres
  (their guarantees are locks, unique indexes and transactions, which in-memory fakes would not prove).
- L6: QR images need a library (not added without the user's approval): the admin copies the link for now.
- L7: Verifier advisories kept open: A3 an open SSE stream of a guest ended by a new QR or deactivation lasts up to
  5 min (event kinds and cart versions only); A4 an ended guest reads the menu until its access token expires (15 min);
  A5 QR rate limit is per token, and no cap on guests per bill (L1: the user cannot control how many enter).
  Review advisories kept open: every cart read loads the tenant's catalog from Postgres (not measured); race tests
  order threads with sleeps. A "double payment re-read is stale" finding was disproved by a mutation test
  (`c8df73c`: without the re-read two payments both answer 200; with it 200/404).
- L8: Not built: Slice 7 (kitchen screen; orders wait `queued`), "pedir la cuenta" from the table, QR images (needs a
  library). One pytest warning appeared once in a full run and did not reproduce.
