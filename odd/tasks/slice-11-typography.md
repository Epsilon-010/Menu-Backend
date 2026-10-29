# Slice 11 — Typography
Objective: per-tenant menu typography (curated Google Fonts, per-element settings, global scale) in the theme document, now `schema_version` 2.
Branch: `feat/slice-11-typography` (Backend + Menu-Frontend). Delivery: single-pr per repo (user: "push de las dos ramas para que yo abra los PRs"). Runners: `uv run pytest`, `npm run typecheck && npm test`.

## Specs
- **S1 Role fonts from a curated Google Fonts list.** "Fuentes para títulos, cuerpo, precios y botones desde una lista curada de Google Fonts." Decision 2026-10-28: 12 fonts — "Sans: Inter, Poppins, Montserrat, Lato, Nunito. Serif: Playfair Display, Lora, Merriweather. Display: Oswald, Bebas Neue. Manuscrita: Pacifico, Caveat." plus "Geist como fuente 13": Geist is the default of the 4 roles (`heading`, `body`, `price`, `button`). Each font records its real weights and whether it has italics.
- **S2 Per-element settings + global scale (decision: "Completo").** "Por elemento (nombre del negocio, categoría, producto, descripción, precio, botones): tamaño, peso, estilo, interlineado, espaciado entre letras, mayúsculas y alineación; escala base global." Each element picks one of the 4 role fonts. Defaults reproduce the current menu (Geist, current sizes and weights).
- **S3 Safe values only.** "no se permite CSS, HTML ni URLs arbitrarias en el theme; solo valores validados (colores hex/rgb, fuentes de la lista curada, números en rangos, enums, `public_id` del tenant)." A font outside the list, a weight or italic the element's font does not have, or a number out of range is rejected (422 naming the field, with tests).
- **S4 Loaded from the Google Fonts CDN (decision 2026-10-28), only what is used.** "solo se cargan las fuentes que se usan." The stylesheet URL is built only from catalog values. "La fuente de la app (Geist) no cambia: la tipografía del negocio solo aplica dentro del menú."
- **S5 Done when.** "cada elemento del menú puede tener su propia fuente y tamaño, se ve en la vista previa y se aplica al publicar".
- **S6 Stored themes migrate to v2 (decision: "Migración de datos Alembic").** "Una migración reescribe draft y published agregando `typography` con los valores por defecto y sube la versión a 2; downgrade() la quita y vuelve a 1. El parser sigue estricto (solo acepta v2)". Cached v1 documents in Redis are never served after the upgrade.
- **S7 Isolation and roles.** "tests de aislamiento por tenant y de que table/guest no pueden editar".

## Tasks
| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 | S1, S2, S3 | inline | todo | Backend domain: font catalog, typography parsing, defaults, v2 |
| T2 | S3, S6, S7 | inline | todo | Backend infra: Pydantic schema, Alembic data migration, cache key by schema version, API tests |
| T3 | S2, S4 | inline | todo | Frontend: types, font catalog, typography CSS variables, Google Fonts loader, menu elements use them |
| T4 | S2, S5 | inline | todo | Frontend editor: typography controls, weight/italic clamping on font change, preview |
| T5 | S5 | inline + verifier | todo | Independent verifier (risk item 1), native review, ROADMAP/CLAUDE.md/memory, push |

Route evidence: frontend depends on the backend contract and one behavior spans both repos; no parallel-writer reason, all inline. T2 is high risk (item 1: persisted format change + data migration) → independent verifier at T5.

Assumptions (2026-10-28, mine, open to correction):
- Document: `typography {scale, fonts {heading, body, price, button}, elements {business_name, category, product_name, description, price, button}}`; element = `{font (role), size, weight, style, line_height, letter_spacing, transform, align}`.
- Ranges: `scale` 80–130 (%); `size` 10–72 (px, before the scale); `weight` 100–900 in steps of 100 and offered by the font; `style` normal|italic (italic only if the font has it); `line_height` 100–200 (% of the size); `letter_spacing` -50–200 (thousandths of an em); `transform` none|uppercase|lowercase|capitalize; `align` left|center|right.
- Font ids are slugs (`playfair_display`); the frontend keeps its own copy of the catalog (family name, weights, italics), as it already does for the contrast pairs.
- The migrated `business_name.align` follows the stored logo position (`center` or `left`), so existing menus keep their look.

## Log
- L1 (2026-10-28, user, verbatim): "Arrancamos el Slice 11 — Tipografía. [...] 4. Antes de codificar, explorá el módulo `theming` del backend [...] y preguntame de a una las decisiones que el ROADMAP no define. [...] 5. Seguí el flujo de siempre: documento ODD en Backend/odd/tasks/slice-11-typography.md, TDD (RED → GREEN), tests de aislamiento por tenant y de que table/guest no pueden editar, y tests de que una fuente fuera de la lista o un valor fuera de rango se rechaza. La fuente de la app (Geist) no cambia: la tipografía del negocio solo aplica dentro del menú. 6. Al terminar: verificador independiente, revisión nativa con `--base-ref <último revisado> --committed-only` [...], actualizar ROADMAP.md, \"Estado actual\" en CLAUDE.md y la memoria, y push de las dos ramas para que yo abra los PRs."
- L2 (2026-10-28): branches from main (Backend `c85b72a`, Frontend `8219287`). `docs/slice-10-closing` still not merged (reminded). CI of main: asked the user (no `gh` session). Docker up.
- L3 (2026-10-28, user decisions): source = "Google Fonts CDN"; list = "12 fuentes"; per-element = "Completo"; v1 → v2 = "Migración de datos Alembic"; default = "Geist como fuente 13".
