# Setup Guide

## Prerequisites

| Tool | Version | Download |
|------|---------|----------|
| Python | 3.11+ | https://python.org/downloads |
| Node.js | 18+ | https://nodejs.org |
| MongoDB | 7+ | https://www.mongodb.com/try/download/community |
| Git | any | https://git-scm.com |

---

## 1. Backend Setup

### Step 1 — Create a virtual environment

The virtual environment keeps project dependencies isolated from your system Python.
Always create it inside the `backend/` folder.

**Windows (PowerShell)**
```powershell
cd backend
python -m venv .venv
```

**Mac / Linux**
```bash
cd backend
python3 -m venv .venv
```

---

### Step 2 — Activate the virtual environment

You must activate the venv every time you open a new terminal session.

**Windows (PowerShell)**
```powershell
.venv\Scripts\Activate.ps1
```

> If you see an error about execution policy, run this first:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then try activating again.

**Windows (Command Prompt)**
```cmd
.venv\Scripts\activate.bat
```

**Mac / Linux**
```bash
source .venv/bin/activate
```

When activated, your terminal prompt will show `(.venv)` at the start.

---

### Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

---

### Step 4 — Install Playwright browsers

Playwright needs to download the actual browser binaries separately.

```bash
playwright install chromium
```

---

### Step 5 — Set up environment variables

```bash
# Copy the example file
cp .env.example .env        # Mac/Linux
copy .env.example .env      # Windows
```

Open `.env` and fill in the values:

```env
MONGODB_URL=mongodb://localhost:27017
DB_NAME=foresight

# Generate ENCRYPTION_KEY — run this in your terminal:
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=paste-generated-key-here

# Generate SECRET_KEY — run this in your terminal:
# python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=paste-generated-key-here
```

---

### Step 6 — Start MongoDB

Make sure MongoDB is running locally before starting the backend.

**Windows** — MongoDB runs as a Windows Service after installation. Check Services or run:
```powershell
net start MongoDB
```

**Mac (with Homebrew)**
```bash
brew services start mongodb-community
```

---

### Step 7 — Run the backend server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.  
Interactive docs (Swagger UI) at `http://localhost:8000/docs`.

---

## 2. Frontend Setup

Open a separate terminal in the `frontend/` folder.

### Step 1 — Install Node dependencies

```bash
cd frontend
npm install
```

---

### Step 2 — Set up environment variables

Create a `.env.local` file in the `frontend/` folder:

```env
VITE_API_URL=http://localhost:8000/api
```

---

### Step 3 — Run the dev server

```bash
npm run dev
```

The app will be available at `http://localhost:5173`.

---

## 3. Fix Squiggly Lines in VS Code

Squiggly lines under imports (e.g. `from fastapi import ...`) appear because VS Code's
Python language server (Pylance) doesn't know which Python interpreter to use — it defaults
to your system Python, which doesn't have the project's packages installed.

### Fix: Point VS Code to the venv interpreter

1. Open the Command Palette: `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)
2. Type **"Python: Select Interpreter"** and select it
3. You'll see a list of available interpreters. Choose the one that shows:
   - **Windows:** `Python 3.x.x ('.venv': venv) .\backend\.venv\Scripts\python.exe`
   - **Mac/Linux:** `Python 3.x.x ('.venv': venv) ./backend/.venv/bin/python`

If the venv doesn't appear in the list, click **"Enter interpreter path..."** and paste the path manually:
- **Windows:** `backend\.venv\Scripts\python.exe`
- **Mac/Linux:** `backend/.venv/bin/python`

### Why this works

VS Code uses the selected interpreter to resolve import paths. When pointed to the `.venv`,
Pylance can find all installed packages (fastapi, beanie, loguru, etc.) and the squiggles disappear.

### Tip: Open VS Code from the `backend/` folder

If you open VS Code directly inside `backend/` (not the root), VS Code will automatically
detect the `.venv` folder and select the correct interpreter without any manual steps.

```bash
cd backend
code .
```

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `.venv\Scripts\Activate.ps1` | Activate venv (Windows PS) |
| `source .venv/bin/activate` | Activate venv (Mac/Linux) |
| `deactivate` | Deactivate venv |
| `pip install -r requirements.txt` | Install/update backend deps |
| `uvicorn app.main:app --reload` | Start backend with hot reload |
| `npm run dev` | Start frontend dev server |
| `playwright install chromium` | Download Playwright browser |
