Slice 13 — Product card design: card templates and options in the theme (v4), plus per-product badges in the catalog.
Branch `feat/slice-13-cards` in Backend and Menu-Frontend. Delivery: ask-on-risk. Runners: `uv run pytest`, `npm test`.

## Specs
- S1 (templates, from L2): "Vertical, Horizontal, Imagen completa" (minimal without image is out).
  - Theme `schema_version` 4 adds `cards.template` vertical|horizontal|overlay. vertical = today's grid card (image on
    top); horizontal = image beside the text; overlay = the image fills the card and the text sits on a dark scrim.
  - Without an image every template still reads well: vertical and horizontal drop the image; overlay falls back to a
    plain surface card.
  - The list view keeps drawing rows (horizontal) as today; the template applies to the grid and the carousel.
    (Assumption, not asked: a "list" of vertical cards would be the 1-column grid, which already exists.)
- S2 (badges, from L3/L4): "Sí, en este slice"; list: "Nuevo / Popular, Sin gluten, Vegano / Vegetariano, Picante".
  - Each product has zero or more badges from a fixed list: `new`, `popular`, `spicy`, `vegan`, `vegetarian`,
    `gluten_free` (shown as New, Popular, Spicy, Vegan, Vegetarian, Gluten-free). Stored on the item (catalog), not in
    the theme; the admin ticks them in the product form; `GET /menu` returns them; unknown badges are 422; repeats are
    collapsed. The theme only decides how badges look (`cards.badge_shape` pill|rounded, colors `badge_bg`/`badge_text`).
  - Categories stay as they are: each admin already creates and orders its own (L5).
- S3 (options, from L6): "Imagen, Forma de la tarjeta, Botón "agregar", Hover y animaciones" — all four groups in full.
  - `cards.image`: `aspect` square|landscape|wide (1:1, 4:3, 16:9), `fit` cover|contain, `position` left|right
    (horizontal template).
  - Shape: `radius` none|sm|md|lg|xl, `shadow` none|sm|md|lg, `border` {`width` none|thin|thick, `color`
    border|primary|accent}, `padding` compact|comfortable|spacious, `description_lines` 0-6 (0 hides it),
    `price_position` top|bottom.
  - `cards.add_button`: `style` text|icon|both, `shape` square|rounded|pill.
  - `cards.hover` none|lift|grow, `cards.animation` none|fade|rise; both off under `prefers-reduced-motion`.
  - `cards.overlay_opacity` 30-90 (overlay template scrim).
  - Defaults reproduce today's card (vertical, landscape, cover, left, xl, no shadow, thin border, comfortable, 3 lines,
    price top, both, rounded, no hover, no animation, scrim 60, pill).
- S4 (stored format, from L1): "agregar las tarjetas al theme es otro cambio del documento guardado. Va con
  schema_version 4 y una migración de datos de Alembic igual a 9c2e41b7d5a3 (riesgo item 1). La migración se prueba en
  una BD aparte, nunca bajando la de desarrollo. Las 6 plantillas (presets.py) también tienen que definir sus tarjetas."
  - Every stored v3 draft/published gets the default `cards` and version 4; downgrade removes them. Cache key carries v4.
  - Applying a preset sets colors, typography, layout and cards, never the brand.
- S5 (closing, from L1): "tests de render con react-dom/server (sin librerías nuevas), prueba en Chrome headless en
  celular, tablet y desktop con y sin imagen y con descripciones largas y cortas, y revisión nativa con
  ANTHROPIC_MODEL=claude-sonnet-5-5."
  - ROADMAP "Listo cuando": "cada plantilla se ve correcta con y sin imagen, con descripciones largas y cortas, y todas
    sus opciones se reflejan en la vista previa."

## Tasks
- T1 (S1, S3, S4) backend: `cards` in theme v4 (domain, HTTP schema, presets) + data migration v3→v4, with tests —
  inline (frontend depends on this contract) — Risk item 1 (stored format) — done Backend `a7102ca`; migration tested on
  a copy of the dev data (upgrade, downgrade byte-identical, upgrade); native review approved (`review-0a7ddf58f2128b62`,
  risk + reliability, no findings)
- T2 (S2) backend: item badges (column + migration, domain, use cases, catalog and menu API), with tests — inline —
  done Backend `94a8b85` (native review: under budget, pending in the slice)
- T3 (S1-S3) frontend: menu cards render the template, options and badges; types and `normalizeCards`; render tests —
  inline — done Frontend `de50028`, fix `59c23da`
- T4 (S2, S3) frontend: card controls in `/admin/design` (preview) and badges in the product form, with tests — inline
  — done Frontend `dcfe9ac`
- T5 (S5) closing: Chrome headless phone/tablet/desktop, independent verifier (item 1), native review, docs — browser check done (L8); verifier, review and docs pending

## Log
- L1 2026-10-29 (user): "Arrancamos el Slice 13 — Diseño de tarjetas de producto (ROADMAP.md). El Slice 12 (layout) ya
  está mergeado a main (Backend PR #18, Frontend PR #15). [...] 4. Antes de escribir código, preguntame de a una: qué
  plantillas de tarjeta entran (vertical, horizontal, imagen completa con overlay, minimal sin imagen); los badges por
  producto (nuevo, popular, picante, vegano…) son un dato de cada producto en el catálogo, no del theme: ¿los agregamos
  en este slice?; qué opciones de imagen, borde, sombra, botón "agregar" y animaciones entran completas. 5. Cuidado:
  agregar las tarjetas al theme es otro cambio del documento guardado. Va con schema_version 4 y una migración de datos
  de Alembic igual a 9c2e41b7d5a3 (riesgo item 1). La migración se prueba en una BD aparte, nunca bajando la de
  desarrollo. Las 6 plantillas (presets.py) también tienen que definir sus tarjetas. 6. Punto de partida: ItemCard en
  Menu-Frontend/src/features/ordering/MenuBrowser.tsx [...], layout.ts (mapas fijos de clases) y LayoutControls.tsx
  como modelo para los controles nuevos. 7. Cuando cierres: tests de render con react-dom/server (sin librerías nuevas),
  prueba en Chrome headless en celular, tablet y desktop con y sin imagen y con descripciones largas y cortas, y
  revisión nativa con ANTHROPIC_MODEL=claude-sonnet-5-5."
- L2 2026-10-29 (user, templates): "Vertical, Horizontal, Imagen completa".
- L3 2026-10-29 (user, badges in this slice): "Sí, en este slice (Recommended)".
- L4 2026-10-29 (user, badge list): "Nuevo / Popular, Sin gluten, Vegano / Vegetariano, Picante".
- L5 2026-10-29 (user): "el admin es que qeutien que agragr sus categorias prque cada restaurant tendra o dividira su
  porpio menu o porductos ocmo mehor lo vwea" — then, asked whether it meant custom badges: "No, era sobre categorías".
  Categories are already per tenant and admin-managed (Slice 4); nothing changes.
- L6 2026-10-29 (user, option groups): "Imagen, Forma de la tarjeta, Botón "agregar", Hover y animaciones".
- L7 2026-10-29: environment up, `alembic current` = `9c2e41b7d5a3 (head)`; branches cut from `main` (Backend
  `cf58197`, Frontend `c36f050`). Next: T1.
- L8 2026-10-30: T1-T4 done. Backend 809 tests, frontend 226 tests, lint and build clean. Chrome headless
  (`cards_e2e.py`, demo tenant, two real images uploaded through the signed flow, a long and a short description,
  badges): 5 designs (default; horizontal + right image + icon pill + price bottom; overlay in a 3-column grid; overlay
  template in the list view; carousel + 16:9 contain + thick accent border + no description + square text button) x
  phone 390 / tablet 820 / desktop 1280. First run found a blocker: overlay text and price spilled out of the card in a
  3-column grid (the grid column followed the text width); fixed in `59c23da` with a `minmax(0,1fr)` column and pinned
  in a render test. Second run: no page or card overflow, text and button inside every card, images loaded, overlay add
  form opens, the editor shows Product cards and the preview follows. Demo items and theme restored; the test images
  were discarded and deleted by the worker.
