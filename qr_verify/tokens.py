from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
import hashlib
import secrets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization


TOKEN_VERSION = 1
NONCE_SIZE = 16
SIGNATURE_SIZE = 64
PAYLOAD_PREFIX_SIZE = 7


@dataclass(frozen=True)
class TokenData:
    version: int
    product_id: int
    batch_id: int
    nonce: bytes


class TokenError(ValueError):
    pass


def generate_key_pair() -> tuple[bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_bytes, public_bytes


def generate_token(private_key_bytes: bytes, product_id: int, batch_id: int, nonce: bytes | None = None) -> str:
    if nonce is None:
        nonce = secrets.token_bytes(NONCE_SIZE)
    if len(nonce) != NONCE_SIZE:
        raise ValueError("nonce must be exactly 16 bytes")
    if not 0 <= product_id <= 0xFFFF:
        raise ValueError("product_id must fit uint16")
    if not 0 <= batch_id <= 0xFFFFFFFF:
        raise ValueError("batch_id must fit uint32")
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    payload = TOKEN_VERSION.to_bytes(1, "big") + product_id.to_bytes(2, "big") + batch_id.to_bytes(4, "big") + nonce
    signature = private_key.sign(payload)
    return urlsafe_b64encode(payload + signature).rstrip(b"=").decode("ascii")


def verify_token(public_key_bytes: bytes, token: str) -> TokenData | None:
    try:
        if not token or len(token) > 160 or any(ch not in _SAFE_BASE64 for ch in token):
            return None
        padded = token + "=" * (-len(token) % 4)
        raw = urlsafe_b64decode(padded.encode("ascii"))
        if len(raw) != PAYLOAD_PREFIX_SIZE + NONCE_SIZE + SIGNATURE_SIZE:
            return None
        payload, signature = raw[:-SIGNATURE_SIZE], raw[-SIGNATURE_SIZE:]
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, payload)
        version = int.from_bytes(payload[0:1], "big")
        product_id = int.from_bytes(payload[1:3], "big")
        batch_id = int.from_bytes(payload[3:7], "big")
        nonce = payload[7:]
        if version != TOKEN_VERSION:
            return None
        return TokenData(version, product_id, batch_id, nonce)
    except (ValueError, TypeError, InvalidSignature):
        return None


def token_hash(token: str) -> bytes:
    digest = hashlib.sha256(token.encode("ascii")).digest()
    return digest


_SAFE_BASE64 = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
