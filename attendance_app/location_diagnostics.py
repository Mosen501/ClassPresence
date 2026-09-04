from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Iterable

from attendance_app.utils import haversine_distance_m


LOCATION_REASON_LABELS = {
    "accepted": "Location accepted",
    "outside_radius": "Outside classroom radius",
    "poor_accuracy": "Accuracy above permitted limit",
    "permission_denied": "Location permission denied",
    "timeout": "GPS request timed out",
    "unavailable": "Location unavailable",
    "unsupported": "Geolocation unsupported",
    "stale": "Location reading expired",
    "invalid_coordinates": "Invalid coordinates",
    "invalid_payload": "Incomplete location data",
    "no_active_window": "No active lecture window",
    "course_inactive": "Course outside active dates",
    "device_rejected": "Location captured; device rejected",
    "already_attended": "Attendance already recorded",
    "attendance_recorded": "Attendance recorded",
}

LOCATION_FAILURE_REASONS = {
    "outside_radius",
    "poor_accuracy",
    "permission_denied",
    "timeout",
    "unavailable",
    "unsupported",
    "stale",
    "invalid_coordinates",
    "invalid_payload",
}


def browser_family(user_agent: str) -> str:
    normalized = user_agent.lower()
    if "edg/" in normalized or "edgios" in normalized:
        return "Edge"
    if "opr/" in normalized or "opera" in normalized:
        return "Opera"
    if "brave" in normalized:
        return "Brave"
    if "firefox/" in normalized or "fxios" in normalized:
        return "Firefox"
    if "chrome/" in normalized or "crios" in normalized:
        return "Chrome"
    if "safari/" in normalized:
        return "Safari"
    return "Other" if normalized else "Unknown"


def summarize_location_events(events: Iterable[dict]) -> dict:
    rows = list(events)
    reason_counts = Counter(str(row.get("reason_code") or "unknown") for row in rows)
    affected_students: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        student_id = row.get("student_id")
        if student_id is not None:
            affected_students[str(row.get("reason_code") or "unknown")].add(
                int(student_id)
            )
    diagnostic_attempts = sum(
        count
        for reason, count in reason_counts.items()
        if reason in LOCATION_FAILURE_REASONS or reason in {"accepted", "attendance_recorded"}
    )
    accepted = reason_counts["accepted"] + reason_counts["attendance_recorded"]
    failures = sum(reason_counts[reason] for reason in LOCATION_FAILURE_REASONS)
    windows: dict[tuple[int, str, int, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (
            int(row.get("student_id") or 0),
            str(row.get("attendance_date") or ""),
            int(row.get("schedule_id") or 0),
            str(row.get("attempt_type") or "unknown"),
        )
        windows[key].append(row)
    attendance_windows = {
        key: attempts for key, attempts in windows.items() if key[3] == "attendance"
    }
    completed_attendance_windows = sum(
        any(str(row.get("reason_code")) == "attendance_recorded" for row in attempts)
        for attempts in attendance_windows.values()
    )
    unresolved_students = {
        key[0]
        for key, attempts in attendance_windows.items()
        if not any(str(row.get("reason_code")) == "attendance_recorded" for row in attempts)
    }
    attempts_per_window = [len(attempts) for attempts in attendance_windows.values()]
    return {
        "total_attempts": len(rows),
        "unique_students": len(
            {int(row["student_id"]) for row in rows if row.get("student_id") is not None}
        ),
        "accepted": accepted,
        "failures": failures,
        "diagnostic_attempts": diagnostic_attempts,
        "success_rate": (
            (accepted / diagnostic_attempts) * 100 if diagnostic_attempts else 0.0
        ),
        "attendance_windows_attempted": len(attendance_windows),
        "attendance_windows_completed": completed_attendance_windows,
        "attendance_completion_rate": (
            (completed_attendance_windows / len(attendance_windows)) * 100
            if attendance_windows
            else 0.0
        ),
        "students_with_unresolved_failures": len(unresolved_students),
        "median_attempts_per_window": (
            float(median(attempts_per_window)) if attempts_per_window else 0.0
        ),
        "reason_counts": dict(reason_counts),
        "affected_students": {
            reason: len(student_ids) for reason, student_ids in affected_students.items()
        },
        "recovered_failures": sum(
            str(row.get("reason_code")) in LOCATION_FAILURE_REASONS
            and bool(row.get("recovered_at"))
            for row in rows
        ),
    }


def build_lecture_location_summary(events: Iterable[dict]) -> list[dict]:
    grouped: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in events:
        key = (
            str(row.get("attendance_date") or ""),
            int(row.get("schedule_id") or 0),
            str(row.get("schedule_label") or "Unassigned"),
        )
        grouped[key].append(row)
    result = []
    for (attendance_date, schedule_id, schedule_label), rows in sorted(
        grouped.items(), reverse=True
    ):
        summary = summarize_location_events(rows)
        result.append(
            {
                "attendance_date": attendance_date,
                "schedule_id": schedule_id,
                "schedule_label": schedule_label,
                **summary,
            }
        )
    return result


def analyze_classroom_reference(
    course: dict,
    events: Iterable[dict],
    *,
    maximum_accuracy_m: float = 25.0,
) -> dict:
    best_by_student_window: dict[tuple[int, str, int], dict] = {}
    for row in events:
        if row.get("latitude") is None or row.get("longitude") is None:
            continue
        accuracy = row.get("accuracy_m")
        if accuracy is None or float(accuracy) > maximum_accuracy_m:
            continue
        key = (
            int(row.get("student_id") or 0),
            str(row.get("attendance_date") or ""),
            int(row.get("schedule_id") or 0),
        )
        current = best_by_student_window.get(key)
        if current is None or float(accuracy) < float(current["accuracy_m"]):
            best_by_student_window[key] = row

    points = list(best_by_student_window.values())
    session_count = len(
        {
            (str(row.get("attendance_date") or ""), int(row.get("schedule_id") or 0))
            for row in points
        }
    )
    if not points:
        return {
            "status": "insufficient",
            "message": "No retained high-quality location readings are available yet.",
            "sample_count": 0,
            "session_count": 0,
            "observed_latitude": None,
            "observed_longitude": None,
            "offset_m": None,
        }

    observed_latitude = median(float(row["latitude"]) for row in points)
    observed_longitude = median(float(row["longitude"]) for row in points)
    offset_m = haversine_distance_m(
        float(course["latitude"]),
        float(course["longitude"]),
        observed_latitude,
        observed_longitude,
    )
    enough_evidence = len(points) >= 10 and session_count >= 2
    possibly_misplaced = enough_evidence and offset_m > 20.0
    if possibly_misplaced:
        status = "review"
        message = (
            "Student readings consistently cluster away from the configured classroom point. "
            "Review the marker or run instructor calibration before changing it."
        )
    elif enough_evidence:
        status = "consistent"
        message = "The configured classroom point is consistent with retained student readings."
    else:
        status = "insufficient"
        message = "More high-quality readings across at least two lectures are needed."
    return {
        "status": status,
        "message": message,
        "sample_count": len(points),
        "session_count": session_count,
        "observed_latitude": observed_latitude,
        "observed_longitude": observed_longitude,
        "offset_m": offset_m,
    }
