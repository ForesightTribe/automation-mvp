#!/usr/bin/env bash
# Foresight scraper VM — step 1: system setup.
# Ubuntu 24.04 LTS on GCP (asia-south1 / Mumbai). Run as the normal login user.
#   bash vm-01-system.sh
set -euo pipefail

echo "==> Timezone -> Asia/Kolkata (cloud images default to UTC, which would"
echo "    shift every scraper's 'today' and cron schedule by 5h30m)"
sudo timedatectl set-timezone Asia/Kolkata

echo "==> Swap: 2G"
# GCP images ship with zero swap. Chromium spikes hard, and with no swap the
# kernel OOM-killer terminates it outright -- which on a headless box looks
# like a scraper that silently vanished mid-run.
if swapon --show | grep -q '/swapfile'; then
    echo "    already present, skipping"
else
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> System packages"
sudo apt-get update -qq
sudo apt-get install -y software-properties-common curl git ca-certificates

echo "==> Python 3.11"
# Ubuntu 24.04 ships 3.12, but local dev and Render both run 3.11.9 -- keep the
# three environments on the same interpreter.
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update -qq
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

echo "==> SSH key for GitHub"
if [ -f ~/.ssh/id_ed25519 ]; then
    echo "    already present, skipping"
else
    ssh-keygen -t ed25519 -C "foresight-vm" -f ~/.ssh/id_ed25519 -N ""
fi

cat <<'EOF'

--------------------------------------------------------------------
 Step 1 done.

 Next: authorise this box to clone the repo.
   1. Copy the public key printed below.
   2. GitHub -> ForesightTribe/automation-mvp -> Settings -> Deploy keys
      -> Add deploy key. Title "foresight-vm". Leave write access OFF.
   3. Verify:  ssh -T git@github.com   (expect "successfully authenticated")
   4. Then run: bash vm-02-app.sh
--------------------------------------------------------------------

EOF
cat ~/.ssh/id_ed25519.pub
echo
