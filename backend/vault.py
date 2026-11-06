"""Encrypts users' own API keys before they reach the database.

Fernet (AES-128-CBC + HMAC) from the `cryptography` package, keyed from KEY_VAULT_SECRET. If that
secret is missing we refuse to store keys at all, rather than fall back to plain text.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from backend import config


class VaultUnavailable(RuntimeError):
    """KEY_VAULT_SECRET is not set, so keys cannot be stored safely."""


def _fernet() -> Fernet:
    if not config.KEY_VAULT_SECRET:
        raise VaultUnavailable("KEY_VAULT_SECRET is not set.")
    digest = hashlib.sha256(config.KEY_VAULT_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def available() -> bool:
    return bool(config.KEY_VAULT_SECRET)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str | None:
    """The original text, or None if the token can't be read (secret rotated or data damaged)."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
