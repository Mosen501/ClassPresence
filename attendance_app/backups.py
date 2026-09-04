from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BACKUP_FORMAT = "classpresence-encrypted-backup-v2"
BACKUP_AAD = BACKUP_FORMAT.encode("utf-8")
KDF_ITERATIONS = 600_000


def encrypt_backup_payload(payload: dict[str, Any], passphrase: str) -> bytes:
    normalized = passphrase.strip()
    if len(normalized) < 12:
        raise ValueError("The backup password must contain at least 12 characters.")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        salt,
        KDF_ITERATIONS,
        dklen=32,
    )
    plaintext = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, BACKUP_AAD)
    envelope = {
        "format": BACKUP_FORMAT,
        "cipher": "AES-256-GCM",
        "kdf": "PBKDF2-HMAC-SHA256",
        "kdf_iterations": KDF_ITERATIONS,
        "salt": _encode(salt),
        "nonce": _encode(nonce),
        "ciphertext": _encode(ciphertext),
    }
    return json.dumps(envelope, indent=2, sort_keys=True).encode("utf-8")


def decrypt_backup_payload(content: bytes, passphrase: str) -> dict[str, Any]:
    try:
        envelope = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("The encrypted backup file is invalid.") from error
    if not isinstance(envelope, dict) or envelope.get("format") != BACKUP_FORMAT:
        raise ValueError("This is not a supported encrypted ClassPresence backup.")
    try:
        iterations = int(envelope["kdf_iterations"])
        salt = _decode(str(envelope["salt"]))
        nonce = _decode(str(envelope["nonce"]))
        ciphertext = _decode(str(envelope["ciphertext"]))
    except (KeyError, TypeError, ValueError, binascii.Error) as error:
        raise ValueError("The encrypted backup file is invalid.") from error
    if iterations != KDF_ITERATIONS:
        raise ValueError("This backup uses an unsupported password-derivation policy.")
    normalized = passphrase.strip()
    key = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, BACKUP_AAD)
        payload = json.loads(plaintext.decode("utf-8"))
    except Exception as error:
        raise ValueError("The backup password is incorrect or the file was changed.") from error
    if not isinstance(payload, dict):
        raise TypeError("The decrypted backup payload must be an object.")
    return payload


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
