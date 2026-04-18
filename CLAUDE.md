# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Skanorder — SaaS QR-ordering platform for restaurants (FastAPI backend + vanilla HTML/CSS/JS frontend). Production-deployed on Railway. The directory is named `phonorder` but the product is **Skanorder**.

## Commands

Run locally:
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Seed dev data: `python seed.py`

Production start (Railway, from `railway.toml`): `uvicorn main:app --host 0.0.0.0 --port $PORT`

There is no test suite, linter, or formatter configured. Do not add one unless asked.

## Architecture

**Monolithic FastAPI app.** Entry point `main.py` wires middleware (CORS, security headers, 10 MB body limit, slowapi 200/min rate limit), runs startup tasks, mounts `/static`, registers HTML routes, and includes every router from `routers/`.

**Database layer (`database.py`)** — single-file SQLAlchemy models. `DATABASE_URL` env var switches SQLite (dev) ↔ PostgreSQL (Railway prod); the `postgres://` → `postgresql://` rewrite is required because Railway's URL format is incompatible with SQLAlchemy 2.x. Models: `User`, `Store`, `StoreStaff`, `Category`, `Product`, `QRCode`, `Order`, `OrderItem`, `Payment`, `Subscription`, `SystemConfig`, `StorePaymentConfig`, `SalesLead`. Enums define role/status state machines.

**Migrations: NO Alembic.** `_run_migrations()` in `main.py:59` runs a hardcoded list of `ALTER TABLE ... ADD COLUMN` statements in try/except on startup. `Base.metadata.create_all()` creates new tables but never alters existing ones. When adding a column to an existing model, also append the `ALTER TABLE` to that list so prod DBs get it.

**Auth** — JWT (`python-jose`) + bcrypt (`passlib`). Roles: `superadmin`, `admin` (owner), `staff`. `_ensure_superadmin()` on startup upserts a superadmin from `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` env vars. A `/setup/superadmin` endpoint guarded by `X-Setup-Token` header exists as a bootstrap escape hatch.

**`security.py`** — centralizes env loading (`.env` via `python-dotenv`), `SECRET_KEY`, CORS origins, Fernet field-level encryption (for `StorePaymentConfig.credentials`), MercadoPago webhook HMAC verification, and the `SECURITY_HEADERS` dict. In production (`APP_ENV=production`), the app refuses to boot with the default `SECRET_KEY` and rejects unsigned MP webhooks.

**Routers (`routers/`)** — one module per domain: `auth`, `superadmin`, `stores`, `products`, `staff`, `qrcodes`, `orders`, `payments`, `dashboard`, `websocket`, `menu`, `me`, `gateways`, `billing`, `ai_insights` (exports both `router` and `sa_router`), `contact`. All are included in `main.py:104`.

**Route-ordering gotcha** — paths like `/stores/{sid}` will capture sibling literals (e.g. `/stores/sa-ai-insights`) and fail with 422 before reaching the literal handler, because FastAPI matches the pattern before validating the `int` type. Fix by mounting such routes under a different prefix (see `ai_insights.sa_router` → `/superadmin/ai-insights`).

**Payments** — `payments.py` integrates MercadoPago (`mercadopago` SDK) and Transbank Webpay (`transbank-sdk`). Per-store gateway credentials live in `StorePaymentConfig.credentials` (JSON, Fernet-encrypted via `encrypt_field` / `decrypt_field`). Subscriptions use MP preapproval (`mp_preapproval_id`, `mp_preapproval_url` on `Subscription`).

**Frontend** — static HTML/CSS/JS (no build step). `design/` holds the landing (`index.html`) and admin mock; `static/<section>/index.html` holds the real pages served at `/menu`, `/store`, `/shop`, `/track`, `/deliver`, `/register`, `/admin`, `/kitchen`. `websocket.py` pushes live order updates to the kitchen/deliver views.

**AI** — `ai_insights.py` calls Groq's free API (`GROQ_API_KEY`, model `llama-3.1-8b-instant`) for per-store and superadmin dashboards.

**Email** — `email_service.py` wraps Resend (`RESEND_API_KEY`). Domain `skanorder.com` must be verified in Resend to send from `noreply@skanorder.com`.

## Environment variables

Required in production: `SECRET_KEY`, `APP_ENV=production`, `DATABASE_URL`, `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD`, `SETUP_TOKEN`, `CORS_ORIGINS`, `BASE_URL`, `MP_WEBHOOK_SECRET`, `FIELD_ENCRYPTION_KEY` (hex, ≥32 bytes), `GROQ_API_KEY`, `RESEND_API_KEY`.

Docs endpoints (`/docs`, `/redoc`) are disabled when `APP_ENV=production`.
