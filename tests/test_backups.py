from __future__ import annotations

import unittest

from attendance_app.backups import decrypt_backup_payload, encrypt_backup_payload


class BackupEncryptionTestCase(unittest.TestCase):
    def test_backup_round_trip_hides_plaintext_and_detects_wrong_password(self) -> None:
        payload = {
            "format": "classpresence-reset-backup-v1",
            "tables": {
                "students": [{"university_id": "445009803"}],
                "registered_devices": [{"public_key": "sensitive-public-key"}],
            },
        }

        encrypted = encrypt_backup_payload(payload, "correct horse battery staple")

        self.assertNotIn(b"445009803", encrypted)
        self.assertNotIn(b"sensitive-public-key", encrypted)
        self.assertEqual(
            decrypt_backup_payload(encrypted, "correct horse battery staple"),
            payload,
        )
        with self.assertRaisesRegex(ValueError, "incorrect or the file was changed"):
            decrypt_backup_payload(encrypted, "wrong password")

    def test_short_backup_password_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 12"):
            encrypt_backup_payload({"tables": {}}, "too-short")


if __name__ == "__main__":
    unittest.main()
