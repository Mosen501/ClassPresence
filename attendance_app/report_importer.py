from __future__ import annotations

import json
from datetime import date, datetime
from io import BytesIO

from openpyxl import load_workbook

from attendance_app.database import AttendanceRepository
from attendance_app.services import now_in_app_timezone


WEEKDAY_MAP = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def import_attendance_report_bytes(
    *,
    repo: AttendanceRepository,
    settings,
    source_name: str,
    content: bytes,
) -> dict[str, int | str]:
    workbook = load_workbook(BytesIO(content), data_only=True)

    course_sheet = workbook["Course Details"]
    course_details = {
        _normalize(row[0]): row[1]
        for row in course_sheet.iter_rows(min_row=1, values_only=True)
        if row[0]
    }
    course_code = _normalize(course_details["Course Code"]).upper()
    course_title = _normalize(course_details["Course Name"])
    start_date = _normalize_iso_date(course_details["Start Date"])
    end_date = _normalize_iso_date(course_details["End Date"]) or start_date
    latitude = float(course_details["Latitude"])
    longitude = float(course_details["Longitude"])
    radius_m = float(course_details["Allowed Radius (m)"])
    absence_limit_pct = float(course_details["Absence Limit (%)"])
    generated_at = _normalize_timestamp(course_details["Generated At"]) or now_in_app_timezone(
        settings
    ).isoformat()

    eligibility_sheet = workbook["Eligibility"]
    eligibility_rows = list(eligibility_sheet.iter_rows(min_row=2, values_only=True))
    total_meetings = max(int(row[5]) for row in eligibility_rows if row and row[5] is not None)

    roster_sheet = workbook["Roster"]
    roster_rows = []
    for student_id, student_name, email, phone in roster_sheet.iter_rows(min_row=2, values_only=True):
        if student_id is None:
            continue
        roster_rows.append(
            {
                "university_id": _normalize(student_id),
                "full_name": _normalize(student_name),
                "email": _normalize(email),
                "phone": _normalize(phone),
            }
        )

    timetable_sheet = workbook["Timetable"]
    schedule_rows = []
    for weekday_name, label, start_time, end_time in timetable_sheet.iter_rows(
        min_row=2, values_only=True
    ):
        if weekday_name is None:
            continue
        schedule_rows.append(
            {
                "weekday": WEEKDAY_MAP[_normalize(weekday_name)],
                "label": _normalize(label),
                "start_time": _normalize(start_time),
                "end_time": _normalize(end_time),
            }
        )

    existing_course = repo.get_course_by_code(course_code)
    if existing_course is None:
        repo.create_course(
            code=course_code,
            title=course_title,
            start_date=start_date,
            end_date=end_date,
            total_meetings=total_meetings,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            absence_limit_pct=absence_limit_pct,
            created_at=generated_at,
        )
    else:
        repo.update_course(
            course_id=int(existing_course["id"]),
            code=course_code,
            title=course_title,
            start_date=start_date,
            end_date=end_date,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            absence_limit_pct=absence_limit_pct,
        )

    course = repo.get_course_by_code(course_code)
    if course is None:
        raise RuntimeError("Course import failed.")
    course_id = int(course["id"])

    repo.sync_course_roster(
        course_id=course_id,
        roster_rows=roster_rows,
        created_at=generated_at,
    )
    repo.sync_course_schedules(
        course_id=course_id,
        schedule_rows=schedule_rows,
        created_at=generated_at,
    )

    students_by_university_id = {
        str(row["university_id"]): row for row in repo.list_students_for_course(course_id)
    }
    schedules_by_key = {
        (int(row["weekday"]), str(row["label"])): row
        for row in repo.list_schedules_for_course(course_id)
    }

    attendance_sheet = workbook["Attendance"]
    imported_attendance = 0
    skipped_attendance = 0
    placeholder_device_info = json.dumps(
        {
            "imported_from_report": True,
            "source_file": source_name,
            "original_student_coordinates_unavailable": True,
        },
        ensure_ascii=False,
    )

    for _student_name, student_id, attendance_date, window_label, stamped_at, distance_m in attendance_sheet.iter_rows(
        min_row=2, values_only=True
    ):
        if student_id is None:
            continue

        university_id = _normalize(student_id)
        student = students_by_university_id.get(university_id)
        if student is None:
            skipped_attendance += 1
            continue

        attendance_day = _coerce_date(attendance_date)
        schedule = schedules_by_key.get((attendance_day.weekday(), _normalize(window_label)))
        if schedule is None:
            skipped_attendance += 1
            continue

        if repo.attendance_exists(
            course_id=course_id,
            student_id=int(student["id"]),
            schedule_id=int(schedule["id"]),
            attendance_date=attendance_day.isoformat(),
        ):
            skipped_attendance += 1
            continue

        repo.record_attendance(
            course_id=course_id,
            student_id=int(student["id"]),
            schedule_id=int(schedule["id"]),
            attendance_date=attendance_day.isoformat(),
            stamped_at=_normalize_timestamp(stamped_at),
            student_latitude=latitude,
            student_longitude=longitude,
            accuracy_m=None,
            distance_m=float(distance_m or 0.0),
            device_info=placeholder_device_info,
        )
        imported_attendance += 1

    return {
        "course_code": course_code,
        "course_id": course_id,
        "roster_rows": len(roster_rows),
        "schedule_rows": len(schedule_rows),
        "imported_attendance": imported_attendance,
        "skipped_attendance": skipped_attendance,
    }


def _normalize(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = _normalize(value)
    if not text:
        raise ValueError("A required date value is blank in the attendance report.")

    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text).date()
        except ValueError as error:
            raise ValueError(f"Unsupported date value in the attendance report: {text}") from error


def _normalize_iso_date(value) -> str:
    if value is None:
        return ""
    return _coerce_date(value).isoformat()


def _normalize_timestamp(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return _normalize(value)
