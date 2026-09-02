from __future__ import annotations

import hmac
import json
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from attendance_app.browser_keys import (
    validate_browser_public_key,
    verify_browser_key_signature,
)
from attendance_app.config import Settings
from attendance_app.database import AttendanceRepository
from attendance_app.location_diagnostics import browser_family
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
    attendance_date: str
    session_expires_at: str
    distance_m: float
    radius_m: float
    device_binding_hash: str
    device_enrolled: bool
    purpose: str = "enrollment"


PORTAL_SESSION_HOURS = 12


def record_location_attempt(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course,
    student,
    geolocation_payload: dict,
    attempt_type: str,
    success: bool,
    message: str,
    schedule=None,
) -> None:
    """Persist one privacy-limited location outcome without affecting attendance flow."""
    now = now_in_app_timezone(settings)
    active_schedule = schedule
    if active_schedule is None and _course_is_active_today(course, now):
        active_schedule = find_active_schedule(
            repo.list_schedules_for_course(int(course["id"])),
            now,
        )
    reason_code = _location_reason_code(
        geolocation_payload,
        success=success,
        message=message,
        attempt_type=attempt_type,
    )
    if success:
        outcome = "accepted"
    elif reason_code in {"device_rejected", "already_attended"}:
        outcome = "blocked"
    elif reason_code in {"permission_denied", "timeout", "unavailable", "unsupported"}:
        outcome = "error"
    else:
        outcome = "rejected"

    latitude = _optional_float(geolocation_payload.get("latitude"))
    longitude = _optional_float(geolocation_payload.get("longitude"))
    distance_m = None
    if latitude is not None and longitude is not None:
        distance_m = haversine_distance_m(
            float(course["latitude"]),
            float(course["longitude"]),
            latitude,
            longitude,
        )
    try:
        sample_count = int(geolocation_payload.get("sample_count"))
    except (TypeError, ValueError):
        sample_count = None
    try:
        repo.create_location_attempt_event(
            course_id=int(course["id"]),
            student_id=int(student["id"]),
            schedule_id=(
                int(active_schedule["id"]) if active_schedule is not None else None
            ),
            attendance_date=now.date().isoformat(),
            attempt_type=attempt_type,
            outcome=outcome,
            reason_code=reason_code,
            message=message,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=_optional_float(geolocation_payload.get("accuracy_m")),
            distance_m=distance_m,
            radius_m=float(course["radius_m"]),
            captured_at=(
                str(geolocation_payload.get("captured_at"))
                if geolocation_payload.get("captured_at")
                else None
            ),
            sample_count=sample_count,
            platform=str(geolocation_payload.get("platform") or ""),
            browser_family=browser_family(
                str(geolocation_payload.get("user_agent") or "")
            ),
            created_at=now.isoformat(),
            coordinate_cutoff_iso=(now - timedelta(days=30)).isoformat(),
        )
    except Exception:
        # Diagnostics must never prevent device registration or attendance.
        return


def _location_reason_code(
    payload: dict,
    *,
    success: bool,
    message: str,
    attempt_type: str,
) -> str:
    if success:
        return "attendance_recorded" if attempt_type == "attendance" else "accepted"
    structured = str(payload.get("error_code") or "").strip().lower()
    if structured in {"permission_denied", "timeout", "unavailable", "unsupported"}:
        return structured
    normalized = message.lower()
    if "not in class" in normalized or "outside" in normalized and "active dates" not in normalized:
        return "outside_radius"
    if "accuracy" in normalized:
        return "poor_accuracy"
    if "permission" in normalized or "access was denied" in normalized:
        return "permission_denied"
    if "timed out" in normalized or "timeout" in normalized:
        return "timeout"
    if "does not support geolocation" in normalized or "unsupported" in normalized:
        return "unsupported"
    if "unable to retrieve" in normalized or "unavailable" in normalized:
        return "unavailable"
    if "expired" in normalized and "location" in normalized:
        return "stale"
    if "invalid location coordinates" in normalized:
        return "invalid_coordinates"
    if "location verification data is incomplete" in normalized:
        return "invalid_payload"
    if "outside its active dates" in normalized:
        return "course_inactive"
    if "closed right now" in normalized or "no class is active" in normalized:
        return "no_active_window"
    if "already been stamped" in normalized:
        return "already_attended"
    if "device" in normalized:
        return "device_rejected"
    return "invalid_payload"


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

    now = now_in_app_timezone(settings)
    active_schedule = (
        find_active_schedule(
            repo.list_schedules_for_course(int(course["id"])),
            now,
        )
        if _course_is_active_today(course, now)
        else None
    )
    if active_schedule is None:
        raise ValueError("Student access is closed right now.")
    return _issue_login_code(
        repo,
        settings,
        course=course,
        student=student,
        schedule_id=int(active_schedule["id"]),
        attendance_date=now.date().isoformat(),
        window_expires_at=_schedule_window_end(now, active_schedule),
    )


def resolve_student_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    university_id: str,
    geolocation_payload: dict,
    course_id: int | None = None,
) -> StudentAccessContext:
    if "error" in geolocation_payload:
        raise ValueError(str(geolocation_payload["error"]))

    student_contexts = repo.list_course_contexts_for_student(university_id.strip())
    if not student_contexts:
        raise ValueError("Student ID was not found in any course roster.")
    if course_id is not None:
        student_contexts = [
            context for context in student_contexts if int(context["id"]) == course_id
        ]
        if not student_contexts:
            raise ValueError("Student is not enrolled in the selected course.")

    now = now_in_app_timezone(settings)
    latitude, longitude, _accuracy_m, device_binding_hash = _validate_location_payload(
        geolocation_payload,
        settings,
        now,
    )

    active_but_outside: list[tuple] = []
    eligible_contexts: list[StudentAccessContext] = []
    schedules_by_course = repo.list_schedules_for_courses(
        [int(context["id"]) for context in student_contexts]
    )

    for context in student_contexts:
        if not _course_is_active_today(context, now):
            continue
        schedules = schedules_by_course.get(int(context["id"]), [])
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
                attendance_date=now.date().isoformat(),
                session_expires_at=_schedule_window_end(now, active_schedule).isoformat(),
                distance_m=distance_m,
                radius_m=float(context["radius_m"]),
                device_binding_hash=device_binding_hash,
                device_enrolled=False,
                purpose="enrollment",
            )
        )

    if eligible_contexts:
        eligible_contexts.sort(key=lambda item: (item.distance_m, item.course_code))
        selected = eligible_contexts[0]
        selected_context = next(
            context
            for context in student_contexts
            if int(context["id"]) == selected.course_id
        )
        registered_device = (
            {
                "id": int(selected_context["registered_device_id"]),
                "device_binding_hash": str(
                    selected_context["registered_device_binding_hash"]
                ),
            }
            if selected_context.get("registered_device_id") is not None
            else None
        )
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


def resolve_registered_student_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    university_id: str,
    course_id: int,
) -> StudentAccessContext:
    snapshot = repo.get_student_course_snapshot(
        course_id=course_id,
        university_id=university_id.strip(),
    )
    if snapshot is None:
        raise ValueError("Student is not enrolled in the selected course.")
    selected = snapshot["course"]
    student = snapshot["student"]
    registered_device = snapshot["device"]
    if registered_device is None:
        raise ValueError("Register this device from the classroom before accessing the portal.")

    now = now_in_app_timezone(settings)
    active_schedule = (
        find_active_schedule(
            snapshot["schedules"],
            now,
        )
        if _course_is_active_today(selected, now)
        else None
    )
    return StudentAccessContext(
        course_id=course_id,
        course_code=str(selected["code"]),
        course_title=str(selected["title"]),
        course_latitude=float(selected["latitude"]),
        course_longitude=float(selected["longitude"]),
        student_id=int(student["id"]),
        student_name=str(student["full_name"]),
        student_university_id=str(student["university_id"]),
        student_email=str(student["email"] or ""),
        schedule_id=int(active_schedule["id"]) if active_schedule is not None else 0,
        schedule_label=str(active_schedule["label"]) if active_schedule is not None else "",
        schedule_start_time=(
            str(active_schedule["start_time"]) if active_schedule is not None else ""
        ),
        schedule_end_time=str(active_schedule["end_time"]) if active_schedule is not None else "",
        attendance_date=now.date().isoformat(),
        session_expires_at=(now + timedelta(hours=PORTAL_SESSION_HOURS)).isoformat(),
        distance_m=0.0,
        radius_m=float(selected["radius_m"]),
        device_binding_hash=str(registered_device["device_binding_hash"]),
        device_enrolled=True,
        purpose="portal",
    )


def request_login_code_for_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    access_context: StudentAccessContext,
    verified_device: dict | None = None,
) -> OTPRequestResult:
    snapshot = _require_access_context_window(repo, settings, access_context)
    course = snapshot["course"]
    student = snapshot["student"]
    registered_device = snapshot["device"]
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
            raise ValueError("The verified device does not match this student device.")
        if (
            int(verified_device.get("schedule_id", 0)) != access_context.schedule_id
            or str(verified_device.get("attendance_date", ""))
            != access_context.attendance_date
        ):
            raise ValueError("Verify the device again for this lecture window.")
        credential_id = str(registered_device["credential_id"])

    return _issue_login_code(
        repo,
        settings,
        course=course,
        student=student,
        device_binding_hash=access_context.device_binding_hash,
        credential_id=credential_id,
        schedule_id=access_context.schedule_id,
        attendance_date=access_context.attendance_date,
        window_expires_at=datetime.fromisoformat(access_context.session_expires_at),
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
    schedule_id: int | None = None,
    attendance_date: str | None = None,
):
    snapshot = repo.get_student_course_snapshot(
        course_id=course_id,
        student_id=student_id,
    )
    if snapshot is None:
        raise ValueError("Student access context is no longer valid.")
    course = snapshot["course"]
    student = snapshot["student"]

    now = now_in_app_timezone(settings)
    if not _course_is_active_today(course, now):
        raise ValueError("This course is not active today.")

    active_schedule = find_active_schedule(snapshot["schedules"], now)
    if active_schedule is None:
        raise ValueError("Student access is closed right now. Request a new code during class.")
    current_date = now.date().isoformat()
    if schedule_id != int(active_schedule["id"]) or attendance_date != current_date:
        raise ValueError("This verification belongs to a different lecture window.")

    otp_record = repo.get_latest_active_otp(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        now_iso=now.isoformat(),
    )
    if otp_record is None:
        raise ValueError("No active login code was found. Generate a new code.")

    if (
        int(otp_record.get("schedule_id") or 0) != schedule_id
        or str(otp_record.get("attendance_date") or "") != attendance_date
    ):
        raise ValueError("This code belongs to a different lecture window. Request a new code.")

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
        raise ValueError("This code is not bound to the verified device.")

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
    _require_access_context_window(repo, settings, access_context, now=now)
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
            message="The device identity changed during device registration.",
            device_binding_hash=device_binding_hash,
        )
        raise ValueError("Device identity changed. Start the check-in again.")

    registration_conflicts = repo.list_registered_device_conflicts(
        student_id=access_context.student_id,
        device_binding_hash=device_binding_hash,
    )
    existing_for_student = next(
        (
            device
            for device in registration_conflicts
            if int(device["student_id"]) == access_context.student_id
        ),
        None,
    )
    if existing_for_student is not None:
        raise ValueError("This student already has a registered device.")
    existing_for_device = next(
        (
            device
            for device in registration_conflicts
            if str(device["device_binding_hash"]) == device_binding_hash
        ),
        None,
    )
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
        auth_method="passkey",
    )
    repo.record_device_registration_audit(
        student_id=access_context.student_id,
        course_id=access_context.course_id,
        device_id=device_id,
        device_binding_hash=device_binding_hash,
        created_at=now.isoformat(),
    )
    return {
        "device_id": device_id,
        "credential_id": passkey.credential_id,
        "device_binding_hash": device_binding_hash,
        "schedule_id": access_context.schedule_id,
        "attendance_date": access_context.attendance_date,
        "session_expires_at": access_context.session_expires_at,
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
    snapshot = _require_device_access_context(repo, settings, access_context, now=now)
    device = (
        snapshot["device"]
        if snapshot is not None
        else repo.get_registered_device_for_student(access_context.student_id)
    )
    if device is None:
        raise ValueError("No registered device was found for this student.")
    if str(device.get("auth_method") or "passkey") != "passkey":
        raise ValueError("This student uses a different registered-device verification method.")
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
            schedule_id=access_context.schedule_id or None,
            alert_type="unrecognized_device_verification",
            severity="high",
            message="A device verification attempt came from an unrecognized device.",
            device_binding_hash=device_binding_hash,
        )
        raise ValueError("This is not the registered device for this student.")

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
        "schedule_id": access_context.schedule_id,
        "attendance_date": access_context.attendance_date,
        "session_expires_at": access_context.session_expires_at,
    }


def request_student_browser_key_enrollment(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    access_context: StudentAccessContext,
    credential_id: str,
    public_key: str,
    device_token: str,
    fallback_reason: str = "Primary device protection unavailable",
) -> int:
    now = now_in_app_timezone(settings)
    _require_access_context_window(repo, settings, access_context, now=now)
    validate_browser_public_key(credential_id=credential_id, public_key=public_key)
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
            message="The device identity changed during fallback registration.",
            device_binding_hash=device_binding_hash,
        )
        raise ValueError("Device identity changed. Start the check-in again.")
    registration_conflicts = repo.list_registered_device_conflicts(
        student_id=access_context.student_id,
        device_binding_hash=device_binding_hash,
    )
    if any(
        int(device["student_id"]) == access_context.student_id
        for device in registration_conflicts
    ):
        raise ValueError("This student already has a registered device.")
    existing_for_device = next(
        (
            device
            for device in registration_conflicts
            if str(device["device_binding_hash"]) == device_binding_hash
        ),
        None,
    )
    if existing_for_device is not None:
        raise ValueError("This device is already registered to another student.")
    return repo.create_pending_browser_enrollment(
        student_id=access_context.student_id,
        course_id=access_context.course_id,
        schedule_id=access_context.schedule_id,
        attendance_date=access_context.attendance_date,
        credential_id=credential_id,
        public_key=public_key,
        device_binding_hash=device_binding_hash,
        expires_at=access_context.session_expires_at,
        created_at=now.isoformat(),
        fallback_reason=fallback_reason[:500],
    )


def authenticate_student_browser_key(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    access_context: StudentAccessContext,
    credential_id: str,
    signature: str,
    message: str,
    device_token: str,
) -> dict:
    now = now_in_app_timezone(settings)
    snapshot = _require_device_access_context(repo, settings, access_context, now=now)
    device = (
        snapshot["device"]
        if snapshot is not None
        else repo.get_registered_device_for_student(access_context.student_id)
    )
    if device is None:
        raise ValueError("No registered device was found for this student.")
    if str(device.get("auth_method") or "passkey") != "browser_key":
        raise ValueError("This student must verify using the registered device method.")
    device_binding_hash = hash_device_token(device_token, settings.otp_pepper)
    if not hmac.compare_digest(device_binding_hash, str(device["device_binding_hash"])):
        _record_proxy_alert(
            repo,
            now=now,
            course_id=access_context.course_id,
            student_id=access_context.student_id,
            schedule_id=access_context.schedule_id or None,
            alert_type="unrecognized_device_verification",
            severity="high",
            message="A device verification attempt came from an unrecognized device.",
            device_binding_hash=device_binding_hash,
        )
        raise ValueError("This is not the registered device for this student.")
    if not hmac.compare_digest(credential_id, str(device["credential_id"])):
        raise ValueError("The device credential does not match the registered device.")
    verify_browser_key_signature(
        credential_id=credential_id,
        public_key=str(device["public_key"]),
        message=message,
        signature=signature,
    )
    repo.update_registered_device_usage(
        device_id=int(device["id"]),
        sign_count=int(device["sign_count"]) + 1,
        last_used_at=now.isoformat(),
    )
    return {
        "device_id": int(device["id"]),
        "credential_id": credential_id,
        "device_binding_hash": device_binding_hash,
        "schedule_id": access_context.schedule_id,
        "attendance_date": access_context.attendance_date,
        "session_expires_at": access_context.session_expires_at,
    }


def reset_student_device(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    student_id: int,
    course_id: int,
    actor_identifier: str,
) -> bool:
    now = now_in_app_timezone(settings)
    return repo.reset_registered_device_with_audit(
        student_id=student_id,
        course_id=course_id,
        actor_identifier=actor_identifier,
        created_at=now.isoformat(),
    )


def resolve_active_student_session(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    auth: dict,
):
    now = now_in_app_timezone(settings)
    snapshot = repo.get_student_course_snapshot(
        course_id=int(auth.get("course_id", 0)),
        student_id=int(auth.get("student_id", 0)),
    )
    if snapshot is None:
        raise ValueError("Student session has expired.")
    course = snapshot["course"]
    student = snapshot["student"]
    try:
        expires_at = datetime.fromisoformat(str(auth["session_expires_at"]))
    except (KeyError, ValueError) as error:
        raise ValueError("Student session has expired.") from error
    if now >= expires_at:
        raise ValueError("Student session has expired.")

    active_schedule = (
        find_active_schedule(
            snapshot["schedules"],
            now,
        )
        if _course_is_active_today(course, now)
        else None
    )
    device = snapshot["device"]
    if (
        device is None
        or int(device["id"]) != int(auth.get("device_id", 0))
        or not hmac.compare_digest(
            str(device["device_binding_hash"]),
            str(auth.get("device_binding_hash", "")),
        )
    ):
        raise ValueError("Student device authorization has expired.")
    return course, student, active_schedule


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
    active_schedule = find_active_schedule(
        repo.list_schedules_for_course(int(course["id"])),
        now,
    )
    if active_schedule is None:
        raise ValueError("Student access is closed right now.")
    return verify_login_code_for_access_context(
        repo,
        settings,
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        code=code,
        schedule_id=int(active_schedule["id"]),
        attendance_date=now.date().isoformat(),
    )


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

    stamp_state = repo.get_attendance_stamp_state(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
        schedule_id=int(active_schedule["id"]),
        attendance_date=attendance_date,
        device_binding_hash=device_binding_hash,
    )
    registered_device = stamp_state["registered_device"]
    if registered_device is None or verified_device is None:
        return AttendanceStampResult(
            success=False,
            message="Verify your registered device before submitting attendance.",
        )
    try:
        session_expires_at = datetime.fromisoformat(
            str(verified_device.get("session_expires_at", ""))
        )
    except ValueError:
        session_expires_at = now
    if now >= session_expires_at:
        return AttendanceStampResult(
            success=False,
            message="Your device session has expired. Verify the device again.",
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
            message="The attendance device did not match the verified device session.",
            device_binding_hash=device_binding_hash,
            geolocation_payload=geolocation_payload,
        )
        return AttendanceStampResult(
            success=False,
            message="Attendance must be submitted from the verified device.",
        )

    if stamp_state["existing_attendance"] is not None:
        return AttendanceStampResult(
            success=False,
            message="Attendance has already been stamped for this schedule window.",
        )

    existing_device_stamp = stamp_state["existing_device_stamp"]
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


def _schedule_window_end(now: datetime, schedule) -> datetime:
    return datetime.combine(
        now.date(),
        parse_hhmm(str(schedule["end_time"])),
        tzinfo=now.tzinfo,
    )


def _require_access_context_window(
    repo: AttendanceRepository,
    settings: Settings,
    access_context: StudentAccessContext,
    *,
    now: datetime | None = None,
) -> dict:
    current = now or now_in_app_timezone(settings)
    if access_context.attendance_date != current.date().isoformat():
        raise ValueError("This lecture verification has expired. Start again.")
    snapshot = repo.get_student_course_snapshot(
        course_id=access_context.course_id,
        student_id=access_context.student_id,
    )
    if snapshot is None or not _course_is_active_today(snapshot["course"], current):
        raise ValueError("This lecture verification has expired. Start again.")
    active_schedule = find_active_schedule(
        snapshot["schedules"],
        current,
    )
    if (
        active_schedule is None
        or int(active_schedule["id"]) != access_context.schedule_id
        or current >= datetime.fromisoformat(access_context.session_expires_at)
    ):
        raise ValueError("This lecture verification has expired. Start again.")
    return snapshot


def _require_device_access_context(
    repo: AttendanceRepository,
    settings: Settings,
    access_context: StudentAccessContext,
    *,
    now: datetime | None = None,
) -> dict | None:
    if access_context.purpose != "portal":
        _require_access_context_window(repo, settings, access_context, now=now)
        return None

    current = now or now_in_app_timezone(settings)
    try:
        expires_at = datetime.fromisoformat(access_context.session_expires_at)
    except ValueError as error:
        raise ValueError("Device verification has expired. Start again.") from error
    snapshot = repo.get_student_course_snapshot(
        course_id=access_context.course_id,
        student_id=access_context.student_id,
    )
    if (
        current >= expires_at
        or snapshot is None
    ):
        raise ValueError("Device verification has expired. Start again.")
    return snapshot


def _issue_login_code(
    repo: AttendanceRepository,
    settings: Settings,
    *,
    course,
    student,
    device_binding_hash: str | None = None,
    credential_id: str | None = None,
    schedule_id: int | None = None,
    attendance_date: str | None = None,
    window_expires_at: datetime | None = None,
) -> OTPRequestResult:
    configuration_error = otp_delivery_configuration_error(settings)
    if configuration_error:
        raise RuntimeError(configuration_error)

    if settings.otp_delivery_mode == "email" and not student["email"]:
        raise ValueError("This student does not have an email address configured.")

    issued_at = now_in_app_timezone(settings)
    expires_at = issued_at + timedelta(minutes=settings.otp_expiry_minutes)
    if window_expires_at is not None:
        expires_at = min(expires_at, window_expires_at)
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
        schedule_id=schedule_id,
        attendance_date=attendance_date,
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
