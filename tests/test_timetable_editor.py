from __future__ import annotations

import unittest

from app import _build_timetable_editor_rows


class TimetableEditorTestCase(unittest.TestCase):
    def test_saved_rows_do_not_reintroduce_default_l7_template(self) -> None:
        rows = _build_timetable_editor_rows(
            [
                {
                    "weekday": 6,
                    "label": "L1",
                    "start_time": "07:30",
                    "end_time": "08:20",
                }
            ],
            show_default_rows=False,
        )

        self.assertEqual([row["label"] for row in rows], ["L1"])

    def test_standard_templates_can_be_loaded_explicitly(self) -> None:
        rows = _build_timetable_editor_rows([], show_default_rows=True)

        self.assertEqual([row["label"] for row in rows], ["L1", "L2", "L3", "L4", "L5", "L6", "L7"])


if __name__ == "__main__":
    unittest.main()
