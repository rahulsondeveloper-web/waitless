# WaitLess

**Skip the Wait. Dine Delightfully!** — a multi-tenant restaurant SaaS platform: restaurant discovery, branded storefronts, queues, reservations, ordering with a 15-minute serving promise, kitchen, inventory, billing and SaaS subscriptions.

- Product requirements: [#WAITLESS.md](%23WAITLESS.md)
- Architecture, database, API and plan: [docs/](docs/README.md)

## Repository layout

| Folder | Contents |
|---|---|
| `backend/` | FastAPI app (`app/`), Alembic migrations, tests |
| `frontend/` | Angular 21 app (standalone components, Signals) |
| `docs/` | Planning documents (architecture, ER, API, roles, journeys, plan) |
| `design/` | Brand assets and the default storefront theme (Restaurant Remelle template) |
| `infra/` | Dockerfiles, docker-compose and Nginx for deployment |
| `scripts/` | Developer scripts |

## Local setup (Windows, no Docker)

Prerequisites: Python 3.13, Node 24, PostgreSQL 18 (service), Memurai (service), Git.

```powershell
# 1. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env            # set DB_MIGRATION_PASSWORD (postgres), a random DB_PASSWORD and JWT_SECRET
.\.venv\Scripts\python.exe scripts\create_databases.py        # creates waitless + waitless_test if missing
.\.venv\Scripts\alembic.exe upgrade head                      # dev database (also creates the waitless_app role)
.\.venv\Scripts\alembic.exe -x test=1 upgrade head            # test database
.\.venv\Scripts\python.exe -m app.cli seed                    # permissions, roles, plans (safe to re-run)
.\.venv\Scripts\python.exe -m app.cli create-super-admin --email you@example.com --name "Your Name"   # prompts for password

# 2. Frontend
cd ..\frontend
npm install

# 3. Run everything (API :8000, worker, Angular :4200)
cd ..
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Then open:

- http://localhost:4200 — WaitLess site
- http://localhost:4200/login — sign in (password for restaurants/admin, mobile code for guests)
- http://localhost:4200/register-restaurant — register a restaurant
- http://localhost:4200/super-admin/restaurants — approve / manage restaurants (Super Admin)
- http://localhost:4200/r/urban-bites — storefront shell
- http://localhost:4200/status — live status of database, Redis, worker and Socket.IO
- http://localhost:8000/api/docs — Swagger

## Tests

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest              # unit + DB integration tests
cd frontend; npm run test:ci                                    # Angular unit tests (Vitest)
cd frontend; npm run e2e                                        # Playwright, uses installed Microsoft Edge
```
