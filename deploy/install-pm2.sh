#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run as root: sudo ./deploy/install-pm2.sh" >&2
  exit 1
fi

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP_DIR=/opt/qr_verify
STATE_DIR=/var/lib/qr_verify
CONFIG_DIR=/etc/qr_verify
LOG_DIR=/var/log/qr_verify

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3-cryptography caddy npm

if ! command -v pm2 >/dev/null 2>&1; then
  npm install -g pm2
fi

if ! id qrverify >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --create-home --shell /usr/sbin/nologin qrverify
fi

install -d -o qrverify -g qrverify -m 0750 "$STATE_DIR"
install -d -o qrverify -g qrverify -m 0750 "$LOG_DIR"
install -d -o root -g qrverify -m 0750 "$CONFIG_DIR"

if [[ ! -f "$CONFIG_DIR/public.key" ]]; then
  echo "Missing $CONFIG_DIR/public.key" >&2
  echo "Run: python3 -m qr_verify init-keys --directory /root/qr_prod_keys" >&2
  echo "Then copy only public.key here." >&2
  exit 1
fi
if [[ ! -f "$CONFIG_DIR/products.json" ]]; then
  echo "Missing $CONFIG_DIR/products.json" >&2
  exit 1
fi
if [[ ! -f /etc/caddy/Caddyfile ]]; then
  echo "Missing /etc/caddy/Caddyfile; copy deploy/Caddyfile.example and set real domains first." >&2
  exit 1
fi

systemctl stop qr-verify.service 2>/dev/null || true
pm2 delete qr-verify 2>/dev/null || true

rm -rf "$APP_DIR"
install -d -o root -g root -m 0755 "$APP_DIR"
cp -a "$SOURCE_DIR/qr_verify" "$SOURCE_DIR/run.py" "$APP_DIR/"

chown -R root:root "$APP_DIR"
find "$APP_DIR" -type d -exec chmod 0755 {} +
find "$APP_DIR" -type f -exec chmod 0644 {} +
chown root:qrverify "$CONFIG_DIR/public.key" "$CONFIG_DIR/products.json"
chmod 0640 "$CONFIG_DIR/public.key" "$CONFIG_DIR/products.json"

pm2 start "$SOURCE_DIR/deploy/ecosystem.config.js" --only qr-verify
pm2 save
pm2 startup systemd -u root --hp /root

systemctl enable --now caddy
systemctl restart caddy

pm2 status
