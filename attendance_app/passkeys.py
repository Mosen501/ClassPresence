from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


@dataclass(frozen=True)
class RegisteredPasskey:
    credential_id: str
    public_key: str
    sign_count: int
    aaguid: str
    credential_device_type: str
    credential_backed_up: bool
    transports: str


@dataclass(frozen=True)
class VerifiedPasskey:
    credential_id: str
    sign_count: int


def hash_device_token(token: str, pepper: str) -> str:
    normalized = token.strip()
    if len(normalized) < 20 or len(normalized) > 200:
        raise ValueError("This browser could not provide a valid device identity.")
    return hmac.new(
        pepper.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_registration_options(
    *,
    rp_id: str,
    rp_name: str,
    student_id: int,
    university_id: str,
    student_name: str,
) -> tuple[str, str]:
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=str(student_id).encode("utf-8"),
        user_name=university_id,
        user_display_name=student_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return options_to_json(options), bytes_to_base64url(options.challenge)


def complete_registration(
    *,
    credential: dict,
    expected_challenge: str,
    expected_rp_id: str,
    expected_origin: str,
) -> RegisteredPasskey:
    verification = verify_registration_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(expected_challenge),
        expected_rp_id=expected_rp_id,
        expected_origin=expected_origin,
        require_user_verification=True,
    )
    transports = credential.get("response", {}).get("transports", [])
    return RegisteredPasskey(
        credential_id=bytes_to_base64url(verification.credential_id),
        public_key=bytes_to_base64url(verification.credential_public_key),
        sign_count=int(verification.sign_count),
        aaguid=str(verification.aaguid),
        credential_device_type=str(verification.credential_device_type.value),
        credential_backed_up=bool(verification.credential_backed_up),
        transports=json.dumps(transports),
    )


def build_authentication_options(*, rp_id: str, credential_id: str) -> tuple[str, str]:
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential_id))],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return options_to_json(options), bytes_to_base64url(options.challenge)


def complete_authentication(
    *,
    credential: dict,
    expected_challenge: str,
    expected_rp_id: str,
    expected_origin: str,
    credential_id: str,
    public_key: str,
    sign_count: int,
) -> VerifiedPasskey:
    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(expected_challenge),
        expected_rp_id=expected_rp_id,
        expected_origin=expected_origin,
        credential_public_key=base64url_to_bytes(public_key),
        credential_current_sign_count=sign_count,
        require_user_verification=True,
    )
    verified_credential_id = bytes_to_base64url(verification.credential_id)
    if not hmac.compare_digest(verified_credential_id, credential_id):
        raise ValueError("The passkey does not match the registered device.")
    return VerifiedPasskey(
        credential_id=verified_credential_id,
        sign_count=int(verification.new_sign_count),
    )
