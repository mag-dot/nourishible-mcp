import tempfile
import unittest
from pathlib import Path
from nourishible_worker.spool import EncryptedSpool


class MemorySecretStore:
    def __init__(self, value=b"s" * 64):
        self.value = value
        self.names = []
    def get_or_create(self, name):
        self.names.append(name)
        return self.value


class SpoolTests(unittest.TestCase):
    def test_persists_encrypted_attempts_and_removes_them(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "spool.db")
            first = EncryptedSpool(path, MemorySecretStore(), "worker-key")
            first.put("attempt-1", {"stage": "captured", "nested": {"ok": True}})
            self.assertEqual([], first.connection.execute(
                "SELECT payload FROM attempts WHERE payload LIKE '%captured%'"
            ).fetchall())

            second = EncryptedSpool(path, MemorySecretStore(), "worker-key")
            self.assertEqual({"stage": "captured", "nested": {"ok": True}}, second.pending()[0])
            second.remove("attempt-1")
            self.assertEqual([], second.pending())

    def test_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            spool = EncryptedSpool(str(Path(temp) / "spool.db"), MemorySecretStore())
            spool.put("attempt-1", {"stage": "captured"})
            row = spool.connection.execute("SELECT payload FROM attempts").fetchone()[0]
            tampered = bytearray(row)
            tampered[-1] ^= 1
            spool.connection.execute("UPDATE attempts SET payload = ?", (bytes(tampered),))
            spool.connection.commit()
            with self.assertRaisesRegex(RuntimeError, "integrity"):
                spool.pending()

    def test_rejects_wrong_secret_size(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "64 bytes"):
                EncryptedSpool(str(Path(temp) / "spool.db"), MemorySecretStore(b"short"))
