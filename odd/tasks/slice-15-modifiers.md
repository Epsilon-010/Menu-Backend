Slice 15 — Product modifiers: reusable modifier groups with options and prices, chosen in the shared cart, priced by the backend and shown to waiters, kitchen (no prices) and the bill.
Branch `feat/slice-15-modifiers` in Backend and Menu-Frontend. Delivery: ask-on-risk. Runners: `uv run pytest`, `npm test`.

## Specs
- S1 (groups, from L2): "Reusable library". The admin manages a tenant library of modifier groups and attaches any of
  them to many items; editing a group changes it for every item.
  - Tables `modifier_groups` (tenant_id, name, min_select, max_select), `modifier_options` (tenant_id, group_id, name,
    price_cents, is_available, position) and `item_modifier_groups` (tenant_id, item_id, group_id, position).
  - `GET /catalog/modifier-groups` (admin) lists the tenant's groups by name, each with its options in order:
    `{id, name, min_select, max_select, options: [{id, name, price_cents, is_available}]}`.
  - `POST /catalog/modifier-groups` (admin) `{id?, name, min_select, max_select, options: [{id?, name, price_cents,
    is_available?}]}` → 201 with the group. Idempotent like every create: same id + same data returns the group; same id
    with other data or another tenant's id is 409 "That id is already used by something else".
  - `PATCH /catalog/modifier-groups/{id}` (admin) `{name?, min_select?, max_select?, options?}`. `options` is the full
    new list in order: an option with an id of this group keeps its id (cart lines keep pointing at it), one without id
    is created, an omitted one is deleted. An id that is not an option of this group is 422 "Unknown option".
  - `DELETE /catalog/modifier-groups/{id}` (admin) → 204 and detaches the group from every item.
  - Item create/update accept `modifier_group_ids: list[UUID]` (order = order on the item; repeats collapse; at most
    10; an id that is not a group of this tenant is 422 "Unknown modifier group"). Item output adds
    `modifier_group_ids`.
  - Validation (422, detail names the rule, never the value): name 1-80 chars; 1-30 options; option name 1-80 chars and
    unique in the group (case-insensitive) "Option names must be unique in a group"; price 0..MAX_PRICE_CENTS.
- S2 (rules, from L3): "Min and max per group". `0 <= min_select <= max_select`, `1 <= max_select <= number of
  options`; otherwise 422 "Invalid selection limits".
- S3 (once each, from L4): "No, once each". A selection holds each option at most once; repeats are 422
  "Each option can be chosen once".
- S4 (price, from L5): "Zero or more". Option prices are integer cents >= 0. A line's unit price = item price + sum of
  the chosen options, computed by the backend from the database; the client never sends prices.
- S5 (sold out, from L6): "Yes, per option". Options have `is_available`. The menu shows them with `available: false`
  and they can't be chosen (409, same shape as an unavailable item). An item whose required group (min_select > 0) has
  fewer available options than min_select is hidden from the menu and can't be ordered.
- S6 (menu): `GET /menu` items add `modifier_groups: [{id, name, min_select, max_select, options: [{id, name,
  price_cents, available}]}]` in the item's order. The menu cache format moves to `v3`.
- S7 (cart, from L7): "Edit the options". `POST /table/cart/lines` accepts `modifier_option_ids: list[UUID] = []`;
  `PATCH /table/cart/lines/{id}` accepts optional `modifier_option_ids` (replaces the selection, bumps the version).
  - A selection must satisfy every group of the item: count between min and max ("Choose 1 option for Size", "Choose
    up to 3 options for Extras", "Choose between 1 and 2 options for Size"); an id that is not an option of this item is
    422 "Unknown option".
  - Cart line output adds `modifiers: [{option_id, group, name, price_cents}]` (item group order, then option order);
    `unit_price_cents`/`subtotal_cents` include them. A line whose selection is no longer valid (option removed or sold
    out, group rules changed or detached) is `available: false` like an unavailable item.
  - The idempotency of an add/staff dish compares the selection too; the frontend draft key includes it.
- S8 (submit, assumption 1 confirmed in L8): sending revalidates every line's selection; an invalid one makes the
  send fail with the existing 409 for unavailable items, so the table reviews it.
- S9 (snapshot, assumption 2 confirmed in L8): order items store a copy of the chosen modifiers (group, name,
  price_cents) and the unit price including them; editing the menu later never changes sent orders.
  - Order output (table orders, bill) adds `modifiers: [{group, name, price_cents}]`; kitchen and deliveries output adds
    `modifiers: [{group, name}]` (never prices). Staff `POST /orders/{id}/items` accepts `modifier_option_ids`.
- S10 (frontend): `/admin/modifiers` manages the library; the item form picks groups; the menu card asks for the
  options (radio when max_select is 1, checkboxes otherwise; price updates live; sold-out options disabled) before
  adding; a cart line shows its options and can reopen them to edit; send confirmation, order cards, kitchen, delivery
  and bill cards list them; the waiter's "add dish" form asks for them too.
- S11 (closing): ROADMAP: "Los modificadores se ven en la vista de meseros, en cocina (sin precios) y en la cuenta."
  Tenant isolation and `table`/`guest`/`waiter`/`kitchen` role tests on every new endpoint.

## Tasks
- [x] T1 S1-S3, S5, S6 — Backend catalog: tables + migration, domain, use cases, admin routes, item attach, menu output. Route: inline. Commit `7578f65` (assess: medium, under_budget).
- [x] T2 S3-S5, S7-S9 — Backend orders: cart selection, pricing, submit snapshot + migration, outputs, staff dish. Route: inline.
- [x] T3 S10 — Frontend admin: modifiers page, item form group picker. Route: delegated writer (parallel with T4 and backend; disjoint surfaces). Frontend commit `7fe74fd`.
- [x] T4 S10 — Frontend ordering: menu options picker, cart line edit, send confirmation, order/kitchen/delivery/bill cards, waiter add dish. Route: delegated writer (parallel with T3). Frontend commit `f54f9c0`.
- [ ] T5 S11 — Closing: e2e, independent verifier (item 1: migrations and order snapshot), native review, docs, ROADMAP. Route: verifier delegated.

## Log
- L1 (2026-10-30, user): "continua con la sigueotne slice, checa la memoria y los md para saber en dodn vamos"
- L2 (user): groups → "Reusable library (Recommended)".
- L3 (user): rules → "Min and max per group (Recommended)".
- L4 (user): repeat → "No, once each (Recommended)".
- L5 (user): price → "Zero or more (Recommended)".
- L6 (user): sold out → "Yes, per option (Recommended)".
- L7 (user): edit line → "Edit the options (Recommended)".
- L8 (user, on the two assumptions: revalidate on send with 409; orders snapshot names and prices): "si estan bien tus supiesto haz le codigo"
- L9: Delivery forecast ~2,500 authored lines across both repos (> 400) → ask-on-risk: one PR per repo per slice as in
  previous slices unless the user asks for a chain. Frontend writers run in parallel against the S1-S9 contract.
- L10 (T1): RED import error -> GREEN 76 catalog unit tests; API 7/7 and race tests 3/3 (`test_modifiers_concurrency.py`).
  Migration `dd10627658a8` (modifier_groups, modifier_options, item_modifier_groups; composite FKs keep the tenant;
  ON DELETE CASCADE detaches). Item edits take KEY SHARE on the groups (row lock first) so a concurrent group delete
  either waits or wins and the item answers 422 "Unknown modifier group". Probe: removing that pre-lock still passes
  the race test (the FK translation covers it), so the pre-lock is defense against a deadlock this timing does not
  reproduce. Assumption: items list groups in library order (the item form sends them by name).
- L11 (T3/T4 writers): frontend 308/308, typecheck, lint, build clean. Rule wording is mirrored on the frontend; the
  server's 422/409 detail is still shown. The waiter picker uses the default theme tokens (staff look).
- L12 (T2): selection rules in `orders/domain/modifiers.py` (9 unit tests; one test case had 3 extras for a max of 3,
  fixed to 4). Migration `4d9e8d3a002d` (cart_lines.modifier_option_ids UUID[], order_items.modifiers JSONB copy).
  Cart lines re-price on every read; a selection that no longer fits is `available: false` and sending answers the
  existing 409. API 8/8 (`test_modifier_orders_api.py`); exact-shape tests updated for the new `modifiers` /
  `modifier_group_ids` / `modifier_groups` keys.
