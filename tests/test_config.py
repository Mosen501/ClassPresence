from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from attendance_app.config import load_settings
from attendance_app.database import _normalize_postgres_conninfo


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
        self.assertEqual(Path(settings.database_target), expected)

    def test_absolute_database_path_is_preserved(self) -> None:
        absolute_path = str((Path("/tmp") / "attendance-test.db").resolve())
        settings = load_settings({"ATTENDANCE_DB_PATH": absolute_path})
        self.assertEqual(settings.database_target, absolute_path)

    def test_database_url_takes_priority_over_sqlite_path(self) -> None:
        settings = load_settings(
            {
                "ATTENDANCE_DB_URL": "postgresql://attendance_user:secret@db.example.com:5432/attendance",
                "ATTENDANCE_DB_PATH": "attendance.db",
            }
        )
        self.assertEqual(
            settings.database_target,
            "postgresql://attendance_user:secret@db.example.com:5432/attendance",
        )

    def test_database_url_falls_back_to_standard_database_url_env_var(self) -> None:
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "postgresql://attendance_user:secret@db.example.com:5432/attendance"},
            clear=False,
        ):
            settings = load_settings({})

        self.assertEqual(
            settings.database_target,
            "postgresql://attendance_user:secret@db.example.com:5432/attendance",
        )

    def test_database_url_can_be_built_from_separate_attendance_db_parts(self) -> None:
        settings = load_settings(
            {
                "ATTENDANCE_DB_HOST": "db.example.com",
                "ATTENDANCE_DB_PORT": "5432",
                "ATTENDANCE_DB_NAME": "attendance",
                "ATTENDANCE_DB_USER": "attendance_user",
                "ATTENDANCE_DB_PASSWORD": "S3cr@t:/?#",
                "ATTENDANCE_DB_SSLMODE": "require",
            }
        )
        self.assertEqual(
            settings.database_target,
            "postgresql://attendance_user:S3cr%40t%3A%2F%3F%23@db.example.com:5432/attendance?sslmode=require",
        )

    def test_database_url_can_be_built_from_standard_pg_parts(self) -> None:
        settings = load_settings(
            {
                "PGHOST": "db.example.com",
                "PGPORT": "5432",
                "PGDATABASE": "attendance",
                "PGUSER": "attendance_user",
                "PGPASSWORD": "secret",
                "PGSSLMODE": "require",
            }
        )
        self.assertEqual(
            settings.database_target,
            "postgresql://attendance_user:secret@db.example.com:5432/attendance?sslmode=require",
        )

    def test_postgres_conninfo_defaults_sslmode_require(self) -> None:
        normalized = _normalize_postgres_conninfo(
            "postgresql://attendance_user:secret@db.example.com:5432/attendance"
        )
        self.assertEqual(
            normalized,
            "postgresql://attendance_user:secret@db.example.com:5432/attendance?sslmode=require",
        )

    def test_postgres_conninfo_keeps_existing_sslmode(self) -> None:
        normalized = _normalize_postgres_conninfo(
            "postgresql://attendance_user:secret@db.example.com:5432/attendance?sslmode=verify-full"
        )
        self.assertEqual(
            normalized,
            "postgresql://attendance_user:secret@db.example.com:5432/attendance?sslmode=verify-full",
        )


if __name__ == "__main__":
    unittest.main()
