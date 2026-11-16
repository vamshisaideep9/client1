"""Application-level encryption for sensitive stored fields (AES-256-GCM).

Used for Agent payout destinations (bank account / UPI ID), which the platform
otherwise never stores in raw form. A database dump, replica, or backup alone
does not reveal them; the key lives only in the runtime environment.

Blob layout: ``key_version (1 byte) || nonce (12 bytes) || ciphertext+tag``.
Associated data binds each blob to its purpose and owning row, so a ciphertext
copied into another Agent's row or another field fails authentication.

Key handling:

- ``PAYOUT_DETAILS_ENCRYPTION_KEY`` is a base64-encoded 32-byte key, validated
  at boot when set (core/config.py).
- In ``development`` an unset key falls back to a fixed, clearly non-secret
  development key so the local stack works without setup.
- Anywhere else an unset key makes ``FieldCipherUnavailable`` raise, and the
  feature answers 503. The rest of the API keeps running.

Rotation: blobs carry the key version. Only the configured version decrypts;
a future rotation adds the previous key alongside a re-encryption job.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_NONCE_BYTES = 12
_DEV_KEY = hashlib.sha256(b"dhanadhara-development-only-payout-details-key").digest()


class FieldCipherUnavailable(Exception):
    """No encryption key is configured for this environment."""


class FieldDecryptionError(Exception):
    """A stored blob could not be authenticated or uses an unknown key version."""


def decode_key(raw: str) -> bytes:
    """Decode and validate a configured base64 key (raises ValueError)."""
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("PAYOUT_DETAILS_ENCRYPTION_KEY must be base64.") from exc
    if len(key) != 32:
        raise ValueError("PAYOUT_DETAILS_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def _current_key() -> tuple[int, bytes]:
    version = settings.PAYOUT_DETAILS_ENCRYPTION_KEY_VERSION
    if settings.PAYOUT_DETAILS_ENCRYPTION_KEY:
        return version, decode_key(settings.PAYOUT_DETAILS_ENCRYPTION_KEY)
    if settings.ENV == "development":
        return version, _DEV_KEY
    raise FieldCipherUnavailable


def is_available() -> bool:
    try:
        _current_key()
    except FieldCipherUnavailable:
        return False
    return True


def current_key_version() -> int:
    return _current_key()[0]


def encrypt(plaintext: str, *, associated_data: bytes) -> bytes:
    version, key = _current_key()
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return bytes([version]) + nonce + sealed


def decrypt(blob: bytes, *, associated_data: bytes) -> str:
    version, key = _current_key()
    if len(blob) < 1 + _NONCE_BYTES + 16 or blob[0] != version:
        raise FieldDecryptionError
    nonce = blob[1 : 1 + _NONCE_BYTES]
    try:
        plaintext = AESGCM(key).decrypt(nonce, blob[1 + _NONCE_BYTES :], associated_data)
    except InvalidTag as exc:
        raise FieldDecryptionError from exc
    return plaintext.decode("utf-8")
