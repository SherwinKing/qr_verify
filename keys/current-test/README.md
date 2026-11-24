# Current test key pair

This directory intentionally contains the temporary test private key requested for this development repository.

It is accepted by the current IP-only test deployment. Replace both files before production:

1. Generate a new production key pair.
2. Install only the new public key at `/etc/qr_verify/public.key`.
3. Restart PM2.
4. Generate production batches with the matching new private key.

Never create a production private-key directory in this repository.
