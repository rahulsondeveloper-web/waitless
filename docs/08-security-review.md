# WaitLess — Security review (Phase 12)

Scope: the FastAPI backend, the Angular frontend, the PostgreSQL schema, the production Docker/Nginx setup.
Method: OWASP Top 10 (2021) walk-through of the code and configuration, an automated tenant-isolation suite,
dependency audits, and fixes for everything found. Status as of 17 Nov 2026.

## Summary

| Result | |
|---|---|
| Findings fixed in this review | 7 (see "Fixed in Phase 12") |
| Open high/critical findings | none |
| Dependency audit | `pip-audit -r requirements.txt`: no known vulnerabilities · `npm audit --omit=dev`: 0 |
| Tenant-isolation suite | `tests/integration/test_isolation_sweep.py` (catalogue, database and API level) + `test_tenant_isolation.py` (Phase 2), green |
| Recommended before launch | external penetration test; Razorpay, MSG91/Twilio and AWS keys stored only in the server's env file |

## OWASP Top 10 (2021)

| # | Risk | How WaitLess handles it | Evidence |
|---|---|---|---|
| A01 | Broken access control | Every staff route checks a permission **and** the branch (`require_permission`, `can_act_in_branch`). Tenant data is isolated by PostgreSQL Row-Level Security: the app connects as a non-owner role without `BYPASSRLS`; every table with a `tenant_id` has RLS **enabled and forced** (now also SaaS invoices, payments, support tickets, audit log). Guests use short-lived, PIN-bound table tokens. Super Admin routes require `is_super_admin`. | `test_isolation_sweep.py` (3 levels), `test_tenant_isolation.py`, `test_operations.py`, permission tests in every phase |
| A02 | Cryptographic failures | Passwords: Argon2. OTPs and table PINs stored as HMAC hashes, compared in constant time. JWT HS256 with a ≥32-char secret (enforced in production). TLS 1.2/1.3 only, HSTS one year. Refresh token in an `HttpOnly; Secure; SameSite=Strict` cookie. Card data never touches WaitLess (Razorpay checkout). | `core/security.py`, `config._production_safety`, `nginx/default.conf.template` |
| A03 | Injection | SQLAlchemy with bound parameters everywhere; the only literal SQL fragment (report time zones) is validated against a strict character set. Pydantic validates every request body; templates use Angular's auto-escaping (no `innerHTML`). | `services/analytics._zone_literal` |
| A04 | Insecure design | Money only from the server: orders priced server-side, bills recomputed, payments confirmed **only** by signature-verified webhooks, idempotency keys on every paying action, unique keys against double billing/deduction, immutable ledgers (stock movements, invoices, audit log). Limits on discounts/refunds for non-owners. | Phases 7–10 acceptance tests |
| A05 | Security misconfiguration | Production refuses to start with development defaults (JWT secret, DB password, mock payments, localhost CORS, console SMS, missing S3/Maps keys). API docs off in production. Narrow CORS (methods and headers listed). Security headers on every API response; CSP, HSTS, frame-ancestors none on the SPA. Images contain no `.env`, tests or uploads. `/api/v1/metrics` needs a token and is blocked at Nginx. | `test_integrations.py::test_production_refuses_development_defaults`, `::test_security_headers_and_metrics` |
| A06 | Vulnerable components | Pinned major versions; audits clean today. Re-run `pip-audit` and `npm audit --omit=dev` before every release (release checklist). | this document |
| A07 | Identification & authentication | Per-account and per-IP limits on password sign-in; OTP: 3 sends / 10 min per phone, 5 attempts per code, 5-minute expiry; table PIN: 5 tries / 15 min per code and 30 per IP; Nginx adds 10 requests/min on `/api/v1/auth/`. Refresh tokens rotate and are revoked on reuse/logout. | `test_auth*.py`, `test_orders.py::test_pin_attempts_are_limited` |
| A08 | Software & data integrity | Webhooks: HMAC over the raw body, replay-safe (idempotent on provider order id). Database triggers make invoices, the stock ledger, order timers and the audit log append-only. | `test_billing.py`, `test_inventory.py`, `test_sla.py`, `test_database.py` |
| A09 | Logging & monitoring | JSON logs with request IDs; every sensitive change audited (who, what, before/after, IP) and searchable in Super Admin → Audit log. Phone numbers masked in logs; OTP codes never logged in production. Prometheus metrics + alert rules; Loki for logs. | `infra/monitoring/` |
| A10 | SSRF | The server only calls fixed provider hosts (Razorpay, Nominatim/Google, MSG91/Twilio/Meta, S3); no user-supplied URLs are fetched. Uploads are decoded and re-encoded by Pillow (size and type limits), stored under random names. | `integrations/*`, `services/media.py` |

## Fixed in Phase 12

1. **Reports accepted another restaurant's branch id** and returned an empty 200 (RLS already hid the data) — now 404, like every other route. Found by the new API isolation sweep.
2. **Row-Level Security on platform tables**: SaaS invoices, SaaS payments, support tickets and the audit log carry a `tenant_id` but were only protected by code paths; now forced RLS (migration 0012). `refresh_tokens` and `outbox_events` remain system-only internals (documented exemption, checked by the catalogue test).
3. **Production start-up guard** extended from the JWT secret to all dangerous defaults (see A05).
4. **API docs (`/api/docs`, OpenAPI) disabled in production** unless `API_DOCS=true`.
5. **CORS narrowed** from `*` methods/headers to the ones the app uses.
6. **Security headers** on API responses (`nosniff`, `DENY` framing, referrer policy, permissions policy, `no-store` caching) and a full CSP/HSTS on the SPA through Nginx.
7. **Compose ran PostgreSQL with the app user as the database owner** (which bypasses RLS). The production stack now uses a separate owner for migrations and the non-owner app role at runtime.

## Residual risks & recommendations

| Risk | Mitigation / next step |
|---|---|
| The access token lives in browser memory; an XSS bug could use it while the tab is open | Strict CSP (no inline scripts), Angular escaping, no `innerHTML`; keep the CSP when adding scripts |
| `style-src 'unsafe-inline'` is needed by Angular Material | Acceptable (no script execution); revisit if Material adds nonce support |
| WhatsApp business-initiated messages need approved templates outside the 24-hour window | Configure templates in Meta; failures are logged and never break the request |
| Single PostgreSQL instance | Nightly dumps (+ S3 copy, 14 days); for high availability use a managed PostgreSQL with point-in-time recovery |
| No WAF / DDoS protection beyond Nginx rate limits | Put Cloudflare (or AWS WAF) in front when traffic grows |
| Super Admin accounts are password-only | Add TOTP two-factor for Super Admins before onboarding many restaurants |

## How to re-run

```powershell
cd backend
.venv\Scripts\python -m pytest tests/integration/test_isolation_sweep.py tests/integration/test_tenant_isolation.py tests/unit/test_integrations.py -q
.venv\Scripts\pip-audit -r requirements.txt
cd ..\frontend; npm audit --omit=dev
```
