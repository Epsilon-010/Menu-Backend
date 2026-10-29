# Slice 10 — Theme engine + colors and branding
Objective: versioned per-tenant theme (draft/publish), applied to `/menu` with CSS variables, admin editor with live preview.
Branch: `feat/slice-10-theme` (Backend + Menu-Frontend). Delivery: single-pr per repo (user, L1 step 6: "push de las dos ramas para que yo abra los PRs"). Runners: `uv run pytest`, `npm run typecheck && npm test`.

## Specs
- **S1 Versioned document with defaults.** "El theme es un documento JSON **versionado** (`schema_version`) con valores por defecto para todo; validado en el backend (reglas en `domain`, schema Pydantic en `infrastructure`)." A tenant with no saved theme reads the defaults.
- **S2 Endpoints.** "Documento de theme versionado con valores por defecto, validación y endpoints (leer, guardar borrador, publicar)." Admin reads/saves the draft and publishes; `table`/`guest`/staff read only the published theme.
- **S3 Draft vs published.** "el admin edita un borrador con vista previa en vivo (tamaños tablet y celular) y solo al publicar cambia lo que ven las mesas."
- **S4 Colors (decision 2026-10-28: one palette + `mode`).** "Colores completos (primario, secundario, acento, fondo, superficies, textos, precios, botones, bordes, badges), modo claro/oscuro y aviso de contraste WCAG." Fields: `mode` (light|dark), `primary`, `secondary`, `accent`, `background`, `surface`, `text`, `text_muted`, `price`, `button_bg`, `button_text`, `button_hover`, `border`, `badge_bg`, `badge_text`, `cart_bg`, `cart_text`, `gradient {enabled, from, to, angle}`. Switching mode resets to the light or dark default palette. WCAG AA is a warning, not a rejection.
- **S5 Brand (decision 2026-10-28: image + curated patterns).** "Marca: logo, banner con overlay, fondo con opacidad/desenfoque, nombre, eslogan y bienvenida (imágenes por Cloudinary)." `name` (empty = tenant name), `tagline`, `welcome_message`, `logo {image_id, size, position}`, `banner {image_id, height, overlay_color, overlay_opacity}`, `background {kind: none|image|pattern, image_id, pattern, opacity, blur}`; patterns are an app-shipped enum.
- **S6 Applied with CSS variables + Redis cache.** "Aplicación del theme publicado en `/menu` con variables CSS; caché en Redis por tenant." Publishing invalidates the tenant's cache. "ningún componente del menú tiene colores, fuentes o tamaños del negocio hardcodeados."
- **S7 Safe values only.** "no se permite CSS, HTML ni URLs arbitrarias en el theme; solo valores validados (colores hex/rgb, fuentes de la lista curada, números en rangos, enums, `public_id` del tenant)." Images go through the `media` registry (signed upload, attach/discard).
- **S8 Done when.** "cambio colores y logo en el editor, los veo en la vista previa sin afectar las mesas, publico y la tablet muestra el nuevo diseño; un valor inválido (color mal formado, CSS inyectado) es rechazado (con test)."
- **S9 Isolation and roles.** Tests: a tenant cannot read or modify another tenant's theme; `table`/`guest` (and waiter/kitchen) cannot edit or publish.
- Out of scope (ROADMAP Slice 14): history of published versions, presets, export/import.

## Tasks
| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 | S1, S4, S5, S7 | inline | done | Backend domain: theme document, defaults, value validation, contrast. RED: `No module named app.modules.theming`; GREEN 41 tests. Commit `d42332a` |
| T2 | S2, S3, S6, S7, S9 | inline | done | Backend: `themes` table (JSONB), use cases, `/theme` router, Redis cache, theme images via media registry. GREEN 11 use-case + 12 API tests; full suite 631 passed. Commit `5d8688b` |
| T3 | S6 | inline | done | Frontend: `/menu` applies the published theme through CSS variables (semantic tokens in `index.css`, defaults = previous zinc). RED: missing `./style.ts`; GREEN. Commit `9381753` |
| T4 | S3, S4, S5, S8 | inline | done | Frontend: admin Design editor (`/admin/design`), live preview (tablet/phone), contrast warning, uploads. RED: missing `./editor.ts`; GREEN; 163 tests, typecheck, lint, build ok. Commit `6c60ab5` |
| T5 | S8 | inline | done | Independent verifier: S1-S9 pass, 0 blockers, 7 advisories (3 fixed in frontend `d2b0653`). Native review backend 3851ca4..5d8688b approved and burned (`review-2923272b4721d484`, reliability lens). Frontend assess: medium, `under_budget`. ROADMAP + CLAUDE.md updated; both branches pushed |

Route evidence: backend and frontend share the API contract (frontend depends on it), so no parallel-writer reason; all inline.

Assumptions (2026-10-28): contrast below WCAG AA (4.5:1) is a warning only; an image still used by the published theme is never discarded when removed from the draft; colors are stored normalized as `#rrggbb` (input accepts `#rgb`, `#rrggbb`, `rgb(r, g, b)`); the gradient paints the menu header when enabled.

## Log
- L1 (2026-10-28, user, verbatim): "Arrancamos el Slice 10 — Motor de theme + colores y marca. [...] Seguí el flujo de siempre: documento ODD en Backend/odd/tasks/slice-10-theme.md, TDD (RED → GREEN), tests de aislamiento por tenant y de que el rol table/guest no puede editar el theme, y un test de que un valor inválido (color mal formado, CSS inyectado) se rechaza."
- L2 (2026-10-28): branches created from main (Backend 3851ca4, Frontend 1a71e9c). `Backend/.env` has no `CLOUDINARY_*` values: real uploads return 503; tests use the fake.
- L3 (2026-10-28, user decisions): dark mode = "Una paleta + mode"; brand background = "Imagen + patrones curados".
- L4 (2026-10-28): backend done. API: `GET /theme` (any signed-in role, published or defaults, Redis cache by generation), `GET|PUT /theme/draft`, `POST /theme/publish`, `POST /theme/images/signature {kind: logo|banner|background}` (admin). Draft responses carry `contrast_warnings`, `defaults.{light,dark}` palettes and `image_urls` by public id. Native assess on 3851ca4..5d8688b: medium, `under_budget` (review at slice end, as the user asked).
- L5 (2026-10-28, user question, verbatim): "que es mejor usar cloudinary o aws un buecket en s3?" Answered: Cloudinary for now (on-the-fly transformations, signed direct upload); S3 is cheaper at scale but needs CDN + resizing; switching is one `ImageStorage` adapter.
- L6 (2026-10-28): frontend done. HTTP e2e against Docker (demo tenant, Mesa 5): save normalizes `#ABC` to `#aabbcc`; injected CSS 422 problem+json naming the field; the table keeps the published colors until publish, then sees the new ones; table PUT draft / publish 403. Demo theme restored afterwards. Open menus refresh the theme every 60 s and when shown again (no SSE event in this slice).
- L7 (2026-10-28): verifier PASS (631 backend tests, 163 frontend, 77+5 live probes, 8 parallel first saves and 4 parallel publishes without 500, headless render of /menu and /admin/design). Fixed advisories: menu lost two columns without ThemeScope; admin bar overflowed at 820px after adding Design; secondary/accent/badge saved but not painted. Open advisories: shared UI zinc-600 text now zinc-700 (ink-soft); `brand.name` accepts `<`/`>` (escaped by React); `rgb()` digits accept Unicode digits (normalized to hex, harmless); a never-published tenant shows the default orange theme; theme cache fail-open untested (native review advisory R3-cache-failopen-untested); no contrast warning for `secondary` on the background.
