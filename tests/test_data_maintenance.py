from __future__ import annotations

import tempfile
import unittest

from attendance_app.database import AttendanceRepository


class DataMaintenanceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = AttendanceRepository(f"{self.temp_dir.name}/attendance.db")
        self.repo.init_schema()
        self.created_at = "2026-09-01T09:00:00+03:00"
        self.course_a = self._create_course("RESET101")
        self.course_b = self._create_course("KEEP202")
        self._add_student(self.course_a, "Shared Student", "SHARED")
        self._add_student(self.course_b, "Shared Student", "SHARED")
        self._add_student(self.course_a, "Exclusive Student", "EXCLUSIVE")
        self._add_student(self.course_b, "Other Student", "OTHER")
        self.shared = self.repo.get_student_for_course(self.course_a, "SHARED")
        self.exclusive = self.repo.get_student_for_course(self.course_a, "EXCLUSIVE")
        self.other = self.repo.get_student_for_course(self.course_b, "OTHER")
        assert self.shared is not None
        assert self.exclusive is not None
        assert self.other is not None
        self.schedule_a = self._add_schedule(self.course_a, "A")
        self.schedule_b = self._add_schedule(self.course_b, "B")
        self.shared_device = self._add_device(int(self.shared["id"]), "shared")
        self.exclusive_device = self._add_device(int(self.exclusive["id"]), "exclusive")
        self.other_device = self._add_device(int(self.other["id"]), "other")
        self._add_attendance(
            self.course_a,
            int(self.exclusive["id"]),
            self.schedule_a,
            self.exclusive_device,
            "exclusive",
        )
        self._add_attendance(
            self.course_a,
            int(self.shared["id"]),
            self.schedule_a,
            self.shared_device,
            "shared",
        )
        self._add_attendance(
            self.course_b,
            int(self.other["id"]),
            self.schedule_b,
            self.other_device,
            "other",
        )
        self.repo.create_otp(
            course_id=self.course_a,
            student_id=int(self.exclusive["id"]),
            code_hash="hash",
            delivery_method="console",
            delivery_target="EXCLUSIVE",
            expires_at="2026-09-01T09:10:00+03:00",
            created_at=self.created_at,
            schedule_id=self.schedule_a,
            attendance_date="2026-09-01",
        )
        self.repo.create_pending_browser_enrollment(
            student_id=int(self.exclusive["id"]),
            course_id=self.course_a,
            schedule_id=self.schedule_a,
            attendance_date="2026-09-01",
            credential_id="pending-credential",
            public_key="pending-public-key",
            device_binding_hash="pending-binding",
            expires_at="2026-09-01T09:10:00+03:00",
            created_at=self.created_at,
        )
        self.repo.create_proxy_alert(
            course_id=self.course_a,
            student_id=int(self.exclusive["id"]),
            schedule_id=self.schedule_a,
            attendance_date="2026-09-01",
            alert_type="test_alert",
            severity="high",
            message="Test alert",
            device_binding_hash="exclusive-binding",
            latitude=1.0,
            longitude=1.0,
            accuracy_m=5.0,
            created_at=self.created_at,
        )
        self.repo.record_device_registration_audit(
            student_id=int(self.exclusive["id"]),
            course_id=self.course_a,
            device_id=self.exclusive_device,
            device_binding_hash="exclusive-binding",
            created_at=self.created_at,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_course_attendance_reset_preserves_roster_and_timetable(self) -> None:
        self.repo.create_location_attempt_event(
            course_id=self.course_a,
            student_id=int(self.exclusive["id"]),
            schedule_id=self.schedule_a,
            attendance_date="2026-09-01",
            attempt_type="attendance",
            outcome="accepted",
            reason_code="attendance_recorded",
            message="Attendance recorded",
            latitude=1.0,
            longitude=1.0,
            accuracy_m=5.0,
            distance_m=1.0,
            radius_m=50.0,
            captured_at=self.created_at,
            sample_count=1,
            platform="iPhone",
            browser_family="Safari",
            created_at=self.created_at,
        )
        preview = self.repo.prepare_data_reset(
            action="course_attendance",
            course_id=self.course_a,
        )
        self.assertEqual(preview["counts"]["attendance_records"], 2)
        self.assertEqual(preview["counts"]["location_attempt_events"], 1)
        self.assertEqual(len(preview["tables"]["attendance_records"]), 2)

        result = self.repo.execute_data_reset(
            action="course_attendance",
            course_id=self.course_a,
            actor_identifier="manager",
            created_at=self.created_at,
        )

        self.assertEqual(result["scope_identifier"], "RESET101")
        self.assertEqual(self.repo.list_course_attendance(course_id=self.course_a), [])
        self.assertEqual(
            self.repo.list_location_attempt_events(course_id=self.course_a), []
        )
        self.assertEqual(len(self.repo.list_students_for_course(self.course_a)), 2)
        self.assertEqual(len(self.repo.list_schedules_for_course(self.course_a)), 1)
        self.assertEqual(len(self.repo.list_course_attendance(course_id=self.course_b)), 1)
        self.assertEqual(self.repo.list_data_reset_audit()[0]["action"], "course_attendance")

    def test_timetable_reset_removes_dependent_activity_only(self) -> None:
        result = self.repo.execute_data_reset(
            action="course_timetable",
            course_id=self.course_a,
            actor_identifier="manager",
            created_at=self.created_at,
        )

        self.assertEqual(result["counts"]["course_schedules"], 1)
        self.assertEqual(result["counts"]["attendance_records"], 2)
        self.assertEqual(self.repo.list_schedules_for_course(self.course_a), [])
        self.assertEqual(self.repo.list_pending_browser_enrollments(course_id=self.course_a), [])
        self.assertEqual(len(self.repo.list_students_for_course(self.course_a)), 2)
        self.assertEqual(len(self.repo.list_schedules_for_course(self.course_b)), 1)

    def test_student_device_reset_preserves_attendance_and_other_devices(self) -> None:
        result = self.repo.execute_data_reset(
            action="student_device",
            course_id=self.course_a,
            student_id=int(self.exclusive["id"]),
            actor_identifier="manager",
            created_at=self.created_at,
        )

        self.assertEqual(result["counts"]["registered_devices"], 1)
        self.assertIsNone(
            self.repo.get_registered_device_for_student(int(self.exclusive["id"]))
        )
        self.assertIsNotNone(
            self.repo.get_registered_device_for_student(int(self.shared["id"]))
        )
        self.assertEqual(len(self.repo.list_course_attendance(course_id=self.course_a)), 2)
        audit = self.repo.list_device_audit_events(course_id=self.course_a)
        self.assertEqual(audit[0]["event_type"], "manager_device_reset")

    def test_delete_course_removes_exclusive_students_but_preserves_shared_students(self) -> None:
        preview = self.repo.prepare_data_reset(
            action="delete_course",
            course_id=self.course_a,
        )
        self.assertEqual(
            [row["university_id"] for row in preview["tables"]["students"]],
            ["EXCLUSIVE"],
        )

        self.repo.execute_data_reset(
            action="delete_course",
            course_id=self.course_a,
            actor_identifier="manager",
            created_at=self.created_at,
        )

        self.assertIsNone(self.repo.get_course(self.course_a))
        self.assertIsNone(self.repo.get_student(int(self.exclusive["id"])))
        self.assertIsNotNone(self.repo.get_student(int(self.shared["id"])))
        self.assertIsNotNone(
            self.repo.get_student_for_course(self.course_b, "SHARED")
        )
        self.assertIsNotNone(self.repo.get_course(self.course_b))

    def test_full_system_reset_preserves_schema_and_records_new_audit(self) -> None:
        preview = self.repo.prepare_data_reset(action="full_system")
        self.assertEqual(preview["counts"]["courses"], 2)
        self.assertEqual(preview["counts"]["students"], 3)

        self.repo.execute_data_reset(
            action="full_system",
            actor_identifier="manager",
            created_at=self.created_at,
        )

        self.assertEqual(self.repo.list_courses(), [])
        self.repo.init_schema()
        audit = self.repo.list_data_reset_audit()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "full_system")

    def test_reset_all_students_preserves_courses_and_timetables(self) -> None:
        preview = self.repo.prepare_data_reset(action="reset_all_students")
        self.assertEqual(preview["counts"]["students"], 3)

        self.repo.execute_data_reset(
            action="reset_all_students",
            actor_identifier="manager",
            created_at=self.created_at,
        )

        self.assertEqual(len(self.repo.list_courses()), 2)
        self.assertEqual(len(self.repo.list_schedules_for_course(self.course_a)), 1)
        self.assertEqual(len(self.repo.list_schedules_for_course(self.course_b)), 1)
        self.assertEqual(self.repo.list_students_for_course(self.course_a), [])
        self.assertEqual(self.repo.list_students_for_course(self.course_b), [])
        self.assertEqual(self.repo.list_course_attendance(course_id=self.course_a), [])
        self.assertIsNone(
            self.repo.get_registered_device_for_student(int(self.exclusive["id"]))
        )

    def test_reset_all_course_activity_preserves_rosters_and_devices(self) -> None:
        preview = self.repo.prepare_data_reset(action="reset_all_course_activity")
        self.assertEqual(preview["counts"]["course_schedules"], 2)
        self.assertEqual(preview["counts"]["attendance_records"], 3)

        self.repo.execute_data_reset(
            action="reset_all_course_activity",
            actor_identifier="manager",
            created_at=self.created_at,
        )

        self.assertEqual(len(self.repo.list_courses()), 2)
        self.assertEqual(len(self.repo.list_students_for_course(self.course_a)), 2)
        self.assertEqual(len(self.repo.list_students_for_course(self.course_b)), 2)
        self.assertEqual(self.repo.list_schedules_for_course(self.course_a), [])
        self.assertEqual(self.repo.list_schedules_for_course(self.course_b), [])
        self.assertEqual(self.repo.list_course_attendance(course_id=self.course_a), [])
        self.assertIsNotNone(
            self.repo.get_registered_device_for_student(int(self.exclusive["id"]))
        )

    def _create_course(self, code: str) -> int:
        self.repo.create_course(
            code=code,
            title=code,
            start_date="2026-09-01",
            end_date="2026-12-01",
            total_meetings=10,
            latitude=1.0,
            longitude=1.0,
            radius_m=50.0,
            absence_limit_pct=20.0,
            created_at=self.created_at,
        )
        course = self.repo.get_course_by_code(code)
        assert course is not None
        return int(course["id"])

    def _add_student(self, course_id: int, name: str, university_id: str) -> None:
        self.repo.add_student_to_course(
            course_id=course_id,
            full_name=name,
            university_id=university_id,
            email=f"{university_id.lower()}@example.edu",
            phone="",
            created_at=self.created_at,
        )

    def _add_schedule(self, course_id: int, label: str) -> int:
        self.repo.add_schedule(
            course_id=course_id,
            weekday=1,
            label=label,
            start_time="09:00",
            end_time="10:00",
            created_at=self.created_at,
        )
        return int(self.repo.list_schedules_for_course(course_id)[0]["id"])

    def _add_device(self, student_id: int, token: str) -> int:
        return self.repo.create_registered_device(
            student_id=student_id,
            credential_id=f"{token}-credential",
            public_key=f"{token}-public-key",
            sign_count=0,
            device_binding_hash=f"{token}-binding",
            transports="[]",
            aaguid="",
            credential_device_type="single_device",
            credential_backed_up=False,
            created_at=self.created_at,
        )

    def _add_attendance(
        self,
        course_id: int,
        student_id: int,
        schedule_id: int,
        device_id: int,
        token: str,
    ) -> None:
        self.repo.record_attendance(
            course_id=course_id,
            student_id=student_id,
            schedule_id=schedule_id,
            attendance_date="2026-09-01",
            stamped_at=self.created_at,
            student_latitude=1.0,
            student_longitude=1.0,
            accuracy_m=5.0,
            distance_m=1.0,
            device_info="{}",
            registered_device_id=device_id,
            device_binding_hash=f"{token}-binding",
        )


if __name__ == "__main__":
    unittest.main()
