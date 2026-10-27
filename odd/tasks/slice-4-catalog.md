# Slice 4 — Catalog: categories and items (admin)
Objective: the admin manages the tenant's categories and items (with an image) from the panel.
Branch: `feat/slice-4-catalog` in both repos, from `main`. Delivery: ask-on-risk. Runner: `uv run pytest` (Backend), `npm run typecheck && npm run lint && npm run build` (Menu-Frontend).

## Specs
- S1 Categories (ROADMAP): "CRUD de categorías (con orden)".
  - Name trimmed, 1-60 chars, unique per tenant ignoring case (duplicate -> 409). `is_visible` hides a category (ROADMAP "oculta").
  - New categories go last. Reorder sends the full list of the tenant's category ids; anything else -> 422; positions change in one transaction.
  - Assumption: delete is allowed only for an empty category (409 otherwise; backed by the FK so a concurrent item create cannot leave orphans).
- S2 Items (ROADMAP): "CRUD ... de items (nombre, descripción, precio, disponible)."
  - Name 1-80 chars; description 0-500 chars; price in integer cents 0-10,000,000 (never float); `is_available` hides an item. Item names are not unique (assumption).
  - Each item belongs to one category of the same tenant (composite FK `(category_id, tenant_id)`); moving to another category puts it last there. Reorder inside a category sends the full list of that category's item ids.
  - Assumption: items can be hard-deleted (orders do not exist yet; Slice 6 will snapshot name and price on the order).
- S3 Images (ROADMAP): "Imagen por item con **Cloudinary**: puerto `ImageStorage`, adaptador de Cloudinary, endpoint de firma (solo admin, carpeta del tenant), subida directa desde el navegador y guardado del `public_id`."
  - Port `ImageStorage` in `app/shared/domain` (theming will reuse it for logo/banner); `CloudinaryImageStorage` is the only code importing the SDK (L2: SDK approved).
  - Signature restricted to `tenants/{tenant_id}/items` and formats jpg/png/webp. The backend accepts a `public_id` only inside that folder and only after checking with the storage that it exists, has an allowed format and is at most 5 MB; a rejected upload is deleted.
  - The DB stores the `public_id`; the API returns URLs built with `f_auto,q_auto` and a size per use. Replacing or removing an image (or deleting the item) deletes the previous resource after the commit.
  - Without Cloudinary credentials the API still starts; the signature endpoint answers 503 and items show no image (credentials pending, L2).
- S4 Fake (ROADMAP): "Adaptador fake para tests y CI." Tests never call Cloudinary.
- S5 Done when (ROADMAP, verbatim): "el admin crea, edita, reordena y oculta categorías e items con imagen desde el panel; los datos de otro tenant nunca aparecen (con test)."
- S6 Roles and tenancy (CLAUDE.md): every catalog route is admin only (`waiter`, `kitchen`, `table` -> 403); the tenant always comes from the token; another tenant's ids answer 404; errors are RFC 9457 problems.

## Tasks
- [x] T1 (S1-S4, S6) Backend: shared image port + Cloudinary adapter + settings, `catalog` module, migration, tests — inline (no Writer trigger: one dependent unit) — RED: unit collection error (no `app.modules.catalog`); GREEN: 224 passed — see L3
- [ ] T2 (S1-S3, S5) Frontend: catalog admin panel with direct signed upload — inline
- [ ] T3 (S1-S6) Independent verification — delegated (Risk items 2: upload signing with the API secret; 5: new dependency)

## Log
- L1 (2026-10-27, user): "haz la siguietne slide"
- L2 (2026-10-27, user): "si agrgalo y deja pendiente añadir las credneciales dde cloudnary eso lo hago alrato"
- L3 (evidence, 2026-10-27): `cloudinary==1.46.3` added with `uv add`. Endpoints (admin only, prefix `/api/v1/catalog`): `GET/POST /categories`, `PUT /categories/order` `{ids}`, `PATCH/DELETE /categories/{id}`, `PUT /categories/{id}/items/order` `{ids}`, `POST /items`, `PATCH/DELETE /items/{id}`, `POST /images/signature`, `PUT/DELETE /items/{id}/image` `{public_id}`. Design: the backend signs one exact `public_id` (`tenants/{tenant_id}/items/<uuid hex>`) plus `allowed_formats`, so the browser cannot choose the destination; this works in both Cloudinary folder modes. Cloudinary's upload API has no signed max-size parameter, so the 5 MB limit is checked by the frontend before uploading and by the backend (Admin API `resource`) before saving; oversize or wrong-format uploads are deleted. Input schemas use `extra="forbid"` and strict integer prices. Migration `f05beb4c96b9`: `categories` (unique `(tenant_id, lower(name))`, unique `(id, tenant_id)`), `items` (composite FK `(category_id, tenant_id)` NO ACTION, so a non-empty category cannot be deleted yet a tenant cascade still works; CHECK `price_cents >= 0`). Dev DB upgraded; downgrade/upgrade round-trip and `alembic check` on the `_test` DB. Tests: adapter signature equals Cloudinary's SHA-1 scheme, URLs carry `c_fill,f_auto,q_auto` and sizes, missing credentials -> unconfigured storage even with credentials in the environment. API tests were written before the router but first run after it (RED observed only for unit tests). Ruff/mypy are not project tools.
