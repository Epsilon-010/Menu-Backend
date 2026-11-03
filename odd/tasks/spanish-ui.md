# Spanish UI
Objective: every screen of the frontend in Spanish. Branch `feat/spanish-ui` (Menu-Frontend, from `feat/design-editor-compact`).
Delivery: ask-on-risk. Test runner: Vitest (`npm test`).

## Specs
- S1: "pon en español la app" / "las pantallas siguen en ingles": every user-visible text of the frontend (labels, buttons,
  headings, placeholders, aria labels, empty/error/success messages, titles) is in Spanish.
- S2 (assumption, no new library): Spanish only, written directly in the components; no i18n library and no language switch.
- S3 (assumption): neutral Latin American Spanish with "tú", following the glossary in CLAUDE.md (mesa, orden, platillo,
  cuenta, mesero, cocina, personal, borrador, publicar, plantilla).
- S4: identifiers, API values, routes and messages coming from the backend do not change. Backend error messages stay in
  English for now (pending user decision).

## Tasks
- T1 S1-S4 theming (`src/features/theming/`) — delegated (parallel unit A) — done, Frontend `debb155`
- T2 S1-S4 ordering, pages, app, shared, auth, account, index.html — delegated (parallel unit B) — done, Frontend `bf52b99`
- T3 S1-S4 catalog, modifiers, tables, staff, admins, settings — delegated (parallel unit C) — done, Frontend `09b46f2`
- T4 S1-S4 bills, deliveries, kitchen, stats — delegated (parallel unit D) — done, Frontend `35d5eac`

- T5 S1 template names and descriptions (backend `presets.py`) — inline — done
- T6 S1 admin nav collapses below 2xl (Spanish labels are longer) — inline — done

## Log
- L1 (2026-11-03): "y pon en español la app" — then "tiralo y levantlao las pantallas siguen en ingles".
- L2: route: four parallel writers with disjoint directories (each unit is several files and 100+ changed lines); the
  parent owns git and runs the full suite once at the end.
- L3: seam check after the four writers: 3 cross-unit test expectations fixed; Frontend 377/377, typecheck and lint ok;
  backend theming tests 279 passed. Chrome headless at 1440 and 1600 px. Strings deliberately in English: backend
  `detail` messages and the constants compared against them (`ALREADY_CREATED`, `EMAIL_TAKEN`, `CART_CHANGED`,
  `DISHES_CHANGED`), sample text in previews, font names.
