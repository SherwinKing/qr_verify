from __future__ import annotations

import argparse
import csv
from pathlib import Path
from .db import Database
from .tokens import generate_key_pair, generate_token, token_hash, verify_token


def cmd_init_keys(args: argparse.Namespace) -> None:
    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=False)
    private_bytes, public_bytes = generate_key_pair()
    (directory / "private.key").write_bytes(private_bytes)
    (directory / "public.key").write_bytes(public_bytes)
    (directory / "private.key").chmod(0o600)
    print(directory / "private.key")
    print(directory / "public.key")


def cmd_generate(args: argparse.Namespace) -> None:
    private_bytes = Path(args.private_key).read_bytes()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = 0
    qr_dir = Path(args.qr_dir) if args.qr_dir else None
    if qr_dir:
        qr_dir.mkdir(parents=True, exist_ok=True)
        import qrcode
        from qrcode.image.svg import SvgPathImage
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["code_url", "token", "product_id", "batch_id"])
        for _ in range(args.quantity):
            token = generate_token(private_bytes, args.product_id, args.batch_id)
            url = f"{args.public_base_url.rstrip('/')}/v/{token}"
            writer.writerow([url, token, args.product_id, args.batch_id])
            if qr_dir:
                qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
                qr.add_data(url)
                qr.make(fit=True)
                qr.make_image(image_factory=SvgPathImage).save(qr_dir / f"{token}.svg")
            generated += 1
    print(f"Generated {generated} codes in {output}")


def cmd_revoke(args: argparse.Namespace) -> None:
    if not args.token:
        raise SystemExit("--token is required")
    database = Database(args.db)
    database.connect()
    database.migrate()
    database.revoke(token_hash(args.token))
    database.close()
    print("Token revoked")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qr_verify")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-keys", help="generate an Ed25519 key pair")
    init.add_argument("--directory", required=True)
    init.set_defaults(func=cmd_init_keys)

    gen = commands.add_parser("generate", help="generate signed URLs for printing")
    gen.add_argument("--private-key", required=True)
    gen.add_argument("--public-base-url", default="https://a.lattafa.com")
    gen.add_argument("--product-id", required=True, type=int)
    gen.add_argument("--batch-id", required=True, type=int)
    gen.add_argument("--quantity", required=True, type=int)
    gen.add_argument("--output", required=True)
    gen.add_argument("--qr-dir", help="optional directory for SVG QR files; requires qrcode[csvg]")
    gen.set_defaults(func=cmd_generate)

    revoke = commands.add_parser("revoke", help="revoke one signed token")
    revoke.add_argument("--db", required=True)
    revoke.add_argument("--token", required=True)
    revoke.set_defaults(func=cmd_revoke)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
