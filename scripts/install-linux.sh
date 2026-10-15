#!/usr/bin/env bash
# Sala de escuta on a Linux server (made for Ubuntu 24.04): code, Python, and a systemd service.
# Run it as the normal user (it calls sudo where needed):
#   curl -fsSL https://raw.githubusercontent.com/NejDev/sala-de-escuta/main/scripts/install-linux.sh | bash
# Running it again updates the code and restarts the panel; data/, .env and playlists.json are kept.
set -euo pipefail

REPO="https://github.com/NejDev/sala-de-escuta.git"
DIR="${SALA_DIR:-$HOME/sala-de-escuta}"
TIME_ZONE="${SALA_TZ:-America/Sao_Paulo}"  # times in messages ("back around 12:07") follow the server clock

echo "==> System packages and time zone ($TIME_ZONE)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3 python3-venv >/dev/null
sudo timedatectl set-timezone "$TIME_ZONE"

# Small free machines (Oracle's E2.1.Micro has 1 GB): 2 GB of swap keeps apt and pip from running out of memory.
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 2000000 ] && ! swapon --show | grep -q .; then
  echo "==> 2 GB swap file"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Code in $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone -q "$REPO" "$DIR"
fi

echo "==> Python environment (miniaudio measures BPM for Sensations)"
python3 -m venv "$DIR/.venv"
if ! "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"; then
  sudo apt-get install -y -qq build-essential python3-dev >/dev/null
  "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
fi

echo "==> Service"
sudo tee /etc/systemd/system/sala-de-escuta.service >/dev/null <<EOF
[Unit]
Description=Sala de escuta
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -m spotify_assistant ui --no-browser
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q sala-de-escuta
if [ -f "$DIR/.env" ]; then
  sudo systemctl restart sala-de-escuta
  echo "Panel running (sudo systemctl status sala-de-escuta; logs in $DIR/data/assistant.log)."
else
  echo "Next: copy .env, data/ and playlists.json into $DIR, then run: sudo systemctl start sala-de-escuta"
fi
