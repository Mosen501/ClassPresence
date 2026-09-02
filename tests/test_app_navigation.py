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

from app import (
    MANAGER_SECTIONS,
    STUDENT_RTL_CSS,
    STUDENT_SECTION_LABELS,
    STUDENT_SECTIONS,
    _student_message,
)
from attendance_app.components import geo_capture, passkey_action
from attendance_app.database import AttendanceRepository, DatabaseUnavailableError

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
PASSKEY_COMPONENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "attendance_app"
    / "frontend"
    / "passkey"
    / "index.html"
)
GEO_COMPONENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "attendance_app"
    / "frontend"
    / "geo_capture"
    / "index.html"
)


class AppNavigationTestCase(unittest.TestCase):
    def test_database_outage_shows_retry_panel_instead_of_traceback(self) -> None:
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
                app.session_state["active_role"] = "manager"
                app.session_state["manager_auth"] = {"username": "manager"}

                with patch.object(
                    AttendanceRepository,
                    "list_courses",
                    side_effect=DatabaseUnavailableError("temporary outage"),
                ):
                    app.run(timeout=30)

                self.assertEqual(len(app.exception), 0)
                self.assertIn(
                    "Retry database connection",
                    [button.label for button in app.button],
                )
                self.assertTrue(
                    any(
                        "database connection was briefly interrupted" in error.value
                        for error in app.error
                    )
                )

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
        self.assertEqual(app_source.count("resolve_active_student_session("), 1)

    def test_location_component_reports_structured_browser_failures(self) -> None:
        component_html = GEO_COMPONENT_PATH.read_text()

        for reason in ("permission_denied", "timeout", "unavailable", "unsupported"):
            self.assertIn(f'"{reason}"', component_html)
        self.assertIn("error_code: errorCode", component_html)

    def test_manager_location_diagnostics_exposes_full_workflow(self) -> None:
        app_source = APP_PATH.read_text()

        self.assertIn("Location", MANAGER_SECTIONS)
        for message in (
            "Location diagnostics",
            "Outside radius",
            "Permission denied",
            "GPS timeout",
            "Classroom reference",
            "Instructor calibration",
            "Apply calibrated classroom point",
            "Prepare location diagnostics Excel",
            "automatically removed after 30 days",
        ):
            self.assertIn(message, app_source)
        self.assertIn("repo.anonymize_location_coordinates_before(", app_source)
        self.assertIn("analyze_classroom_reference(course, events)", app_source)

    def test_repository_initialization_is_cached_as_a_resource(self) -> None:
        app_source = APP_PATH.read_text()

        self.assertIn("@st.cache_resource(show_spinner=False)", app_source)
        self.assertIn("AttendanceRepository(database_target, use_pool=True)", app_source)
        self.assertNotIn("st.cache_data.clear()", app_source)
        today_start = app_source.index("def _render_manager_today")
        today_end = app_source.index("def _render_manager_timetable")
        today_source = app_source[today_start:today_end]
        self.assertIn("_cached_manager_today_snapshot", today_source)
        self.assertNotIn("_cached_list_course_attendance", today_source)

    def test_manager_settings_exposes_guarded_reset_workflow(self) -> None:
        app_source = APP_PATH.read_text()

        self.assertIn("Settings", MANAGER_SECTIONS)
        for message in (
            "Prepare reset",
            "Download reset backup",
            "Type {confirmation_target} to confirm",
            "Execute permanent reset",
            "RESET ALL DATA",
            "Manager password",
            "Data-management audit",
        ):
            self.assertIn(message, app_source)
        self.assertIn("repo.prepare_data_reset(", app_source)
        self.assertIn("repo.execute_data_reset(", app_source)
        self.assertIn("verify_password(", app_source)

    def test_manager_settings_prepares_a_scoped_backup_before_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "attendance.db")
            repo = AttendanceRepository(database_path)
            repo.init_schema()
            repo.create_course(
                code="SET101",
                title="Settings",
                start_date="2026-09-01",
                end_date="2026-12-01",
                total_meetings=10,
                latitude=1.0,
                longitude=1.0,
                radius_m=50.0,
                absence_limit_pct=20.0,
                created_at="2026-09-01T09:00:00+03:00",
            )
            with patch.dict(
                os.environ,
                {
                    "ATTENDANCE_DB_PATH": database_path,
                    "APP_ENV": "development",
                },
                clear=False,
            ):
                app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
                app.session_state["active_role"] = "manager"
                app.session_state["manager_auth"] = {"username": "manager"}
                app.session_state["manager_section"] = "Settings"
                app.run(timeout=30)

                labels = [button.label for button in app.button]
                self.assertIn("Prepare reset", labels)
                self.assertIn("Prepare full JSON backup", labels)
                self.assertIn("Clear application cache", labels)
                self._button(app, "Prepare reset").click()
                app.run(timeout=30)

                package = app.session_state["manager_reset_package"]
                self.assertEqual(package["action"], "course_attendance")
                self.assertEqual(package["scope_identifier"], "SET101")
                self.assertTrue(package["backup_bytes"].startswith(b"{"))
                self.assertIn("Execute permanent reset", [button.label for button in app.button])

    def test_manager_location_page_renders_recorded_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "attendance.db")
            repo = AttendanceRepository(database_path)
            repo.init_schema()
            repo.create_course(
                code="GEO101",
                title="Geolocation",
                start_date="2026-09-01",
                end_date="2026-12-01",
                total_meetings=10,
                latitude=1.0,
                longitude=1.0,
                radius_m=50.0,
                absence_limit_pct=20.0,
                created_at="2026-09-01T09:00:00+03:00",
            )
            course = repo.get_course_by_code("GEO101")
            assert course is not None
            repo.add_student_to_course(
                course_id=int(course["id"]),
                full_name="Location Student",
                university_id="GEO-STUDENT",
                email="geo@example.edu",
                phone="",
                created_at="2026-09-01T09:00:00+03:00",
            )
            student = repo.get_student_for_course(int(course["id"]), "GEO-STUDENT")
            assert student is not None
            repo.create_location_attempt_event(
                course_id=int(course["id"]),
                student_id=int(student["id"]),
                schedule_id=None,
                attendance_date="2026-09-01",
                attempt_type="attendance",
                outcome="rejected",
                reason_code="outside_radius",
                message="Outside radius",
                latitude=1.001,
                longitude=1.001,
                accuracy_m=10.0,
                distance_m=100.0,
                radius_m=50.0,
                captured_at="2026-09-01T09:00:00+03:00",
                sample_count=1,
                platform="iPhone",
                browser_family="Safari",
                created_at="2026-09-01T09:00:00+03:00",
            )
            with patch.dict(
                os.environ,
                {
                    "ATTENDANCE_DB_PATH": database_path,
                    "APP_ENV": "development",
                },
                clear=False,
            ):
                app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
                app.session_state["active_role"] = "manager"
                app.session_state["manager_auth"] = {"username": "manager"}
                app.session_state["manager_section"] = "Location"
                app.run(timeout=30)

                self.assertEqual(len(app.exception), 0)
                self.assertIn(
                    "Prepare location diagnostics Excel",
                    [button.label for button in app.button],
                )

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
        self.assertEqual(
            _student_message("A one-time code has been generated and shown on this page."),
            "استخدم رمز التحقق الظاهر أدناه لإكمال تسجيل الجهاز.",
        )
        self.assertEqual(
            _student_message("This code must be verified on the device that requested it."),
            "أدخل الرمز من نفس الجهاز الذي بدأت منه عملية التسجيل.",
        )
        self.assertEqual(
            _student_message("Location accuracy must be within 50 m."),
            "تعذر تحديد موقعك بدقة. تأكد من تفعيل «الموقع الدقيق»، ثم حاول مرة أخرى.",
        )
        self.assertEqual(
            _student_message("NotAllowedError: لم يكتمل طلب بيانات الاعتماد."),
            "لم يكتمل التحقق من الجهاز. حاول مرة أخرى.",
        )

    def test_student_cards_and_streamlit_containers_are_forced_to_rtl(self) -> None:
        for selector in (
            ".block-container .cp-access-card",
            ".block-container .cp-metric",
            ".block-container .cp-result-ok",
            '[data-testid="stVerticalBlockBorderWrapper"]',
            '[data-testid="stForm"]',
            '[data-testid="stAlert"]',
            '[data-testid="stDataFrame"]',
        ):
            self.assertIn(selector, STUDENT_RTL_CSS)
        self.assertIn("direction: rtl", STUDENT_RTL_CSS)
        self.assertIn("text-align: right", STUDENT_RTL_CSS)

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
                self.assertIn('class="cp-metrics compact" lang="ar" dir="rtl"', self._markdown_text(app))
                self.assertIn("بانتظار تسجيل الحضور", self._markdown_text(app))

                app.session_state["student_section"] = "Status"
                app.run(timeout=30)
                self.assertIn("أهلية الاختبار النهائي", self._markdown_text(app))
                self.assertIn("مؤهل للاختبار النهائي", self._markdown_text(app))
                self.assertIn('class="cp-metrics" lang="ar" dir="rtl"', self._markdown_text(app))

                app.session_state["student_section"] = "History"
                app.run(timeout=30)
                self.assertIn("لا توجد سجلات حضور حتى الآن.", self._markdown_text(app))
                self.assertIn('class="cp-empty-state" lang="ar" dir="rtl"', self._markdown_text(app))

    def test_student_approval_message_uses_instructor_language(self) -> None:
        app_source = APP_PATH.read_text()

        self.assertIn(
            "اطلب من مدرس المقرر الموافقة على الطلب",
            app_source,
        )
        self.assertNotIn(
            "تحقق المسؤول من هويتك حضورياً ثم يوافق على الطلب من صفحة الأمان.",
            app_source,
        )

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
