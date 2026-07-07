from __future__ import annotations

import unittest
from pathlib import Path

from attendance_app.config import load_settings


class ConfigTestCase(unittest.TestCase):
    def test_development_defaults_to_console_otp(self) -> None:
        settings = load_settings({"APP_ENV": "development"})
        self.assertEqual(settings.otp_delivery_mode, "console")

    def test_production_defaults_to_email_otp(self) -> None:
        settings = load_settings({"APP_ENV": "production"})
        self.assertEqual(settings.otp_delivery_mode, "email")

    def test_relative_database_path_resolves_to_project_root(self) -> None:
        settings = load_settings({"ATTENDANCE_DB_PATH": "attendance.db"})
        expected = (Path(__file__).resolve().parent.parent / "attendance.db").resolve()
        self.assertEqual(Path(settings.database_path), expected)

    def test_absolute_database_path_is_preserved(self) -> None:
        absolute_path = str((Path("/tmp") / "attendance-test.db").resolve())
        settings = load_settings({"ATTENDANCE_DB_PATH": absolute_path})
        self.assertEqual(settings.database_path, absolute_path)


if __name__ == "__main__":
    unittest.main()
