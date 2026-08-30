from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import _cached_course_report, _cached_list_courses


class PerformanceCacheTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        _cached_list_courses.clear()
        _cached_course_report.clear()

    def test_course_list_query_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "attendance.db")
            with patch("app.AttendanceRepository.list_courses", return_value=[]) as query:
                self.assertEqual(_cached_list_courses(database_path), [])
                self.assertEqual(_cached_list_courses(database_path), [])

            query.assert_called_once()

    def test_identical_report_is_built_once(self) -> None:
        course = {
            "id": 1,
            "code": "MAT101",
            "title": "Mathematics",
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
            "latitude": 0.0,
            "longitude": 0.0,
            "radius_m": 3.0,
            "absence_limit_pct": 20.0,
        }
        with patch("app.build_course_report_xlsx", return_value=b"report") as build:
            first = _cached_course_report(
                course=course,
                students=[],
                schedules=[],
                attendance_records=[],
                eligibility_rows=[],
                timezone_name="UTC",
            )
            second = _cached_course_report(
                course=course,
                students=[],
                schedules=[],
                attendance_records=[],
                eligibility_rows=[],
                timezone_name="UTC",
            )

        self.assertEqual(first, b"report")
        self.assertEqual(second, b"report")
        build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
