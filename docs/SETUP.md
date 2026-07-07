# Setup Guide

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ (frontend only) |
| Git | any |

No local database needed — PostgreSQL is hosted on Supabase.

---

## 1. Backend

### Create virtual environment

Run from inside `automation-mvp/backend/`.

```powershell
# Windows (PowerShell)
python -m venv .venv
```

```bash
# Mac / Linux
python3 -m venv .venv
```

### Activate

```powershell
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

> If you get an execution policy error:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then activate again.

```bash
# Mac / Linux
source .venv/bin/activate
```

Prompt shows `(.venv)` when active. You must activate every new terminal session.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Install Playwright browser

```bash
playwright install chromium
```

---

## 2. Environment Variables

```bash
cp .env.example .env     # Mac/Linux
copy .env.example .env   # Windows
```

Open `.env` and set these three values:

```env
# Supabase Session Pooler URL — NOT the direct connection URL (direct is IPv6-only)
# Format: postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
DATABASE_URL=postgresql://...

# Fernet encryption key for stored sessions
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=...

# JWT signing secret
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=...
```

---

## 3. Database Setup

Run once to create all tables:

```bash
# from automation-mvp/backend/ with venv active
alembic upgrade head
```

This applies the Alembic migration in `alembic/versions/` and creates the full schema in Supabase.

---

## 4. Run the API Server

Start the FastAPI backend — this serves the REST API the frontend calls.

```bash
# from automation-mvp/backend/ with venv active
uvicorn app.main:app --reload --port 8000
```

- `--reload` auto-restarts on code changes (development only).
- **API base:** http://localhost:8000/api
- **Swagger UI (interactive docs):** http://localhost:8000/docs — lists every endpoint and lets you fire real requests from the browser.
- **OpenAPI spec:** http://localhost:8000/openapi.json

### Calling protected endpoints from Swagger

Most endpoints need a logged-in user:

1. Create an account + admin login (see First Run below).
2. `POST /api/auth/login` with that email/password → copy the `access_token` from the response.
3. Click **Authorize** (top-right in `/docs`), paste the token (Swagger adds the `Bearer ` prefix automatically), Authorize.
4. **Try it out** now works on the `/clients/{client_id}/...` endpoints.

> The server only serves the API. The scrapers below are separate CLI commands and don't need the server running.

---

## 5. First Run

### Create an account + admin login

Accounts and users are provisioned via the CLI — there is no public signup.

```bash
python -m cli account create --name "Foresight" --admin-email you@example.com
#    Prompts for a password; creates the Account + its first admin User.
#    Log in with this email/password at the dashboard (the landing-page modal),
#    or directly at POST /api/auth/login.
```

### Add more users to an account

Teammates are added to an existing account so they can see all of its clients'
data. Default role is `member`; pass `--admin` for an admin.

```bash
python -m cli account list                       # find the account UUID
python -m cli account add-user --account <account-id> --email teammate@example.com --name "Teammate"
#    Prompts for a password. Add --admin to grant Settings/admin access.
```

**Roles & data scope:** data is **account-scoped** — every user under an account
sees all of its clients. `member` vs `admin` only gates the Settings/admin UI,
not the data. Identity + role are baked into the JWT at login, so a newly added
user just logs in fresh, and a role change takes effect on that user's next login.

### Public scraper — no login needed

Config-driven (Blinkit only). Fill `config.xlsx`, sync it, then run per tenant:

```bash
python -m cli sync --file config.xlsx                 # locations + watchlist (+ keyword_cap/brand_cap) + coverage → DB
python -m cli scrape public-run   --tenant <id>       # keyword scrape: SoV/rank + competitors → search_snapshots/listings
python -m cli scrape public-skus  --tenant <id>       # targeted own-SKU scrape: price/stock/inventory → sku_snapshots

# ad-hoc single scrape (quick check); --save needs --tenant
python -m cli scrape public --keyword "cola" --brand "dobra" --platform blinkit --city delhi
```

`public-run` and `public-skus` are independent (separate `scrape_job`s, separate
tables) — run them on their own cadences. Both take `--resume` and `--workers N`.

Brand and marketplace rows are created automatically (`ensure_refs`). No manual seeding.

### Private scrapers — requires a client + seller login

```bash
# 1. Create a client (tenant) UNDER your account
python -m cli tenant create --name "My Brand" --account <account-id>
#    Prints a client UUID — copy it for the commands below.

# 2. Authenticate (browser opens)
python -m cli auth blinkit --tenant <client-uuid>           # marketing dashboard
python -m cli auth blinkit-seller --tenant <client-uuid>    # seller dashboard

# 3. Scrape
python -m cli scrape blinkit --tenant <client-uuid>
python -m cli scrape blinkit-seller --tenant <client-uuid>
```

---

## 6. VS Code — Fix Import Squiggles

1. Open Command Palette: `Ctrl+Shift+P`
2. Select **Python: Select Interpreter**
3. Choose the `.venv` entry:
   - Windows: `.\backend\.venv\Scripts\python.exe`
   - Mac/Linux: `./backend/.venv/bin/python`

Tip: open VS Code from inside `backend/` and it auto-detects the venv.

---

## 7. Frontend (optional)

```bash
cd automation-mvp/frontend
npm install
```

Create `frontend/.env.local`:

```env
VITE_API_URL=http://localhost:8000/api
```

```bash
npm run dev   # → http://localhost:5173
```

---

## Quick Reference

| Command | What it does |
|---|---|
| `.venv\Scripts\Activate.ps1` | Activate venv (Windows PS) |
| `source .venv/bin/activate` | Activate venv (Mac/Linux) |
| `alembic upgrade head` | Apply all migrations |
| `alembic revision --autogenerate -m "msg"` | Generate migration after model change |
| `uvicorn app.main:app --reload --port 8000` | Start the API server (Swagger at `/docs`) |
| `python -m cli account create --name N --admin-email E` | Create an account + admin login |
| `python -m cli account add-user --account ID --email E` | Add a user to an existing account (`--admin` for admin) |
| `python -m cli --help` | Show CLI commands |
| `playwright install chromium` | Download Playwright browser |
