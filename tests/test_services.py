from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from attendance_app.config import Settings
from attendance_app.database import BROWSER_KEY_RECOVERY_REASON, AttendanceRepository
from attendance_app.passkeys import RegisteredPasskey, VerifiedPasskey, hash_device_token
from attendance_app.services import (
    StudentAccessContext,
    authenticate_student_browser_key,
    authenticate_student_passkey,
    otp_delivery_configuration_error,
    request_login_code_for_access_context,
    request_student_browser_key_enrollment,
    request_student_browser_key_recovery,
    request_student_passkey_enrollment,
    reset_student_device,
    resolve_active_student_session,
    resolve_registered_student_access_context,
    resolve_student_access_context,
    stamp_attendance,
    verify_login_code_for_access_context,
)
from attendance_app.utils import hash_otp

TEST_COURSE_LATITUDE = 1.234567
TEST_COURSE_LONGITUDE = -2.345678


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class ServicesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = AttendanceRepository(f"{self.temp_dir.name}/attendance.db")
        self.repo.init_schema()
        self.settings = Settings(
            app_env="development",
            app_timezone="Asia/Riyadh",
            database_target=f"{self.temp_dir.name}/attendance.db",
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
                    "accuracy_m": 5,
                    "captured_at": now.isoformat(),
                    "device_token": "test-device-token-00000001",
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
                        "accuracy_m": 5,
                        "captured_at": now.isoformat(),
                        "device_token": "test-device-token-00000001",
                    },
                )

            access_context = resolve_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                geolocation_payload={
                    "latitude": new_lat,
                    "longitude": new_lon,
                    "accuracy_m": 5,
                    "captured_at": now.isoformat(),
                    "device_token": "test-device-token-00000001",
                },
            )

        self.assertAlmostEqual(access_context.course_latitude, new_lat)
        self.assertAlmostEqual(access_context.course_longitude, new_lon)
        self.assertAlmostEqual(access_context.distance_m, 0.0)

    def test_location_validation_rejects_stale_and_inaccurate_payloads(self) -> None:
        self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        base_payload = {
            "latitude": TEST_COURSE_LATITUDE,
            "longitude": TEST_COURSE_LONGITUDE,
            "accuracy_m": 5,
            "captured_at": now.isoformat(),
            "device_token": "test-device-token-00000001",
        }

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            with self.assertRaisesRegex(ValueError, "Location expired"):
                resolve_student_access_context(
                    self.repo,
                    self.settings,
                    university_id="20260001",
                    geolocation_payload={
                        **base_payload,
                        "captured_at": "2026-07-01T09:55:00+03:00",
                    },
                )
            with self.assertRaisesRegex(ValueError, "Location accuracy"):
                resolve_student_access_context(
                    self.repo,
                    self.settings,
                    university_id="20260001",
                    geolocation_payload={**base_payload, "accuracy_m": 75},
                )

    def test_passkey_registration_and_authentication_bind_one_device(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        payload = {
            "latitude": TEST_COURSE_LATITUDE,
            "longitude": TEST_COURSE_LONGITUDE,
            "accuracy_m": 5,
            "captured_at": now.isoformat(),
            "device_token": "test-device-token-00000001",
        }
        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            context = resolve_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                geolocation_payload=payload,
            )
            with patch(
                "attendance_app.services.complete_registration",
                return_value=RegisteredPasskey(
                    credential_id="credential-one",
                    public_key="public-key-one",
                    sign_count=0,
                    aaguid="test-aaguid",
                    credential_device_type="single_device",
                    credential_backed_up=False,
                    transports='["internal"]',
                ),
            ):
                pending_id = request_student_passkey_enrollment(
                    self.repo,
                    self.settings,
                    access_context=context,
                    credential={},
                    device_token=payload["device_token"],
                    expected_challenge="challenge",
                    expected_rp_id="localhost",
                    expected_origin="http://localhost:8501",
                )

            self.assertIsNone(
                self.repo.get_registered_device_for_student(int(student["id"]))
            )
            pending = self.repo.get_pending_device_enrollment(pending_id)
            assert pending is not None
            self.assertEqual(pending["auth_method"], "passkey")
            self.assertEqual(pending["credential_device_type"], "single_device")
            device_id = self.repo.approve_pending_device_enrollment(
                pending_id=pending_id,
                actor_identifier="manager_user",
                reviewed_at="2026-07-01T10:01:00+03:00",
            )

            with patch(
                "attendance_app.services.complete_authentication",
                return_value=VerifiedPasskey(
                    credential_id="credential-one",
                    sign_count=1,
                ),
            ):
                verified = authenticate_student_passkey(
                    self.repo,
                    self.settings,
                    access_context=StudentAccessContext(
                        **{**context.__dict__, "device_enrolled": True}
                    ),
                    credential={},
                    device_token="a-new-token-after-clearing-browser-storage",
                    expected_challenge="challenge",
                    expected_rp_id="localhost",
                    expected_origin="http://localhost:8501",
                )

        self.assertEqual(verified["device_id"], device_id)
        self.assertEqual(verified["trust_level"], "strict")
        self.assertEqual(verified["schedule_id"], context.schedule_id)
        self.assertEqual(verified["attendance_date"], context.attendance_date)
        self.assertEqual(verified["session_expires_at"], context.session_expires_at)
        device = self.repo.get_registered_device_for_student(int(student["id"]))
        assert device is not None
        self.assertEqual(int(device["sign_count"]), 1)
        self.assertEqual(device["auth_method"], "passkey")
        self.assertEqual(device["credential_device_type"], "single_device")
        self.assertEqual(int(device["credential_backed_up"]), 0)
        audit = self.repo.list_device_audit_events(course_id=int(course["id"]))
        self.assertEqual(audit[0]["event_type"], "manager_passkey_approved")
        auth = {
            "course_id": int(course["id"]),
            "student_id": int(student["id"]),
            **verified,
        }
        with patch(
            "attendance_app.services.now_in_app_timezone",
            return_value=datetime(2026, 7, 1, 10, 30, tzinfo=ZoneInfo("Asia/Riyadh")),
        ):
            active_course, active_student, active_schedule = resolve_active_student_session(
                self.repo,
                self.settings,
                auth=auth,
            )
        self.assertEqual(int(active_course["id"]), int(course["id"]))
        self.assertEqual(int(active_student["id"]), int(student["id"]))
        self.assertEqual(int(active_schedule["id"]), context.schedule_id)
        with patch(
            "attendance_app.services.now_in_app_timezone",
            return_value=datetime(2026, 7, 1, 11, 0, tzinfo=ZoneInfo("Asia/Riyadh")),
        ):
            with self.assertRaisesRegex(ValueError, "session has expired"):
                resolve_active_student_session(
                    self.repo,
                    self.settings,
                    auth=auth,
                )

    def test_registered_device_opens_portal_outside_lecture_without_location(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 14, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        device_token = "test-device-token-00000001"
        device_hash = hash_device_token(device_token, self.settings.otp_pepper)
        device_id = self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="credential-one",
            public_key="public-key-one",
            sign_count=0,
            device_binding_hash=device_hash,
            transports="[]",
            aaguid="",
            credential_device_type="single_device",
            credential_backed_up=False,
            created_at=now.isoformat(),
        )

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            context = resolve_registered_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                course_id=int(course["id"]),
            )
            with patch(
                "attendance_app.services.complete_authentication",
                return_value=VerifiedPasskey(credential_id="credential-one", sign_count=1),
            ):
                verified = authenticate_student_passkey(
                    self.repo,
                    self.settings,
                    access_context=context,
                    credential={},
                    device_token=device_token,
                    expected_challenge="challenge",
                    expected_rp_id="localhost",
                    expected_origin="http://localhost:8501",
                )
            active_course, active_student, active_schedule = resolve_active_student_session(
                self.repo,
                self.settings,
                auth={
                    "course_id": int(course["id"]),
                    "student_id": int(student["id"]),
                    **verified,
                },
            )

        self.assertEqual(context.purpose, "portal")
        self.assertEqual(context.schedule_id, 0)
        self.assertEqual(int(active_course["id"]), int(course["id"]))
        self.assertEqual(int(active_student["id"]), int(student["id"]))
        self.assertIsNone(active_schedule)
        self.assertEqual(verified["device_id"], device_id)

    def test_attendance_stamp_uses_fresh_location_with_portal_device_session(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 15, tzinfo=ZoneInfo("Asia/Riyadh"))
        device_token = "test-device-token-00000001"
        device_hash = hash_device_token(device_token, self.settings.otp_pepper)
        device_id = self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="credential-one",
            public_key="public-key-one",
            sign_count=0,
            device_binding_hash=device_hash,
            transports="[]",
            aaguid="",
            credential_device_type="single_device",
            credential_backed_up=False,
            created_at=now.isoformat(),
        )

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            result = stamp_attendance(
                self.repo,
                self.settings,
                course=course,
                student=student,
                geolocation_payload={
                    "latitude": TEST_COURSE_LATITUDE,
                    "longitude": TEST_COURSE_LONGITUDE,
                    "accuracy_m": 5,
                    "sample_count": 3,
                    "captured_at": now.isoformat(),
                    "device_token": "fresh-location-component-token-after-browser-cleanup",
                },
                verified_device={
                    "device_id": device_id,
                    "credential_id": "credential-one",
                    "device_binding_hash": device_hash,
                    "auth_method": "passkey",
                    "session_expires_at": "2026-07-01T22:00:00+03:00",
                },
            )

        self.assertTrue(result.success)
        self.assertIn("Attendance stamped successfully", result.message)
        self.assertEqual(
            self.repo.count_attendance(
                course_id=int(course["id"]),
                student_id=int(student["id"]),
            ),
            1,
        )

    def test_browser_key_fallback_requires_manager_approval_and_authenticates(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        device_token = "test-browser-key-device-00001"
        payload = {
            "latitude": TEST_COURSE_LATITUDE,
            "longitude": TEST_COURSE_LONGITUDE,
            "accuracy_m": 5,
            "captured_at": now.isoformat(),
            "device_token": device_token,
        }
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_key = _base64url(public_key_bytes)
        credential_id = _base64url(hashlib.sha256(public_key_bytes).digest())

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            context = resolve_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                geolocation_payload=payload,
            )
            pending_id = request_student_browser_key_enrollment(
                self.repo,
                self.settings,
                access_context=context,
                credential_id=credential_id,
                public_key=public_key,
                device_token=device_token,
                fallback_reason="NotAllowedError: iCloud Keychain is unavailable",
            )

        self.assertIsNone(self.repo.get_registered_device_for_student(int(student["id"])))
        pending = self.repo.list_pending_browser_enrollments(course_id=int(course["id"]))
        self.assertEqual([int(row["id"]) for row in pending], [pending_id])
        self.assertEqual(
            pending[0]["fallback_reason"],
            "NotAllowedError: iCloud Keychain is unavailable",
        )

        device_id = self.repo.approve_pending_browser_enrollment(
            pending_id=pending_id,
            actor_identifier="manager_user",
            reviewed_at="2026-07-01T10:01:00+03:00",
        )
        message_bytes = b"signed-browser-key-lecture-message"
        signature = private_key.sign(message_bytes, ec.ECDSA(hashes.SHA256()))
        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            verified = authenticate_student_browser_key(
                self.repo,
                self.settings,
                access_context=StudentAccessContext(
                    **{**context.__dict__, "device_enrolled": True}
                ),
                credential_id=credential_id,
                signature=_base64url(signature),
                message=_base64url(message_bytes),
                device_token=device_token,
            )

        self.assertEqual(verified["device_id"], device_id)
        device = self.repo.get_registered_device_for_student(int(student["id"]))
        assert device is not None
        self.assertEqual(device["auth_method"], "browser_key")
        self.assertEqual(int(device["sign_count"]), 1)
        audit = self.repo.list_device_audit_events(course_id=int(course["id"]))
        self.assertEqual(audit[0]["event_type"], "manager_device_approved")
        self.assertEqual(audit[0]["actor_identifier"], "manager_user")

    def test_legacy_browser_registration_expires_at_course_end(self) -> None:
        course, student = self._seed_course(end_date="2026-07-31")
        now = datetime(2026, 8, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        device_token = "test-browser-key-device-00001"
        self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="legacy-browser-credential",
            public_key="legacy-browser-public-key",
            sign_count=0,
            device_binding_hash=hash_device_token(
                device_token,
                self.settings.otp_pepper,
            ),
            transports="[]",
            aaguid="",
            credential_device_type="device_credential",
            credential_backed_up=False,
            created_at="2026-07-01T10:00:00+03:00",
            auth_method="browser_key",
        )

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            context = resolve_registered_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                course_id=int(course["id"]),
            )
            with self.assertRaisesRegex(ValueError, "expired at the end of the course"):
                authenticate_student_browser_key(
                    self.repo,
                    self.settings,
                    access_context=context,
                    credential_id="legacy-browser-credential",
                    signature="unused",
                    message="unused",
                    device_token=device_token,
                )

    def test_missing_browser_key_can_be_recovered_on_same_registered_device(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        device_token = "test-browser-key-device-00001"
        device_hash = hash_device_token(device_token, self.settings.otp_pepper)
        original_device_id = self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="original-browser-credential",
            public_key="original-browser-public-key",
            sign_count=4,
            device_binding_hash=device_hash,
            transports="[]",
            aaguid="",
            credential_device_type="device_credential",
            credential_backed_up=False,
            created_at=now.isoformat(),
            auth_method="browser_key",
        )
        replacement_private_key = ec.generate_private_key(ec.SECP256R1())
        replacement_public_key_bytes = replacement_private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        replacement_public_key = _base64url(replacement_public_key_bytes)
        replacement_credential_id = _base64url(
            hashlib.sha256(replacement_public_key_bytes).digest()
        )

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            context = resolve_registered_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                course_id=int(course["id"]),
            )
            pending_id = request_student_browser_key_recovery(
                self.repo,
                self.settings,
                access_context=context,
                credential_id=replacement_credential_id,
                public_key=replacement_public_key,
                device_token=device_token,
            )

        pending = self.repo.get_pending_browser_enrollment(pending_id)
        assert pending is not None
        self.assertEqual(pending["fallback_reason"], BROWSER_KEY_RECOVERY_REASON)
        before_approval = self.repo.get_registered_device_for_student(int(student["id"]))
        assert before_approval is not None
        self.assertEqual(int(before_approval["id"]), original_device_id)
        self.assertEqual(before_approval["credential_id"], "original-browser-credential")

        approved_device_id = self.repo.approve_pending_browser_enrollment(
            pending_id=pending_id,
            actor_identifier="manager_user",
            reviewed_at="2026-07-01T10:01:00+03:00",
        )

        self.assertEqual(approved_device_id, original_device_id)
        recovered_device = self.repo.get_registered_device_for_student(int(student["id"]))
        assert recovered_device is not None
        self.assertEqual(int(recovered_device["id"]), original_device_id)
        self.assertEqual(recovered_device["credential_id"], replacement_credential_id)
        self.assertEqual(int(recovered_device["sign_count"]), 0)

        message_bytes = b"recovered-browser-key-message"
        signature = replacement_private_key.sign(
            message_bytes,
            ec.ECDSA(hashes.SHA256()),
        )
        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            verified = authenticate_student_browser_key(
                self.repo,
                self.settings,
                access_context=context,
                credential_id=replacement_credential_id,
                signature=_base64url(signature),
                message=_base64url(message_bytes),
                device_token=device_token,
            )

        self.assertEqual(verified["device_id"], original_device_id)
        audit = self.repo.list_device_audit_events(course_id=int(course["id"]))
        self.assertEqual(audit[0]["event_type"], "manager_browser_key_recovered")
        self.assertEqual(audit[0]["previous_device_id"], original_device_id)
        self.assertEqual(audit[0]["new_device_id"], original_device_id)

    def test_browser_key_recovery_rejects_an_unrecognized_browser(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        registered_token = "test-browser-key-device-00001"
        self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="original-browser-credential",
            public_key="original-browser-public-key",
            sign_count=0,
            device_binding_hash=hash_device_token(
                registered_token,
                self.settings.otp_pepper,
            ),
            transports="[]",
            aaguid="",
            credential_device_type="device_credential",
            credential_backed_up=False,
            created_at=now.isoformat(),
            auth_method="browser_key",
        )
        replacement_private_key = ec.generate_private_key(ec.SECP256R1())
        replacement_public_key_bytes = replacement_private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            context = resolve_registered_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                course_id=int(course["id"]),
            )
            with self.assertRaisesRegex(ValueError, "not the registered device"):
                request_student_browser_key_recovery(
                    self.repo,
                    self.settings,
                    access_context=context,
                    credential_id=_base64url(
                        hashlib.sha256(replacement_public_key_bytes).digest()
                    ),
                    public_key=_base64url(replacement_public_key_bytes),
                    device_token="a-different-browser-device-token",
                )

        self.assertEqual(
            self.repo.list_pending_browser_enrollments(course_id=int(course["id"])),
            [],
        )
        alerts = self.repo.list_proxy_alerts(course_id=int(course["id"]))
        self.assertEqual(
            alerts[0]["alert_type"],
            "browser_key_recovery_from_unrecognized_device",
        )

    def test_registered_device_blocks_another_student_and_creates_alert(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        device_hash = hash_device_token(
            "test-device-token-00000001",
            self.settings.otp_pepper,
        )
        self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="credential-one",
            public_key="public-key-one",
            sign_count=0,
            device_binding_hash=device_hash,
            transports="[]",
            aaguid="",
            credential_device_type="single_device",
            credential_backed_up=False,
            created_at=now.isoformat(),
        )
        self.repo.add_student_to_course(
            course_id=int(course["id"]),
            full_name="SECOND STUDENT",
            university_id="20260002",
            email="second@example.edu",
            phone="",
            created_at=now.isoformat(),
        )

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            with self.assertRaisesRegex(ValueError, "already registered to another student"):
                resolve_student_access_context(
                    self.repo,
                    self.settings,
                    university_id="20260002",
                    geolocation_payload={
                        "latitude": TEST_COURSE_LATITUDE,
                        "longitude": TEST_COURSE_LONGITUDE,
                        "accuracy_m": 5,
                        "captured_at": now.isoformat(),
                        "device_token": "test-device-token-00000001",
                    },
                )

        alerts = self.repo.list_proxy_alerts(course_id=int(course["id"]))
        self.assertEqual(alerts[0]["alert_type"], "device_linked_to_another_student")

    def test_otp_is_rejected_on_a_different_device(self) -> None:
        course, student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        self.repo.create_otp(
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            code_hash=hash_otp("123456", self.settings.otp_pepper),
            delivery_method="email",
            delivery_target="masa@example.edu",
            expires_at=datetime(2026, 7, 1, 10, 10, tzinfo=ZoneInfo("Asia/Riyadh")).isoformat(),
            created_at=now.isoformat(),
            device_binding_hash="expected-device-hash",
            credential_id="credential-one",
            schedule_id=int(self.repo.list_schedules_for_course(int(course["id"]))[0]["id"]),
            attendance_date="2026-07-01",
        )
        schedule = self.repo.list_schedules_for_course(int(course["id"]))[0]

        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            with self.assertRaisesRegex(ValueError, "device that requested it"):
                verify_login_code_for_access_context(
                    self.repo,
                    self.settings,
                    course_id=int(course["id"]),
                    student_id=int(student["id"]),
                    code="123456",
                    device_binding_hash="different-device-hash",
                    credential_id="credential-one",
                    schedule_id=int(schedule["id"]),
                    attendance_date="2026-07-01",
                )

    def test_otp_is_bound_to_schedule_and_expires_at_window_end(self) -> None:
        course, _student = self._seed_course()
        now = datetime(2026, 7, 1, 10, 55, tzinfo=ZoneInfo("Asia/Riyadh"))
        payload = {
            "latitude": TEST_COURSE_LATITUDE,
            "longitude": TEST_COURSE_LONGITUDE,
            "accuracy_m": 5,
            "captured_at": now.isoformat(),
            "device_token": "test-device-token-00000001",
        }
        with patch("attendance_app.services.now_in_app_timezone", return_value=now):
            context = resolve_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                geolocation_payload=payload,
            )
            request_login_code_for_access_context(
                self.repo,
                self.settings,
                access_context=context,
            )

        otp = self.repo.get_latest_active_otp(
            course_id=int(course["id"]),
            student_id=context.student_id,
            now_iso=now.isoformat(),
        )
        assert otp is not None
        self.assertEqual(int(otp["schedule_id"]), context.schedule_id)
        self.assertEqual(otp["attendance_date"], context.attendance_date)
        self.assertEqual(otp["expires_at"], context.session_expires_at)

    def test_otp_from_previous_window_is_rejected_in_next_window(self) -> None:
        course, student = self._seed_course()
        first_schedule = self.repo.list_schedules_for_course(int(course["id"]))[0]
        self.repo.add_schedule(
            course_id=int(course["id"]),
            weekday=2,
            label="Second Lecture",
            start_time="11:01",
            end_time="12:00",
            created_at="2026-07-01T08:00:00+03:00",
        )
        second_schedule = self.repo.list_schedules_for_course(int(course["id"]))[1]
        self.repo.create_otp(
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            code_hash=hash_otp("123456", self.settings.otp_pepper),
            delivery_method="email",
            delivery_target="masa@example.edu",
            expires_at="2026-07-01T11:10:00+03:00",
            created_at="2026-07-01T10:59:00+03:00",
            device_binding_hash="expected-device-hash",
            credential_id="credential-one",
            schedule_id=int(first_schedule["id"]),
            attendance_date="2026-07-01",
        )

        with patch(
            "attendance_app.services.now_in_app_timezone",
            return_value=datetime(2026, 7, 1, 11, 5, tzinfo=ZoneInfo("Asia/Riyadh")),
        ):
            with self.assertRaisesRegex(ValueError, "different lecture window"):
                verify_login_code_for_access_context(
                    self.repo,
                    self.settings,
                    course_id=int(course["id"]),
                    student_id=int(student["id"]),
                    code="123456",
                    device_binding_hash="expected-device-hash",
                    credential_id="credential-one",
                    schedule_id=int(second_schedule["id"]),
                    attendance_date="2026-07-01",
                )

    def test_passkey_proof_from_previous_window_cannot_request_next_otp(self) -> None:
        course, student = self._seed_course()
        first_schedule = self.repo.list_schedules_for_course(int(course["id"]))[0]
        self.repo.add_schedule(
            course_id=int(course["id"]),
            weekday=2,
            label="Second Lecture",
            start_time="11:01",
            end_time="12:00",
            created_at="2026-07-01T08:00:00+03:00",
        )
        device_hash = hash_device_token(
            "test-device-token-00000001",
            self.settings.otp_pepper,
        )
        device_id = self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="credential-one",
            public_key="public-key-one",
            sign_count=0,
            device_binding_hash=device_hash,
            transports="[]",
            aaguid="",
            credential_device_type="single_device",
            credential_backed_up=False,
            created_at="2026-07-01T08:00:00+03:00",
        )
        next_window = datetime(2026, 7, 1, 11, 5, tzinfo=ZoneInfo("Asia/Riyadh"))
        with patch("attendance_app.services.now_in_app_timezone", return_value=next_window):
            context = resolve_student_access_context(
                self.repo,
                self.settings,
                university_id="20260001",
                geolocation_payload={
                    "latitude": TEST_COURSE_LATITUDE,
                    "longitude": TEST_COURSE_LONGITUDE,
                    "accuracy_m": 5,
                    "captured_at": next_window.isoformat(),
                    "device_token": "test-device-token-00000001",
                },
            )
            with self.assertRaisesRegex(ValueError, "device again"):
                request_login_code_for_access_context(
                    self.repo,
                    self.settings,
                    access_context=context,
                    verified_device={
                        "device_id": device_id,
                        "credential_id": "credential-one",
                        "device_binding_hash": device_hash,
                        "schedule_id": int(first_schedule["id"]),
                        "attendance_date": "2026-07-01",
                        "session_expires_at": "2026-07-01T11:00:00+03:00",
                    },
                )

    def test_device_reset_is_allowed_during_lecture_and_audited(self) -> None:
        course, student = self._seed_course()
        device_id = self.repo.create_registered_device(
            student_id=int(student["id"]),
            credential_id="credential-one",
            public_key="public-key-one",
            sign_count=0,
            device_binding_hash="registered-device-hash",
            transports="[]",
            aaguid="",
            credential_device_type="single_device",
            credential_backed_up=False,
            created_at="2026-07-01T08:00:00+03:00",
        )
        self.assertGreater(device_id, 0)

        with patch(
            "attendance_app.services.now_in_app_timezone",
            return_value=datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Riyadh")),
        ):
            self.assertTrue(
                reset_student_device(
                    self.repo,
                    self.settings,
                    student_id=int(student["id"]),
                    course_id=int(course["id"]),
                    actor_identifier="manager_user",
                    reason="Student replaced the registered phone",
                )
            )

        self.assertIsNone(self.repo.get_registered_device_for_student(int(student["id"])))
        audit = self.repo.list_device_audit_events(course_id=int(course["id"]))
        self.assertEqual(audit[0]["event_type"], "manager_device_reset")
        self.assertEqual(audit[0]["actor_identifier"], "manager_user")
        self.assertEqual(audit[0]["reason"], "Student replaced the registered phone")
        self.assertEqual(int(audit[0]["previous_device_id"]), device_id)
        audited_student_name = audit[0]["student_name"]
        self.repo.sync_course_roster(
            course_id=int(course["id"]),
            roster_rows=[],
            created_at="2026-07-01T12:01:00+03:00",
        )
        permanent_audit = self.repo.list_device_audit_events(course_id=int(course["id"]))
        self.assertEqual(len(permanent_audit), 1)
        self.assertEqual(permanent_audit[0]["student_name"], audited_student_name)

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

    def test_otp_delivery_configuration_error_accepts_console_mode(self) -> None:
        production_settings = Settings(
            app_env="production",
            app_timezone="Asia/Riyadh",
            database_target=f"{self.temp_dir.name}/attendance.db",
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

        self.assertIsNone(otp_delivery_configuration_error(production_settings))

    def test_otp_delivery_configuration_error_accepts_complete_email_settings(self) -> None:
        email_settings = Settings(
            app_env="production",
            app_timezone="Asia/Riyadh",
            database_target=f"{self.temp_dir.name}/attendance.db",
            manager_username="manager_user",
            manager_password_hash="unused",
            otp_delivery_mode="email",
            otp_expiry_minutes=10,
            otp_pepper="pepper",
            smtp_host="smtp.example.edu",
            smtp_port=587,
            smtp_username="mailer@example.edu",
            smtp_password="password",
            smtp_sender="mailer@example.edu",
            smtp_use_tls=True,
        )

        self.assertIsNone(otp_delivery_configuration_error(email_settings))

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
