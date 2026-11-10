# Menu sections — drag-and-drop page builder for the table menu

Objective: the admin builds the menu page from an ordered list of sections (start from a template or from scratch),
adds prefabricated blocks (featured carousel/grid, text, divider, image) and drags them, with few options in view.
Branches: `feat/menu-sections` in Backend (worktree `Backend-worktrees/menu-sections`) and Menu-Frontend.
Delivery: one PR per repo (as previous slices); Backend merges first. Tests: `uv run pytest`, `npm test`.

## Specs

- **S1 — Goal (user, verbatim):** "si quiesiera que fuera mas tipo como canvas de que arrastrar y todo eso osea de que
  diseñarlo desde 0 o partir de una paltnilla y poder arrastrar compnetes o poner cosas prefrabicada como cuadriculas
  caruseles y todo eso para poder diseñar un mejor menu" and "que de libertad para un mejor diseño y ais y mas sencillo
  o que sea mas facil de editar porque recuerda qeu va para personas que no tiene mucho cocnomiento en diseño o
  tecnolgoia y ver tantas opcioens y dmeas puede que lso confunda".
- **S2 — Section builder, not a free canvas** (decision delegated by the user: "lo que veas que sea mejor"): the page is
  a vertical, ordered list of sections; inside each section the layout stays responsive (phone, tablet, desktop).
  No x/y positioning.
- **S3 — Theme `schema_version` 6:** `layout.sections` is an ordered list (1–20) of sections, each with a unique UUID
  `id` and a `type`; unknown fields are rejected like the rest of the theme:
  - `hero`: the current header (banner, name, tagline, welcome, as `header_blocks` and `show_*` say). At most one.
  - `menu`: the categories with their navigation and per-category designs. Exactly one; it cannot be removed.
  - `featured`: `title` (0–60 chars), `item_ids` (0–12 unique UUIDs), `view` `carousel|grid`. Items that no longer
    exist or are unavailable are skipped when drawing; an empty one draws nothing.
  - `text`: `title` (0–80), `body` (0–500), `align` `left|center`, `style` `plain|highlight`. Plain text only.
  - `divider`: no settings.
  - `image` (T5): a tenant image (`public_id` under `tenants/{tenant_id}/section/`), `caption` (0–120). Assumption:
    goes last; it needs the image registry to keep each image `attached` while a theme uses it.
- **S4 — Upgrade of stored themes:** draft, published and `theme_versions` move from v5 to v6 with
  `sections = [hero, menu]` (the page looks exactly as before); importing a v1–v5 export converts it the same way;
  downgrade removes `sections`.
- **S5 — Templates:** every preset defines its sections (exactly one `menu`, never `featured`: a template is shared by
  every tenant and cannot name one tenant's products); "Restablecer" keeps working.
- **S8 — More and better templates (user, verbatim):** "igual añade mas platillas y usa o descagra alguna skill de
  disñeo para hacer las palntuillas y que queden mejor porfavor". Uses the installed `landing-page-design` skill (no new
  download needed); new presets use sections (welcome/promo text, dividers) besides colors, fonts, layout and cards.
- **S6 — Simple editor ("Página"):** the first panel of `/admin/design` lists the sections with a drag handle,
  up/down buttons and delete; "Agregar sección" shows a small gallery (icon + one-line description). Selecting a
  section shows only its essential options; extra ones under "Más opciones". Clicking a section in the preview selects
  it. Featured products are chosen from the tenant's menu with checkboxes (max 12).
- **S7 — Same drawing everywhere:** the table menu (`/menu`) and the editor preview draw the sections in order with the
  theme's colors, fonts and cards; featured products use the normal product card and add-to-cart.

## Tasks

| ID | Specs | Route | Status | Commit |
|---|---|---|---|---|
| T1 | S3, S5, S4 (import) | inline | done | Backend `ca431f6` |
| T2 | S4 (migration) — Risk item 1 | inline, own commit | done | Backend `f06fc2b` |
| T3 | S3, S7 (frontend types + renderer) | inline | done | Frontend `f675311` |
| T4 | S6 (editor) | inline | done | Frontend `d5de521` |
| T5 | S3 `image`, S6, S7 | inline | pending | |
| T6 | S5, S8 (new presets, `landing-page-design` skill) | inline | done | Backend `4c056bc` |

## Log

- **L1 (2026-11-10, user):** "en la parte para diseñar la carta si quiesiera que fuera mas tipo como canvas de que
  arrastrar y todo eso osea de que diseñarlo desde 0 o partir de una paltnilla y poder arrastrar compnetes o poner
  cosas prefrabicada como cuadriculas caruseles y todo eso para poder diseñar un mejor menu que puedo hacer? o como se
  puede mejhorar esa parte?"
- **L2 (2026-11-10, user):** "si lo que veas que sea mejor pero que de libertad para un mejor diseño y ais y mas
  sencillo o que sea mas facil de editar porque recuerda qeu va para personas que no tiene mucho cocnomiento en diseño
  o tecnolgoia y ver tantas opcioens y dmeas puede que lso confunda o asi"
- **L3:** map of v5 (explorer): `domain/theme.py` (Layout :237, parse_theme :765, only v5 accepted :769),
  `domain/import_theme.py` `_upgrade` :96, `domain/presets.py` `_layout` :71, migrations b7e3a91c4d52/e2a6c0b9d817
  update draft/published/theme_versions with `jsonb_set`; Alembic head `de3bacf10d81`. Frontend: `ThemeEditorPanel.tsx`
  (3-column tabs), `ThemePreview.tsx`, `MenuBrowser.tsx`, `MenuPage.tsx`, `layout.ts` `normalizeLayout` :164.
  Next: T1 (RED tests for v6 sections in the domain).
- **L4 (2026-11-10, user):** "igual añade mas platillas y usa o descagra alguna skill de disñeo para hacer las
  palntuillas y que queden mejor porfavor" → S5 reworded (templates may carry text/divider sections), S8 and T6 added.
- **L5 (2026-11-10) evidence:** RED observed for T1 (`DEFAULT_SECTIONS` import error) and T6 (`len(PRESETS) >= 12`).
  Backend: theming unit 337 passed; theming integration 92 passed (incl. `test_sections_migration.py`: upgrade, downgrade,
  re-upgrade of draft/published/history; downgrade drops added sections); full suite 1290 passed before T6.
  Frontend: 489 tests, typecheck, lint and build ok. Templates: `landing-page-design` rules applied (one typeface,
  no italics, weights ≤700, flat backgrounds, approved dark grounds, Tailwind type steps, copy without hyphens or
  exclamation marks). Not done: browser check of the editor (the running Docker backend is on `main`, v5; applying
  the v6 migration to the dev DB would break it until this branch is merged).
  Advisories: applying a template or "Restablecer" replaces the page sections (featured products included); featured
  item ids of another tenant in an imported file are kept but never drawn; the preview click is a mouse shortcut
  (the panel list is the keyboard path). Next: T5 (image section) and native review.
- **L6 (2026-11-10) review and verification:** native review of Backend `38d796a..` (lenses risk, reliability)
  approved with no findings and acknowledged (`review-7bd9555d8c0c69b0`); Frontend assessed medium, `under_budget`
  (pending in its slice). Independent verifier: S4, S5, S8 and invariants ok (migration probed on a scratch DB, 21 docs
  up/down/up); **1 blocker in S3**: the Pydantic tagged union echoed an unknown `type` value in the 422
  (`union_tag_invalid`). Fixed: `LayoutDoc.sections` is now `list[dict]` and the domain names the path
  (`layout.sections.N.type`) without the value; pinned by `test_theme_sections_api.py` (PUT and import, RED observed).
  Theming tests 429 passed. Advisories kept: the name (not the value) of an unknown key still appears in the 422, as
  everywhere in the project (Slice 14 advisory); text sections accept `<b>` as plain text (React escapes it).
