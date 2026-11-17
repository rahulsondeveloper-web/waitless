# WaitLess — Load test (Phase 12)

Tool: [Locust](https://locust.io) — `loadtest/locustfile.py`. The test uses the e2e copy of the demo restaurant
(`e2e-urban-bites`), so real data is never touched.

## Scenario

| User type | Share | What it does |
|---|---|---|
| StorefrontVisitor | 60 % | discovery list (with searches), storefront, menu, website content — every 1–3 s |
| TableGuest | 30 % | follows its table page and places an order (1–3 dishes) every 3–8 s, with an `Idempotency-Key` |
| KitchenScreen | 10 % | polls the active tickets like the kitchen display, every 4–6 s |

At start it signs in once as the owner, seats guests at every free table and joins each table once (table
joins are rate limited per IP, so the guests share those tables).

## Run (17 Nov 2026, development laptop)

Single Uvicorn process with `--reload`, PostgreSQL 18 and Memurai on the same Windows laptop — the slowest
possible setup; production runs 2+ replicas without the reloader.

40 users, 60 seconds, 0 failures:

| Request | Count | Median | 95 % | Max |
|---|---:|---:|---:|---:|
| storefront | 344 | 4 ms | 11 ms | 403 ms |
| menu | 344 | 4 ms | 10 ms | 22 ms |
| website content | 92 | 3 ms | 10 ms | 71 ms |
| discover (search) | 240 | 34 ms | 140 ms | 440 ms |
| table page | 91 | 32 ms | 180 ms | 460 ms |
| place order | 36 | 61 ms | 270 ms | 290 ms |
| kitchen tickets | 47 | 39 ms | 190 ms | 400 ms |
| **all** | **1 194** (20 req/s) | **5 ms** | **72 ms** | 460 ms |

Storefront and menu are served from the Redis cache (Phase 4), which is why they stay in single-digit
milliseconds. Ordering and the table page do real work (pricing, inventory, timers) and stay well under the
300 ms target at the 95th percentile.

## Run it yourself

```powershell
cd backend
.venv\Scripts\python -m app.cli seed-demo --e2e          # fresh test restaurant
.venv\Scripts\locust -f ..\loadtest\locustfile.py --host http://127.0.0.1:8000 --headless -u 40 -r 10 -t 2m --csv ..\loadtest\results\run
.venv\Scripts\python -m app.cli seed-demo --e2e          # free the tables again
```

Against a staging server use `--host https://staging.example.in` and set `WL_SLUG`, `WL_OWNER`, `WL_PASSWORD`
for a test restaurant there. Raise the API's IP rate limits on staging, or run Locust from several machines,
for tests beyond ~30 table joins.

## Targets for launch

- p95 < 300 ms for ordering and table pages, < 100 ms for cached storefront pages, error rate < 0.5 %.
- Re-run on the production-sized server before launch with 200 users (`-u 200 -r 20 -t 10m`).
