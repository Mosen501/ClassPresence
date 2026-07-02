from __future__ import annotations

import unittest

from attendance_app.security import hash_password, verify_password


class SecurityTestCase(unittest.TestCase):
    def test_password_hash_round_trip(self) -> None:
        password_hash = hash_password("ExamplePassword123!", salt_hex="0123456789abcdef0123456789abcdef")
        self.assertTrue(verify_password("ExamplePassword123!", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))


if __name__ == "__main__":
    unittest.main()
