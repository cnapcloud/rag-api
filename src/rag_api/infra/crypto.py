"""Symmetric encryption for connector config secrets (Fernet/AES-128-CBC).

Default key is derived from a fixed passphrase and is intentionally weak —
set CONNECTOR_SECRET_KEY (URL-safe base64, 32 bytes) in production.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Fields in connector config that must be encrypted at rest.
SECRET_FIELDS: frozenset[str] = frozenset({"auth_token_secret", "auth_headers", "auth_basic"})

# Sentinel returned by mask_config() in place of a real secret value. A PATCH
# request that resubmits this unchanged means "keep the existing value".
MASK_VALUE = "*" * 20

_ENC_PREFIX = "ENC:"
_DEFAULT_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(b"rag-api-default-connector-secret").digest()
)


def _fernet() -> Fernet:
    raw = os.environ.get("CONNECTOR_SECRET_KEY", "").strip().encode()
    if raw:
        try:
            return Fernet(raw)
        except Exception:
            logger.warning("CONNECTOR_SECRET_KEY is invalid — falling back to default key")
    return Fernet(_DEFAULT_KEY)


def encrypt_config(config: dict) -> dict:
    """Return a copy of config with SECRET_FIELDS values encrypted.

    Values already carrying the ENC: prefix are left untouched (they are
    ciphertext reused as-is from a previous save, e.g. an unchanged secret
    field) instead of being encrypted a second time.
    """
    result = dict(config)
    f = _fernet()
    for field in SECRET_FIELDS:
        val = result.get(field)
        if val is None or (isinstance(val, str) and val.startswith(_ENC_PREFIX)):
            continue
        data = json.dumps(val).encode()
        result[field] = _ENC_PREFIX + f.encrypt(data).decode()
    return result


def decrypt_config(config: dict) -> dict:
    """Return a copy of config with ENC:-prefixed values decrypted."""
    result = dict(config)
    f = _fernet()
    for field in SECRET_FIELDS:
        val = result.get(field)
        if not isinstance(val, str) or not val.startswith(_ENC_PREFIX):
            continue
        try:
            result[field] = json.loads(f.decrypt(val[len(_ENC_PREFIX):].encode()))
        except (InvalidToken, Exception) as e:
            logger.warning("Failed to decrypt config field %s: %s", field, e)
            result[field] = None
    return result


def mask_config(config: dict) -> dict:
    """Return a copy of config with SECRET_FIELDS values replaced by MASK_VALUE."""
    result = dict(config)
    for field in SECRET_FIELDS:
        if result.get(field) is not None:
            result[field] = MASK_VALUE
    return result
