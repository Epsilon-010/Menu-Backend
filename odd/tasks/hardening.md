# Hardening — idempotent operations and every open advisory closed
Objective: no known defect left open, however small; every write operation safe to retry.
Branch: `feat/image-cleanup` (Backend) and `feat/redesign` (Menu-Frontend). Delivery: ask-on-risk. Runner: `uv run pytest` (Backend), `npm test && npm run typecheck && npm run lint && npm run build` (Menu-Frontend).

## Specs
- S1 Rule (L1, verbatim): "arregla lo de los duplicadops y recuerda matneer la impotracina de operaciones de ideptencia y quita eso de duplicados no vayas dejando erroes aunqeu sean por ams pequeño o ai debe de ir todo bien si no alf final todos esos erroes los perderemos y se quedaran ahi"
- S2 Idempotent creates: `POST /catalog/categories`, `/catalog/items`, `/tables`, `/staff` accept an optional client UUID `id`. The same request again returns the existing resource (same tenant, same data); the same id with other data or from another tenant answers 409 without revealing anything. The primary key is the guarantee (no Redis, no crash window). Tables: a replay cannot show the PIN again (only its hash exists), so it answers 409 asking for a new PIN. The frontend keeps one id per form until the create succeeds.
- S3 UI outcomes: a change that succeeded but whose reload failed is a success (form cleared, separate notice); deleting something already gone counts as done.
- S4 Concurrency on items (verifier A1, A2): every item write reads the row `FOR UPDATE`; no lost update can resurrect or orphan an image.
- S5 Image registry (A3, A4, A5): a rejected upload is discarded only while `pending`; deleting a tenant cannot drop untracked images (FK RESTRICT); failed deletes back off per row instead of blocking the queue.
- S6 Every other open advisory of Slices 4/redesign/cleanup (listed in Tasks), plus the earlier slices' advisories with a clear fix.

## Tasks
- [x] H1 (S2) Idempotent creates: catalog categories/items, tables, staff (backend; frontend ids in H10) — inline — RED 7 catalog + 2 collection errors; GREEN — see L4
- [ ] H2 (S3) Frontend: "saved but not refreshed" is success; delete of a missing row is done
- [x] H3 (S4) Row locks (get_for_update) in every read-then-write use case of catalog, tables and staff — inline — RED 3 lock tests; GREEN — see L4
- [x] H4 (S5) Reject discards only pending; FK RESTRICT on image_uploads.tenant_id; per-row retry backoff (new migration) — inline — tests written first but RED not run before the code; GREEN 244 passed; migration e5be48d96257
- [ ] H5 (S6) NUL characters in any text field -> 422, not 500 (all modules)
- [x] H6 (S6) UPDATE/DELETE that hit no row -> not-found error (catalog, tables, staff) via ffected_rows — inline — see L4
- [x] H7 (S6) Order locks (pg_advisory_xact_lock per tenant / per category) for create, move, delete, reorder; partial reorder -> 422 — inline — see L4
- [ ] H8 (S6) Schema 422s carry a readable `detail` as well as `errors`
- [ ] H9 (S6) `extra="forbid"` on staff and tables input schemas
- [ ] H10 (S6) Frontend: request timeout in the HTTP client; sign-out button display on phones; shared row-action hook; one money formatter; credential format constants shared by login; tests for the catalog change runner
- [ ] H11 (S6, Slice 3) Two creates drawing the same table code -> retry, never 500; limiter keys of table and staff logins can never collide
- [ ] H12 (S6, Slice 1) Expired and revoked refresh tokens are purged periodically (Celery beat)
- [ ] H13 Needs user decision: refresh in flight during a PIN regeneration/password reset may survive; account lockout by third parties (limit is per account)
- [ ] H14 Independent verification

## Log
- L1 (2026-10-27, user): "arregla lo de los duplicadops y recuerda matneer la impotracina de operaciones de ideptencia y quita eso de duplicados no vayas dejando erroes aunqeu sean por ams pequeño o ai debe de ir todo bien si no alf final todos esos erroes los perderemos y se quedaran ahi"
- L2 (2026-10-27, decision): idempotency by client-supplied resource id (primary key guarantee) instead of an `Idempotency-Key` header in Redis, which still duplicates if the process dies between commit and storing the response.
- L3 (evidence, 2026-10-27): image-cleanup verifier: S1-S6 PASS, no blockers; advisories A1-A5 (above) reproduced with a race probe on `menu_test`; scratch removed by the parent.
- L4 (evidence, 2026-10-27): creates accept an optional client id; the replay check runs after the order lock, so concurrent replays serialize; a clash (other data or another tenant) answers 409 "That id is already used by something else"; tables answer 409 "This table was already created; generate a new PIN to see its credentials" (the PIN cannot be shown twice); primary-key violations map to the same 409. Every read-then-write uses get_for_update; moves and deletes of items take the order lock before the row lock (same order as reorder, no deadlock). Integration tests in 	ests/integration/modules/catalog/test_catalog_concurrency.py use repositories that pause after each read; with the locks disabled by monkeypatch all 4 fail (lost category edit, shared positions, duplicate creates, stale image written back), with them all pass. `uv run pytest`: 263 passed + tables/staff API tests (42 passed).
