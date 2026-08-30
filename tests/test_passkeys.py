from __future__ import annotations

import json
import unittest

from attendance_app.passkeys import (
    build_authentication_options,
    build_registration_options,
    hash_device_token,
)


class PasskeyTestCase(unittest.TestCase):
    def test_device_token_hash_is_stable_and_peppered(self) -> None:
        first = hash_device_token("test-device-token-00000001", "pepper-one")
        second = hash_device_token("test-device-token-00000001", "pepper-one")
        different = hash_device_token("test-device-token-00000001", "pepper-two")

        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_registration_options_require_platform_user_verification(self) -> None:
        options_json, challenge = build_registration_options(
            rp_id="localhost",
            rp_name="ClassPresence",
            student_id=7,
            university_id="U2026007",
            student_name="Student Seven",
        )
        options = json.loads(options_json)

        self.assertEqual(options["rp"]["id"], "localhost")
        self.assertEqual(options["authenticatorSelection"]["authenticatorAttachment"], "platform")
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


if __name__ == "__main__":
    unittest.main()
