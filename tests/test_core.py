from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qr_verify.db import Database
from qr_verify.tokens import generate_key_pair, generate_token, token_hash, verify_token


class TokenAndDatabaseTests(unittest.TestCase):
    def test_signed_token_round_trip(self) -> None:
        private_key, public_key = generate_key_pair()
        token = generate_token(private_key, 42, 2026001)
        data = verify_token(public_key, token)
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(42, data.product_id)
        self.assertEqual(2026001, data.batch_id)
        self.assertEqual(32, len(token_hash(token)))
        self.assertIsNone(verify_token(public_key, token[:-1] + ("A" if token[-1] != "A" else "B")))

    def test_scan_count_is_atomic_across_two_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_one = Database(str(Path(directory) / "counts.sqlite3"))
            database_two = Database(database_one.path)
            try:
                for database in (database_one, database_two):
                    database.connect()
                    database.migrate()
                digest = token_hash("example-token")
                first = database_one.record_scan(digest, 42, 1)
                second = database_two.record_scan(digest, 42, 1)
                self.assertTrue(first.is_first_scan)
                self.assertFalse(second.is_first_scan)
                self.assertEqual(2, second.scan_count)
            finally:
                database_one.close()
                database_two.close()
