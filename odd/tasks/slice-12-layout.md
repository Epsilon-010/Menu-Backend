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
- S2+ (layout): pending the user's decisions (navigation styles, product views, carousel, migration to v3).

## Tasks
- T1 (S1) backend preset catalog + `presets` in the draft response, with tests — inline — done (commit below)
- T2 (S1) frontend template gallery in `/admin/design`, with tests — inline — done (commit below)

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
