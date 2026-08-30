from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppNavigationTestCase(unittest.TestCase):
    def test_student_back_clears_id_without_mutating_rendered_widget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "attendance.db")
            with patch.dict(
                os.environ,
                {
                    "ATTENDANCE_DB_PATH": database_path,
                    "APP_ENV": "development",
                },
                clear=False,
            ):
                app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
                self._button(app, "Start check-in").click()
                app.run(timeout=30)

                app.text_input[0].set_value("20260001")
                app.run(timeout=30)
                self._button(app, "Back").click()
                app.run(timeout=30)

                self.assertEqual(len(app.exception), 0)
                self.assertIsNone(app.session_state["active_role"])

                self._button(app, "Start check-in").click()
                app.run(timeout=30)
                self.assertEqual(app.text_input[0].value, "")

    @staticmethod
    def _button(app: AppTest, label: str):
        return next(button for button in app.button if button.label == label)


if __name__ == "__main__":
    unittest.main()
