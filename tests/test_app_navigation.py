from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from inspect import signature
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from app import STUDENT_SECTION_LABELS, STUDENT_SECTIONS, _student_message
from attendance_app.components import geo_capture, passkey_action
from attendance_app.database import AttendanceRepository

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
PASSKEY_COMPONENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "attendance_app"
    / "frontend"
    / "passkey"
    / "index.html"
)


class AppNavigationTestCase(unittest.TestCase):
    def test_student_components_keep_warm_deployment_compatible_signatures(self) -> None:
        self.assertNotIn("locale", signature(geo_capture).parameters)
        self.assertNotIn("locale", signature(passkey_action).parameters)

    def test_device_registration_uses_one_passkey_first_action_with_automatic_fallback(self) -> None:
        component_html = PASSKEY_COMPONENT_PATH.read_text()

        self.assertIn('register: "Register this device"', component_html)
        self.assertIn('componentArgs.action === "browser_register_auto"', component_html)
        self.assertIn("void performAction()", component_html)
        self.assertNotIn('register: "Register with a passkey"', component_html)

    def test_attendance_uses_one_location_and_stamp_action(self) -> None:
        app_source = APP_PATH.read_text()

        self.assertIn('geo_capture(\n            "تسجيل الحضور"', app_source)
        self.assertNotIn('key="submit_attendance"', app_source)
        self.assertNotIn('"تحديد موقعي الحالي"', app_source)

    def test_student_localization_keeps_internal_navigation_values(self) -> None:
        self.assertEqual(STUDENT_SECTIONS, ["Check in", "Status", "History"])
        self.assertEqual(
            [STUDENT_SECTION_LABELS[value] for value in STUDENT_SECTIONS],
            ["تسجيل الحضور", "الحالة", "السجل"],
        )
        self.assertEqual(
            _student_message("The one-time code is invalid."),
            "رمز التحقق غير صحيح.",
        )
        self.assertEqual(
            _student_message("A one-time code has been sent to student@example.edu."),
            "تم إرسال رمز التحقق إلى student@example.edu.",
        )

    def test_authenticated_student_sections_render_in_arabic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "attendance.db")
            now = datetime.now(ZoneInfo("Asia/Riyadh"))
            repo = AttendanceRepository(database_path)
            repo.init_schema()
            repo.create_course(
                code="ARB101",
                title="Arabic Portal",
                start_date=(now.date() - timedelta(days=1)).isoformat(),
                end_date=(now.date() + timedelta(days=1)).isoformat(),
                total_meetings=10,
                latitude=24.7136,
                longitude=46.6753,
                radius_m=20,
                absence_limit_pct=20,
                created_at=now.isoformat(),
            )
            course = repo.get_course_by_code("ARB101")
            assert course is not None
            repo.add_student_to_course(
                course_id=int(course["id"]),
                full_name="Student One",
                university_id="U1001",
                email="student@example.edu",
                phone="",
                created_at=now.isoformat(),
            )
            student = repo.get_student_for_course(int(course["id"]), "U1001")
            assert student is not None
            repo.add_schedule(
                course_id=int(course["id"]),
                weekday=now.weekday(),
                label="Lecture 1",
                start_time="00:00",
                end_time="23:59",
                created_at=now.isoformat(),
            )
            schedule = repo.list_schedules_for_course(int(course["id"]))[0]
            device_id = repo.create_registered_device(
                student_id=int(student["id"]),
                credential_id="credential",
                public_key="public-key",
                sign_count=0,
                device_binding_hash="binding",
                transports="[]",
                aaguid="",
                credential_device_type="single_device",
                credential_backed_up=False,
                created_at=now.isoformat(),
            )
            with patch.dict(
                os.environ,
                {
                    "ATTENDANCE_DB_PATH": database_path,
                    "APP_ENV": "development",
                    "APP_TIMEZONE": "Asia/Riyadh",
                },
                clear=False,
            ):
                app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
                app.session_state["active_role"] = "student"
                app.session_state["student_auth"] = {
                    "course_id": int(course["id"]),
                    "student_id": int(student["id"]),
                    "device_id": device_id,
                    "credential_id": "credential",
                    "device_binding_hash": "binding",
                    "schedule_id": int(schedule["id"]),
                    "attendance_date": now.date().isoformat(),
                    "session_expires_at": now.replace(hour=23, minute=59).isoformat(),
                }
                app.run(timeout=30)

                self.assertEqual(len(app.exception), 0)
                self.assertIn("خروج", [button.label for button in app.button])
                self.assertIn("تسجيل الحضور", self._markdown_text(app))

                app.session_state["student_section"] = "Status"
                app.run(timeout=30)
                self.assertIn("أهلية الاختبار", self._markdown_text(app))

                app.session_state["student_section"] = "History"
                app.run(timeout=30)
                self.assertIn("لا توجد سجلات حضور حتى الآن.", self._markdown_text(app))

    def test_student_back_clears_id_without_mutating_rendered_widget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "attendance.db")
            with patch.dict(
                os.environ,
                {
                    "ATTENDANCE_DB_PATH": database_path,
                    "APP_ENV": "development",
                },
                clear=False,
            ):
                app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
                labels = [button.label for button in app.button]
                self.assertIn("الدخول إلى بوابة الطالب", labels)
                self.assertIn("Manager access", labels)

                self._button(app, "الدخول إلى بوابة الطالب").click()
                app.run(timeout=30)
                self.assertEqual(app.session_state["active_role"], "student")
                self.assertEqual(app.text_input[0].label, "الرقم الجامعي")

                app.text_input[0].set_value("20260001")
                app.run(timeout=30)
                self._button(app, "رجوع").click()
                app.run(timeout=30)

                self.assertEqual(len(app.exception), 0)
                self.assertIsNone(app.session_state["active_role"])

                self._button(app, "الدخول إلى بوابة الطالب").click()
                app.run(timeout=30)
                self.assertEqual(app.text_input[0].value, "")

    @staticmethod
    def _button(app: AppTest, label: str):
        return next(button for button in app.button if button.label == label)

    @staticmethod
    def _markdown_text(app: AppTest) -> str:
        return "\n".join(str(element.value) for element in app.markdown)


if __name__ == "__main__":
    unittest.main()
