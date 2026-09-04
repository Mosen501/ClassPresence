from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from unittest.mock import patch

from attendance_app.database import AttendanceRepository, DatabaseUnavailableError


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

    def test_student_course_snapshot_uses_one_connection_checkout(self) -> None:
        student = self.repo.get_student_for_course(int(self.course["id"]), "U1")
        assert student is not None

        with patch.object(self.repo, "_connect", wraps=self.repo._connect) as connect:
            snapshot = self.repo.get_student_course_snapshot(
                course_id=int(self.course["id"]),
                student_id=int(student["id"]),
            )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["course"]["code"], "SEC101")
        self.assertEqual(snapshot["student"]["university_id"], "U1")
        self.assertEqual(len(snapshot["schedules"]), 1)
        connect.assert_called_once_with()

    def test_manager_today_snapshot_uses_aggregates_in_one_connection(self) -> None:
        course_id = int(self.course["id"])
        student = self.repo.get_student_for_course(course_id, "U1")
        schedule = self.repo.list_schedules_for_course(course_id)[0]
        assert student is not None
        self.repo.record_attendance(
            course_id=course_id,
            student_id=int(student["id"]),
            schedule_id=int(schedule["id"]),
            attendance_date="2026-09-01",
            stamped_at="2026-09-01T09:05:00+03:00",
            student_latitude=24.0,
            student_longitude=46.0,
            accuracy_m=5.0,
            distance_m=1.0,
            device_info="{}",
        )

        with patch.object(self.repo, "_connect", wraps=self.repo._connect) as connect:
            snapshot = self.repo.get_manager_today_snapshot(
                course_ids=[course_id],
                attendance_date="2026-09-01",
            )

        self.assertEqual(snapshot["student_counts"][course_id], 2)
        self.assertEqual(snapshot["records_today"], 1)
        self.assertEqual(
            snapshot["attendance_counts"][(course_id, int(schedule["id"]))],
            1,
        )
        connect.assert_called_once_with()

    def test_expired_device_enrollment_is_removed_from_pending_queue(self) -> None:
        student = self.repo.get_student_for_course(int(self.course["id"]), "U1")
        schedule = self.repo.list_schedules_for_course(int(self.course["id"]))[0]
        assert student is not None
        pending_id = self.repo.create_pending_device_enrollment(
            student_id=int(student["id"]),
            course_id=int(self.course["id"]),
            schedule_id=int(schedule["id"]),
            attendance_date="2026-08-01",
            credential_id="pending-passkey",
            public_key="pending-public-key",
            device_binding_hash="pending-device-hash",
            expires_at="2026-08-01T09:00:00+00:00",
            created_at="2026-08-01T08:00:00+00:00",
            auth_method="passkey",
        )

        pending = self.repo.list_pending_device_enrollments(
            course_id=int(self.course["id"]),
            now_iso="2026-08-01T09:01:00+00:00",
        )

        self.assertEqual(pending, [])
        row = self.repo.get_pending_device_enrollment(pending_id)
        assert row is not None
        self.assertEqual(row["status"], "expired")

    def test_postgres_repository_starts_a_bounded_connection_pool(self) -> None:
        with patch("attendance_app.database.ConnectionPool") as pool_factory:
            pool = pool_factory.return_value
            repo = AttendanceRepository(
                "postgresql://user:password@example.test/database",
                use_pool=True,
            )

        self.assertIs(repo._pool, pool)
        pool.wait.assert_called_once_with(timeout=10)
        self.assertEqual(pool_factory.call_args.kwargs["min_size"], 1)
        self.assertEqual(pool_factory.call_args.kwargs["max_size"], 8)
        self.assertIs(
            pool_factory.call_args.kwargs["check"],
            pool_factory.check_connection,
        )
        self.assertEqual(pool_factory.call_args.kwargs["reconnect_timeout"], 10)

        repo.check_connections()
        pool.check.assert_called_once_with()

    def test_read_retries_once_after_a_temporary_database_failure(self) -> None:
        class SuccessfulConnection:
            def execute(self, query, parameters):
                del query, parameters
                return self

            def fetchall(self):
                return [{"id": 7, "code": "RECOVERED"}]

        @contextmanager
        def failed_checkout():
            raise DatabaseUnavailableError("temporary outage")
            yield  # pragma: no cover

        @contextmanager
        def successful_checkout():
            yield SuccessfulConnection()

        with patch.object(
            self.repo,
            "_connection",
            side_effect=[failed_checkout(), successful_checkout()],
        ) as connection:
            rows = self.repo._fetchall("SELECT * FROM courses")

        self.assertEqual(rows, [{"id": 7, "code": "RECOVERED"}])
        self.assertEqual(connection.call_count, 2)

    def test_read_reports_database_failure_after_second_attempt(self) -> None:
        @contextmanager
        def failed_checkout():
            raise DatabaseUnavailableError("temporary outage")
            yield  # pragma: no cover

        with patch.object(
            self.repo,
            "_connection",
            side_effect=[failed_checkout(), failed_checkout()],
        ) as connection:
            with self.assertRaises(DatabaseUnavailableError):
                self.repo._fetchone("SELECT * FROM courses WHERE id = ?", (1,))

        self.assertEqual(connection.call_count, 2)

    def test_connection_translates_transient_driver_errors(self) -> None:
        @contextmanager
        def failed_checkout():
            raise OSError("connection closed")
            yield  # pragma: no cover

        class FailingPool:
            def connection(self):
                return failed_checkout()

        self.repo._pool = FailingPool()
        with patch.object(self.repo, "_is_transient_database_error", return_value=True):
            with self.assertRaises(DatabaseUnavailableError):
                with self.repo._connection():
                    pass

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
        with patch.object(legacy_repo, "_migrate_schema") as migrate:
            legacy_repo.init_schema()
        migrate.assert_not_called()

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
            pending_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(pending_browser_enrollments)")
            }
            audit_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(device_audit_events)")
            }
            schedule_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(course_schedules)")
            }
            attendance_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(attendance_records)")
            }
            location_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(location_attempt_events)")
            }
            location_audit_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("course_location_change_audit",),
            ).fetchone()
            credential_attempt_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("credential_attempt_events",),
            ).fetchone()

        self.assertIn("schedule_id", otp_columns)
        self.assertIn("attendance_date", otp_columns)
        self.assertIsNotNone(audit_table)
        self.assertIsNotNone(audit_index)
        self.assertIn("auth_method", device_columns)
        self.assertIsNotNone(pending_table)
        self.assertIn("fallback_reason", pending_columns)
        for column in (
            "auth_method",
            "sign_count",
            "transports",
            "aaguid",
            "credential_device_type",
            "credential_backed_up",
        ):
            self.assertIn(column, pending_columns)
        self.assertIn("reason", audit_columns)
        self.assertIn("attendance_grace_minutes", schedule_columns)
        self.assertIn("archived_at", schedule_columns)
        for column in (
            "schedule_label_snapshot",
            "schedule_start_time_snapshot",
            "schedule_end_time_snapshot",
            "reference_latitude",
            "reference_longitude",
            "reference_radius_m",
            "attendance_status",
            "record_source",
            "override_reason",
            "recorded_by",
            "evidence_snapshot_source",
        ):
            self.assertIn(column, attendance_columns)
        self.assertIn("reference_latitude", location_columns)
        self.assertIn("schedule_label_snapshot", location_columns)
        self.assertIn("evidence_snapshot_source", location_columns)
        self.assertIsNotNone(location_audit_table)
        self.assertIsNotNone(credential_attempt_table)


if __name__ == "__main__":
    unittest.main()
