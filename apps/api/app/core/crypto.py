"""Fernet encryption for integration tokens at rest (SECURITY.md §5)."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().secret_encryption_key
    if not key:
        # Deterministic dev fallback derived from SECRET_KEY so local setups
        # work out of the box; production must set SECRET_ENCRYPTION_KEY.
        derived = hashlib.sha256(
            (get_settings().secret_key + "|token-encryption").encode()
        ).digest()
        key = base64.urlsafe_b64encode(derived).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict | None:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except (InvalidToken, ValueError):
        return None
