"""Encrypted, durable lease metadata spool for macOS workers.

Only encrypted lease/manifest metadata is kept here. Capture media stays in a mode-0700
directory and must be purged by the upload-retention policy after acceptance.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Protocol


class SecretStore(Protocol):
    def get_or_create(self, name: str) -> bytes: ...


class MacOSKeychainSecretStore:
    """Stores a 64-byte spool secret in the login Keychain; fails closed elsewhere."""
    def get_or_create(self, name: str) -> bytes:
        service = "com.nourishible.local-worker"
        found = subprocess.run(["security", "find-generic-password", "-s", service, "-a", name, "-w"],
                               capture_output=True, text=True)
        if found.returncode == 0:
            return base64.b64decode(found.stdout.strip(), validate=True)
        secret = secrets.token_bytes(64)
        created = subprocess.run(["security", "add-generic-password", "-U", "-s", service, "-a", name,
                                  "-w", base64.b64encode(secret).decode("ascii")], capture_output=True, text=True)
        if created.returncode != 0:
            raise RuntimeError("could not create local worker Keychain secret")
        return secret


class EncryptedSpool:
    def __init__(self, path: str, secret_store: SecretStore, key_name: str = "default"):
        secret = secret_store.get_or_create(key_name)
        if len(secret) != 64:
            raise ValueError("spool secret must be 64 bytes")
        self.enc_key, self.mac_key = secret[:32], secret[32:]
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        os.chmod(self.path, 0o600)
        self.connection.execute("CREATE TABLE IF NOT EXISTS attempts (attempt_id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        self.connection.commit()

    def _crypt(self, payload: bytes, decrypt: bool = False) -> bytes:
        key_file = tempfile.NamedTemporaryFile(mode="wb", delete=False)
        try:
            # ``openssl enc -pass file:`` expects a text passphrase, not arbitrary
            # bytes. Encoding the random key also avoids NUL/newline truncation.
            key_file.write(base64.b64encode(self.enc_key))
            key_file.close()
            os.chmod(key_file.name, 0o600)
            command = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt",
                       "-pass", "file:" + key_file.name]
            if decrypt:
                command.append("-d")
            completed = subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if completed.returncode != 0:
                raise RuntimeError("local spool encryption operation failed")
            return completed.stdout
        finally:
            try:
                os.unlink(key_file.name)
            except FileNotFoundError:
                pass

    def _seal(self, value: Dict[str, object]) -> bytes:
        encrypted = self._crypt(json.dumps(value, sort_keys=True).encode("utf-8"))
        signature = hmac.new(self.mac_key, encrypted, hashlib.sha256).digest()
        return base64.b64encode(signature + encrypted)

    def _open(self, blob: bytes) -> Dict[str, object]:
        try:
            raw = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("local spool integrity check failed") from exc
        if len(raw) < 33:
            raise RuntimeError("local spool integrity check failed")
        signature, encrypted = raw[:32], raw[32:]
        expected = hmac.new(self.mac_key, encrypted, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise RuntimeError("local spool integrity check failed")
        try:
            value = json.loads(self._crypt(encrypted, decrypt=True).decode("utf-8"))
        except (RuntimeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("local spool integrity check failed") from exc
        if not isinstance(value, dict):
            raise RuntimeError("local spool integrity check failed")
        return value

    def put(self, attempt_id: str, value: Dict[str, object]) -> None:
        self.connection.execute("INSERT OR REPLACE INTO attempts(attempt_id, payload) VALUES (?, ?)",
                                (attempt_id, self._seal(value)))
        self.connection.commit()

    def pending(self) -> List[Dict[str, object]]:
        return [self._open(row[0]) for row in self.connection.execute("SELECT payload FROM attempts")]

    def remove(self, attempt_id: str) -> None:
        self.connection.execute("DELETE FROM attempts WHERE attempt_id = ?", (attempt_id,))
        self.connection.commit()
