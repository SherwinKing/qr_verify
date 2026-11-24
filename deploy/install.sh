#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run as root: sudo ./deploy/install.sh" >&2
  exit 1
fi

echo "This project now defaults to PM2 deployment." >&2
echo "Use deploy/install-pm2.sh instead." >&2
exit 1

if ! id qrverify >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --create-home --shell /usr/sbin/nologin qrverify
fi

install -d -o qrverify -g qrverify -m 0750 "$STATE_DIR"
install -d -o root -g root -m 0750 "$CONFIG_DIR"
systemctl stop qr-verify.service 2>/dev/null || true
rm -rf "$APP_DIR"
install -d -o root -g root -m 0755 "$APP_DIR"
cp -a "$SOURCE_DIR/qr_verify" "$APP_DIR/"

