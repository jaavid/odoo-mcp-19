"""Encrypt/decrypt utilities for multi-user registry secrets.

Fernet key derivation contract:
- PBKDF2-HMAC-SHA256
- 480,000 iterations
- 32-byte derived key
- salt stored in ``.token_salt`` next to ``users.db``

``TOKEN_ENCRYPTION_KEY`` or ``TOKEN_ENCRYPTION_KEY_FILE`` holds the secret
password. The salt and database may be readable by the MCP container; the
encryption password must remain secret.
"""

from __future__ import annotations

import base64
import json
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_PBKDF2_ITERATIONS = 480_000
_SALT_BYTES = 16


def _read_encryption_password() -> str:
    """Read the registry encryption password from env or Docker secret."""
    value = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if value:
        return value.strip()

    file_path = os.environ.get("TOKEN_ENCRYPTION_KEY_FILE")
    if file_path and Path(file_path).is_file():
        value = Path(file_path).read_text().strip()
        if value:
            return value

    raise RuntimeError(
        "TOKEN_ENCRYPTION_KEY (or TOKEN_ENCRYPTION_KEY_FILE) is required to "
        "encrypt/decrypt registry credentials."
    )


def ensure_salt(db_path: Path) -> bytes:
    """Return the registry salt, creating it atomically when absent."""
    salt_path = db_path.parent / ".token_salt"
    if salt_path.is_file():
        salt = salt_path.read_bytes()
        if not salt:
            raise RuntimeError(f"Registry salt file is empty: {salt_path}")
        return salt

    db_path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(_SALT_BYTES)
    try:
        fd = os.open(salt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        existing = salt_path.read_bytes()
        if not existing:
            raise RuntimeError(f"Registry salt file is empty: {salt_path}")
        return existing

    with os.fdopen(fd, "wb") as f:
        f.write(salt)
    return salt


@lru_cache(maxsize=4)
def _fernet(salt: bytes, password: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))


def encrypt_secret(payload: dict[str, object], db_path: Path) -> str:
    """Encrypt a JSON object for storage in ``encrypted_secret``."""
    if not isinstance(payload, dict):
        raise TypeError("Registry secret payload must be a JSON object")
    salt = ensure_salt(db_path)
    fernet = _fernet(salt, _read_encryption_password())
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return fernet.encrypt(serialized).decode()


def decrypt_secret(encrypted: str, db_path: Path) -> dict[str, object]:
    """Decrypt a registry ``encrypted_secret`` value."""
    salt_path = db_path.parent / ".token_salt"
    if not salt_path.is_file():
        raise RuntimeError(f"Registry salt file not found: {salt_path}")

    salt = salt_path.read_bytes()
    if not salt:
        raise RuntimeError(f"Registry salt file is empty: {salt_path}")

    fernet = _fernet(salt, _read_encryption_password())
    try:
        decrypted = fernet.decrypt(encrypted.encode())
    except InvalidToken as exc:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY mismatch with registry — use the same secret "
            "that was used when the Odoo credentials were stored."
        ) from exc

    result = json.loads(decrypted)
    if not isinstance(result, dict):
        raise RuntimeError("Registry secret payload is not a JSON object")
    return result
