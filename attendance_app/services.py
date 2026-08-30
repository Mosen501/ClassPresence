from __future__ import annotations

import hmac
import json
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from attendance_app.config import Settings
from attendance_app.database import AttendanceRepository
from attendance_app.passkeys import (
    complete_authentication,
    complete_registration,
    hash_device_token,
)
from attendance_app.utils import (
    AttendanceSummary,
    build_attendance_summary,
    generate_expected_occurrences,
    generate_otp,
    hash_otp,
    haversine_distance_m,
    parse_hhmm,
    parse_iso_date,
)


@dataclass(frozen=True)
class OTPRequestResult:
    message: str
    preview_code: str | None = None


@dataclass(frozen=True)
class AttendanceStampResult:
    success: bool
    message: str
    distance_m: float | None = None


@dataclass(frozen=True)
class StudentAccessContext:
    course_id: int
    course_code: str
    course_title: str
    course_latitude: float
    course_longitude: float
    student_id: int
    student_name: str
    student_university_id: str
    student_email: str
    schedule_id: int
    schedule_label: str
    schedule_start_time: str
    schedule_end_time: str
    distance_m: float
    radius_m: float
    device_binding_hash: str
    device_enrolled: bool


def otp_delivery_configuration_error(settings: Settings) -> str | None:
    if settings.otp_delivery_mode == "console":
        return None

    if settings.otp_delivery_mode != "email":
        return (
            "Unsupported OTP delivery mode. Use `email` for production deployments or `console` "
            "only for local development."
        )

    if not settings.smtp_host or not settings.smtp_sender:
        return (
            "Email OTP is enabled, but SMTP settings are incomplete. Add `SMTP_HOST`, "
            "`SMTP_SENDER`, and any required SMTP credentials in Streamlit secrets."
        )
    return None


def now_in_app_timezone(settings: Settings) -> datetime:
    return datetime.now(ZoneInfo(settings.app_timezone))


def request_login_code(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course_code: str,
    university_id: str,
) -> OTPRequestResult:
    course = repo.get_course_by_code(course_code.strip().upper())
    if course is None:
        raise ValueError("Course code was not found.")

    student = repo.get_student_for_course(int(course["id"]), university_id.strip())
    if student is None:
        raise ValueError("Student is not enrolled in that course.")

    return _issue_login_code(
        repo,
        settings,
        course=course,
        student=student,
    )


def resolve_student_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    university_id: str,
    geolocation_payload: dict,
) -> StudentAccessContext:
    if "error" in geolocation_payload:
        raise ValueError(str(geolocation_payload["error"]))

    student_contexts = repo.list_course_contexts_for_student(university_id.strip())
    if not student_contexts:
        raise ValueError("Student ID was not found in any course roster.")

    now = now_in_app_timezone(settings)
    latitude, longitude, _accuracy_m, device_binding_hash = _validate_location_payload(
        geolocation_payload,
        settings,
        now,
    )

    active_but_outside: list[tuple] = []
    eligible_contexts: list[StudentAccessContext] = []

    for context in student_contexts:
        if not _course_is_active_today(context, now):
            continue
        schedules = repo.list_schedules_for_course(int(context["id"]))
        active_schedule = find_active_schedule(schedules, now)
        if active_schedule is None:
            continue

        distance_m = haversine_distance_m(
            float(context["latitude"]),
            float(context["longitude"]),
            latitude,
            longitude,
        )
        if distance_m > float(context["radius_m"]):
            active_but_outside.append((context, active_schedule, distance_m))
            continue

        eligible_contexts.append(
            StudentAccessContext(
                course_id=int(context["id"]),
                course_code=str(context["code"]),
                course_title=str(context["title"]),
                course_latitude=float(context["latitude"]),
                course_longitude=float(context["longitude"]),
                student_id=int(context["student_id"]),
                student_name=str(context["student_name"]),
                student_university_id=str(context["university_id"]),
                student_email=str(context["email"] or ""),
                schedule_id=int(active_schedule["id"]),
                schedule_label=str(active_schedule["label"]),
                schedule_start_time=str(active_schedule["start_time"]),
                schedule_end_time=str(active_schedule["end_time"]),
                distance_m=distance_m,
                radius_m=float(context["radius_m"]),
                device_binding_hash=device_binding_hash,
                device_enrolled=False,
            )
        )

    if eligible_contexts:
        eligible_contexts.sort(key=lambda item: (item.distance_m, item.course_code))
        selected = eligible_contexts[0]
        registered_device = repo.get_registered_device_for_student(selected.student_id)
        conflicting_device = repo.get_registered_device_by_binding_hash(device_binding_hash)
        if (
            conflicting_device is not None
            and int(conflicting_device["student_id"]) != selected.student_id
        ):
            _record_proxy_alert(
                repo,
                now=now,
                course_id=selected.course_id,
                student_id=selected.student_id,
                schedule_id=selected.schedule_id,
                alert_type="device_linked_to_another_student",
                severity="high",
                message="This device is already registered to another student.",
                device_binding_hash=device_binding_hash,
                geolocation_payload=geolocation_payload,
            )
            raise ValueError("This device is already registered to another student.")
        if (
            registered_device is not None
            and not hmac.compare_digest(
                str(registered_device["device_binding_hash"]),
                device_binding_hash,
            )
        ):
            _record_proxy_alert(
                repo,
                now=now,
                course_id=selected.course_id,
                student_id=selected.student_id,
                schedule_id=selected.schedule_id,
                alert_type="unrecognized_device",
                severity="high",
                message="A non-registered device attempted to access this student account.",
                device_binding_hash=device_binding_hash,
                geolocation_payload=geolocation_payload,
            )
            raise ValueError("Use your registered device or ask the manager to reset it.")
        return StudentAccessContext(
            **{
                **selected.__dict__,
                "device_enrolled": registered_device is not None,
            }
        )

    if active_but_outside:
        nearest = min(active_but_outside, key=lambda item: item[2])
        _, active_schedule, distance_m = nearest
        raise ValueError(
            f"You are not in class. You are {distance_m:.2f} m away from the classroom for "
            f"{active_schedule['label']}."
        )

    raise ValueError(
        "No class is active for your student ID right now. Student access is only available "
        "during the current timetable window."
    )


def request_login_code_for_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    access_context: StudentAccessContext,
    verified_device: dict | None = None,
) -> OTPRequestResult:
    course = repo.get_course(access_context.course_id)
    student = repo.get_student(access_context.student_id)
    if course is None or student is None:
        raise ValueError("Student access context is no longer valid.")

    registered_device = repo.get_registered_device_for_student(access_context.student_id)
    credential_id = None
    if registered_device is not None:
        if not verified_device:
            raise ValueError("Verify the registered device before requesting a code.")
        if (
            int(verified_device.get("device_id", 0)) != int(registered_device["id"])
            or not hmac.compare_digest(
                str(verified_device.get("device_binding_hash", "")),
                str(registered_device["device_binding_hash"]),
            )
        ):
            raise ValueError("The verified passkey does not match this student device.")
        credential_id = str(registered_device["credential_id"])

    return _issue_login_code(
        repo,
        settings,
        course=course,
        student=student,
        device_binding_hash=access_context.device_binding_hash,
        credential_id=credential_id,
    )


def verify_login_code_for_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course_id: int,
    student_id: int,
    code: str,
    device_binding_hash: str | None = None,
    credential_id: str | None = None,
):
    course = repo.get_course(course_id)
    if course is None:
        raise ValueError("Course was not found.")

    student = repo.get_student(student_id)
    if student is None:
        raise ValueError("Student was not found.")

    now = now_in_app_timezone(settings)
    if not _course_is_active_today(course, now):
        raise ValueError("This course is not active today.")

    schedules = repo.list_schedules_for_course(int(course["id"]))
    if find_active_schedule(schedules, now) is None:
        raise ValueError("Student access is closed right now. Request a new code during class.")

    otp_record = repo.get_latest_active_otp(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        now_iso=now.isoformat(),
    )
    if otp_record is None:
        raise ValueError("No active login code was found. Generate a new code.")

    expected_device_hash = str(otp_record.get("device_binding_hash") or "")
    if expected_device_hash and not hmac.compare_digest(
        expected_device_hash,
        str(device_binding_hash or ""),
    ):
        raise ValueError("This code must be verified on the device that requested it.")
    expected_credential_id = str(otp_record.get("credential_id") or "")
    if expected_credential_id and not hmac.compare_digest(
        expected_credential_id,
        str(credential_id or ""),
    ):
        raise ValueError("This code is not bound to the verified passkey.")

    if hash_otp(code.strip(), settings.otp_pepper) != otp_record["code_hash"]:
        raise ValueError("The one-time code is invalid.")

    repo.mark_otp_used(int(otp_record["id"]), now.isoformat())
    return course, student


def register_student_passkey(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    access_context: StudentAccessContext,
    credential: dict,
    device_token: str,
    expected_challenge: str,
    expected_rp_id: str,
    expected_origin: str,
) -> dict:
    now = now_in_app_timezone(settings)
    device_binding_hash = hash_device_token(device_token, settings.otp_pepper)
    if not hmac.compare_digest(device_binding_hash, access_context.device_binding_hash):
        _record_proxy_alert(
            repo,
            now=now,
            course_id=access_context.course_id,
            student_id=access_context.student_id,
            schedule_id=access_context.schedule_id,
            alert_type="device_changed_during_registration",
            severity="high",
            message="The browser identity changed during passkey registration.",
            device_binding_hash=device_binding_hash,
        )
        raise ValueError("Device identity changed. Start the check-in again.")

    existing_for_student = repo.get_registered_device_for_student(access_context.student_id)
    if existing_for_student is not None:
        raise ValueError("This student already has a registered device.")
    existing_for_device = repo.get_registered_device_by_binding_hash(device_binding_hash)
    if existing_for_device is not None:
        _record_proxy_alert(
            repo,
            now=now,
            course_id=access_context.course_id,
            student_id=access_context.student_id,
            schedule_id=access_context.schedule_id,
            alert_type="device_linked_to_another_student",
            severity="high",
            message="A device registration was blocked because it belongs to another student.",
            device_binding_hash=device_binding_hash,
        )
        raise ValueError("This device is already registered to another student.")

    passkey = complete_registration(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=expected_rp_id,
        expected_origin=expected_origin,
    )
    device_id = repo.create_registered_device(
        student_id=access_context.student_id,
        credential_id=passkey.credential_id,
        public_key=passkey.public_key,
        sign_count=passkey.sign_count,
        device_binding_hash=device_binding_hash,
        transports=passkey.transports,
        aaguid=passkey.aaguid,
        credential_device_type=passkey.credential_device_type,
        credential_backed_up=passkey.credential_backed_up,
        created_at=now.isoformat(),
    )
    return {
        "device_id": device_id,
        "credential_id": passkey.credential_id,
        "device_binding_hash": device_binding_hash,
    }


def authenticate_student_passkey(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    access_context: StudentAccessContext,
    credential: dict,
    device_token: str,
    expected_challenge: str,
    expected_rp_id: str,
    expected_origin: str,
) -> dict:
    now = now_in_app_timezone(settings)
    device = repo.get_registered_device_for_student(access_context.student_id)
    if device is None:
        raise ValueError("No registered device was found for this student.")
    device_binding_hash = hash_device_token(device_token, settings.otp_pepper)
    if not hmac.compare_digest(
        device_binding_hash,
        str(device["device_binding_hash"]),
    ):
        _record_proxy_alert(
            repo,
            now=now,
            course_id=access_context.course_id,
            student_id=access_context.student_id,
            schedule_id=access_context.schedule_id,
            alert_type="passkey_from_unrecognized_device",
            severity="high",
            message="A passkey attempt came from an unrecognized browser device.",
            device_binding_hash=device_binding_hash,
        )
        raise ValueError("This is not the registered browser for this student.")

    passkey = complete_authentication(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=expected_rp_id,
        expected_origin=expected_origin,
        credential_id=str(device["credential_id"]),
        public_key=str(device["public_key"]),
        sign_count=int(device["sign_count"]),
    )
    repo.update_registered_device_usage(
        device_id=int(device["id"]),
        sign_count=passkey.sign_count,
        last_used_at=now.isoformat(),
    )
    return {
        "device_id": int(device["id"]),
        "credential_id": passkey.credential_id,
        "device_binding_hash": device_binding_hash,
    }


def verify_login_code(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course_code: str,
    university_id: str,
    code: str,
):
    course = repo.get_course_by_code(course_code.strip().upper())
    if course is None:
        raise ValueError("Course code was not found.")

    student = repo.get_student_for_course(int(course["id"]), university_id.strip())
    if student is None:
        raise ValueError("Student is not enrolled in that course.")

    now = now_in_app_timezone(settings)
    otp_record = repo.get_latest_active_otp(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        now_iso=now.isoformat(),
    )
    if otp_record is None:
        raise ValueError("No active login code was found. Request a new code.")

    if hash_otp(code.strip(), settings.otp_pepper) != otp_record["code_hash"]:
        raise ValueError("The one-time code is invalid.")

    repo.mark_otp_used(int(otp_record["id"]), now.isoformat())
    return course, student


def find_active_schedule(schedules, now: datetime):
    current_weekday = now.weekday()
    current_time = now.timetz().replace(tzinfo=None)
    for schedule in schedules:
        if int(schedule["weekday"]) != current_weekday:
            continue
        start_time = parse_hhmm(schedule["start_time"])
        end_time = parse_hhmm(schedule["end_time"])
        if start_time <= current_time <= end_time:
            return schedule
    return None


def build_student_attendance_summary(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course,
    student,
    schedules: list[dict] | None = None,
    attended_count: int | None = None,
) -> AttendanceSummary:
    now = now_in_app_timezone(settings)
    schedules = schedules if schedules is not None else repo.list_schedules_for_course(int(course["id"]))
    elapsed_occurrences = generate_expected_occurrences(
        course["start_date"],
        course["end_date"] or course["start_date"],
        schedules,
        now,
        only_elapsed=True,
    )
    total_occurrences = generate_expected_occurrences(
        course["start_date"],
        course["end_date"] or course["start_date"],
        schedules,
        now,
        only_elapsed=False,
    )
    if attended_count is None:
        attended_count = repo.count_attendance(
            course_id=int(course["id"]),
            student_id=int(student["id"]),
        )
    return build_attendance_summary(
        attended_count=attended_count,
        elapsed_meetings=len(elapsed_occurrences),
        total_meetings=len(total_occurrences),
        absence_limit_pct=float(course["absence_limit_pct"]),
    )


def stamp_attendance(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course,
    student,
    geolocation_payload: dict,
    verified_device: dict | None = None,
) -> AttendanceStampResult:
    now = now_in_app_timezone(settings)
    if not _course_is_active_today(course, now):
        return AttendanceStampResult(
            success=False,
            message="Attendance is not available because this course is outside its active dates.",
        )

    schedules = repo.list_schedules_for_course(int(course["id"]))
    active_schedule = find_active_schedule(schedules, now)
    if active_schedule is None:
        return AttendanceStampResult(
            success=False,
            message="Attendance is closed right now. Try again during an approved schedule window.",
        )

    if "error" in geolocation_payload:
        return AttendanceStampResult(success=False, message=str(geolocation_payload["error"]))

    try:
        latitude, longitude, accuracy_m, device_binding_hash = _validate_location_payload(
            geolocation_payload,
            settings,
            now,
        )
    except ValueError as error:
        return AttendanceStampResult(success=False, message=str(error))
    attendance_date = now.date().isoformat()

    registered_device = repo.get_registered_device_for_student(int(student["id"]))
    if registered_device is None or verified_device is None:
        return AttendanceStampResult(
            success=False,
            message="Verify your registered passkey before submitting attendance.",
        )
    verified_binding_hash = str(verified_device.get("device_binding_hash", ""))
    if (
        int(verified_device.get("device_id", 0)) != int(registered_device["id"])
        or not hmac.compare_digest(
            verified_binding_hash,
            str(registered_device["device_binding_hash"]),
        )
        or not hmac.compare_digest(verified_binding_hash, device_binding_hash)
    ):
        _record_proxy_alert(
            repo,
            now=now,
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            schedule_id=int(active_schedule["id"]),
            alert_type="device_changed_before_stamp",
            severity="high",
            message="The attendance device did not match the verified passkey session.",
            device_binding_hash=device_binding_hash,
            geolocation_payload=geolocation_payload,
        )
        return AttendanceStampResult(
            success=False,
            message="Attendance must be submitted from the verified device.",
        )

    if repo.attendance_exists(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        schedule_id=int(active_schedule["id"]),
        attendance_date=attendance_date,
    ):
        return AttendanceStampResult(
            success=False,
            message="Attendance has already been stamped for this schedule window.",
        )

    existing_device_stamp = repo.find_attendance_for_device_window(
        course_id=int(course["id"]),
        schedule_id=int(active_schedule["id"]),
        attendance_date=attendance_date,
        device_binding_hash=device_binding_hash,
    )
    if (
        existing_device_stamp is not None
        and int(existing_device_stamp["student_id"]) != int(student["id"])
    ):
        _record_proxy_alert(
            repo,
            now=now,
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            schedule_id=int(active_schedule["id"]),
            alert_type="multiple_students_same_device",
            severity="critical",
            message="One device attempted attendance for multiple students in the same lecture.",
            device_binding_hash=device_binding_hash,
            geolocation_payload=geolocation_payload,
        )
        return AttendanceStampResult(
            success=False,
            message="This device has already been used for another student in this lecture.",
        )

    distance_m = haversine_distance_m(
        float(course["latitude"]),
        float(course["longitude"]),
        latitude,
        longitude,
    )
    if distance_m > float(course["radius_m"]):
        return AttendanceStampResult(
            success=False,
            message=(
                f"You are not in class. You are {distance_m:.2f} m away from the allowed location, "
                f"and you must be within {float(course['radius_m']):.2f} m."
            ),
            distance_m=distance_m,
        )

    try:
        repo.record_attendance(
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            schedule_id=int(active_schedule["id"]),
            attendance_date=attendance_date,
            stamped_at=now.isoformat(),
            student_latitude=latitude,
            student_longitude=longitude,
            accuracy_m=accuracy_m,
            distance_m=distance_m,
            device_info=json.dumps(_sanitize_device_info(geolocation_payload)),
            registered_device_id=int(registered_device["id"]),
            device_binding_hash=device_binding_hash,
        )
    except Exception:
        if repo.attendance_exists(
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            schedule_id=int(active_schedule["id"]),
            attendance_date=attendance_date,
        ):
            return AttendanceStampResult(
                success=False,
                message="Attendance has already been stamped for this schedule window.",
            )
        concurrent_device_stamp = repo.find_attendance_for_device_window(
            course_id=int(course["id"]),
            schedule_id=int(active_schedule["id"]),
            attendance_date=attendance_date,
            device_binding_hash=device_binding_hash,
        )
        if concurrent_device_stamp is not None:
            _record_proxy_alert(
                repo,
                now=now,
                course_id=int(course["id"]),
                student_id=int(student["id"]),
                schedule_id=int(active_schedule["id"]),
                alert_type="multiple_students_same_device",
                severity="critical",
                message="A concurrent proxy attendance attempt was blocked.",
                device_binding_hash=device_binding_hash,
                geolocation_payload=geolocation_payload,
            )
            return AttendanceStampResult(
                success=False,
                message="This device has already been used in this lecture.",
            )
        raise
    accuracy_suffix = f" Reported GPS accuracy: {accuracy_m:.2f} m." if accuracy_m else ""
    return AttendanceStampResult(
        success=True,
        message=(
            f"Attendance stamped successfully for {active_schedule['label']} at {now.strftime('%H:%M')}."
            f" Distance to classroom: {distance_m:.2f} m.{accuracy_suffix}"
        ),
        distance_m=distance_m,
    )


def seed_demo_data(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    latitude: float,
    longitude: float,
) -> bool:
    if repo.get_course_by_code("MAT1116") is not None:
        return False

    now = now_in_app_timezone(settings)
    created_at = now.isoformat()
    repo.create_course(
        code="MAT1116",
        title="Foundations of Mathematics",
        start_date=now.date().isoformat(),
        end_date=(now.date() + timedelta(days=84)).isoformat(),
        total_meetings=24,
        latitude=latitude,
        longitude=longitude,
        radius_m=3.0,
        absence_limit_pct=20.0,
        created_at=created_at,
    )
    course = repo.get_course_by_code("MAT1116")
    if course is None:
        return False

    repo.add_student_to_course(
        course_id=int(course["id"]),
        full_name="Amina Yusuf",
        university_id="U2026001",
        email="amina.yusuf@example.edu",
        phone="+1555000001",
        created_at=created_at,
    )
    repo.add_student_to_course(
        course_id=int(course["id"]),
        full_name="Daniel Okoro",
        university_id="U2026002",
        email="daniel.okoro@example.edu",
        phone="+1555000002",
        created_at=created_at,
    )
    today = now.weekday()
    repo.add_schedule(
        course_id=int(course["id"]),
        weekday=today,
        label="Morning Window",
        start_time="00:00",
        end_time="11:59",
        created_at=created_at,
    )
    repo.add_schedule(
        course_id=int(course["id"]),
        weekday=today,
        label="Afternoon Window",
        start_time="12:00",
        end_time="23:59",
        created_at=created_at,
    )
    return True


def _delivery_target(student, delivery_mode: str) -> str:
    if delivery_mode == "email":
        return str(student["email"] or "")
    return str(student["university_id"])


def _deliver_otp(
    *,
    settings: Settings,
    student_name: str,
    recipient_email: str,
    course_code: str,
    code: str,
    expires_at: datetime,
) -> OTPRequestResult:
    if settings.otp_delivery_mode == "console":
        return OTPRequestResult(
            message="A one-time code has been generated and shown on this page.",
            preview_code=code,
        )

    if settings.otp_delivery_mode != "email":
        raise RuntimeError(
            "Only email and console OTP delivery are supported in this build. "
            "SMS normally requires a paid provider."
        )

    if not recipient_email:
        raise RuntimeError("The student record does not have an email address for OTP delivery.")
    _send_email(
        settings=settings,
        recipient_email=recipient_email,
        subject=f"{course_code} login code",
        body=(
            f"Hello {student_name},\n\n"
            f"Your one-time login code for {course_code} is {code}.\n"
            f"This code expires at {expires_at.strftime('%Y-%m-%d %H:%M %Z')}.\n\n"
            "If you did not request this code, you can ignore this email."
        ),
    )
    return OTPRequestResult(
        message=f"A one-time code has been sent to {recipient_email}.",
        preview_code=None,
    )


def _send_email(*, settings: Settings, recipient_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_sender:
        raise RuntimeError(
            "Email OTP is enabled, but SMTP settings are incomplete. "
            "Set SMTP_HOST and SMTP_SENDER first."
        )

    message = EmailMessage()
    message["From"] = settings.smtp_sender
    message["To"] = recipient_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def _sanitize_device_info(geolocation_payload: dict) -> dict:
    keys = [
        "captured_at",
        "accuracy_m",
        "user_agent",
        "platform",
        "language",
        "timezone",
        "screen_width",
        "screen_height",
    ]
    return {key: geolocation_payload.get(key) for key in keys}


def _validate_location_payload(
    geolocation_payload: dict,
    settings: Settings,
    now: datetime,
) -> tuple[float, float, float, str]:
    try:
        latitude = float(geolocation_payload["latitude"])
        longitude = float(geolocation_payload["longitude"])
        accuracy_m = float(geolocation_payload["accuracy_m"])
        captured_at_raw = str(geolocation_payload["captured_at"])
        device_token = str(geolocation_payload["device_token"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Location verification data is incomplete. Capture location again.") from error

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("The device returned invalid location coordinates.")
    if accuracy_m <= 0 or accuracy_m > settings.location_max_accuracy_m:
        raise ValueError(
            f"Location accuracy must be within {settings.location_max_accuracy_m:.0f} m. "
            "Move near a window and capture again."
        )

    try:
        captured_at = datetime.fromisoformat(captured_at_raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("The location timestamp is invalid. Capture location again.") from error
    if captured_at.tzinfo is None:
        raise ValueError("The location timestamp must include a timezone.")
    age_seconds = (now.astimezone(timezone.utc) - captured_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -30 or age_seconds > settings.location_max_age_seconds:
        raise ValueError("Location expired. Capture a fresh classroom location.")

    return (
        latitude,
        longitude,
        accuracy_m,
        hash_device_token(device_token, settings.otp_pepper),
    )


def _record_proxy_alert(
    repo: AttendanceRepository,
    *,
    now: datetime,
    course_id: int | None,
    student_id: int | None,
    schedule_id: int | None,
    alert_type: str,
    severity: str,
    message: str,
    device_binding_hash: str | None,
    geolocation_payload: dict | None = None,
) -> None:
    payload = geolocation_payload or {}
    repo.create_proxy_alert(
        course_id=course_id,
        student_id=student_id,
        schedule_id=schedule_id,
        attendance_date=now.date().isoformat(),
        alert_type=alert_type,
        severity=severity,
        message=message,
        device_binding_hash=device_binding_hash,
        latitude=_optional_float(payload.get("latitude")),
        longitude=_optional_float(payload.get("longitude")),
        accuracy_m=_optional_float(payload.get("accuracy_m")),
        created_at=now.isoformat(),
    )


def _optional_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _course_is_active_today(course, now: datetime) -> bool:
    start_date = parse_iso_date(course["start_date"])
    end_date = parse_iso_date(course["end_date"] or course["start_date"])
    return start_date <= now.date() <= end_date


def _issue_login_code(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course,
    student,
    device_binding_hash: str | None = None,
    credential_id: str | None = None,
) -> OTPRequestResult:
    configuration_error = otp_delivery_configuration_error(settings)
    if configuration_error:
        raise RuntimeError(configuration_error)

    if settings.otp_delivery_mode == "email" and not student["email"]:
        raise ValueError("This student does not have an email address configured.")

    issued_at = now_in_app_timezone(settings)
    expires_at = issued_at + timedelta(minutes=settings.otp_expiry_minutes)
    code = generate_otp()

    repo.invalidate_active_otps(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        invalidated_at=issued_at.isoformat(),
    )
    otp_id = repo.create_otp(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        code_hash=hash_otp(code, settings.otp_pepper),
        delivery_method=settings.otp_delivery_mode,
        delivery_target=_delivery_target(student, settings.otp_delivery_mode),
        expires_at=expires_at.isoformat(),
        created_at=issued_at.isoformat(),
        device_binding_hash=device_binding_hash,
        credential_id=credential_id,
    )

    try:
        delivery_result = _deliver_otp(
            settings=settings,
            student_name=str(student["full_name"]),
            recipient_email=str(student["email"] or ""),
            course_code=str(course["code"]),
            code=code,
            expires_at=expires_at,
        )
    except Exception as error:
        repo.invalidate_otp(otp_id, issued_at.isoformat())
        raise RuntimeError(str(error)) from error

    return delivery_result
