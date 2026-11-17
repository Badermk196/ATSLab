#!/usr/bin/env bash
# 1000Jobs ATS Lab - one-shot setup for a Manus Cloud Computer (Ubuntu 24.04).
#
# Run it on the cloud computer, from the repo root, after the code is in place:
#   sudo bash deploy/cloud/install.sh            # direct port mode  -> http://IP:8501
#   sudo bash deploy/cloud/install.sh https      # HTTPS mode        -> https://DOMAIN
#
# What it does, in order:
#   1. installs Docker + the compose plugin if they are missing
#   2. opens the firewall ports (UFW: only 22 is open by default)
#   3. checks that .env exists and has the two required values
#   4. builds the image and starts the container(s)
#   5. turns on auto-start after a reboot (systemd unit)
#   6. prints the address to open
#
# It is safe to run again: nothing is deleted, an existing .env and the data volume are kept.

set -euo pipefail

MODE="${1:-port}"                       # "port" or "https"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# apt must never stop to ask a question (tzdata and friends would block the install).
export DEBIAN_FRONTEND=noninteractive

say() { printf '\n=== %s ===\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "run this with sudo: sudo bash deploy/cloud/install.sh"

say "1/6 Docker"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
else
  echo "docker already installed: $(docker --version)"
fi
docker compose version >/dev/null 2>&1 || fail "the docker compose plugin is missing"

say "2/6 Firewall"
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp >/dev/null 2>&1 || true
  if [ "$MODE" = "https" ]; then
    ufw allow 80/tcp  >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
    echo "opened 80 and 443"
  else
    ufw allow 8501/tcp >/dev/null 2>&1 || true
    echo "opened 8501"
  fi
  ufw --force enable >/dev/null 2>&1 || true
  ufw status | sed -n '1,20p'
else
  echo "ufw not present: nothing to open"
fi

say "3/6 Settings file"
ENV_FILE="$HERE/.env"
[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE - copy .env.example to .env and fill it in first"
grep -q '^OPENROUTER_API_KEY=..*' "$ENV_FILE" || fail "OPENROUTER_API_KEY is empty in .env"
grep -q '^ATSLAB_ADMINS=..*' "$ENV_FILE" || fail "ATSLAB_ADMINS is empty in .env"
if [ "$MODE" = "https" ]; then
  grep -q '^DOMAIN=..*' "$ENV_FILE" || fail "DOMAIN is empty in .env (https mode needs it)"
fi
echo "settings look complete"

say "4/6 Build and start"
cd "$HERE"
if [ "$MODE" = "https" ]; then
  docker compose -f docker-compose.https.yml up -d --build
else
  docker compose up -d --build
fi

say "Waiting for the app to answer"
for i in $(seq 1 40); do
  if docker exec atslab-app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" >/dev/null 2>&1; then
    echo "the app is up (after ${i}0 seconds)"
    break
  fi
  if [ "$i" -eq 40 ]; then
    echo "the app did not answer within 400 seconds. Check the logs:"
    echo "  docker compose -f $HERE/docker-compose.yml logs --tail 60"
    exit 1
  fi
  sleep 10
done

say "5/6 Auto-start after a reboot"
say "5/6 Waiting for the app to answer"
READY=0
for i in $(seq 1 60); do
  if curl -fsS -m 3 http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1; then READY=1; break; fi
  sleep 2
done
if [ "$READY" = "1" ]; then
  echo "the app answers on port 8501"
else
  echo "the app did not answer yet; check: docker compose logs --tail 40"
fi

say "6/6 Auto-start after a reboot"
if [ "$MODE" = "https" ]; then COMPOSE_FILE="$HERE/docker-compose.https.yml"; else COMPOSE_FILE="$HERE/docker-compose.yml"; fi
cat > /etc/systemd/system/atslab.service <<EOF
[Unit]
Description=1000Jobs ATS Lab
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$HERE
ExecStart=/usr/bin/docker compose -f $COMPOSE_FILE up -d
ExecStop=/usr/bin/docker compose -f $COMPOSE_FILE down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable atslab.service >/dev/null
echo "systemd unit atslab.service enabled"

say "6/6 Address"
IP="$(curl -fsS -4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
if [ "$MODE" = "https" ]; then
  DOMAIN_VALUE="$(grep '^DOMAIN=' "$ENV_FILE" | cut -d= -f2-)"
  echo "User page : https://$DOMAIN_VALUE/user"
  echo "Admin page: https://$DOMAIN_VALUE/admin"
  echo "The first load can take ~30 seconds while Caddy gets the certificate."
else
  echo "User page : http://$IP:8501/user"
  echo "Admin page: http://$IP:8501/admin"
fi
echo
echo "Logs:   docker compose -f $COMPOSE_FILE logs -f"
echo "Status: docker compose -f $COMPOSE_FILE ps"
echo "Note: no HTTPS in port mode. The admin password travels unencrypted; use https mode for real use."
