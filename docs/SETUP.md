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

## 4. First Run

### Public scraper — no login needed

```bash
# Dry run — print results, no DB write
python -m cli scrape public --keyword "cola" --brand "dobra" --platform blinkit

# Save to DB
python -m cli scrape public --keyword "cola" --brand "dobra" --platform blinkit --save
```

Brand and marketplace rows are created automatically on first `--save`. No manual seeding.

### Private scrapers — requires seller login

```bash
# 1. Create a tenant
python -m cli tenant create --name "My Brand"
#    Prints a UUID — copy it for use in all subsequent commands

# 2. Authenticate (browser opens)
python -m cli auth blinkit --tenant <uuid>           # marketing dashboard
python -m cli auth blinkit-seller --tenant <uuid>    # seller dashboard

# 3. Scrape
python -m cli scrape blinkit --tenant <uuid>
python -m cli scrape blinkit-seller --tenant <uuid>
```

---

## 5. VS Code — Fix Import Squiggles

1. Open Command Palette: `Ctrl+Shift+P`
2. Select **Python: Select Interpreter**
3. Choose the `.venv` entry:
   - Windows: `.\backend\.venv\Scripts\python.exe`
   - Mac/Linux: `./backend/.venv/bin/python`

Tip: open VS Code from inside `backend/` and it auto-detects the venv.

---

## 6. Frontend (optional)

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
| `python -m cli --help` | Show CLI commands |
| `playwright install chromium` | Download Playwright browser |
