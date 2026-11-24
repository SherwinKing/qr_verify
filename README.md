# QR Verify

Small, low-storage product verification service. Codes are Ed25519-signed URLs and are not stored until the
first successful consumer scan.

## Local test

```bash
python3 -m unittest discover -s tests
python3 -m qr_verify generate \
  --private-key examples/private.key \
  --product-id 42 --batch-id 1 --quantity 3 \
  --public-base-url https://a.lattafa.com \
  --output /tmp/sample.csv
QR_VERIFY_DB=/tmp/qr-test.sqlite3 \
QR_VERIFY_PRODUCTS=examples/products.json \
python3 -m http.server --directory . 8000
```

Open one `/v/{token}` URL from the generated CSV in a browser. Repeat to see the counter increase.

For QR SVG export on a workstation, install:

```bash
python3 -m pip install "cryptography>=44" qrcode==8.2
```

On a Mac, run the generator from the directory that contains the `qr_verify` package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install "cryptography>=44" qrcode==8.2

python3 -m qr_verify generate \
  --private-key /path/to/private.key \
  --product-id 42 \
  --batch-id 2026001 \
  --quantity 10 \
  --public-base-url http://121.43.32.57 \
  --output test-codes.csv \
  --qr-dir test-qr-svg
```

Only the private key is needed for signing. The server only needs the matching public key. Never put the
private key in Git, chat, email, iCloud Drive, or an unencrypted backup.

## Production

### Temporary IP-only deployment

Until DNS is ready, use HTTP on the ECS public IP:

1. Copy the IP-only Caddy configuration:

   ```bash
   cp deploy/Caddyfile.ip.example /etc/caddy/Caddyfile
   ```

2. Generate print URLs with the ECS public IP:

   ```bash
   python3 -m qr_verify generate \
     --private-key /root/qr_prod_keys/private.key \
     --product-id 42 \
     --batch-id 2026001 \
     --quantity 10000 \
     --public-base-url http://<ECS_PUBLIC_IP> \
     --output /tmp/batch-2026001.csv
   ```

3. Open TCP port 80 in the Alibaba Cloud security group. Do not expose `127.0.0.1:8000`.

HTTP is suitable only for temporary testing. Move to HTTPS with a real domain before putting printed packaging
into production.

### Domain deployment

Before running `deploy/install-pm2.sh`:

1. Point both DNS names to the ECS public IP.
2. Generate keys with `python3 -m qr_verify init-keys --directory /root/qr_prod_keys`.
3. Put only `public.key` at `/etc/qr_verify/public.key`.
4. Put the product catalog at `/etc/qr_verify/products.json`.
5. Copy `deploy/Caddyfile.example` to `/etc/caddy/Caddyfile` and confirm domains.
6. Edit `deploy/ecosystem.config.js` and set `QR_VERIFY_PRINT_BASE_URL` plus `QR_VERIFY_VERIFY_BASE_URL`.

Because PM2 is your preferred process manager, run:

```bash
sudo ./deploy/install-pm2.sh
```

It installs Node/npm/PM2 if needed, runs the Python application as the non-login `qrverify` user, binds only to
`127.0.0.1:8000`, configures PM2 restart-on-boot, and starts Caddy. Useful commands:

```bash
pm2 status
pm2 logs qr-verify
pm2 restart qr-verify
pm2 save
```

Keep the private key off the web app host, or protect it if generation must also run there.
