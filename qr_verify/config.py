from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class AppConfig:
    db_path: str
    public_key: bytes
    print_base_url: str = "https://a.lattafa.com"
    verify_base_url: str = "https://verify.lattafa.com"
    products_path: str | None = None
    strong_repeat_threshold: int = 3

    @classmethod
    def from_env(cls) -> "AppConfig":
        import os

        public_key_path = Path(os.environ.get("QR_VERIFY_PUBLIC_KEY", "examples/public.key"))
        products_path = os.environ.get("QR_VERIFY_PRODUCTS")
        return cls(
            db_path=os.environ.get("QR_VERIFY_DB", "data/qr_verify.sqlite3"),
            public_key=public_key_path.read_bytes(),
            print_base_url=os.environ.get("QR_VERIFY_PRINT_BASE_URL", "https://a.lattafa.com").rstrip("/"),
            verify_base_url=os.environ.get("QR_VERIFY_VERIFY_BASE_URL", "https://verify.lattafa.com").rstrip("/"),
            products_path=products_path,
            strong_repeat_threshold=int(os.environ.get("QR_VERIFY_STRONG_REPEAT_THRESHOLD", "3")),
        )

    @property
    def print_host(self) -> str:
        return urlparse(self.print_base_url).netloc.lower()

    def products(self) -> dict:
        if not self.products_path:
            return {}
        raw = json.loads(Path(self.products_path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("products file must contain an object")
        return raw
