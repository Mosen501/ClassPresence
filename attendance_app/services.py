from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from attendance_app.config import Settings
from attendance_app.database import AttendanceRepository
from attendance_app.utils import (
    AttendanceSummary,
    build_attendance_summary,
    generate_expected_occurrences,
    generate_otp,
    hash_otp,
    haversine_distance_m,
    parse_iso_date,
    parse_hhmm,
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

    latitude = float(geolocation_payload["latitude"])
    longitude = float(geolocation_payload["longitude"])
    now = now_in_app_timezone(settings)

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
            )
        )

    if eligible_contexts:
        eligible_contexts.sort(key=lambda item: (item.distance_m, item.course_code))
        return eligible_contexts[0]

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
) -> OTPRequestResult:
    course = repo.get_course(access_context.course_id)
    student = repo.get_student(access_context.student_id)
    if course is None or student is None:
        raise ValueError("Student access context is no longer valid.")

    return _issue_login_code(
        repo,
        settings,
        course=course,
        student=student,
    )


def verify_login_code_for_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course_id: int,
    student_id: int,
    code: str,
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

    if hash_otp(code.strip(), settings.otp_pepper) != otp_record["code_hash"]:
        raise ValueError("The one-time code is invalid.")

    repo.mark_otp_used(int(otp_record["id"]), now.isoformat())
    return course, student


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

    latitude = float(geolocation_payload["latitude"])
    longitude = float(geolocation_payload["longitude"])
    accuracy_m = (
        float(geolocation_payload["accuracy_m"])
        if geolocation_payload.get("accuracy_m") is not None
        else None
    )
    attendance_date = now.date().isoformat()

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
    )
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
