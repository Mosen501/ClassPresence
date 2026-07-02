from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable


WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


@dataclass(frozen=True)
class ScheduleOccurrence:
    schedule_id: int
    label: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class AttendanceSummary:
    attended_count: int
    elapsed_meetings: int
    total_meetings: int
    absences: int
    absence_threshold: int
    denied_exam_entry: bool
    remaining_safe_absences: int
    attendance_pct_of_total: float
    absence_pct_of_total: float


def generate_otp(length: int = 6) -> str:
    minimum = 10 ** (length - 1)
    maximum = (10**length) - 1
    return str(secrets.randbelow(maximum - minimum + 1) + minimum)


def hash_otp(code: str, pepper: str) -> str:
    return hashlib.sha256(f"{code}:{pepper}".encode("utf-8")).hexdigest()


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_m * c


def parse_iso_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def parse_hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return value
    return time.fromisoformat(value)


def weekday_label(index: int) -> str:
    return WEEKDAY_NAMES[index]


def generate_expected_occurrences(
    course_start_date: str | date,
    course_end_date: str | date,
    schedules: Iterable,
    now: datetime,
    *,
    only_elapsed: bool,
) -> list[ScheduleOccurrence]:
    start_date = parse_iso_date(course_start_date)
    end_date = parse_iso_date(course_end_date)
    if end_date < start_date:
        return []
    if start_date > now.date():
        return []

    occurrences: list[ScheduleOccurrence] = []
    current_date = start_date
    timezone = now.tzinfo
    final_date = min(end_date, now.date()) if only_elapsed else end_date

    while current_date <= final_date:
        daily_schedules = sorted(
            (
                schedule
                for schedule in schedules
                if int(schedule["weekday"]) == current_date.weekday()
            ),
            key=lambda item: item["start_time"],
        )
        for schedule in daily_schedules:
            starts_at = datetime.combine(current_date, parse_hhmm(schedule["start_time"]), timezone)
            ends_at = datetime.combine(current_date, parse_hhmm(schedule["end_time"]), timezone)
            if only_elapsed and current_date == now.date() and ends_at > now:
                continue
            occurrences.append(
                ScheduleOccurrence(
                    schedule_id=int(schedule["id"]),
                    label=str(schedule["label"]),
                    starts_at=starts_at,
                    ends_at=ends_at,
                )
            )
        current_date += timedelta(days=1)

    return occurrences


def calculate_absence_threshold(total_meetings: int, absence_limit_pct: float) -> int:
    if total_meetings <= 0:
        return 0
    return math.ceil(total_meetings * (absence_limit_pct / 100))


def build_attendance_summary(
    attended_count: int,
    elapsed_meetings: int,
    total_meetings: int,
    absence_limit_pct: float,
) -> AttendanceSummary:
    absences = max(elapsed_meetings - attended_count, 0)
    threshold = calculate_absence_threshold(total_meetings, absence_limit_pct)
    denied_exam_entry = threshold > 0 and absences >= threshold
    remaining_safe_absences = max(threshold - absences, 0)
    attendance_pct_of_total = (attended_count / total_meetings * 100) if total_meetings else 0.0
    absence_pct_of_total = (absences / total_meetings * 100) if total_meetings else 0.0

    return AttendanceSummary(
        attended_count=attended_count,
        elapsed_meetings=elapsed_meetings,
        total_meetings=total_meetings,
        absences=absences,
        absence_threshold=threshold,
        denied_exam_entry=denied_exam_entry,
        remaining_safe_absences=remaining_safe_absences,
        attendance_pct_of_total=attendance_pct_of_total,
        absence_pct_of_total=absence_pct_of_total,
    )
