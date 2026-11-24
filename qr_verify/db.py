from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
import threading


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class ScanResult:
    scan_count: int
    first_seen_utc: str
    is_first_scan: bool


class Database:
    def __init__(self, path: str):
        self.path = path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._state_lock = threading.RLock()

    def connect(self) -> None:
        with self._state_lock:
            if self._connection is not None:
                return
            self._connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
            self._connection.execute("PRAGMA busy_timeout = 10000")
            self._connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        with self._state_lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def migrate(self) -> None:
        assert self._connection is not None
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scan_counts (
                  token_hash BLOB PRIMARY KEY,
                  product_id INTEGER NOT NULL,
                  batch_id INTEGER NOT NULL,
                  scan_count INTEGER NOT NULL CHECK (scan_count >= 1),
                  first_seen_utc TEXT NOT NULL,
                  last_seen_utc TEXT NOT NULL
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS revocations (
                  token_hash BLOB PRIMARY KEY,
                  revoked_at_utc TEXT NOT NULL
                ) WITHOUT ROWID;
                """
            )
            self._connection.commit()

    def is_revoked(self, hashed_token: bytes) -> bool:
        assert self._connection is not None
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM revocations WHERE token_hash = ?", (hashed_token,)
            ).fetchone()
            return row is not None

    def record_scan(self, hashed_token: bytes, product_id: int, batch_id: int) -> ScanResult:
        assert self._connection is not None
        with self._lock:
            now = utc_now()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT scan_count, first_seen_utc FROM scan_counts WHERE token_hash = ?",
                    (hashed_token,),
                ).fetchone()
                if row is None:
                    self._connection.execute(
                        """
                        INSERT INTO scan_counts
                          (token_hash, product_id, batch_id, scan_count, first_seen_utc, last_seen_utc)
                        VALUES (?, ?, ?, 1, ?, ?)
                        """,
                        (hashed_token, product_id, batch_id, now, now),
                    )
                    scan_count, first_seen = 1, now
                else:
                    scan_count = int(row["scan_count"]) + 1
                    first_seen = str(row["first_seen_utc"])
                    self._connection.execute(
                        """
                        UPDATE scan_counts
                        SET scan_count = ?, last_seen_utc = ?
                        WHERE token_hash = ?
                        """,
                        (scan_count, now, hashed_token),
                    )
                self._connection.execute(
                    "COMMIT"
                )
                return ScanResult(scan_count, first_seen, row is None)
            except Exception:
                self._connection.rollback()
                raise

    def revoke(self, hashed_token: bytes) -> None:
        assert self._connection is not None
        with self._lock:
            self._connection.execute(
                "INSERT OR IGNORE INTO revocations (token_hash, revoked_at_utc) VALUES (?, ?)",
                (hashed_token, utc_now()),
            )
            self._connection.commit()
