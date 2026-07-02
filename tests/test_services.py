from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from attendance_app.config import Settings
from attendance_app.database import AttendanceRepository
from attendance_app.services import (
    resolve_student_access_context,
    stamp_attendance,
    verify_login_code_for_access_context,
)
from attendance_app.utils import hash_otp


TEST_COURSE_LATITUDE = 1.234567
TEST_COURSE_LONGITUDE = -2.345678


class ServicesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = AttendanceRepository(f"{self.temp_dir.name}/attendance.db")
        self.repo.init_schema()
        self.settings = Settings(
            app_env="development",
            app_timezone="Asia/Riyadh",
            database_path=f"{self.temp_dir.name}/attendance.db",
            manager_username="manager_user",
            manager_password_hash="unused",
            otp_delivery_mode="console",
            otp_expiry_minutes=10,
            otp_pepper="pepper",
            smtp_host="",
            smtp_port=587,
            smtp_username="",
            smtp_password="",
            smtp_sender="",
            smtp_use_tls=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_resolve_student_access_context_returns_roster_linked_course(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            access_context = resolve_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                geolocation_payload={
                    "latitude": TEST_COURSE_LATITUDE,
                    "longitude": TEST_COURSE_LONGITUDE,
                    "captured_at": now.isoformat(),
                },
            )

        self.assertEqual(access_context.course_id, int(course["id"]))
        self.assertEqual(access_context.student_id, int(student["id"]))
        self.assertEqual(access_context.course_title, "Calculus I")

    def test_verify_login_code_for_access_context_rejects_closed_window(self) -> None:
        course, student = self._seed_course()
        otp_now = datetime(2026, 7, 1, 9, 15, tzinfo=ZoneInfo("Asia/Riyadh"))
        self.repo.create_otp(
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            code_hash=hash_otp("123456", self.settings.otp_pepper),
            delivery_method="email",
            delivery_target="masa@example.edu",
            expires_at=datetime(2026, 7, 1, 13, 0, tzinfo=ZoneInfo("Asia/Riyadh")).isoformat(),
            created_at=otp_now.isoformat(),
        )

        with patch(
            "attendance_app.services.now_in_app_timezone",
            return_value=datetime(2026, 7, 1, 13, 30, tzinfo=ZoneInfo("Asia/Riyadh")),
        ):
            with self.assertRaisesRegex(ValueError, "Student access is closed right now"):
                verify_login_code_for_access_context(
                    self.repo,
                    self.settings,
                    course_id=int(course["id"]),
                    student_id=int(student["id"]),
                    code="123456",
                )

    def test_stamp_attendance_rejects_course_outside_active_dates(self) -> None:
        course, student = self._seed_course(end_date="2026-06-30")

        with patch(
            "attendance_app.services.now_in_app_timezone",
            return_value=datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh")),
        ):
            result = stamp_attendance(
                self.repo,
                self.settings,
                course=course,
                student=student,
                geolocation_payload={
                    "latitude": TEST_COURSE_LATITUDE,
                    "longitude": TEST_COURSE_LONGITUDE,
                    "captured_at": "2026-07-01T10:00:00+03:00",
                },
            )

        self.assertFalse(result.success)
        self.assertIn("outside its active dates", result.message)

    def test_location_change_for_existing_course_rejects_old_point_and_accepts_new_point(self) -> None:
        course, _student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        original_lat = float(course["latitude"])
        original_lon = float(course["longitude"])
        new_lat = original_lat + 0.0001
        new_lon = original_lon + 0.0001

        self.repo.update_course(
            course_id=int(course["id"]),
            code=str(course["code"]),
            title=str(course["title"]),
            start_date=str(course["start_date"]),
            end_date=str(course["end_date"] or course["start_date"]),
            latitude=new_lat,
            longitude=new_lon,
            radius_m=float(course["radius_m"]),
            absence_limit_pct=float(course["absence_limit_pct"]),
        )

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            with self.assertRaisesRegex(ValueError, "You are not in class"):
                resolve_student_access_context(
                    self.repo,
                    self.settings,
                    university_id="20260001",
                    geolocation_payload={
                        "latitude": original_lat,
                        "longitude": original_lon,
                        "captured_at": now.isoformat(),
                    },
                )

            access_context = resolve_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                geolocation_payload={
                    "latitude": new_lat,
                    "longitude": new_lon,
                    "captured_at": now.isoformat(),
                },
            )

        self.assertAlmostEqual(access_context.course_latitude, new_lat)
        self.assertAlmostEqual(access_context.course_longitude, new_lon)
        self.assertAlmostEqual(access_context.distance_m, 0.0)

    def test_delete_schedule_removes_existing_time_window(self) -> None:
        course, _student = self._seed_course()
        schedules = self.repo.list_schedules_for_course(int(course["id"]))
        self.assertEqual(len(schedules), 1)

        deleted = self.repo.delete_schedule(
            schedule_id=int(schedules[0]["id"]),
            course_id=int(course["id"]),
        )

        self.assertTrue(deleted)
        self.assertEqual(self.repo.list_schedules_for_course(int(course["id"])), [])

    def test_sync_course_schedules_updates_weekly_grid(self) -> None:
        course, _student = self._seed_course()

        self.repo.sync_course_schedules(
            course_id=int(course["id"]),
            schedule_rows=[
                {
                    "weekday": 6,
                    "label": "L1",
                    "start_time": "07:30",
                    "end_time": "08:20",
                },
                {
                    "weekday": 0,
                    "label": "L1",
                    "start_time": "07:30",
                    "end_time": "08:20",
                },
                {
                    "weekday": 1,
                    "label": "Lab",
                    "start_time": "14:30",
                    "end_time": "15:20",
                },
            ],
            created_at="2026-07-01T08:00:00+03:00",
        )

        schedules = self.repo.list_schedules_for_course(int(course["id"]))
        self.assertEqual(
            [
                (int(row["weekday"]), str(row["label"]), str(row["start_time"]), str(row["end_time"]))
                for row in schedules
            ],
            [
                (0, "L1", "07:30", "08:20"),
                (1, "Lab", "14:30", "15:20"),
                (6, "L1", "07:30", "08:20"),
            ],
        )

    def _seed_course(self, *, end_date: str = "2026-07-31"):
        created_at = "2026-06-25T08:00:00+03:00"
        self.repo.create_course(
            code="MAT1116",
            title="Calculus I",
            start_date="2026-07-01",
            end_date=end_date,
            total_meetings=1,
            latitude=TEST_COURSE_LATITUDE,
            longitude=TEST_COURSE_LONGITUDE,
            radius_m=3.0,
            absence_limit_pct=20.0,
            created_at=created_at,
        )
        course = self.repo.get_course_by_code("MAT1116")
        assert course is not None

        self.repo.add_student_to_course(
            course_id=int(course["id"]),
            full_name="MASA",
            university_id="20260001",
            email="masa@example.edu",
            phone="",
            created_at=created_at,
        )
        self.repo.add_schedule(
            course_id=int(course["id"]),
            weekday=2,
            label="Morning Lecture",
            start_time="09:00",
            end_time="11:00",
            created_at=created_at,
        )
        student = self.repo.get_student_for_course(int(course["id"]), "20260001")
        assert student is not None
        return course, student


if __name__ == "__main__":
    unittest.main()
