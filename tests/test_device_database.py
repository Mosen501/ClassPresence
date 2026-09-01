from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing

from attendance_app.database import AttendanceRepository


class DeviceDatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = AttendanceRepository(f"{self.temp_dir.name}/attendance.db")
        self.repo.init_schema()
        self.repo.create_course(
            code="SEC101",
            title="Security",
            start_date="2026-08-01",
            end_date="2026-08-31",
            total_meetings=1,
            latitude=1.0,
            longitude=1.0,
            radius_m=10,
            absence_limit_pct=20,
            created_at="2026-08-01T08:00:00+00:00",
        )
        self.course = self.repo.get_course_by_code("SEC101")
        assert self.course is not None
        for index in (1, 2):
            self.repo.add_student_to_course(
                course_id=int(self.course["id"]),
                full_name=f"Student {index}",
                university_id=f"U{index}",
                email=f"student{index}@example.edu",
                phone="",
                created_at="2026-08-01T08:00:00+00:00",
            )
        self.repo.add_schedule(
            course_id=int(self.course["id"]),
            weekday=5,
            label="Lecture",
            start_time="08:00",
            end_time="09:00",
            created_at="2026-08-01T08:00:00+00:00",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_database_rejects_one_device_for_two_students_in_same_window(self) -> None:
        students = self.repo.list_students_for_course(int(self.course["id"]))
        schedule = self.repo.list_schedules_for_course(int(self.course["id"]))[0]
        values = {
            "course_id": int(self.course["id"]),
            "schedule_id": int(schedule["id"]),
            "attendance_date": "2026-08-01",
            "stamped_at": "2026-08-01T08:15:00+00:00",
            "student_latitude": 1.0,
            "student_longitude": 1.0,
            "accuracy_m": 5.0,
            "distance_m": 0.0,
            "device_info": "{}",
            "device_binding_hash": "same-device-hash",
        }
        self.repo.record_attendance(student_id=int(students[0]["id"]), **values)

        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.record_attendance(student_id=int(students[1]["id"]), **values)

    def test_existing_database_migrates_lecture_security_columns(self) -> None:
        database_path = f"{self.temp_dir.name}/legacy.db"
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE otp_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    code_hash TEXT NOT NULL,
                    delivery_method TEXT NOT NULL,
                    delivery_target TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    invalidated_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE attendance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    schedule_id INTEGER NOT NULL,
                    attendance_date TEXT NOT NULL,
                    stamped_at TEXT NOT NULL,
                    student_latitude REAL NOT NULL,
                    student_longitude REAL NOT NULL,
                    accuracy_m REAL,
                    distance_m REAL NOT NULL,
                    device_info TEXT NOT NULL
                )
                """
            )
            connection.commit()

        legacy_repo = AttendanceRepository(database_path)
        legacy_repo.init_schema()
        legacy_repo.init_schema()

        with closing(sqlite3.connect(database_path)) as connection:
            otp_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(otp_codes)")
            }
            audit_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("device_audit_events",),
            ).fetchone()
            audit_index = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
                ("ix_device_audit_course_created",),
            ).fetchone()
            device_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(registered_devices)")
            }
            pending_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("pending_browser_enrollments",),
            ).fetchone()

        self.assertIn("schedule_id", otp_columns)
        self.assertIn("attendance_date", otp_columns)
        self.assertIsNotNone(audit_table)
        self.assertIsNotNone(audit_index)
        self.assertIn("auth_method", device_columns)
        self.assertIsNotNone(pending_table)


if __name__ == "__main__":
    unittest.main()
