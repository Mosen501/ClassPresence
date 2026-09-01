from __future__ import annotations

import base64
import hashlib
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from attendance_app.browser_keys import (
    build_browser_key_options,
    validate_browser_public_key,
    verify_browser_key_signature,
)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class BrowserKeyTestCase(unittest.TestCase):
    def test_browser_key_options_bind_the_lecture_context(self) -> None:
        options_json, challenge = build_browser_key_options(
            rp_id="classpresence.example",
            student_id=7,
            course_id=11,
            schedule_id=13,
            attendance_date="2026-09-02",
            credential_id="credential",
        )

        self.assertIn('"credentialId":"credential"', options_json)
        self.assertIn('"message":', options_json)
        self.assertGreater(len(challenge), 30)

    def test_p256_browser_key_registration_and_signature(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_key = _base64url(public_key_bytes)
        credential_id = _base64url(hashlib.sha256(public_key_bytes).digest())
        message_bytes = b"browser-key-lecture-challenge"
        message = _base64url(message_bytes)
        signature = _base64url(private_key.sign(message_bytes, ec.ECDSA(hashes.SHA256())))

        validate_browser_public_key(
            credential_id=credential_id,
            public_key=public_key,
        )
        verify_browser_key_signature(
            credential_id=credential_id,
            public_key=public_key,
            message=message,
            signature=signature,
        )

        r_value, s_value = decode_dss_signature(
            private_key.sign(message_bytes, ec.ECDSA(hashes.SHA256()))
        )
        browser_signature = _base64url(
            r_value.to_bytes(32, "big") + s_value.to_bytes(32, "big")
        )
        verify_browser_key_signature(
            credential_id=credential_id,
            public_key=public_key,
            message=message,
            signature=browser_signature,
        )

        with self.assertRaisesRegex(ValueError, "signature is invalid"):
            verify_browser_key_signature(
                credential_id=credential_id,
                public_key=public_key,
                message=_base64url(b"different-message"),
                signature=signature,
            )


if __name__ == "__main__":
    unittest.main()
