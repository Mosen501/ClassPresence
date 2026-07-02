from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    total_meetings INTEGER NOT NULL CHECK(total_meetings > 0),
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    radius_m REAL NOT NULL DEFAULT 3,
    absence_limit_pct REAL NOT NULL DEFAULT 20,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    university_id TEXT NOT NULL UNIQUE,
    email TEXT,
    phone TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS course_students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    enrolled_at TEXT NOT NULL,
    UNIQUE(course_id, student_id)
);

CREATE TABLE IF NOT EXISTS course_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
    label TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(course_id, weekday, label)
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    delivery_method TEXT NOT NULL,
    delivery_target TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    invalidated_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    schedule_id INTEGER NOT NULL REFERENCES course_schedules(id) ON DELETE CASCADE,
    attendance_date TEXT NOT NULL,
    stamped_at TEXT NOT NULL,
    student_latitude REAL NOT NULL,
    student_longitude REAL NOT NULL,
    accuracy_m REAL,
    distance_m REAL NOT NULL,
    device_info TEXT NOT NULL,
    UNIQUE(course_id, student_id, schedule_id, attendance_date)
);
"""


class AttendanceRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)

    def init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_schema(connection)

    def create_course(
        self,
        *,
        code: str,
        title: str,
        start_date: str,
        end_date: str,
        total_meetings: int,
        latitude: float,
        longitude: float,
        radius_m: float,
        absence_limit_pct: float,
        created_at: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO courses (
                code, title, start_date, end_date, total_meetings, latitude, longitude,
                radius_m, absence_limit_pct, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                title,
                start_date,
                end_date,
                total_meetings,
                latitude,
                longitude,
                radius_m,
                absence_limit_pct,
                created_at,
            ),
        )

    def update_course(
        self,
        *,
        course_id: int,
        code: str,
        title: str,
        start_date: str,
        end_date: str,
        latitude: float,
        longitude: float,
        radius_m: float,
        absence_limit_pct: float,
    ) -> None:
        self._execute(
            """
            UPDATE courses
            SET code = ?, title = ?, start_date = ?, end_date = ?, latitude = ?,
                longitude = ?, radius_m = ?, absence_limit_pct = ?
            WHERE id = ?
            """,
            (
                code,
                title,
                start_date,
                end_date,
                latitude,
                longitude,
                radius_m,
                absence_limit_pct,
                course_id,
            ),
        )

    def list_courses(self) -> list[sqlite3.Row]:
        return self._fetchall("SELECT * FROM courses ORDER BY code")

    def get_course(self, course_id: int) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM courses WHERE id = ?", (course_id,))

    def get_course_by_code(self, code: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM courses WHERE code = ?", (code,))

    def add_student_to_course(
        self,
        *,
        course_id: int,
        full_name: str,
        university_id: str,
        email: str,
        phone: str,
        created_at: str,
    ) -> None:
        with self._connect() as connection:
            existing_student = connection.execute(
                "SELECT id FROM students WHERE university_id = ?",
                (university_id,),
            ).fetchone()
            if existing_student:
                student_id = int(existing_student["id"])
                connection.execute(
                    """
                    UPDATE students
                    SET full_name = ?, email = ?, phone = ?
                    WHERE id = ?
                    """,
                    (full_name, email, phone, student_id),
                )
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO students (full_name, university_id, email, phone, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (full_name, university_id, email, phone, created_at),
                )
                student_id = int(cursor.lastrowid)

            connection.execute(
                """
                INSERT OR IGNORE INTO course_students (course_id, student_id, enrolled_at)
                VALUES (?, ?, ?)
                """,
                (course_id, student_id, created_at),
            )

    def sync_course_roster(
        self,
        *,
        course_id: int,
        roster_rows: list[dict[str, str]],
        created_at: str,
    ) -> None:
        with self._connect() as connection:
            enrolled_student_ids: list[int] = []
            for row in roster_rows:
                existing_student = connection.execute(
                    "SELECT id FROM students WHERE university_id = ?",
                    (row["university_id"],),
                ).fetchone()
                if existing_student:
                    student_id = int(existing_student["id"])
                    connection.execute(
                        """
                        UPDATE students
                        SET full_name = ?, email = ?, phone = ?
                        WHERE id = ?
                        """,
                        (row["full_name"], row["email"], row.get("phone", ""), student_id),
                    )
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO students (full_name, university_id, email, phone, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            row["full_name"],
                            row["university_id"],
                            row["email"],
                            row.get("phone", ""),
                            created_at,
                        ),
                    )
                    student_id = int(cursor.lastrowid)

                enrolled_student_ids.append(student_id)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO course_students (course_id, student_id, enrolled_at)
                    VALUES (?, ?, ?)
                    """,
                    (course_id, student_id, created_at),
                )

            if enrolled_student_ids:
                placeholders = ", ".join("?" for _ in enrolled_student_ids)
                connection.execute(
                    f"""
                    DELETE FROM course_students
                    WHERE course_id = ?
                      AND student_id NOT IN ({placeholders})
                    """,
                    (course_id, *enrolled_student_ids),
                )
            else:
                connection.execute(
                    "DELETE FROM course_students WHERE course_id = ?",
                    (course_id,),
                )

    def get_student(self, student_id: int) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM students WHERE id = ?", (student_id,))

    def get_student_for_course(self, course_id: int, university_id: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT s.*
            FROM students s
            INNER JOIN course_students cs ON cs.student_id = s.id
            WHERE cs.course_id = ? AND s.university_id = ?
            """,
            (course_id, university_id),
        )

    def list_students_for_course(self, course_id: int) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT s.*
            FROM students s
            INNER JOIN course_students cs ON cs.student_id = s.id
            WHERE cs.course_id = ?
            ORDER BY s.full_name
            """,
            (course_id,),
        )

    def list_course_contexts_for_student(self, university_id: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                c.*,
                s.id AS student_id,
                s.full_name AS student_name,
                s.university_id,
                s.email,
                s.phone
            FROM students s
            INNER JOIN course_students cs ON cs.student_id = s.id
            INNER JOIN courses c ON c.id = cs.course_id
            WHERE s.university_id = ?
            ORDER BY c.code
            """,
            (university_id,),
        )

    def add_schedule(
        self,
        *,
        course_id: int,
        weekday: int,
        label: str,
        start_time: str,
        end_time: str,
        created_at: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO course_schedules (course_id, weekday, label, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (course_id, weekday, label, start_time, end_time, created_at),
        )

    def list_schedules_for_course(self, course_id: int) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT *
            FROM course_schedules
            WHERE course_id = ?
            ORDER BY weekday, start_time, label
            """,
            (course_id,),
        )

    def delete_schedule(self, *, schedule_id: int, course_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM course_schedules
                WHERE id = ? AND course_id = ?
                """,
                (schedule_id, course_id),
            )
            return cursor.rowcount > 0

    def sync_course_schedules(
        self,
        *,
        course_id: int,
        schedule_rows: list[dict[str, str | int]],
        created_at: str,
    ) -> None:
        existing_rows = self.list_schedules_for_course(course_id)
        existing_by_key = {
            (int(row["weekday"]), str(row["label"])): row
            for row in existing_rows
        }
        incoming_by_key = {
            (int(row["weekday"]), str(row["label"])): row
            for row in schedule_rows
        }

        with self._connect() as connection:
            for key, row in incoming_by_key.items():
                existing = existing_by_key.get(key)
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO course_schedules (
                            course_id, weekday, label, start_time, end_time, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            course_id,
                            int(row["weekday"]),
                            str(row["label"]),
                            str(row["start_time"]),
                            str(row["end_time"]),
                            created_at,
                        ),
                    )
                    continue

                if (
                    str(existing["start_time"]) != str(row["start_time"])
                    or str(existing["end_time"]) != str(row["end_time"])
                ):
                    connection.execute(
                        """
                        UPDATE course_schedules
                        SET start_time = ?, end_time = ?
                        WHERE id = ?
                        """,
                        (
                            str(row["start_time"]),
                            str(row["end_time"]),
                            int(existing["id"]),
                        ),
                    )

            for key, row in existing_by_key.items():
                if key in incoming_by_key:
                    continue
                connection.execute(
                    "DELETE FROM course_schedules WHERE id = ?",
                    (int(row["id"]),),
                )

    def invalidate_active_otps(self, *, course_id: int, student_id: int, invalidated_at: str) -> None:
        self._execute(
            """
            UPDATE otp_codes
            SET invalidated_at = ?
            WHERE course_id = ?
              AND student_id = ?
              AND used_at IS NULL
              AND invalidated_at IS NULL
            """,
            (invalidated_at, course_id, student_id),
        )

    def create_otp(
        self,
        *,
        course_id: int,
        student_id: int,
        code_hash: str,
        delivery_method: str,
        delivery_target: str,
        expires_at: str,
        created_at: str,
    ) -> int:
        return self._execute(
            """
            INSERT INTO otp_codes (
                course_id, student_id, code_hash, delivery_method, delivery_target,
                expires_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                student_id,
                code_hash,
                delivery_method,
                delivery_target,
                expires_at,
                created_at,
            ),
        )

    def invalidate_otp(self, otp_id: int, invalidated_at: str) -> None:
        self._execute(
            "UPDATE otp_codes SET invalidated_at = ? WHERE id = ?",
            (invalidated_at, otp_id),
        )

    def get_latest_active_otp(
        self,
        *,
        course_id: int,
        student_id: int,
        now_iso: str,
    ) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT *
            FROM otp_codes
            WHERE course_id = ?
              AND student_id = ?
              AND used_at IS NULL
              AND invalidated_at IS NULL
              AND expires_at > ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (course_id, student_id, now_iso),
        )

    def mark_otp_used(self, otp_id: int, used_at: str) -> None:
        self._execute("UPDATE otp_codes SET used_at = ? WHERE id = ?", (used_at, otp_id))

    def attendance_exists(
        self,
        *,
        course_id: int,
        student_id: int,
        schedule_id: int,
        attendance_date: str,
    ) -> bool:
        row = self._fetchone(
            """
            SELECT id
            FROM attendance_records
            WHERE course_id = ?
              AND student_id = ?
              AND schedule_id = ?
              AND attendance_date = ?
            """,
            (course_id, student_id, schedule_id, attendance_date),
        )
        return row is not None

    def record_attendance(
        self,
        *,
        course_id: int,
        student_id: int,
        schedule_id: int,
        attendance_date: str,
        stamped_at: str,
        student_latitude: float,
        student_longitude: float,
        accuracy_m: float | None,
        distance_m: float,
        device_info: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO attendance_records (
                course_id, student_id, schedule_id, attendance_date, stamped_at,
                student_latitude, student_longitude, accuracy_m, distance_m, device_info
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                student_id,
                schedule_id,
                attendance_date,
                stamped_at,
                student_latitude,
                student_longitude,
                accuracy_m,
                distance_m,
                device_info,
            ),
        )

    def count_attendance(self, *, course_id: int, student_id: int) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS attendance_count
            FROM attendance_records
            WHERE course_id = ? AND student_id = ?
            """,
            (course_id, student_id),
        )
        return int(row["attendance_count"]) if row else 0

    def list_attendance(self, *, course_id: int, student_id: int, limit: int = 30) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                ar.attendance_date,
                ar.stamped_at,
                ar.distance_m,
                ar.accuracy_m,
                cs.label AS schedule_label
            FROM attendance_records ar
            INNER JOIN course_schedules cs ON cs.id = ar.schedule_id
            WHERE ar.course_id = ? AND ar.student_id = ?
            ORDER BY ar.stamped_at DESC
            LIMIT ?
            """,
            (course_id, student_id, limit),
        )

    def list_course_attendance(self, *, course_id: int, limit: int = 100) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                s.full_name,
                s.university_id,
                ar.attendance_date,
                ar.stamped_at,
                ar.distance_m,
                cs.label AS schedule_label
            FROM attendance_records ar
            INNER JOIN students s ON s.id = ar.student_id
            INNER JOIN course_schedules cs ON cs.id = ar.schedule_id
            WHERE ar.course_id = ?
            ORDER BY ar.stamped_at DESC
            LIMIT ?
            """,
            (course_id, limit),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        course_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(courses)").fetchall()
        }
        if "end_date" not in course_columns:
            connection.execute("ALTER TABLE courses ADD COLUMN end_date TEXT")
            connection.execute("UPDATE courses SET end_date = start_date WHERE end_date IS NULL")


    def _fetchone(self, query: str, parameters: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(query, tuple(parameters)).fetchone()

    def _fetchall(self, query: str, parameters: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(query, tuple(parameters)).fetchall()

    def _execute(self, query: str, parameters: Iterable[Any] = ()) -> int:
        with self._connect() as connection:
            cursor = connection.execute(query, tuple(parameters))
            return int(cursor.lastrowid)
