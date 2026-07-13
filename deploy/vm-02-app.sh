#!/usr/bin/env bash
# Foresight scraper VM — step 2: clone repo, build venv, install Playwright.
# Run only after the deploy key from step 1 is registered on GitHub.
#   bash vm-02-app.sh
set -euo pipefail

REPO_URL="git@github.com:ForesightTribe/automation-mvp.git"
BRANCH="main"
APP_DIR="$HOME/automation-mvp"
BACKEND="$APP_DIR/backend"

echo "==> Verifying GitHub access"
# ssh -T against GitHub always exits 1 even on success, so match the banner.
if ! ssh -T -o StrictHostKeyChecking=accept-new git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo "!! GitHub rejected this box's key. Add ~/.ssh/id_ed25519.pub as a deploy" >&2
    echo "   key on ForesightTribe/automation-mvp, then re-run." >&2
    exit 1
fi

echo "==> Repo ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch origin "$BRANCH"
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

echo "==> Virtualenv + dependencies"
cd "$BACKEND"
[ -d venv ] || python3.11 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Playwright (Chromium)"
# Two separate calls on purpose: the OS libraries need root, but the browser
# binary must be downloaded as the login user. Running the download under sudo
# would put it in root's cache where the scraper (running as this user) can't
# find it -- a confusing "Executable doesn't exist" at scrape time.
sudo ./venv/bin/playwright install-deps chromium
./venv/bin/playwright install chromium

echo "==> Logs directory"
mkdir -p "$BACKEND/logs"

cat <<EOF

--------------------------------------------------------------------
 Step 2 done.

 Remaining: the .env file. It is deliberately not in git, so recreate it
 by hand on this box with the SAME values as local:

   nano $BACKEND/.env

   DATABASE_URL=postgresql://...    # Supabase Session Pooler (:5432, IPv4)
   ENCRYPTION_KEY=...               # MUST match local, or the stored Blinkit
                                    # session cannot be decrypted
   SECRET_KEY=...
   CORS_ORIGINS=["http://localhost:5173"]
   DEBUG=false

 Then smoke-test:
   cd $BACKEND && ./venv/bin/python -m cli auth status --tenant <uuid>
--------------------------------------------------------------------
EOF
