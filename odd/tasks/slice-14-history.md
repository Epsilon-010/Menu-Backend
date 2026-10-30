Slice 14 — Theme history, reset to defaults and JSON export/import (the preset gallery already exists since Slice 12).
Branch `feat/slice-14-history` in Backend and Menu-Frontend. Delivery: ask-on-risk. Runners: `uv run pytest`, `npm test`.

## Specs
- S1 (history, from L2): "Últimas 20".
  - Every publish stores a copy of the published theme in a new table `theme_versions` (tenant_id, theme JSONB,
    published_at). Each tenant keeps its last 20; publishing the 21st deletes the oldest in the same transaction.
  - A data migration seeds the history with each tenant's current published theme (riesgo item 1). Downgrade drops the
    table. Tested on a separate database, never by downgrading the dev one.
  - `GET /theme/versions` (admin only, own tenant) lists them newest first with their image URLs.
  - Images a stored version uses stay attached while the version is in the history (assumption: restoring must never
    show a deleted image); pruning a version discards the images nothing else uses (draft, published, other versions).
- S2 (restore): restoring a version copies it (brand included) into the draft; the tables only change when the admin
  publishes (CLAUDE.md: "solo al publicar cambia lo que ven las mesas"). Publishing it adds a new version on top.
- S3 (reset, from L5): "Todo menos la marca".
  - "Reset to defaults" sets colors, typography, layout and cards of the draft to the defaults; name, tagline, welcome,
    logo, banner and background stay. Not saved until the admin saves or publishes.
- S4 (export): the editor downloads the current draft as a JSON file (the theme document, with `schema_version`).
- S5 (import conversion, from L3): "Convertirlo".
  - `POST /theme/import` (admin only) validates an uploaded theme document and returns it as the current version
    without saving it; the editor puts it in the draft. Versions 1-3 are upgraded with the same frozen defaults as the
    migrations (`3f7686d2fe3f`, `9c2e41b7d5a3`, `c5d18a7e4f20`); any other `schema_version` or a malformed document is
    422 naming the field, never the value.
- S6 (import images, from L4): "Se descartan".
  - Images of another tenant are removed (and a background image becomes no background); images of this tenant are
    kept only if one of its themes still uses them (draft, published or history). The answer names the removed slots
    so the editor warns the admin.
- S7 (closing): ROADMAP "Listo cuando": "aplico un preset, lo ajusto, publico, restauro una versión anterior y puedo
  exportar/importar el diseño entre dos tenants de prueba." Tenant isolation and `table` role tests on every endpoint.

## Tasks
- [x] T1 S1, S2 — Backend history: table + data migration, repository, publish/save keep images, `GET /theme/versions`. Route: inline. Commit `2c695a9`.
- [x] T2 S5, S6 — Backend import: domain upgrade v1-v3 → v4, image stripping, `POST /theme/import`. Route: inline. Commit `9272808`.
- [x] T3 S2, S3, S4, S5, S6 — Frontend: history list with restore, reset, export and import in `/admin/design`. Route: inline. Frontend commit `70cfdb4`.
- [ ] T4 S7 — Closing: e2e between two tenants, independent verifier (item 1), native review, docs, ROADMAP. Route: verifier delegated.

Route evidence: no Writer trigger (units depend on each other: the frontend needs both endpoints); parent writes inline.
Forecast: ~1.000 authored lines (backend ~650, frontend ~350). Delivery as in Slices 10-13: one PR per repo for the
slice, made of work-unit commits, each reviewed natively by range (`--base-ref <last reviewed> --committed-only`).

## Log
- L1 (2026-10-30, user): "ve le etasdo del proeycto y sifue con lo que queda"
- L2 (2026-10-30, user, historial): "Últimas 20 (Recomendado)"
- L3 (2026-10-30, user, importar versión vieja): "Convertirlo (Recomendado)"
- L4 (2026-10-30, user, imágenes del import): "Se descartan (Recomendado)"
- L5 (2026-10-30, user, restablecer): "Todo menos la marca (Recomendado)"
- L6 (2026-10-30): state check — Slices 11 and 13 and `docs/slice-10-closing` merged to `main` in both repos (Backend
  PR #19, Frontend PR #16). CI of `main` not confirmed (`gh` without session). Branches created from `main`.
- L7 (2026-10-30, T1): RED observed (ImportError, then 3 failing image-retention tests from a wrong "dropped" formula,
  fixed). GREEN: unit 187 passed; theming integration 52 passed; race test `test_theme_concurrency.py` passes with the
  row lock and fails with `UniqueViolationError` when `.with_for_update()` is removed. Full suite 822 passed. Behavior
  change pinned: republishing no longer discards the old published image while a kept version uses it.
- L8 (2026-10-30, T1 review): native review `review-86f2884d090ad43f` (risk + reliability, Sonnet) approved with no
  findings and acknowledged. Reviewed boundary: `1764a03`.
- L9 (2026-10-30, T2): RED observed (ImportError; then `schema_version: 4.0` accepted by `parse_theme` → now requires
  an int). GREEN: unit + theming integration 564 passed (`test_import_theme.py`, import cases in
  `test_manage_theme.py`, `test_theme_import_api.py`). Full suite not rerun after T2. Commit `9272808`.
- L10 (2026-10-30, user): "para por el moennto fgfuarda un registro de lo que llevas para que cuando de continudad a
  las esion sepas que sigue". Stopped here. Next: (1) run the full backend suite; (2) native review of T2 with
  `--base-ref 1764a03 --committed-only` (`gentle-ai review assess` first); (3) apply migration `699f2f507bc4` to the dev
  DB (`docker compose exec backend uv run alembic upgrade head`); (4) T3 frontend on `feat/slice-14-history`
  (already created from `main`, no commits): `api.ts` (`fetchThemeVersions`, `importTheme`), history list with
  "Restore" (puts the version in the draft), "Reset to defaults" (default colors/typography/layout/cards, brand kept;
  the backend still needs to expose the default theme, e.g. in `ThemeDraftOut`), export (download the draft JSON) and
  import (file → `POST /theme/import`, warn about `removed_images`) in `ThemeEditorPanel.tsx`; (5) T4 closing.
  Nothing pushed yet.
- L11 (2026-10-30, resume, user): "sigue". Docker Desktop was stopped (started it). Migration `699f2f507bc4` applied to
  the dev DB (11 tenants seeded with version 1). T2 assessed `medium`, `under_budget` (pending in the slice). Full
  backend suite after T2: 860 passed.
- L12 (2026-10-30, T3): RED observed (8 failing frontend tests). Reset = apply the first template, which the backend pins
  as the default design (`test_the_first_preset_is_the_default_design`), so no backend change. GREEN: `npm test` 238
  passed, typecheck, lint and build clean. E2E over HTTP through :5173 (two new tenants `e2e14-a/b-*@example.com`):
  preset + adjust + publish, restore v1 through the draft, export A → import B → publish, v3 export converted, unknown
  version 422 — 10/10. Chrome headless at 1280px: the "Versions and backups" card renders with Reset/Export/Import and
  versions 3-2-1, newest marked "On the tables". Independent verifier launched (item 1: data migration).
- L13 (2026-10-30, independent verifier): S1-S7 ok, no blockers. Evidence: 22 publishes keep 20 (22..3); 8 concurrent
  publishes at 20 and 12 on a fresh tenant all 200 with gapless numbers; migration on a separate DB `menu_verify14`
  (seed only published, `published_at` kept, NULL → now(); downgrade drops the table; re-upgrade reseeds); restore,
  import v1-v4, foreign/own-unused images, malformed bodies, roles 403/401, tenant isolation; ~30 imports leave B's data
  byte-identical. Full suite 860 passed; `npm test` 238. Advisories fixed: (1) import nested ~600+ levels gave 500
  (RecursionError in deepcopy) → 422 "Invalid theme value: theme", Backend `2972cd2`, re-probed 800 levels: 422;
  (2) the import warning blamed another business even for own unused images → reworded, Frontend `3465acb`; minor:
  `revokeObjectURL` right after `click()` → delayed 60 s. Open advisories: an unknown key name is echoed in full in
  the 422 `detail` (a name, not a value); every save/publish/import parses all kept versions, so a future schema v5
  migration MUST also migrate `theme_versions`; restore and import replace unsaved edits without asking; export
  takes the editor state (unsaved edits included). Verifier data: DB `menu_verify14`; dev tenants
  `verify14-A-d932ba@example.com` (31 publishes, staff/tables "Verify14 ...") and `verify14-B-1ebbc9@example.com`;
  E2E tenants `e2e14-a/b-*@example.com`.
