from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from attendance_app.utils import weekday_label


HEADER_FILL = PatternFill("solid", fgColor="0F766E")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def build_course_report_xlsx(
    *,
    course,
    students: Iterable,
    schedules: Iterable,
    attendance_records: Iterable,
    eligibility_rows: list[dict[str, object]],
    generated_at: datetime,
) -> bytes:
    workbook = Workbook()
    details_sheet = workbook.active
    details_sheet.title = "Course Details"

    _write_key_value_sheet(
        details_sheet,
        [
            ("Course Code", course["code"]),
            ("Course Name", course["title"]),
            ("Start Date", course["start_date"]),
            ("End Date", course["end_date"] or course["start_date"]),
            ("Latitude", course["latitude"]),
            ("Longitude", course["longitude"]),
            ("Allowed Radius (m)", course["radius_m"]),
            ("Absence Limit (%)", course["absence_limit_pct"]),
            ("Generated At", generated_at.isoformat()),
        ],
    )

    roster_sheet = workbook.create_sheet("Roster")
    _write_table(
        roster_sheet,
        headers=["Student ID", "Student Name", "Email", "Phone"],
        rows=[
            [student["university_id"], student["full_name"], student["email"], student["phone"]]
            for student in students
        ],
    )

    timetable_sheet = workbook.create_sheet("Timetable")
    _write_table(
        timetable_sheet,
        headers=["Weekday", "Window Label", "Start Time", "End Time"],
        rows=[
            [
                weekday_label(int(schedule["weekday"])),
                schedule["label"],
                schedule["start_time"],
                schedule["end_time"],
            ]
            for schedule in schedules
        ],
    )

    attendance_sheet = workbook.create_sheet("Attendance")
    _write_table(
        attendance_sheet,
        headers=["Student Name", "Student ID", "Date", "Window", "Stamped At", "Distance (m)"],
        rows=[
            [
                row["full_name"],
                row["university_id"],
                row["attendance_date"],
                row["schedule_label"],
                row["stamped_at"],
                float(row["distance_m"]),
            ]
            for row in attendance_records
        ],
    )

    eligibility_sheet = workbook.create_sheet("Eligibility")
    _write_table(
        eligibility_sheet,
        headers=[
            "Student",
            "University ID",
            "Attended",
            "Absences",
            "Elapsed Meetings",
            "Total Meetings",
            "Threshold",
            "Status",
        ],
        rows=[
            [
                row["Student"],
                row["University ID"],
                row["Attended"],
                row["Absences"],
                row["Elapsed Meetings"],
                row["Total Meetings"],
                row["Threshold"],
                row["Status"],
            ]
            for row in eligibility_rows
        ],
    )

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _write_key_value_sheet(sheet, items: list[tuple[str, object]]) -> None:
    for row_index, (label, value) in enumerate(items, start=1):
        sheet.cell(row=row_index, column=1, value=label)
        sheet.cell(row=row_index, column=2, value=value)
        sheet.cell(row=row_index, column=1).font = Font(bold=True)
    _autosize_columns(sheet)


def _write_table(sheet, *, headers: list[str], rows: list[list[object]]) -> None:
    for column_index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=column_index, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    for row_index, row in enumerate(rows, start=2):
        for column_index, value in enumerate(row, start=1):
            sheet.cell(row=row_index, column=column_index, value=value)

    sheet.freeze_panes = "A2"
    _autosize_columns(sheet)


def _autosize_columns(sheet) -> None:
    for column_cells in sheet.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            value_length = len(str(cell.value)) if cell.value is not None else 0
            max_length = max(max_length, value_length)
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 40)
