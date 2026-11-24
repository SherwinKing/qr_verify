# Product Anti-Counterfeit Verification System — Architecture Draft

## 1. Current server snapshot

- Alibaba Cloud ECS, Ubuntu 26.04, x86_64.
- 2 vCPU, about 1.7 GiB RAM, no swap.
- 40 GiB root disk, about 33 GiB free.
- Python 3.14 is installed; Go, Docker, Docker Compose, Caddy and the SQLite CLI are not installed.
- No service is listening on a TCP port.
- Apt repositories are available.

The service is expected to remain comfortably within this server size.

## 2. Recommended stack

### Initial choice

| Area | Recommendation |
| --- | --- |
| Backend | Python 3 standard-library threaded HTTP server |
| Database | SQLite in WAL mode |
| Consumer frontend | Server-rendered mobile-first HTML/CSS with minimal JavaScript |
| Reverse proxy / HTTPS | Caddy |
| Process management | PM2 (customer-preferred); alternatively systemd |
| Packaging | Ubuntu Python package for runtime; defer Docker |
| Code generation | Ed25519-signed anti-counterfeit tokens |
| Language | English and Arabic, selected by query parameter and `Accept-Language` |

### Why this is preferable for this project

The business has low traffic and low storage volume. The most important requirements are correctness, small
operational surface, cheap migration, and low maintenance cost.

Go is technically attractive because it compiles to a small static binary and has excellent deployment
characteristics. However, the developer already knows Python and Linux and has limited Go experience. For this
scale, Python's runtime overhead is not a practical concern. AI-assisted development and later human maintenance
should be easier in Python.

The first implementation deliberately avoids a web-framework dependency. Python's standard threaded HTTP server
is sufficient behind Caddy for this scan volume, and the only runtime cryptography dependency is Ubuntu's
`python3-cryptography`. This makes deployment smaller and easier to audit.

Docker adds reproducibility, but on a single small ECS it also adds image updates, volume handling, database
placement questions and another operational layer. PM2 plus Ubuntu's packaged Python cryptography module is
straightforward for this operator. A Dockerfile can be added later without changing the core architecture.

PostgreSQL, Redis, Kubernetes, separate front-end frameworks and message queues are unnecessary here.

## 3. Anti-counterfeit token design

The key idea is that each code is a self-authenticating signed token. The server verifies it by public-key
cryptography; it does not need to look up a list of all issued codes.

### Token payload

Use a compact binary payload:

```text
payload = version(1) || product_id(u16) || batch_id(u32) || random_nonce(16 bytes)
signature = Ed25519(payload, private_key)
token = urlsafe_base64_no_padding(payload || signature)
public_url = https://verify.example.com/v/{token}
```

Rough token size:

- payload: 23 bytes
- Ed25519 signature: 64 bytes
- URL-safe Base64: about 116 characters
- complete public URL: usually around 130–160 characters

This is acceptable for a modern QR code and remains easy to scan from packaging.

### Printed-domain and verification-domain split

The code can follow the common two-domain pattern:

```text
printed URL:      https://a.lattafa.com/v/{token}
302 redirect to:  https://verify.lattafa.com/v/{token}
verification app: https://verify.lattafa.com/v/{token}
```

This separates the permanent print URL from the verification implementation. The app receives the same token
path on both hostnames. If the verification host changes later, only the redirect target on `a.lattafa.com`
has to change. The `a.lattafa.com` hostname and its DNS remain a long-term dependency for printed packaging.

The server determines redirect behavior by comparing the request `Host` header with `QR_VERIFY_PRINT_BASE_URL`.
Requests arriving directly on `verify.lattafa.com` are processed without another redirect.

For temporary IP-only deployment, both configured base URLs are the local loopback URL and the printed QR uses
`http://<ECS_PUBLIC_IP>/v/{token}`. Caddy reverse-proxies that request to the Python service. This avoids HTTPS
certificate problems before DNS is available, but printed packaging should not ship until the domain/HTTPS
deployment is ready.

### Validation rules

The consumer route performs these checks in order:

1. Parse and length-check the token.
2. Verify the Ed25519 signature with the production public key.
3. Parse the product and batch IDs.
4. Confirm that the product exists in the small product catalog.
5. Compute `token_hash = SHA-256(token)`.
6. Check whether that hash has been revoked.
7. Atomically create or update the scan record and obtain the current count.
8. Render an English/Arabic result page.

An invalid signature, malformed token or unknown product is shown as an invalid code.

### Database design

There is no table containing every generated code. A code creates a row only on its first successful scan.

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE scan_counts (
  token_hash BLOB PRIMARY KEY,
  product_id INTEGER NOT NULL,
  batch_id INTEGER NOT NULL,
  scan_count INTEGER NOT NULL CHECK (scan_count >= 1),
  first_seen_utc TEXT NOT NULL,
  last_seen_utc TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE revocations (
  token_hash BLOB PRIMARY KEY,
  revoked_at_utc TEXT NOT NULL
) WITHOUT ROWID;
```

The product catalog may initially be a versioned JSON file, or a tiny SQLite table if editing through a
protected admin interface is required.

The raw token is not stored. The SHA-256 hash is sufficient for counting and revocation while avoiding a
database that could reproduce printable URLs.

### Concurrency

SQLite can safely support this traffic when the process uses one writer-friendly transaction and WAL mode. The
count update should be a single UPSERT:

```sql
INSERT INTO scan_counts (
  token_hash, product_id, batch_id,
  scan_count, first_seen_utc, last_seen_utc
) VALUES (?, ?, ?, 1, ?, ?)
ON CONFLICT(token_hash) DO UPDATE SET
  scan_count = scan_count + 1,
  last_seen_utc = excluded.last_seen_utc
RETURNING scan_count, first_seen_utc;
```

The application must set a busy timeout and handle the rare `SQLITE_BUSY` result safely. Running one Uvicorn
worker is recommended initially.

## 4. Generation workflow

Generation should initially be a CLI command rather than a public admin web page:

```bash
qr-generate \
  --key /etc/qr_verify/keys/ed25519_private.key \
  --product-id 42 \
  --batch-id 2026001 \
  --quantity 10000 \
  --format csv \
  --output /tmp/batch-2026001.csv
```

The command creates fresh 128-bit random nonces, signs each token, and exports the full verification URLs for
the printing vendor. Optional formats are CSV plus SVG/PDF QR assets.

The private key is used only for generation. It should not be readable by the web application process. The
verification service only needs the Ed25519 public key.

Export files are unavoidable if they are required for printing, but they should be transferred and removed
securely. The system should not keep duplicate generation artifacts as logs.

## 5. Repeated scans and consumer display

The result page should show:

- valid / invalid state;
- product name in the selected language;
- batch ID if useful and non-sensitive;
- first verification message on count 1;
- total previous verification count on later scans;
- a risk warning when count is greater than 1, with stronger wording at a configurable threshold such as 3;
- guidance that a valid code alone does not prove the physical product is genuine.

The page must be mobile-first, RTL-aware for Arabic, cached-disabled, indexed-disabled and free of unnecessary
tracking.

Repeated scans can be inflated intentionally because the QR URL can be copied. That limitation should be
explained to consumers: the counter is risk information, not cryptographic proof of authenticity.

## 6. Security, privacy and operations

### Key management

- Generate Ed25519 keys offline or in a protected server directory.
- Give the web process only the public key.
- Back up the private key encrypted in a separate location.
- Put the key version byte in the token so future key rotation is possible.
- If the private signing key leaks, all future codes are vulnerable; old printed codes remain verifiable only
  while their key/public key is trusted.

### Logging and data minimization

- Do not log raw verification tokens.
- Do not log consumer IP addresses for the normal verification path.
- Disable access logs for `/v/{token}` or configure token redaction.
- Keep only minimal application error logs, with tokens excluded.
- Avoid permanent request bodies and analytics unless a future requirement appears.

### Administrative protection

The first release should use SSH-only administration and CLI commands. If a web admin UI is added later, it must
be protected by strong authentication, HTTPS, CSRF protection, audit events and separate permissions.

### Backups and migration

Persistent state should be limited to:

- SQLite database;
- signing/verification keys;
- product catalog/configuration;
- deployment configuration.

Nightly encrypted SQLite backups should be stored off the main server. Migration requires copying this small
state and pointing the same public domain to the new server. The public domain is a permanent dependency: once
packaging is printed, changing the domain will invalidate all existing QR codes from a consumer access
perspective.

### Deployment

Initial topology:

```text
Consumer phone
    | HTTP :80 redirect / HTTPS :443
Caddy
    | reverse proxy 127.0.0.1:8000
Python verification service
    | SQLite WAL database
Small local state
```

Caddy should terminate TLS, obtain certificates automatically, and serve only the needed routes.

### Process manager

The implementation now defaults to PM2 because the operator knows it well. PM2 starts Python through
`deploy/ecosystem.config.js`, runs it as the non-login `qrverify` user, restarts it after failure, and can be
enabled at boot with `pm2 startup` plus `pm2 save`. This adds a Node runtime dependency, but that tradeoff is
acceptable when it lowers maintenance friction for the person operating the server.

## 7. Main limitations of zero prestorage

1. **Revocation needs generated manifests.** To revoke one specific code, the system needs its token hash. That
   is usually obtained from the batch export or offline manifest.
2. **Batch recall is easier by product/batch rule than by individual code.** A small batch-level revocation table
   can be added if this becomes a business requirement.
3. **Generation statistics require an external manifest.** If no export or manifest is retained, the system cannot
   later answer how many codes were issued, only how many were scanned.
4. **URLs embed the public domain.** Printed QR codes cannot be changed after production.
5. **Valid does not mean genuine.** Copies of a valid QR code remain valid; scan count is only a risk signal.
6. **Counts can be manipulated.** Someone with a copied code can scan it repeatedly.
7. **Link previews may count as scans.** If this becomes problematic, verification can be changed to a two-step
   page with an explicit POST confirmation, at the cost of one extra consumer tap.
8. **Key loss or compromise is serious.** Encrypted private-key backup and key-versioning are mandatory.

## 8. Development phases

### Phase 0 — Decisions and foundations

- Register/select a stable verification domain.
- Create repository structure, configuration loader, tests and code style.
- Generate Ed25519 key pair.

### Phase 1 — Minimum business loop

- SQLite schema and migration runner.
- Token encoding/decoding/signature verification module.
- CLI batch generator exporting CSV URLs.
- Consumer verification route with bilingual result page.
- Accurate first/repeat scan counting.

This is the first deployable business closure.

### Phase 2 — Product and batch metadata

- Product catalog.
- English/Arabic product descriptions.
- Batch visibility rules.
- Invalid-product and revoked-code user experience.

### Phase 3 — Production hardening

- Caddy HTTPS configuration.
- PM2 restart and boot-start configuration.
- Security headers, disabled verification access logs, rate protection for obvious abuse.
- Nightly encrypted SQLite backup.
- Restore test.

### Phase 4 — Operational tooling

- Minimal health endpoint.
- Deployment script.
- Optional Docker packaging.
- Batch manifest verification tool.
- Simple admin CLI for revocation.

### Phase 5 — Disk monitoring and alerts

Only after the core service is stable:

- systemd timer checking disk usage and absolute free space;
- alert through the customer's preferred channel, such as SMTP, Telegram or Alibaba Cloud notification;
- periodic disk-growth report for SQLite/WAL, backups and system logs.

## 9. Initial implementation preference

Build the minimum loop first: signed tokens, CSV/QR export, SQLite count UPSERT, bilingual mobile page, then
Caddy/PM2 production hardening. Keep the first release deliberately small and avoid any database record for
unscanned codes.
