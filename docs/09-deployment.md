# WaitLess — Deployment & operations (Phase 12)

The production stack is one Docker Compose project: PostgreSQL 18, Redis 7, the API (2+ replicas), the worker,
Nginx (TLS, the Angular app, proxy), Certbot (Let's Encrypt), and nightly backups. Optional: Prometheus, Loki,
Promtail and Grafana. Local Windows development stays Docker-free (decision D24).

## 1. Server

- Ubuntu 24.04 LTS, 2 vCPU / 4 GB RAM to start (handles the load test below many times over), 40 GB disk.
- Docker Engine 27+ with the Compose plugin. Firewall: allow 22 (SSH, your IP only), 80, 443.
- DNS: an `A` record for your domain (e.g. `app.waitless.in`) pointing at the server.
- Recommended: an S3 bucket for media behind CloudFront, a second bucket for backups (versioned, SSE on).

## 2. First deployment

```bash
git clone https://github.com/rahulsondeveloper-web/waitless.git && cd waitless
cp infra/env/production.env.example infra/env/production.env
nano infra/env/production.env          # replace every CHANGE_ME (see table below)
docker compose -f infra/docker-compose.yml --env-file infra/env/production.env up -d --build
docker compose -f infra/docker-compose.yml --env-file infra/env/production.env logs -f migrate certbot
```

What happens: `migrate` runs `alembic upgrade head` (creating the non-owner app role) and syncs reference
data; the API and worker start; Nginx starts with a temporary self-signed certificate, Certbot obtains the real
one over HTTP, and Nginx switches to it within 6 hours (or run `docker compose … exec web nginx -s reload`
after the certificate appears).

Then create your Super Admin:

```bash
docker compose -f infra/docker-compose.yml --env-file infra/env/production.env exec api \
  python -m app.cli create-super-admin --email you@yourcompany.in --name "Your Name" --password '…'
```

### Settings that must be set

| Setting | Where to get it |
|---|---|
| `DOMAIN`, `ACME_EMAIL`, `PUBLIC_BASE_URL`, `CORS_ORIGINS` | your domain |
| `DB_MIGRATION_PASSWORD`, `DB_PASSWORD`, `JWT_SECRET`, `METRICS_TOKEN` | generate: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CASHFREE_APP_ID` / `CASHFREE_SECRET_KEY` / `CASHFREE_ENV=production` | Cashfree Dashboard → Developers → API Keys (production keys after KYC). Webhooks → URL `https://DOMAIN/api/v1/webhooks/payments/cashfree`, version 2023-08-01, events *Payment success / failed / user dropped* (orders also carry this `notify_url`). Whitelist the domain in Cashfree → Developers → Whitelisting. |
| `S3_*`, `AWS_*`, `MEDIA_HOST` | AWS: bucket + IAM user/role with `s3:PutObject`, `s3:DeleteObject` on `arn:aws:s3:::BUCKET/media/*`; CloudFront distribution URL |
| `MAPS_PROVIDER=google`, `GOOGLE_MAPS_API_KEY` | Google Cloud → Geocoding API key restricted to the server's IP |
| `SMS_PROVIDER=msg91`, `MSG91_*` | MSG91 + a DLT-approved OTP template (India); or `twilio` |
| `WHATSAPP_PROVIDER`, `META_*` / `TWILIO_*` | Meta WhatsApp Cloud API (phone number id + permanent token) |
| `EMAIL_PROVIDER=smtp`, `SMTP_*` | Amazon SES / any SMTP provider |

The API **refuses to start** if a production setting is unsafe and prints the list — fix and restart.

## 3. Updates

```bash
git pull
docker compose -f infra/docker-compose.yml --env-file infra/env/production.env up -d --build
```

`migrate` runs again automatically before the new API starts. Migrations are additive; for a rollback use the
previous image tag (`WAITLESS_VERSION`) **and** restore the backup taken just before (migrations are not
designed to be downgraded in production). Take a manual backup first: `docker compose … run --rm backup once`.

## 4. Backups & restore

- The `backup` service dumps PostgreSQL nightly (`BACKUP_AT`, default 02:30) in custom format, verifies the
  archive, archives uploaded media (local storage), keeps `BACKUP_KEEP_DAYS` (14) and copies to `BACKUP_S3_URI`.
- Manual backup now: `docker compose -f infra/docker-compose.yml --env-file infra/env/production.env run --rm backup once`
- Restore (stop the API and worker first):

```bash
docker compose … stop api worker
docker compose … exec postgres sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB" /backups/db-YYYYMMDD-HHMMSS.dump'
docker compose … up -d
```

  (mount the backups volume into `postgres`, or `docker cp` the file in.) **Practise a restore once a month**
  on a spare server — an untested backup is not a backup.
- Development (Windows): `.\scripts\backup.ps1` → `backups\`, and `.\scripts\backup.ps1 -Restore <file>`.

## 5. Monitoring

```bash
echo "$METRICS_TOKEN" > infra/monitoring/metrics-token
GRAFANA_ADMIN_PASSWORD='…' docker compose -f infra/docker-compose.yml -f infra/monitoring/docker-compose.monitoring.yml \
  --env-file infra/env/production.env up -d
ssh -L 3000:127.0.0.1:3000 you@server     # then open http://localhost:3000
```

- **Metrics**: every API replica exposes request counts by status class, a latency histogram and uptime at
  `/api/v1/metrics` (token required; blocked at Nginx). Alerts (`infra/monitoring/alerts.yml`): replica down,
  >2 % 5xx, p95 > 1 s, restarts.
- **Logs**: JSON logs (`LOG_JSON=true`) with `request_id` (also returned as the `X-Request-ID` header — ask
  users for it in support tickets) shipped by Promtail to Loki. Docker rotates local logs (5 × 20 MB).
- **Health**: `GET /api/v1/health` — database, Redis and worker heartbeat (the worker writes one every 30 s).
  Point an external uptime monitor (e.g. UptimeRobot) at `https://DOMAIN/api/v1/health`.

## 6. Scaling

- API: raise `API_REPLICAS`; Socket.IO rooms are shared through Redis and Nginx keeps each browser on one
  replica (`ip_hash`). Keep **one** worker (jobs are also protected by Redis locks).
- Database connections: `DB_POOL_SIZE` × replicas + worker must stay below `max_connections` (200).
- Media: with S3 + CloudFront, Nginx and the API never serve images.

## 7. Runbook

| Symptom | Check | Fix |
|---|---|---|
| Site down | `docker compose … ps`; `logs web api` | restart the failing service; check disk (`df -h`) |
| API restarts in a loop with "Unsafe production settings" | the log line lists what is missing | fix `production.env`, `up -d` |
| Payments stay "pending" | Cashfree dashboard → Developers → Webhooks → delivery log; `logs api \| grep webhook` | webhook URL/secret; payments are confirmed only by the webhook |
| Guests don't get sign-in codes | `logs api \| grep OTP` | provider balance / DLT template; codes are never shown in production |
| Timers or renewals not moving | `GET /api/v1/health` → worker heartbeat | `restart worker` |
| Certificate expired | `logs certbot` | port 80 reachable? `docker compose … restart certbot web` |

## 8. Release checklist

1. All tests green: backend `pytest`, frontend `ng test`, `npx playwright test` (desktop + mobile).
2. `pip-audit -r backend/requirements.txt` and `npm audit --omit=dev` clean.
3. `ng build --configuration production` without errors.
4. Backup taken; migration reviewed (`alembic upgrade head --sql` for the new revisions).
5. Deploy; watch `logs migrate api` and the Grafana error-rate panel for 15 minutes.
6. Smoke test: storefront, sign-in by OTP, order → kitchen → bill → online payment (₹1 test on live keys), receipt PDF.
