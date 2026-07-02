from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from attendance_app.utils import (
    build_attendance_summary,
    calculate_absence_threshold,
    generate_expected_occurrences,
    hash_otp,
    haversine_distance_m,
)


class UtilsTestCase(unittest.TestCase):
    def test_hash_otp_is_deterministic(self) -> None:
        self.assertEqual(hash_otp("123456", "pepper"), hash_otp("123456", "pepper"))
        self.assertNotEqual(hash_otp("123456", "pepper"), hash_otp("654321", "pepper"))

    def test_haversine_distance_is_zero_for_same_point(self) -> None:
        distance = haversine_distance_m(40.7128, -74.0060, 40.7128, -74.0060)
        self.assertAlmostEqual(distance, 0.0, places=6)

    def test_generate_expected_occurrences_ignores_future_window_today(self) -> None:
        now = datetime(2026, 7, 1, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        schedules = [
            {"id": 1, "weekday": 2, "label": "Morning", "start_time": "09:00", "end_time": "10:00"},
            {"id": 2, "weekday": 2, "label": "Afternoon", "start_time": "15:00", "end_time": "16:00"},
        ]
        occurrences = generate_expected_occurrences(
            "2026-07-01",
            "2026-07-01",
            schedules,
            now,
            only_elapsed=True,
        )
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0].label, "Morning")

    def test_generate_expected_occurrences_includes_future_when_requested(self) -> None:
        now = datetime(2026, 7, 1, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        schedules = [
            {"id": 1, "weekday": 2, "label": "Morning", "start_time": "09:00", "end_time": "10:00"},
            {"id": 2, "weekday": 2, "label": "Afternoon", "start_time": "15:00", "end_time": "16:00"},
        ]
        occurrences = generate_expected_occurrences(
            "2026-07-01",
            "2026-07-01",
            schedules,
            now,
            only_elapsed=False,
        )
        self.assertEqual(len(occurrences), 2)

    def test_absence_threshold_rounds_up(self) -> None:
        self.assertEqual(calculate_absence_threshold(11, 20), 3)

    def test_attendance_summary_flags_exam_denial(self) -> None:
        summary = build_attendance_summary(
            attended_count=4,
            elapsed_meetings=10,
            total_meetings=20,
            absence_limit_pct=20,
        )
        self.assertEqual(summary.absences, 6)
        self.assertTrue(summary.denied_exam_entry)


if __name__ == "__main__":
    unittest.main()
