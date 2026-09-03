from __future__ import annotations

import json
import unittest

from attendance_app.passkeys import (
    build_authentication_options,
    build_registration_options,
    hash_device_token,
    passkey_trust_level,
)


class PasskeyTestCase(unittest.TestCase):
    def test_device_token_hash_is_stable_and_peppered(self) -> None:
        first = hash_device_token("test-device-token-00000001", "pepper-one")
        second = hash_device_token("test-device-token-00000001", "pepper-one")
        different = hash_device_token("test-device-token-00000001", "pepper-two")

        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_registration_options_allow_available_authenticator_with_verification(self) -> None:
        options_json, challenge = build_registration_options(
            rp_id="localhost",
            rp_name="ClassPresence",
            student_id=7,
            university_id="U2026007",
            student_name="Student Seven",
        )
        options = json.loads(options_json)

        self.assertEqual(options["rp"]["id"], "localhost")
        self.assertNotIn("authenticatorAttachment", options["authenticatorSelection"])
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(options["challenge"], challenge)

    def test_authentication_options_allow_only_registered_credential(self) -> None:
        options_json, challenge = build_authentication_options(
            rp_id="localhost",
            credential_id="Y3JlZGVudGlhbC1pZA",
        )
        options = json.loads(options_json)

        self.assertEqual(options["rpId"], "localhost")
        self.assertEqual(options["allowCredentials"][0]["id"], "Y3JlZGVudGlhbC1pZA")
        self.assertEqual(options["userVerification"], "required")
        self.assertEqual(options["challenge"], challenge)

    def test_only_non_synced_single_device_credentials_are_strict(self) -> None:
        self.assertEqual(
            passkey_trust_level(
                credential_device_type="single_device",
                credential_backed_up=False,
            ),
            "strict",
        )
        self.assertEqual(
            passkey_trust_level(
                credential_device_type="multi_device",
                credential_backed_up=True,
            ),
            "compatibility",
        )


if __name__ == "__main__":
    unittest.main()
