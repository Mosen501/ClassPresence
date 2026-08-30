from __future__ import annotations

import sqlite3
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
