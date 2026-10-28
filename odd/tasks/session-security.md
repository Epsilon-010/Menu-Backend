# Session security (H13)
Objective: close H13 — sessions surviving a credential change, and third-party account lockout.
Branch: `fix/session-security` (Backend) + `fix/forward-client-ip` (Menu-Frontend). Delivery: single PR per repo.
Test runner: `uv run pytest` (Backend), `npm test` (Menu-Frontend).

## Specs
- S1. "si alguien cambia de codigo para las mesas que expiren las sesiones de esa mesa": regenerating a table's
  PIN (the code never changes) or deactivating it ends every session of that table, including a refresh that was
  in flight at the same moment. Same rule for staff: password reset, role change and deactivation (the same race,
  agreed as H13 point 1).
  - Mechanism: `session_version` on tables and users, bumped on each of those changes; refresh tokens and access
    tokens carry the version they were issued for and are rejected once it is stale (refresh: compared with the
    row; access: compared with a Redis floor written after the commit, fail-open as before).
- S2. "en la 2 que sea por ip y cuenta": login attempts are limited per client IP + account
  (`LOGIN_MAX_FAILURES_PER_CLIENT`, default 5), so failures from one device no longer lock the account for others.
  A higher per-account backstop (`LOGIN_MAX_FAILURES_BACKSTOP`, default 50; renamed from the old per-account setting so an old value of 5 cannot silently undo S2) keeps a spoofed or rotating IP from
  turning it into unlimited guessing (proposed as option (b), accepted: "si hazlo").
  - The client IP is only taken from `X-Forwarded-For` when the request comes from the frontend proxy
    (uvicorn `FORWARDED_ALLOW_IPS`); a direct request to the API port cannot choose its IP.

## Tasks
- [x] T1 (S1) inline — session versions: migration `75e13c35bff4`, entities, tokens, refresh check, access floor, use
  cases. RED: escaped refresh token and post-change access token both answered 200; GREEN: 401.
- [x] T2 (S2) inline — per-client limiter, client IP, proxy trust (compose fixed frontend IP + Vite `xfwd`), docs.
  RED: per-device tests failed on the old per-account limiter; GREEN.
- [x] T3 independent verifier (risk items 1, 2, 4): S1 PASS, S2 blocker B1 fixed (`cfda726`), recheck PASS.
- [x] T4 native review (risk, resilience, reliability) approved and acknowledged; advisories fixed in the next commit.

## Log
- L1 (2026-10-27): "en la 1 si si alguien cambia de codigo para las mesas que expiren las sesiones de esa mesa en la 2
  que sea por ip y cuenta pero el progrma sera interno asi que no veo que mas ips lo ataquen por lo que pues si hazlo"
- L2: Row locks in the refresh were rejected (refresh locks the token then would lock the table; the PIN change locks
  the table then the tokens: deadlock). Versions close the race without locks.
- L3: Proxy trust: uvicorn's own ProxyHeadersMiddleware (`FORWARDED_ALLOW_IPS`) instead of app code. Compose pins the
  frontend to `10.213.57.10` in `10.213.57.0/24`; the first pick (172.30.57.0/24) overlapped another local project's
  network (`dbinspector_default` 172.30.0.0/16), and Docker hands out 172.17-31/192.168 automatically.
- L4: Success clears only that device's counter, not the account backstop, so a real login does not refill an attacker's
  budget. Access floor is a Redis max (Lua) written after the commit: before it, a failed commit would reject new logins.
- L5: Evidence: `uv run pytest` 303 passed; Menu-Frontend typecheck, lint, 57 tests, build OK. E2E on the dev stack
  (scratch script, not committed) 8/8: host blocked after 5 through Vite while another container still gets 401 on the
  same account; spoofed X-Forwarded-For straight to :8020 ignored (6th is 429); PIN change makes the tablet /me and its
  refresh 401. Once, before a test fix, a full `uv run pytest` hung >600 s with no DB connections; the rerun and every
  later run finished in ~60 s. Not reproduced.
- L6: Verifier (independent): S1 PASS (40 concurrent refresh-vs-PIN rounds, no token escaped; forged `sv` values
  rejected; migration down/up OK). S2 FAIL, blocker B1: attempts refused by the per-client limit still incremented the
  account backstop, so one device retrying 51 times locked every other device out. Fix: one Lua script counts the client
  first and only moves the account counter while the client is within its limit (RED test
  `test_attempts_refused_for_one_device_never_count_towards_the_account`). Advisories fixed too: IPv4-mapped IPv6
  (`::ffff:a.b.c.d`, how requests arrive through Vite) is normalized to IPv4 so a device has one counter; the backstop
  setting is renamed `LOGIN_MAX_FAILURES_BACKSTOP` so an old `LOGIN_MAX_FAILURES_PER_ACCOUNT=5` is ignored instead of
  silently undoing S2. Known limit (environment, not code): on Docker Desktop (Windows/macOS) every request through a
  published port reaches the containers from the Docker gateway (10.213.57.1), so LAN tablets in dev share one device
  counter; a Linux Docker host keeps the real client IP. Accepted advisories: the backstop also counts successful
  logins; fail-open access floor if Redis is down; production nginx not exercised. `uv run pytest` 305 passed.
- L7: Native review approved (lineage review-69f90032906d2f20), 3 informational findings: a stale write could lower
  session_version (now `GREATEST` in both repositories, test `test_a_stale_write_never_lowers_a_session_version`); the `sv`
  validation had no test (now 6 cases in `test_me_rejects_invalid_access_tokens`); deploy cutover (tokens without `sv` get
  one 401 and the frontend refreshes: accepted). Frontend review approved; its finding (lost `changeOrigin`) fixed in
  `ce4c1c2`. `uv run pytest` 312 passed.
- L8 (2026-10-27, user): "si arregla el 4 y ya has push de lo qeu llevamos abrire otra sesion". Advisory 4 fixed: a
  successful login takes its own attempt back from the account backstop (Lua, never below 0), so a device that signs in
  often is never blocked (test `test_successful_logins_never_count_towards_the_account_backstop`). 313 passed. Next: the
  user opens the PRs (`fix/session-security`, `fix/forward-client-ip`) and merges; Slice 5 only when the user asks.
