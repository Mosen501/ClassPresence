from __future__ import annotations

import binascii
import hashlib
import hmac
import os


DEFAULT_PASSWORD_ITERATIONS = 390_000


def hash_password(password: str, *, salt_hex: str | None = None, iterations: int = DEFAULT_PASSWORD_ITERATIONS) -> str:
    salt_bytes = (
        binascii.unhexlify(salt_hex.encode("utf-8"))
        if salt_hex is not None
        else os.urandom(16)
    )
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iterations,
    )
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{binascii.hexlify(salt_bytes).decode('utf-8')}$"
        f"{binascii.hexlify(password_hash).decode('utf-8')}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hash = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False

    candidate_hash = hash_password(
        password,
        salt_hex=salt_hex,
        iterations=int(iterations),
    )
    return hmac.compare_digest(candidate_hash, stored_hash)

