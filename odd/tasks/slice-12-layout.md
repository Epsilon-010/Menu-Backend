Slice 12 — Menu layout and navigation, preceded by theme presets (templates) pulled forward from Slice 14.
Branch `feat/slice-12-layout` in Backend and Menu-Frontend. Delivery: ask-on-risk. Runners: `uv run pytest`, `npm test`.

## Specs
- S1 (presets, from L2/L3): "antes quiero que añadas tipo plantillas para que si no quiere personalizar el menú o
  quieren algo rápido las seleccione"; "checa que sea consistente".
  - A gallery of complete designs (palette + mode + typography) the admin applies to the draft in one click.
  - Applying a preset never changes the brand (name, tagline, welcome, logo, banner, background); it lands in the
    draft, shows in the preview and reaches the tables only after publishing.
  - Consistency (checked by tests): every preset is a valid theme (fonts, weights, ranges), has no WCAG AA contrast
    warning (also button text on its hover color), its mode matches its background, ids are unique.
  - Presets come with the draft (`presets` field next to `defaults`); no new endpoint. Layout (S2+) and cards
    (Slice 13) extend each preset when they exist. History and import/export stay in Slice 14.
- S2 (layout, from L7/L8): "si que el admin pueda elegir porfavor" (all four category navigations); category header
  image: "si sin imagen" (no image per category; the theme only styles the header).
  - Theme `schema_version` 3 adds `layout`: `navigation` chips|tabs|sidebar|sections (chips = today: sticky chips that
    jump within one long page; sections = one long page with a sticky text bar that highlights the current section;
    tabs and sidebar show one category at a time, the sidebar becomes a row on narrow screens), `product_view`
    grid|list|carousel (carousel = CSS scroll-snap, no new library), `columns` 1-4 (grid; fewer on narrow screens),
    `density` compact|comfortable|spacious, `sticky_header` bool, `category_header` plain|underline|band,
    `show_banner`/`show_tagline`/`show_welcome` bools, `cart` bar|panel|floating (bar = today).
  - Defaults reproduce today's menu (chips, grid, 2 columns, comfortable, sticky header, plain, all shown, bar).
  - Alembic data migration: every stored v2 draft/published gets the default layout and version 3; downgrade removes
    it. The cache key carries the version (v3).
  - Every preset defines a layout too; applying a preset sets colors, typography and layout, never the brand.
  - The admin picks each option in `/admin/design`; the preview shows it at tablet and phone size; the menu stays usable
    on both (no horizontal scroll, the cart is always reachable).

## Tasks
- T1 (S1) backend preset catalog + `presets` in the draft response, with tests — inline — done (commit below)
- T2 (S1) frontend template gallery in `/admin/design`, with tests — inline — done (commit below)
- T3 (S2) backend layout in theme v3 (domain, HTTP schema, presets) + data migration v2→v3, with tests — inline (no
  writer reason: frontend depends on this contract) — Risk item 1 (stored format) — done `b916d64`
- T4 (S2) frontend: menu renders the layout (navigation, product view, density, headers, sections, cart), with tests —
  inline — pending
- T5 (S2) frontend: layout controls in the editor + presets carry the layout, with tests — inline — done `c015092`
  (Frontend)

## Log
- L1 2026-10-29 (user): "ya exitse la rama para la slice 12 empiezala y antes quiero que aladas tipo pantillas para eur
  si no quiere personalziar el menu o queiren algo rapido las seleccione porfavor"
- L2 2026-10-29: proposed scope (only the preset gallery now; history/import/export stay in Slice 14; presets set
  palette, mode and typography, never the brand; applying replaces the draft). User: "si checa ue sea consistente".
- L3 2026-10-29: T1/T2 done. Six presets in `app/modules/theming/domain/presets.py` (classic = the default design,
  bistro and street dark, fiesta, cafe, garden light), each with its own font pairing. RED observed (missing module;
  missing `presets` field). Consistency tests: valid theme, no AA warning, plus button_text/button_hover,
  secondary/background (category headings use `text-secondary`), text_muted/background and price/background; lowest
  ratio 5.18 (classic). Frontend: `PresetGallery.tsx` (sample drawn in each preset's colors and fonts), `withPreset`,
  `matchingPreset` (marks the template the draft still matches). Checks: backend `uv run pytest` 709 passed; frontend
  typecheck, lint, `npm test` 175 passed, build ok; headless Chrome at 1400px and 420px: applying Street/Fiesta marks
  it, the preview changes, the brand stays, no horizontal scroll. Next: layout decisions (S2+).
- L4 2026-10-29 (user): "quieor que hasta donde vamos pruebs flujos puierabs unitarias y revises si hay riegos de
  seguridad o integridad de datos asi como bugs". Audit: backend 709 / frontend 175 green; e2e 177/177 against Docker;
  reviewers found 5 real issues (verified in code). Frontend presets commit: native review approved
  (`review-f761398f34f22c4c`), advisories: matchingPreset key order, missing `presets` guard.
- L5 2026-10-29 (user): "puedes arreglar los primero 5 qu eme diste?". Fixes, each with RED first:
  F1 `f6abd97` compose binds data services and API to HOST_BIND_IP (127.0.0.1) and Redis requires REDIS_PASSWORD
  (checked: NOAUTH/WRONGPASS without it, LAN IP sees only 5173, login 200). F2+F3 `d979e96` (frontend) refresh ends the
  session only on 401/403; 5xx/network/timeout throw SessionUnavailableError; refresh has the 15 s deadline; tabs take
  turns via navigator.locks (5 new tests). F4 `6c2392c` advisory lock `client-id:{id}` inside the free-id checks +
  IntegrityError → OrderIdTaken on cart lines and orders (3 race tests; 2 fail without the lock). F5 `70e5d90`
  `keepNewerEdits` keeps edits made while save/publish is in flight (2 tests).
- L6 2026-10-29: closing the fixes. Independent verifier: F1-F5 OK, no blockers (HTTP probes: 25 cart-line pairs
  200/409 and 10 order pairs 201/409 across two tables, replays return the existing resource; refresh differential
  identical for 401/403/200). Advisories: `_flush_new` names the order id even when the clash is on an item id
  (generic 409, nothing visible); a malformed 200 refresh body throws SyntaxError. Regression found while closing:
  after F1 the services listen on IPv4 only and Windows "localhost" tries IPv6 first (2.07 s per connection vs 0 s on
  127.0.0.1), so host URLs (config defaults, `.env.example`, local `.env`) now use 127.0.0.1. Full backend suite alone:
  712 passed in 4:25 (earlier errors came from two pytest runs sharing `menu_test`). Frontend: 183 passed, typecheck,
  lint clean.
- L7 2026-10-29 (user, on which category navigations enter): "si que el admin pueda elegir porfavor".
- L8 2026-10-29 (user, on a header image per category): "si sin imagen". Carousel without a library (CSS scroll-snap)
  and presets carrying a layout were announced without objection. Specs S2, tasks T3-T5.
- L9 2026-10-29: T3 done (`b916d64`). RED observed (ImportError: no CART_STYLES). `Layout` in the domain, `LayoutDoc`
  in the HTTP schema, `DEFAULT_LAYOUT` = today's menu; presets: classic default, bistro sidebar/list/panel, fiesta
  chips/carousel/floating, cafe sections/grid 3, garden tabs/grid/panel, street tabs/list/compact/floating. Migration
  `9c2e41b7d5a3` (v2→v3 with a frozen default layout; downgrade removes it); the typography migration test now stops at
  its own revision. A wrong JSON type (e.g. `sticky_header: 1`) is a schema 422 ("Invalid field"), like
  `gradient.enabled`. Backend `uv run pytest` 755 passed. Native review (risk + reliability) approved
  `review-a174c8ab271beb43`; its advisory (the "already v3" migration test ran at head, so it never ran the upgrade)
  fixed in the next commit.
- L10 2026-10-29: T4/T5 done (Frontend `de78ace`, `c015092`). RED observed (missing `layout.ts`). `layout.ts` (options,
  `DEFAULT_LAYOUT`, fixed class maps for columns and density, `showsOneCategory`, `currentCategoryId`), `withLayout`;
  `withPreset`/`matchingPreset` include the layout. `MenuBrowser`: chips (today), sections (scroll-spy bar), tabs and
  sidebar (one category; the sidebar is a row when the menu is narrow), grid/list/carousel (scroll-snap), category header
  plain/underline/band; it is its own size container (beside the cart panel the menu is narrower than the page).
  `MenuHero` hides banner/tagline/welcome; `AppShell` `fixedBar`; `MenuPage` cart bar/panel (from md)/floating;
  `LayoutControls.tsx` in `/admin/design`. Checks: typecheck, lint, `npm test` 190 passed, build ok. Headless Chrome on
  the demo tenant (4 layouts x phone 390 / tablet 820 / desktop 1280, then the theme restored): no horizontal scroll,
  cart reachable in all 12, default keeps 1/2/2 columns and a fixed header, tabs switch category, sidebar is a column
  only on desktop with the panel. Native review: frontend range medium, `under_budget` (766 lines), pending in the
  slice. Independent verifier launched for the feature (item 1).
- L11 2026-10-29: independent verifier (S2): schema, migration (scratch DB `menu_verify_layout`, dropped), presets,
  editor, cart reachability, 403 for tables and tenant isolation ok; 1 blocker: the default grid went to two columns from
  a 576px menu (608px screen) instead of a 672px screen. Fixed in Frontend `f739059`: two columns from a 39rem
  (624px) menu; headless check over 13 widths (600-1280) matches the old rule exactly (2 columns iff screen >= 672px).
  Advisories kept: 3-4 columns never show on large screens with the `bar` cart (the menu column is 640px); an unknown
  density/cart value would crash the menu (the server prevents it); `MenuHero` has no fallback for a theme without
  `layout` (frontend and backend deploy together); no render tests for `MenuBrowser`/`MenuPage`; downgrade also strips
  a document that was already v3. Dev data: the verifier left tenant "Verify layout other". Slice 12 done.
- L12 2026-10-29 (user): "si pero arregla lo que me dices de los avisos". Frontend `4b1c6c7`, RED first (5 new layout
  tests): three columns from a 37rem menu (the column beside the cart bar is ~630px with the scrollbar), four from
  50rem with the menu page widened to `max-w-7xl` (`menuWidthClass`); `cartPlacement` moved to `layout.ts` with a test
  that the compact cart shows exactly where the side panel does not; `normalizeLayout`/`withDrawableLayout` at the API
  boundary (published, draft, presets), so a missing or unknown value falls back to the default (also covers
  `MenuHero` and an older server). Render tests without new libraries (`react-dom/server`): `MenuBrowser.test.tsx`
  (each navigation, view, density, header style, empty menu) and `MenuHero.test.tsx` (hidden parts). Checks: typecheck,
  lint, `npm test` 205 passed, build ok; headless widths 390-1440 x 2/3/4 columns with the cart bar: default unchanged
  (2 from 672px), 3 columns from 1024px desktop (199px cards), 4 from 1280px (188px), no horizontal scroll, theme
  restored. Not changed: downgrade stripping a document that was already v3 (cannot be told apart; by spec). The
  verifier's dev tenant "Verify layout other" stays (harmless dev data). Native review of the frontend range: medium,
  `under_budget` (1055 lines).
