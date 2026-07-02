from __future__ import annotations

import unittest

from attendance_app.config import load_settings


class ConfigTestCase(unittest.TestCase):
    def test_development_defaults_to_console_otp(self) -> None:
        settings = load_settings({"APP_ENV": "development"})
        self.assertEqual(settings.otp_delivery_mode, "console")

    def test_production_defaults_to_email_otp(self) -> None:
        settings = load_settings({"APP_ENV": "production"})
        self.assertEqual(settings.otp_delivery_mode, "email")


if __name__ == "__main__":
    unittest.main()
