# UX round 2
Objective: tables that open themselves on QR scan, a modern UI on every role (shadcn/ui + Radix), and a menu designer with
draggable blocks and a structure per category. Branch `feat/ux-round-2` in Backend (from main) and Menu-Frontend (from
`feat/spanish-ui`). Delivery: ask-on-risk. Runners: `uv run pytest` (backend), Vitest `npm test` (frontend).

## Specs
- S1 (user, 2026-11-03): "eso de que siempre debe de estar abriendo la mesa mejóralo, mejor que esté abierta y al cobrar
  una orden cierre todas las sesiones". Decision: **the table opens by itself when the first guest scans the QR**
  ("Se abre sola al escanear"): `POST /auth/qr` on an active table without an open bill opens a new bill (visit) and
  joins it, atomically (two guests scanning at once share one bill). Paying or closing the bill still ends every guest
  session of that visit; the next scan opens a new visit. The waiter/admin "open table" action keeps working. The guest
  cap per visit (30), the QR regeneration and deactivation rules stay. The 409 "This table is not open yet; ask your
  waiter" no longer happens for an active table.
- S2 (user): "si se cobra las sesiones que estaban en la mesa de antes se invaliden y ya no puedan pedir si tienen la
  página web abierta" — already true (guest sessions are bound to `bill_id`; every cart/order read or write re-checks the
  guest in Postgres). Keep it true with S1: a guest of a paid visit must never reach the new visit; add a regression test
  that a guest of visit A gets refused after payment even though the next scan opened visit B.
- S3 (user): "mejorar el diseño de pantalla de todos los roles para que sea más fácil de usar ... mejora los botones y
  demás usa librerías de diseño" and "méntele más diseño a las barras de opciones, se ve como un programa viejo".
  Decision: **shadcn/ui + Radix** (components copied into the repo, Tailwind and the current tokens; Phosphor icons, not
  lucide). Native `<select>` option bars become styled selects / segmented controls / switches / sliders.
- S4 (user): "al diseñar el menú que se puedan arrastrar las cards, los botones y demás ... que si entran a desayunos se
  vea con cierta estructura, si entran a bebidas acomodado de otra forma". Decision: **blocks + per category**: drag to
  order the parts of a product card (image, name, description, price, add button) and the parts of the menu header
  (banner, name, tagline, welcome); each category can override the product view (grid/list/carousel), columns and card
  template; categories without an override use the general layout. Drag library: dnd-kit.
- S6 (contract for S4, decided by the parent): theme `schema_version` **5** adds, with defaults that reproduce the
  current look exactly:
  - `cards.blocks`: ordered list, a permutation of exactly `["image", "heading", "description", "badges",
    "add_button"]` (default in that order). `heading` is the name with the price (still placed by `price_position`).
    The `image` position is honored only by the `vertical` template; `horizontal` and `overlay` keep their fixed image.
  - `layout.header_blocks`: ordered list, a permutation of exactly `["banner", "name", "tagline", "welcome"]` (default
    in that order); the logo stays with the name; `show_*` flags still hide blocks.
  - `layout.categories`: object keyed by category id (UUID string, lowercase), at most 100 entries, each value
    `{"product_view": grid|list|carousel, "columns": 1-4, "card_template": vertical|horizontal|overlay}` (all three
    required). Default `{}`. A category without an entry uses the general layout and cards; ids of deleted categories
    are ignored when rendering (never an error). No extra keys anywhere (422).
  - Migration v4→v5 on `themes.draft`, `themes.published` **and every row of `theme_versions`**; downgrade removes the
    three fields. Import accepts v1-v5 and converts. Presets get the defaults. Theme cache key bumped.
- S5 (done before this doc): waiter "Entregadas" notes (Frontend `843ddb4`), visible "Subir imagen" button
  (`e1dd7c7`), category bar overlap fix (`ae8f18c`).

## Tasks
- T1 S1-S2 backend auto-open on QR + frontend copy that says the QR opens the table — delegated (parallel unit A) — done (see L5)
- T2 S3 shadcn/ui foundation + design editor controls — delegated (parallel unit B) — done, Frontend `b1fb760`
- T3 S3 staff screens (waiter, kitchen, admin panels) restyled — pending (after T2)
- T4 S4 backend theme `schema_version` 5 (card block order, header block order, per-category overrides) + migration of
  `themes` and `theme_versions` + import conversion — pending
- T5 S4 frontend drag-and-drop editor and per-category rendering — pending (after T2, T4)

## Log
- L1 (2026-11-03, verbatim): "El mesero puede ver las ordenes que ya entrego que le aparezcan como unas notas mejor y
  mejorar el diseño de pantalla de todos los roles para que sea mas fácil de usar / igual el mesero debe de tener un
  apartado de ordenes que ya entrego aunque ya esten completadas ... mejora los botones y demás usa librerias de diseño /
  ahora eso de que siempre debe de estar abriendo la mesa mejoralo ... / también que se puedan añadir opcionales por
  ejemplo si unas enchiladas suizas pueden llevar pollo, tasajo ... / checa lo de las opciones y así porque en la carta
  se solapan las categorías con las cards / igual al diseñar el menú que se puedan arrastrar las cards ... / Igual métele
  más diseño a las barras de opciones se ve como un programa viejo esas barras" (typos normalized only).
- L2: optional extras with prices already exist (Slice 15 modifiers); explained to the user, no change.
- L3: decisions taken with the user: shadcn/ui + Radix; table opens on scan; blocks + per category.
- L4: T1 and T2 are high/medium risk: T1 touches auth (high-risk item 2) and gets an independent verifier; T4 changes
  the persisted theme format (high-risk item 1) and must migrate `theme_versions` too.
- L5 (2026-11-04): T1 GREEN. One helper `open_bill` (`orders/application/ordering.py`) used by the QR scan, "open
  table" and the tablet's first order; `JoinTable` opens the bill under the table lock and announces `bill.opened` after
  commit; `TableNotOpen` removed. RED 5 failed / GREEN: unit 599, full suite 1123 passed; frontend 31 passed. Race test
  fails without the lock (duplicate key on `uq_bills_open_table_id`). Risk items 3 (the `/auth/qr` 409 is gone) and 4
  (bill created under the table lock at sign-in): independent verifier required.
- L6: T2 committed after a parent fix: the segmented control now estimates its width (7.5 px per character + 20 px per
  option, 165 px budget) because "Compacto / Cómodo / Amplio" and "Cuadrada / 4:3 / 16:9" were clipped.
- L7: T3 done: waiter/kitchen Frontend `7c933d6`, admin panels `c6bf4bb` (row helpers moved to `shared/ui`; the
  modifiers section renamed "Opciones y extras"). Frontend 390 tests.
- L8: T1 independent verifier: S1 pass, S2 pass, no blockers (full suite 1123 passed; race test fails without the
  lock). Advisories: anyone with the QR can open or join a visit (decision S1; regenerate the QR); >5 simultaneous
  scans from one IP get 429 (pre-existing limiter counts in-flight logins); an old guest's SSE can see the next visit's
  events up to 5 min if `bill.closed` is missed (pre-existing); no test for `/table/events` after payment. Stale texts
  fixed (Frontend `775c19f`, CLAUDE.md).
