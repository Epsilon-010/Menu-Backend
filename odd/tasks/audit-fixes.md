# Audit fixes (2026-11-09)

Objective: fix every defect found by the 2026-11-09 audit. Branches: `fix/audit-findings` in Backend (worktree `Backend-worktrees/audit-fixes`, from `0625d08`) and in Menu-Frontend (from `0ad411c`).
Delivery strategy: `single-pr` per repository; push and PRs stay with the user. Test runners: `uv run pytest` (Backend), `npm test`, `npm run typecheck`, `npm run lint`, `npm run build` (Menu-Frontend).

## Specs

Frontend paths are relative to `Menu-Frontend/src`; backend paths to the backend root.

### Backend

- S1. Deactivating a table with an unpaid bill must not strand the bill. `app/modules/tables/application/manage_tables.py:122-143`, `app/modules/orders/application/bills.py:71`, `app/modules/orders/infrastructure/adapters.py:84`. Assumption (no new business rule): the admin may still deactivate; `GET /bills/tables` also lists inactive tables that have an open bill, so staff can charge or close it.
- S2. One tenant cannot take every SSE stream. `app/modules/orders/infrastructure/stream_slots.py:22-30`, `app/shared/infrastructure/config.py:31-32`. Assumption: a per-tenant cap, new setting defaulting to 200 per process (documented in `.env.example`), answers the same 503 as the global cap; the existing per-subject and global caps stay.
- S3. Adding to the cart no longer reloads the whole catalog. `app/modules/catalog/application/menu.py:55-63`, `app/modules/orders/application/ordering.py:163,171`. Orderable items are fetched by the requested ids, same rules and errors as today.
- S4. `GET /bills/tables` has no per-table queries and open bills are found through an index. `app/modules/orders/application/bills.py:71-77`, `app/modules/orders/infrastructure/repository.py:92-96,338-355,414`, `app/modules/orders/infrastructure/models.py:16`. Alembic migration adds a partial index `(tenant_id) WHERE closed_at IS NULL`, working `upgrade()` and `downgrade()`.
- S5. A tenant cannot request unlimited upload signatures. `app/modules/catalog/application/item_images.py:37-42`, `app/shared/infrastructure/images.py:57-71`, `app/modules/theming/application/manage_theme.py:97-104`. Assumption: refuse with 429 when the tenant already has too many `pending` rows in `image_uploads` (new setting, default 100, in `.env.example`); `media` keeps owning its tables.
- S6. A lone surrogate (`"\ud800"`) in any JSON body is a 422, never a 500. `app/shared/infrastructure/http/validation.py` (next to the NUL rule, same global dependency), reproduced through `PUT /theme/draft` and `POST /theme/import` (`app/modules/theming/domain/theme.py:81,553-561`).
- S7. `POST /bills/{id}/payment` accepts an optional `expected_total_cents`. When sent and different from the bill's total: 409 "The bill changed, review it", nothing is charged. Omitted: behaves exactly as today.

### Frontend

- S8. `features/ordering/logic.ts:127-135`: the send id is tied to the reviewed cart version, so a retry of the same version reuses it (no duplicate order) and a later round never replays an earlier order after a lost answer.
- S9. `pages/JoinTablePage.tsx:19`: a guest with a live visit who scans a different table's QR gets the join form for that table; scanning the same QR still goes to the menu.
- S10. `features/ordering/useTableOrdering.ts:120-132`: the menu refreshes on the 60 s and visibility schedule `usePublishedTheme` uses, and after an error saying an item is unavailable. A background refresh failure keeps the menu on screen.
- S11. `features/auth/AuthProvider.tsx:30-36`, `features/auth/api.ts:113-116`: only a confirmed 401 ends a session on load. Any other failure shows an error screen with retry.
- S12. `features/bills/TableBillCard.tsx:65,207`: the open dialog resets when `bill?.id` changes.
- S13. `shared/api/http.ts:105`: `publicFetch` uses `withDeadline`; login, QR join and logout cannot hang forever.
- S14. `features/theming/ThemeEditorPanel.tsx:200`: leaving with unsaved changes asks for confirmation (in-app navigation and `beforeunload`).
- S15. `shared/sound/beep.ts:17`: while audio is suspended after a reload, the toggle tells the user to tap to enable sound.
- S16. `features/bills/TableBillCard.tsx:237,280`: a payment error is cleared when the dialog closes.
- S17. `features/bills/api.ts:90`: payment sends the total the waiter saw (S7); on 409 the dialog shows the new total and asks to confirm again.
- S18. `pages/menu/MenuPage.tsx:208`: the cart bar shows a placeholder, not $0.00, while the cart is loading or failed.
- S19. `nginx.conf` (repository root): `gzip on` for text assets, `no-cache` on the entry page, long immutable cache on `/assets`, SSE keeps `gzip off`, security headers unchanged.
- S20. `components/ui/card.tsx`: delete the unused file (verify 0 importers first).

## Tasks

| ID | Specs | Route | Status | Commit |
|---|---|---|---|---|
| T1 | S1-S7 | delegated, parallel with T2 (disjoint repositories, each several minutes) | done, pytest 1246 passed | `e9d18c3`, `e3e5a7f`, `072ac88`, `3260d58`, `9e769fd`, `7923322`, `bc6c762` |
| T2 | S8-S20 | delegated, parallel with T1 | done, vitest 469 passed, typecheck, lint and build pass | 11 commits after `0ad411c` |
| T3 | S1-S20 | independent verifier (Risk items 1, 2, 4) | pending | |

## Log

- L1 (2026-11-09, user, first request): "queirmque chesques la app si hay algun error de diseño o en el backend o vunerabildiad y queiro qeu mejroes el disñeo ene l fornt"
- L2 (2026-11-09, user, after the audit report): "corrgie todos"
- L3: Scope read as every defect reported, not only the three High ones. Not included: the backend architecture bends and root Dockerfile user / open `/docs` (audit item 7): a refactor and deployment hardening, deployment being out of scope per CLAUDE.md. Report to the user.
- L4: Forecast about 500 authored lines backend and 350 frontend. The uncommitted `fix/load-hardening` work in `Backend/` stays untouched; its files (`qr_login.py`, `cache.py`) are not in scope here.
