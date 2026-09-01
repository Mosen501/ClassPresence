from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


def _decode_base64url(value: str) -> bytes:
    normalized = value.strip()
    if not normalized:
        raise ValueError("The device credential data is incomplete.")
    padding = "=" * ((4 - len(normalized) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(normalized + padding)
    except Exception as error:
        raise ValueError("The device credential data is invalid.") from error


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def validate_browser_public_key(*, credential_id: str, public_key: str) -> None:
    key_bytes = _decode_base64url(public_key)
    if len(key_bytes) > 512:
        raise ValueError("The device public key is invalid.")
    expected_id = _encode_base64url(hashlib.sha256(key_bytes).digest())
    if not hmac.compare_digest(expected_id, credential_id.strip()):
        raise ValueError("The device credential identifier is invalid.")
    try:
        key = serialization.load_der_public_key(key_bytes)
    except (TypeError, ValueError) as error:
        raise ValueError("The device public key is invalid.") from error
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise TypeError("The device credential must use a P-256 signing key.")


def build_browser_key_options(
    *,
    rp_id: str,
    student_id: int,
    course_id: int,
    schedule_id: int,
    attendance_date: str,
    credential_id: str | None = None,
) -> tuple[str, str]:
    challenge = _encode_base64url(secrets.token_bytes(32))
    message = json.dumps(
        {
            "attendance_date": attendance_date,
            "challenge": challenge,
            "course_id": course_id,
            "rp_id": rp_id,
            "schedule_id": schedule_id,
            "student_id": student_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    options = {
        "credentialId": credential_id or "",
        "message": _encode_base64url(message),
    }
    return json.dumps(options, separators=(",", ":")), challenge


def verify_browser_key_signature(
    *,
    credential_id: str,
    public_key: str,
    message: str,
    signature: str,
) -> None:
    validate_browser_public_key(credential_id=credential_id, public_key=public_key)
    key = serialization.load_der_public_key(_decode_base64url(public_key))
    if not isinstance(key, ec.EllipticCurvePublicKey):  # pragma: no cover - validated above
        raise TypeError("The device public key is invalid.")
    signature_bytes = _decode_base64url(signature)
    if len(signature_bytes) == 64:
        signature_bytes = encode_dss_signature(
            int.from_bytes(signature_bytes[:32], "big"),
            int.from_bytes(signature_bytes[32:], "big"),
        )
    try:
        key.verify(
            signature_bytes,
            _decode_base64url(message),
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as error:
        raise ValueError("The registered device signature is invalid.") from error
