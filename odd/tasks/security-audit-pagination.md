Security audit + pagination: attack the running app (black box) and its code (white box), record every finding, fix them, and add cursor pagination to the list endpoints.
Branch `feat/security-audit-pagination` in Backend and Menu-Frontend (both from `main` after PRs #23/#20). Delivery: one PR per repo, work-unit commits. Runners: `uv run pytest`, `npm test`.

## Specs
- S1 (from L1): "audítala, intenta vulnerarla y encuentra bugs o demás cosas que puedan hacer que falle, que la tiren;
  prueba los endpoints; checa que no sea fácil de vulnerar; atácala". Three passes: live black-box attack against
  http://localhost:5173 and :8020, backend white-box review, frontend white-box review. Every finding is recorded in
  `## Findings` with severity, reproduction and status.
- S2 (from L1): "checa la seguridad así como el rate limit". Login/table-login/QR/register/password limits are attacked,
  including `X-Forwarded-For` spoofing through the proxy and directly against the API.
- S3 (from L1): "cuando encuentres errores lo guardas y lo corriges". Each confirmed finding gets a fix with a
  regression test (or a recorded reason when it is accepted/out of scope).
- S4 (from L1): "en los endpoints pon paginación por cursor o así, pero pon alguna paginación". Decision (assumption,
  recorded in L2): keyset cursor pagination on the admin lists that grow with the business:
  `GET /staff`, `GET /admins`, `GET /tables`, `GET /catalog/modifier-groups`.
  - Query: `limit` (1–100, default 50) and `cursor` (opaque string from the previous page). Response
    `{items: [...], next_cursor: string | null}`; `null` means the last page. Order unchanged (by name, case-insensitive),
    ties broken by id so no row is skipped or repeated across pages.
  - A malformed or tampered cursor → 422 "Invalid cursor". `limit` outside 1–100 → 422 (schema error).
    A cursor only moves the start position: the query stays filtered by the caller's tenant.
  - Not paginated on purpose: live queues (`/kitchen/orders`, `/deliveries`, `/bills/tables`) must show every open item;
    `/table/orders` is bounded by one visit; `/catalog/categories` is reordered as a whole; `/menu` is one cached
    document; `/theme/versions` is already capped at 20. Their inputs get size limits instead where missing.
  - Frontend (changed in L3): `collectPages` follows the cursors 100 rows at a time (at most 50 pages), so the panels
    keep showing the whole list and every request stays bounded.

## Tasks
- [x] T1 S1-S3 audit passes (delegated: 3 read-only agents in parallel, breadth beyond the inline budget).
- [x] T2 S4 backend cursor pagination (inline). Backend `9e87bbf`.
- [x] T3 S4 frontend pagination (inline). Frontend `3662087`.
- [x] T4 S3 fixes: backend W1-W3, W5, W6, W8, W10 (inline), frontend FE1-FE4 (delegated writer: independent unit with a
  disjoint surface, run in parallel with the backend fixes). Frontend `df6fbd4`; backend in the commit after `9e87bbf`.
- [x] T5 verification: backend 1114 passed, frontend 377; independent verifier; two native reviews approved; live replay 16/16.

## Findings
Backend white-box (W*), frontend white-box (FE*), live black-box (B*). Status: fix | advisory (needs a user decision).
- W1 HIGH: SSE streams (`/table/events`, `/staff/events`) hold one connection each of the shared Redis pool
  (redis-py default 100, then `MaxConnectionsError`); ~100 streams make every login 500 and revocation fail open.
  Fix: SSE gets its own bounded pool and a per-subject + global cap of open streams (503 beyond it).
- W2 HIGH: login/table-login keep the DB connection while Argon2 (64 MiB) runs, and random usernames are never limited:
  a flood exhausts the 5+10 pool. Fix: release the connection before hashing, bound concurrent hashes, and cap per IP
  only the logins to accounts that do not exist (see L6/L7; real accounts never count there).
- W3 MEDIUM: `/auth/register` replay (known tenant id + business name) checks the admin password counting only
  `signup:<ip>`, skipping the `staff:<email>` backstop. Fix: count it under `staff:<email>` too.
- W4 MEDIUM: 6-digit PINs vs 5/device + 50/account: a distributed attacker gets 4,800 guesses/day per account, and
  can lock a legitimate device out through the backstop. Advisory: needs a product decision (longer PINs/lockout).
- W5 MEDIUM: no request body size limit (the dev Vite proxy has none). Fix: reject bodies over 1 MiB in a middleware
  (Content-Length and streamed), `client_max_body_size` in nginx.
- W6 LOW/MEDIUM: `bills.paid_cents` and `order_items.unit_price_cents` are int4; ~5 big rounds make paying 500 and the
  bill can never be paid or closed. Fix: cap unit price and bill total in the domain (409).
- W7 LOW: unbounded guest joins per visit. Advisory: the spec says "puede entrar cualquier cantidad de personas"; a
  cap is the user's call.
- W8 LOW: `/stats?from=9999-12-31` → 500 (date overflow); deeply nested JSON on body-less POSTs → 500
  (`RecursionError`). Fix: bound years; catch `RecursionError`.
- W9 LOW: kitchen sees prices through `/menu`. Advisory: the spec contradicts itself (matrix "ver menú" vs glossary).
- W10 LOW: a tablet with no open bill replaying an old `order_id` gets the past visit's order back. Fix: 409.
- FE1 MEDIUM: an unknown font id / missing typography element or `colors.gradient` throws while rendering and, with no
  error boundary, takes down `/menu` on every table (refetched every 60 s). Fix: normalize + route error element.
- FE2 LOW/MEDIUM: no security headers (CSP, frame-ancestors, nosniff, Referrer-Policy). Fix: nginx + Vite headers.
- FE3 LOW: QR token could leak by Referer. Fix: `Referrer-Policy: same-origin` (+ meta).
- FE4 LOW: `/api/v1/staff/events` lacks the SSE proxy settings in nginx. Fix: one location for both streams.
- FE5 INFO: tablets reach the Vite dev server. Advisory: use the `runtime` image beyond development.
- B1 LOW (live): after logout the access token keeps working until it expires (≤ 15 min); the refresh dies. Advisory:
  ending it would need a per-token denylist (bumping `session_version` would sign out the user's other devices).
- B2 INFO (live): an admin on a temporary password can still read `/menu` and `/theme` (known Slice 17 advisory).
- Live black box held up: 20 parallel submits → one order; 10 parallel payments → one; guests cut off in the request
  after paying; alg none / tampered JWT → 401; spoofed XFF direct and through the proxy → still 429 on the 6th login;
  every cross-tenant id → 404/422; no 500 found; no CORS reflection.
- Held up: tenant isolation on every repository and body id, role guards vs the matrix, `pwc` gate, JWT (HS256 pinned,
  `exp`/`sv` required), refresh rotation, 192-bit QR token, XFF chain (uvicorn takes the right-most untrusted hop from
  the single trusted proxy IP), no XSS sink, no open redirect, tokens never in JS.

## Log
- L1 (2026-10-31, user, verbatim): "quiero qeu audtries mi app, quiero que la intentes vulneral y encuntres bugs o demas
  cosas que puedan hacer que falle que la tires que pruevbes los end poitns que cheques mas que nada que no sea facil de
  vuneral, atacala, igual en los end poitns pon paginacion por cursor o asi pero pon alguna paginanciion y chec al
  aseguridad asi comodel rate limti cuantod encurtre errores lo guardas y lo corriges"
- L2 (2026-10-31): pagination scope chosen by the agent (S4) since the user left it open ("por cursor o así"): keyset
  over (lower(name), id) because offsets skip/repeat rows when the list changes between pages.
- L3 (2026-10-31): frontend pagination changed from "Load more" to following every cursor: same UX, bounded requests,
  far less risk in four panels. Audit results: no critical; two HIGH outages (W1, W2) and three MEDIUM (W3, W5, FE1).
- L4 (2026-10-31) evidence: RED observed before each fix (pagination 60 cases; limiter address cap; release before
  hashing; bounded hashes; stream caps; register replay counted as login; stats years; nested JSON; 413 bodies; bill
  cap; past-visit replay). While writing the limiter test, 120 concurrent acquires raised `MaxConnectionsError` from
  the shared Redis pool, reproducing W1. Backend `uv run pytest`: 1100 passed. Frontend: typecheck, lint, 377 tests,
  build, `nginx -t` on the runtime image.
- L5: open decisions for the user: W4 (PIN length / lockout), W7 (guest cap), W9 (kitchen prices on `/menu`), B1.
- L6 (2026-10-31): native review `review-62f25ec3e3fb7150` (risk, resilience, reliability; range b3e2b00..656da56)
  approved and acknowledged, with advisories: (a) a forged cursor with a NUL or lone surrogate in its key answered 500
  (also reported by a parallel session and reproduced live) → fixed in `bb76f4a` (422 "Invalid cursor");
  (b) the per-IP failure cap counted every account, so a diner on the venue's Wi-Fi could lock staff and tablet
  logins sharing that IP → redesigned: only logins to accounts that do not exist count per address
  (`LOGIN_MAX_UNKNOWN_PER_ADDRESS`), checked after the lookup and before the hash; real accounts keep the per-device
  and per-account limits as before; (c) 429/503 on a stream cap: the frontend already polls and reconnects with a
  growing delay on any stream error (`useLiveEvents.ts`), no change; (d) unlimited guests could fill the global stream
  cap: tied to the open W7 decision.
- L7 (2026-10-31): native review `review-bd3d31dd087bb061` (4 lenses, whole branch b3e2b00..db821ff) approved and
  acknowledged. Fixed from its advisories: once an address spent its unknown-login budget, unknown logins answered 429
  and real ones 401 (an account-enumeration oracle) → now the same 401 after waiting as long as a hash takes
  (`wait_like_verify`, no hash computed); the 512-character cursor cap rejected cursors the server itself makes for
  long non-ASCII names → derived from the key cap; config grouping; this Findings text. Left as is: two list-use-case
  shapes (tables and groups keep their full list for orders, stats and the menu), the fake helper name, the nested-JSON
  walk (already iterative, per the verifier).
  Independent verifier (whole document, baseline b3e2b00): S4 and every "Fix" finding ok; its one blocker (tampered
  cursor → 500) is `bb76f4a`; its per-IP lockout advisory is `db821ff`. Backend suite at `656da56`: 1100 passed;
  frontend typecheck, lint, 377 tests.
- L8 (2026-10-31, user, verbatim): "si hazlo corrige y si ya estan corregido pushealo"
- L9: fixed the open items with defaults (W4 stays open: a longer PIN changes what staff type and is the user's call):
  W9 the kitchen gets `/menu` without any `price_cents` (glossary: "No ve precios ni cobros"); B1 logout also ends that
  access token (`jti` kept in Redis until it would expire; other devices keep their sessions); W7 a visit takes up to
  30 guests (`MAX_GUESTS_PER_VISIT`), the 31st scan gets 409 "This table already has the most guests it allows; ask
  your waiter" (CLAUDE.md spec updated from "cualquier cantidad"); this also bounds the guest share of the SSE cap.
