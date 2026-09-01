from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:  # pragma: no cover - exercised in deployments with Postgres configured
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - sqlite-only local/test environments
    psycopg = None
    dict_row = None


Record = dict[str, Any]

_SQLITE_SCHEMA_STATEMENTS = (
    """
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        university_id TEXT NOT NULL UNIQUE,
        email TEXT,
        phone TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS course_students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        enrolled_at TEXT NOT NULL,
        UNIQUE(course_id, student_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS course_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
        label TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(course_id, weekday, label)
    )
    """,
    """
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
        device_binding_hash TEXT,
        credential_id TEXT,
        schedule_id INTEGER REFERENCES course_schedules(id) ON DELETE CASCADE,
        attendance_date TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS registered_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
        credential_id TEXT NOT NULL UNIQUE,
        public_key TEXT NOT NULL,
        sign_count INTEGER NOT NULL DEFAULT 0,
        device_binding_hash TEXT NOT NULL UNIQUE,
        transports TEXT NOT NULL DEFAULT '[]',
        aaguid TEXT NOT NULL DEFAULT '',
        credential_device_type TEXT NOT NULL DEFAULT '',
        credential_backed_up INTEGER NOT NULL DEFAULT 0,
        auth_method TEXT NOT NULL DEFAULT 'passkey',
        created_at TEXT NOT NULL,
        last_used_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_browser_enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        schedule_id INTEGER REFERENCES course_schedules(id) ON DELETE SET NULL,
        attendance_date TEXT NOT NULL,
        credential_id TEXT NOT NULL,
        public_key TEXT NOT NULL,
        device_binding_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        fallback_reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by TEXT,
        registered_device_id INTEGER REFERENCES registered_devices(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        university_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        course_id INTEGER,
        course_code TEXT,
        event_type TEXT NOT NULL,
        actor_type TEXT NOT NULL,
        actor_identifier TEXT NOT NULL,
        previous_device_id INTEGER,
        previous_device_binding_hash TEXT,
        new_device_id INTEGER,
        new_device_binding_hash TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
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
        registered_device_id INTEGER REFERENCES registered_devices(id) ON DELETE SET NULL,
        device_binding_hash TEXT,
        UNIQUE(course_id, student_id, schedule_id, attendance_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS proxy_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
        student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
        schedule_id INTEGER REFERENCES course_schedules(id) ON DELETE SET NULL,
        attendance_date TEXT,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        device_binding_hash TEXT,
        latitude REAL,
        longitude REAL,
        accuracy_m REAL,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
)

_POSTGRES_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS courses (
        id BIGSERIAL PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        total_meetings INTEGER NOT NULL CHECK(total_meetings > 0),
        latitude DOUBLE PRECISION NOT NULL,
        longitude DOUBLE PRECISION NOT NULL,
        radius_m DOUBLE PRECISION NOT NULL DEFAULT 3,
        absence_limit_pct DOUBLE PRECISION NOT NULL DEFAULT 20,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS students (
        id BIGSERIAL PRIMARY KEY,
        full_name TEXT NOT NULL,
        university_id TEXT NOT NULL UNIQUE,
        email TEXT,
        phone TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS course_students (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        enrolled_at TEXT NOT NULL,
        UNIQUE(course_id, student_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS course_schedules (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
        label TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(course_id, weekday, label)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS otp_codes (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        code_hash TEXT NOT NULL,
        delivery_method TEXT NOT NULL,
        delivery_target TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        invalidated_at TEXT,
        device_binding_hash TEXT,
        credential_id TEXT,
        schedule_id BIGINT REFERENCES course_schedules(id) ON DELETE CASCADE,
        attendance_date TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS registered_devices (
        id BIGSERIAL PRIMARY KEY,
        student_id BIGINT NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
        credential_id TEXT NOT NULL UNIQUE,
        public_key TEXT NOT NULL,
        sign_count BIGINT NOT NULL DEFAULT 0,
        device_binding_hash TEXT NOT NULL UNIQUE,
        transports TEXT NOT NULL DEFAULT '[]',
        aaguid TEXT NOT NULL DEFAULT '',
        credential_device_type TEXT NOT NULL DEFAULT '',
        credential_backed_up INTEGER NOT NULL DEFAULT 0,
        auth_method TEXT NOT NULL DEFAULT 'passkey',
        created_at TEXT NOT NULL,
        last_used_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_browser_enrollments (
        id BIGSERIAL PRIMARY KEY,
        student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        schedule_id BIGINT REFERENCES course_schedules(id) ON DELETE SET NULL,
        attendance_date TEXT NOT NULL,
        credential_id TEXT NOT NULL,
        public_key TEXT NOT NULL,
        device_binding_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        fallback_reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by TEXT,
        registered_device_id BIGINT REFERENCES registered_devices(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_audit_events (
        id BIGSERIAL PRIMARY KEY,
        student_id BIGINT NOT NULL,
        university_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        course_id BIGINT,
        course_code TEXT,
        event_type TEXT NOT NULL,
        actor_type TEXT NOT NULL,
        actor_identifier TEXT NOT NULL,
        previous_device_id BIGINT,
        previous_device_binding_hash TEXT,
        new_device_id BIGINT,
        new_device_binding_hash TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_records (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        schedule_id BIGINT NOT NULL REFERENCES course_schedules(id) ON DELETE CASCADE,
        attendance_date TEXT NOT NULL,
        stamped_at TEXT NOT NULL,
        student_latitude DOUBLE PRECISION NOT NULL,
        student_longitude DOUBLE PRECISION NOT NULL,
        accuracy_m DOUBLE PRECISION,
        distance_m DOUBLE PRECISION NOT NULL,
        device_info TEXT NOT NULL,
        registered_device_id BIGINT REFERENCES registered_devices(id) ON DELETE SET NULL,
        device_binding_hash TEXT,
        UNIQUE(course_id, student_id, schedule_id, attendance_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS proxy_alerts (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT REFERENCES courses(id) ON DELETE CASCADE,
        student_id BIGINT REFERENCES students(id) ON DELETE CASCADE,
        schedule_id BIGINT REFERENCES course_schedules(id) ON DELETE SET NULL,
        attendance_date TEXT,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        device_binding_hash TEXT,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        accuracy_m DOUBLE PRECISION,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
)


class AttendanceRepository:
    def __init__(self, database_target: str) -> None:
        self.database_target = database_target.strip()
        self.backend = _detect_backend(self.database_target)
        self.db_path = (
            Path(_sqlite_path_from_target(self.database_target))
            if self.backend == "sqlite"
            else None
        )

    def init_schema(self) -> None:
        if self.backend == "sqlite" and self.db_path is not None and str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as connection:
            for statement in self._schema_statements():
                connection.execute(statement)
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

    def list_courses(self) -> list[Record]:
        return self._fetchall("SELECT * FROM courses ORDER BY code")

    def get_course(self, course_id: int) -> Record | None:
        return self._fetchone("SELECT * FROM courses WHERE id = ?", (course_id,))

    def get_course_by_code(self, code: str) -> Record | None:
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
        with self._connection() as connection:
            student_id = self._upsert_student(
                connection,
                full_name=full_name,
                university_id=university_id,
                email=email,
                phone=phone,
                created_at=created_at,
            )
            self._insert_course_student(connection, course_id=course_id, student_id=student_id, enrolled_at=created_at)

    def sync_course_roster(
        self,
        *,
        course_id: int,
        roster_rows: list[dict[str, str]],
        created_at: str,
    ) -> None:
        with self._connection() as connection:
            enrolled_student_ids: list[int] = []
            for row in roster_rows:
                student_id = self._upsert_student(
                    connection,
                    full_name=row["full_name"],
                    university_id=row["university_id"],
                    email=row["email"],
                    phone=row.get("phone", ""),
                    created_at=created_at,
                )
                enrolled_student_ids.append(student_id)
                self._insert_course_student(
                    connection,
                    course_id=course_id,
                    student_id=student_id,
                    enrolled_at=created_at,
                )

            if enrolled_student_ids:
                placeholders = ", ".join("?" for _ in enrolled_student_ids)
                connection.execute(
                    self._sql(
                        f"""
                        DELETE FROM course_students
                        WHERE course_id = ?
                          AND student_id NOT IN ({placeholders})
                        """
                    ),
                    (course_id, *enrolled_student_ids),
                )
            else:
                connection.execute(
                    self._sql("DELETE FROM course_students WHERE course_id = ?"),
                    (course_id,),
                )

    def get_student(self, student_id: int) -> Record | None:
        return self._fetchone("SELECT * FROM students WHERE id = ?", (student_id,))

    def get_student_for_course(self, course_id: int, university_id: str) -> Record | None:
        return self._fetchone(
            """
            SELECT s.*
            FROM students s
            INNER JOIN course_students cs ON cs.student_id = s.id
            WHERE cs.course_id = ? AND s.university_id = ?
            """,
            (course_id, university_id),
        )

    def list_students_for_course(self, course_id: int) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                s.*,
                rd.id AS registered_device_id,
                rd.created_at AS device_registered_at,
                rd.last_used_at AS device_last_used_at,
                rd.credential_device_type AS device_type,
                rd.credential_backed_up AS device_backed_up,
                rd.auth_method AS device_auth_method
            FROM students s
            INNER JOIN course_students cs ON cs.student_id = s.id
            LEFT JOIN registered_devices rd ON rd.student_id = s.id
            WHERE cs.course_id = ?
            ORDER BY s.full_name
            """,
            (course_id,),
        )

    def list_course_contexts_for_student(self, university_id: str) -> list[Record]:
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

    def list_course_contexts_for_student_id(self, student_id: int) -> list[Record]:
        return self._fetchall(
            """
            SELECT c.*
            FROM courses c
            INNER JOIN course_students cs ON cs.course_id = c.id
            WHERE cs.student_id = ?
            ORDER BY c.code
            """,
            (student_id,),
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

    def list_schedules_for_course(self, course_id: int) -> list[Record]:
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
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql(
                    """
                    DELETE FROM course_schedules
                    WHERE id = ? AND course_id = ?
                    """
                ),
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

        with self._connection() as connection:
            for key, row in incoming_by_key.items():
                existing = existing_by_key.get(key)
                if existing is None:
                    connection.execute(
                        self._sql(
                            """
                            INSERT INTO course_schedules (
                                course_id, weekday, label, start_time, end_time, created_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """
                        ),
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
                        self._sql(
                            """
                            UPDATE course_schedules
                            SET start_time = ?, end_time = ?
                            WHERE id = ?
                            """
                        ),
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
                    self._sql("DELETE FROM course_schedules WHERE id = ?"),
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
        device_binding_hash: str | None = None,
        credential_id: str | None = None,
        schedule_id: int | None = None,
        attendance_date: str | None = None,
    ) -> int:
        query = """
            INSERT INTO otp_codes (
                course_id, student_id, code_hash, delivery_method, delivery_target,
                expires_at, device_binding_hash, credential_id, schedule_id,
                attendance_date, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if self.backend == "postgres":
            query += " RETURNING id"
        return self._execute(
            query,
            (
                course_id,
                student_id,
                code_hash,
                delivery_method,
                delivery_target,
                expires_at,
                device_binding_hash,
                credential_id,
                schedule_id,
                attendance_date,
                created_at,
            ),
            returns_id=True,
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
    ) -> Record | None:
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

    def get_registered_device_for_student(self, student_id: int) -> Record | None:
        return self._fetchone(
            "SELECT * FROM registered_devices WHERE student_id = ?",
            (student_id,),
        )

    def get_registered_device_by_binding_hash(self, device_binding_hash: str) -> Record | None:
        return self._fetchone(
            "SELECT * FROM registered_devices WHERE device_binding_hash = ?",
            (device_binding_hash,),
        )

    def create_registered_device(
        self,
        *,
        student_id: int,
        credential_id: str,
        public_key: str,
        sign_count: int,
        device_binding_hash: str,
        transports: str,
        aaguid: str,
        credential_device_type: str,
        credential_backed_up: bool,
        created_at: str,
        auth_method: str = "passkey",
    ) -> int:
        query = """
            INSERT INTO registered_devices (
                student_id, credential_id, public_key, sign_count, device_binding_hash,
                transports, aaguid, credential_device_type, credential_backed_up,
                auth_method, created_at, last_used_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if self.backend == "postgres":
            query += " RETURNING id"
        return self._execute(
            query,
            (
                student_id,
                credential_id,
                public_key,
                sign_count,
                device_binding_hash,
                transports,
                aaguid,
                credential_device_type,
                int(credential_backed_up),
                auth_method,
                created_at,
                created_at,
            ),
            returns_id=True,
        )

    def update_registered_device_usage(
        self,
        *,
        device_id: int,
        sign_count: int,
        last_used_at: str,
    ) -> None:
        self._execute(
            """
            UPDATE registered_devices
            SET sign_count = ?, last_used_at = ?
            WHERE id = ?
            """,
            (sign_count, last_used_at, device_id),
        )

    def create_pending_browser_enrollment(
        self,
        *,
        student_id: int,
        course_id: int,
        schedule_id: int,
        attendance_date: str,
        credential_id: str,
        public_key: str,
        device_binding_hash: str,
        expires_at: str,
        created_at: str,
        fallback_reason: str = "",
    ) -> int:
        with self._connection() as connection:
            connection.execute(
                self._sql(
                    """
                    UPDATE pending_browser_enrollments
                    SET status = 'superseded', reviewed_at = ?
                    WHERE status = 'pending'
                      AND (student_id = ? OR device_binding_hash = ?)
                    """
                ),
                (created_at, student_id, device_binding_hash),
            )
            query = """
                INSERT INTO pending_browser_enrollments (
                    student_id, course_id, schedule_id, attendance_date,
                    credential_id, public_key, device_binding_hash, expires_at,
                    fallback_reason, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """
            if self.backend == "postgres":
                query += " RETURNING id"
            cursor = connection.execute(
                self._sql(query),
                (
                    student_id,
                    course_id,
                    schedule_id,
                    attendance_date,
                    credential_id,
                    public_key,
                    device_binding_hash,
                    expires_at,
                    fallback_reason,
                    created_at,
                ),
            )
            if self.backend == "postgres":
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Expected a pending enrollment ID.")
                return int(row["id"])
            return int(cursor.lastrowid)

    def get_pending_browser_enrollment(self, pending_id: int) -> Record | None:
        return self._fetchone(
            "SELECT * FROM pending_browser_enrollments WHERE id = ?",
            (pending_id,),
        )

    def list_pending_browser_enrollments(self, *, course_id: int) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                pbe.*, s.full_name, s.university_id, cs.label AS schedule_label
            FROM pending_browser_enrollments pbe
            INNER JOIN students s ON s.id = pbe.student_id
            LEFT JOIN course_schedules cs ON cs.id = pbe.schedule_id
            WHERE pbe.course_id = ? AND pbe.status = 'pending'
            ORDER BY pbe.created_at
            """,
            (course_id,),
        )

    def approve_pending_browser_enrollment(
        self,
        *,
        pending_id: int,
        actor_identifier: str,
        reviewed_at: str,
    ) -> int:
        with self._connection() as connection:
            pending = connection.execute(
                self._sql("SELECT * FROM pending_browser_enrollments WHERE id = ?"),
                (pending_id,),
            ).fetchone()
            if pending is None or str(pending["status"]) != "pending":
                raise ValueError("This browser enrollment request is no longer pending.")
            if str(pending["expires_at"]) <= reviewed_at:
                connection.execute(
                    self._sql(
                        """
                        UPDATE pending_browser_enrollments
                        SET status = 'expired', reviewed_at = ?, reviewed_by = ?
                        WHERE id = ?
                        """
                    ),
                    (reviewed_at, actor_identifier, pending_id),
                )
                raise ValueError("This browser enrollment request has expired.")

            existing = connection.execute(
                self._sql(
                    """
                    SELECT * FROM registered_devices
                    WHERE student_id = ? OR device_binding_hash = ? OR credential_id = ?
                    LIMIT 1
                    """
                ),
                (
                    int(pending["student_id"]),
                    str(pending["device_binding_hash"]),
                    str(pending["credential_id"]),
                ),
            ).fetchone()
            if existing is not None:
                raise ValueError("The student or browser already has a registered device.")

            insert_query = """
                INSERT INTO registered_devices (
                    student_id, credential_id, public_key, sign_count,
                    device_binding_hash, transports, aaguid,
                    credential_device_type, credential_backed_up, auth_method,
                    created_at, last_used_at
                )
                VALUES (?, ?, ?, 0, ?, '[]', '', 'browser_key', 0,
                        'browser_key', ?, ?)
            """
            if self.backend == "postgres":
                insert_query += " RETURNING id"
            cursor = connection.execute(
                self._sql(insert_query),
                (
                    int(pending["student_id"]),
                    str(pending["credential_id"]),
                    str(pending["public_key"]),
                    str(pending["device_binding_hash"]),
                    reviewed_at,
                    reviewed_at,
                ),
            )
            if self.backend == "postgres":
                inserted = cursor.fetchone()
                if inserted is None:
                    raise RuntimeError("Expected a registered device ID.")
                device_id = int(inserted["id"])
            else:
                device_id = int(cursor.lastrowid)

            connection.execute(
                self._sql(
                    """
                    UPDATE pending_browser_enrollments
                    SET status = 'approved', reviewed_at = ?, reviewed_by = ?,
                        registered_device_id = ?
                    WHERE id = ?
                    """
                ),
                (reviewed_at, actor_identifier, device_id, pending_id),
            )
            student = connection.execute(
                self._sql("SELECT * FROM students WHERE id = ?"),
                (int(pending["student_id"]),),
            ).fetchone()
            course = connection.execute(
                self._sql("SELECT * FROM courses WHERE id = ?"),
                (int(pending["course_id"]),),
            ).fetchone()
            if student is None:
                raise ValueError("Student was not found.")
            self._insert_device_audit_event(
                connection,
                student_id=int(pending["student_id"]),
                university_id=str(student["university_id"]),
                student_name=str(student["full_name"]),
                course_id=int(pending["course_id"]),
                course_code=str(course["code"]) if course is not None else "",
                event_type="manager_browser_key_approved",
                actor_type="manager",
                actor_identifier=actor_identifier,
                previous_device_id=None,
                previous_device_binding_hash=None,
                new_device_id=device_id,
                new_device_binding_hash=str(pending["device_binding_hash"]),
                created_at=reviewed_at,
            )
            return device_id

    def reject_pending_browser_enrollment(
        self,
        *,
        pending_id: int,
        actor_identifier: str,
        reviewed_at: str,
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql(
                    """
                    UPDATE pending_browser_enrollments
                    SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
                    WHERE id = ? AND status = 'pending'
                    """
                ),
                (reviewed_at, actor_identifier, pending_id),
            )
            return cursor.rowcount > 0

    def reset_registered_device_with_audit(
        self,
        *,
        student_id: int,
        course_id: int,
        actor_identifier: str,
        created_at: str,
    ) -> bool:
        with self._connection() as connection:
            device = connection.execute(
                self._sql("SELECT * FROM registered_devices WHERE student_id = ?"),
                (student_id,),
            ).fetchone()
            if device is None:
                return False
            student = connection.execute(
                self._sql("SELECT * FROM students WHERE id = ?"),
                (student_id,),
            ).fetchone()
            course = connection.execute(
                self._sql("SELECT * FROM courses WHERE id = ?"),
                (course_id,),
            ).fetchone()
            if student is None:
                raise ValueError("Student was not found.")
            self._insert_device_audit_event(
                connection,
                student_id=student_id,
                university_id=str(student["university_id"]),
                student_name=str(student["full_name"]),
                course_id=course_id,
                course_code=str(course["code"]) if course is not None else "",
                event_type="manager_device_reset",
                actor_type="manager",
                actor_identifier=actor_identifier,
                previous_device_id=int(device["id"]),
                previous_device_binding_hash=str(device["device_binding_hash"]),
                new_device_id=None,
                new_device_binding_hash=None,
                created_at=created_at,
            )
            cursor = connection.execute(
                self._sql("DELETE FROM registered_devices WHERE student_id = ?"),
                (student_id,),
            )
            return cursor.rowcount > 0

    def record_device_registration_audit(
        self,
        *,
        student_id: int,
        course_id: int,
        device_id: int,
        device_binding_hash: str,
        created_at: str,
    ) -> None:
        with self._connection() as connection:
            student = connection.execute(
                self._sql("SELECT * FROM students WHERE id = ?"),
                (student_id,),
            ).fetchone()
            course = connection.execute(
                self._sql("SELECT * FROM courses WHERE id = ?"),
                (course_id,),
            ).fetchone()
            if student is None:
                raise ValueError("Student was not found.")
            self._insert_device_audit_event(
                connection,
                student_id=student_id,
                university_id=str(student["university_id"]),
                student_name=str(student["full_name"]),
                course_id=course_id,
                course_code=str(course["code"]) if course is not None else "",
                event_type="student_device_registered",
                actor_type="student",
                actor_identifier=str(student["university_id"]),
                previous_device_id=None,
                previous_device_binding_hash=None,
                new_device_id=device_id,
                new_device_binding_hash=device_binding_hash,
                created_at=created_at,
            )

    def list_device_audit_events(self, *, course_id: int, limit: int = 500) -> list[Record]:
        return self._fetchall(
            """
            SELECT dae.*
            FROM device_audit_events dae
            WHERE dae.course_id = ?
            ORDER BY dae.created_at DESC
            LIMIT ?
            """,
            (course_id, limit),
        )

    def list_device_audit_events_for_report(self, *, course_id: int) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                id, student_id, university_id, student_name, course_id, course_code,
                event_type, actor_type, actor_identifier, previous_device_id,
                new_device_id, created_at
            FROM device_audit_events
            WHERE course_id = ?
            ORDER BY created_at DESC
            """,
            (course_id,),
        )

    def find_attendance_for_device_window(
        self,
        *,
        course_id: int,
        schedule_id: int,
        attendance_date: str,
        device_binding_hash: str,
    ) -> Record | None:
        return self._fetchone(
            """
            SELECT ar.*, s.full_name, s.university_id
            FROM attendance_records ar
            INNER JOIN students s ON s.id = ar.student_id
            WHERE ar.course_id = ?
              AND ar.schedule_id = ?
              AND ar.attendance_date = ?
              AND ar.device_binding_hash = ?
            LIMIT 1
            """,
            (course_id, schedule_id, attendance_date, device_binding_hash),
        )

    def create_proxy_alert(
        self,
        *,
        course_id: int | None,
        student_id: int | None,
        schedule_id: int | None,
        attendance_date: str | None,
        alert_type: str,
        severity: str,
        message: str,
        device_binding_hash: str | None,
        latitude: float | None,
        longitude: float | None,
        accuracy_m: float | None,
        created_at: str,
    ) -> int:
        query = """
            INSERT INTO proxy_alerts (
                course_id, student_id, schedule_id, attendance_date, alert_type,
                severity, message, device_binding_hash, latitude, longitude,
                accuracy_m, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if self.backend == "postgres":
            query += " RETURNING id"
        return self._execute(
            query,
            (
                course_id,
                student_id,
                schedule_id,
                attendance_date,
                alert_type,
                severity,
                message,
                device_binding_hash,
                latitude,
                longitude,
                accuracy_m,
                created_at,
            ),
            returns_id=True,
        )

    def list_proxy_alerts(self, *, course_id: int, limit: int = 500) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                pa.*,
                s.full_name,
                s.university_id,
                cs.label AS schedule_label
            FROM proxy_alerts pa
            LEFT JOIN students s ON s.id = pa.student_id
            LEFT JOIN course_schedules cs ON cs.id = pa.schedule_id
            WHERE pa.course_id = ?
            ORDER BY pa.created_at DESC
            LIMIT ?
            """,
            (course_id, limit),
        )

    def list_proxy_alerts_for_report(self, *, course_id: int) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                pa.id, pa.attendance_date, pa.alert_type, pa.severity, pa.message,
                pa.device_binding_hash, pa.latitude, pa.longitude, pa.accuracy_m,
                pa.created_at, pa.resolved_at, s.full_name, s.university_id,
                cs.label AS schedule_label
            FROM proxy_alerts pa
            LEFT JOIN students s ON s.id = pa.student_id
            LEFT JOIN course_schedules cs ON cs.id = pa.schedule_id
            WHERE pa.course_id = ?
            ORDER BY pa.created_at DESC
            """,
            (course_id,),
        )

    def list_otp_activity_for_report(self, *, course_id: int) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                otp.id, otp.attendance_date, otp.delivery_method, otp.delivery_target,
                otp.expires_at, otp.used_at, otp.invalidated_at, otp.created_at,
                s.full_name, s.university_id, cs.label AS schedule_label
            FROM otp_codes otp
            INNER JOIN students s ON s.id = otp.student_id
            LEFT JOIN course_schedules cs ON cs.id = otp.schedule_id
            WHERE otp.course_id = ?
            ORDER BY otp.created_at DESC
            """,
            (course_id,),
        )

    def resolve_proxy_alert(self, *, alert_id: int, resolved_at: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql(
                    "UPDATE proxy_alerts SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL"
                ),
                (resolved_at, alert_id),
            )
            return cursor.rowcount > 0

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
        registered_device_id: int | None = None,
        device_binding_hash: str | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO attendance_records (
                course_id, student_id, schedule_id, attendance_date, stamped_at,
                student_latitude, student_longitude, accuracy_m, distance_m, device_info,
                registered_device_id, device_binding_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                registered_device_id,
                device_binding_hash,
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

    def count_attendance_by_student_for_course(self, *, course_id: int) -> dict[int, int]:
        rows = self._fetchall(
            """
            SELECT student_id, COUNT(*) AS attendance_count
            FROM attendance_records
            WHERE course_id = ?
            GROUP BY student_id
            """,
            (course_id,),
        )
        return {int(row["student_id"]): int(row["attendance_count"]) for row in rows}

    def list_attendance(self, *, course_id: int, student_id: int, limit: int = 30) -> list[Record]:
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

    def list_course_attendance(self, *, course_id: int, limit: int = 100) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                s.full_name,
                s.university_id,
                ar.attendance_date,
                ar.stamped_at,
                ar.distance_m,
                ar.accuracy_m,
                ar.registered_device_id,
                ar.device_binding_hash,
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

    def list_course_attendance_for_report(self, *, course_id: int) -> list[Record]:
        return self._fetchall(
            """
            SELECT
                ar.id AS attendance_id,
                ar.schedule_id,
                s.full_name,
                s.university_id,
                ar.attendance_date,
                ar.stamped_at,
                ar.student_latitude,
                ar.student_longitude,
                ar.distance_m,
                ar.accuracy_m,
                ar.registered_device_id,
                ar.device_binding_hash,
                rd.auth_method AS device_auth_method,
                cs.label AS schedule_label,
                cs.start_time AS schedule_start_time,
                cs.end_time AS schedule_end_time
            FROM attendance_records ar
            INNER JOIN students s ON s.id = ar.student_id
            INNER JOIN course_schedules cs ON cs.id = ar.schedule_id
            LEFT JOIN registered_devices rd ON rd.id = ar.registered_device_id
            WHERE ar.course_id = ?
            ORDER BY ar.stamped_at DESC
            """,
            (course_id,),
        )

    def _connect(self):
        if self.backend == "sqlite":
            if self.db_path is None:
                raise RuntimeError("SQLite database path is not configured.")
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        if psycopg is None or dict_row is None:
            raise RuntimeError(
                "PostgreSQL support requires `psycopg[binary]`. Install dependencies before "
                "running the app with ATTENDANCE_DB_URL."
            )
        try:
            return psycopg.connect(
                _normalize_postgres_conninfo(self.database_target),
                row_factory=dict_row,
            )
        except psycopg.OperationalError as error:
            raise RuntimeError(
                "Could not connect to PostgreSQL. Check `ATTENDANCE_DB_URL` in Streamlit secrets, "
                "make sure it is a full `postgresql://...` URL, add `sslmode=require`, and "
                "URL-encode any special characters in the username or password such as `@`, `:`, "
                "`/`, `?`, or `#`."
            ) from error

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _schema_statements(self) -> tuple[str, ...]:
        if self.backend == "postgres":
            return _POSTGRES_SCHEMA_STATEMENTS
        return _SQLITE_SCHEMA_STATEMENTS

    def _migrate_schema(self, connection) -> None:
        if self.backend == "postgres":
            course_columns = self._postgres_columns(connection, "courses")
            if "end_date" not in course_columns:
                connection.execute("ALTER TABLE courses ADD COLUMN end_date TEXT")
                connection.execute("UPDATE courses SET end_date = start_date WHERE end_date IS NULL")
            otp_columns = self._postgres_columns(connection, "otp_codes")
            if "device_binding_hash" not in otp_columns:
                connection.execute("ALTER TABLE otp_codes ADD COLUMN device_binding_hash TEXT")
            if "credential_id" not in otp_columns:
                connection.execute("ALTER TABLE otp_codes ADD COLUMN credential_id TEXT")
            if "schedule_id" not in otp_columns:
                connection.execute(
                    "ALTER TABLE otp_codes ADD COLUMN schedule_id BIGINT "
                    "REFERENCES course_schedules(id) ON DELETE CASCADE"
                )
            if "attendance_date" not in otp_columns:
                connection.execute("ALTER TABLE otp_codes ADD COLUMN attendance_date TEXT")
            device_columns = self._postgres_columns(connection, "registered_devices")
            if "auth_method" not in device_columns:
                connection.execute(
                    "ALTER TABLE registered_devices ADD COLUMN auth_method TEXT "
                    "NOT NULL DEFAULT 'passkey'"
                )
            pending_columns = self._postgres_columns(connection, "pending_browser_enrollments")
            if "fallback_reason" not in pending_columns:
                connection.execute(
                    "ALTER TABLE pending_browser_enrollments ADD COLUMN fallback_reason TEXT "
                    "NOT NULL DEFAULT ''"
                )
            attendance_columns = self._postgres_columns(connection, "attendance_records")
            if "registered_device_id" not in attendance_columns:
                connection.execute(
                    "ALTER TABLE attendance_records ADD COLUMN registered_device_id BIGINT "
                    "REFERENCES registered_devices(id) ON DELETE SET NULL"
                )
            if "device_binding_hash" not in attendance_columns:
                connection.execute(
                    "ALTER TABLE attendance_records ADD COLUMN device_binding_hash TEXT"
                )
            self._create_security_indexes(connection)
            return

        rows = connection.execute("PRAGMA table_info(courses)").fetchall()
        course_columns = {str(row["name"]) for row in rows}
        if "end_date" not in course_columns:
            connection.execute("ALTER TABLE courses ADD COLUMN end_date TEXT")
            connection.execute("UPDATE courses SET end_date = start_date WHERE end_date IS NULL")
        otp_columns = self._sqlite_columns(connection, "otp_codes")
        if "device_binding_hash" not in otp_columns:
            connection.execute("ALTER TABLE otp_codes ADD COLUMN device_binding_hash TEXT")
        if "credential_id" not in otp_columns:
            connection.execute("ALTER TABLE otp_codes ADD COLUMN credential_id TEXT")
        if "schedule_id" not in otp_columns:
            connection.execute("ALTER TABLE otp_codes ADD COLUMN schedule_id INTEGER")
        if "attendance_date" not in otp_columns:
            connection.execute("ALTER TABLE otp_codes ADD COLUMN attendance_date TEXT")
        device_columns = self._sqlite_columns(connection, "registered_devices")
        if "auth_method" not in device_columns:
            connection.execute(
                "ALTER TABLE registered_devices ADD COLUMN auth_method TEXT "
                "NOT NULL DEFAULT 'passkey'"
            )
        pending_columns = self._sqlite_columns(connection, "pending_browser_enrollments")
        if "fallback_reason" not in pending_columns:
            connection.execute(
                "ALTER TABLE pending_browser_enrollments ADD COLUMN fallback_reason TEXT "
                "NOT NULL DEFAULT ''"
            )
        attendance_columns = self._sqlite_columns(connection, "attendance_records")
        if "registered_device_id" not in attendance_columns:
            connection.execute("ALTER TABLE attendance_records ADD COLUMN registered_device_id INTEGER")
        if "device_binding_hash" not in attendance_columns:
            connection.execute("ALTER TABLE attendance_records ADD COLUMN device_binding_hash TEXT")
        self._create_security_indexes(connection)

    def _postgres_columns(self, connection, table_name: str) -> set[str]:
        rows = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
              AND table_schema = current_schema()
            """,
            (table_name,),
        ).fetchall()
        return {str(row["column_name"]) for row in rows}

    @staticmethod
    def _sqlite_columns(connection, table_name: str) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    def _create_security_indexes(self, connection) -> None:
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_device_window
            ON attendance_records (
                course_id, schedule_id, attendance_date, device_binding_hash
            )
            WHERE device_binding_hash IS NOT NULL
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_device_audit_student_created
            ON device_audit_events (student_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_device_audit_course_created
            ON device_audit_events (course_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_proxy_alerts_course_created
            ON proxy_alerts (course_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_pending_browser_course_status
            ON pending_browser_enrollments (course_id, status, created_at)
            """
        )

    def _insert_device_audit_event(
        self,
        connection,
        *,
        student_id: int,
        university_id: str,
        student_name: str,
        course_id: int | None,
        course_code: str,
        event_type: str,
        actor_type: str,
        actor_identifier: str,
        previous_device_id: int | None,
        previous_device_binding_hash: str | None,
        new_device_id: int | None,
        new_device_binding_hash: str | None,
        created_at: str,
    ) -> None:
        connection.execute(
            self._sql(
                """
                INSERT INTO device_audit_events (
                    student_id, university_id, student_name, course_id, course_code,
                    event_type, actor_type, actor_identifier, previous_device_id,
                    previous_device_binding_hash, new_device_id, new_device_binding_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
            ),
            (
                student_id,
                university_id,
                student_name,
                course_id,
                course_code,
                event_type,
                actor_type,
                actor_identifier,
                previous_device_id,
                previous_device_binding_hash,
                new_device_id,
                new_device_binding_hash,
                created_at,
            ),
        )

    def _fetchone(self, query: str, parameters: Iterable[Any] = ()) -> Record | None:
        with self._connection() as connection:
            row = connection.execute(self._sql(query), tuple(parameters)).fetchone()
        if row is None:
            return None
        return dict(row)

    def _fetchall(self, query: str, parameters: Iterable[Any] = ()) -> list[Record]:
        with self._connection() as connection:
            rows = connection.execute(self._sql(query), tuple(parameters)).fetchall()
        return [dict(row) for row in rows]

    def _execute(
        self,
        query: str,
        parameters: Iterable[Any] = (),
        *,
        returns_id: bool = False,
    ) -> int:
        with self._connection() as connection:
            cursor = connection.execute(self._sql(query), tuple(parameters))
            if not returns_id:
                return int(getattr(cursor, "lastrowid", 0) or 0)

            if self.backend == "postgres":
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Expected an inserted row ID from PostgreSQL.")
                return int(row["id"])

            return int(cursor.lastrowid)

    def _sql(self, query: str) -> str:
        if self.backend == "postgres":
            return query.replace("?", "%s")
        return query

    def _upsert_student(
        self,
        connection,
        *,
        full_name: str,
        university_id: str,
        email: str,
        phone: str,
        created_at: str,
    ) -> int:
        existing_student = connection.execute(
            self._sql("SELECT id FROM students WHERE university_id = ?"),
            (university_id,),
        ).fetchone()
        if existing_student is not None:
            student_id = int(existing_student["id"])
            connection.execute(
                self._sql(
                    """
                    UPDATE students
                    SET full_name = ?, email = ?, phone = ?
                    WHERE id = ?
                    """
                ),
                (full_name, email, phone, student_id),
            )
            return student_id

        insert_query = """
            INSERT INTO students (full_name, university_id, email, phone, created_at)
            VALUES (?, ?, ?, ?, ?)
        """
        if self.backend == "postgres":
            insert_query += " RETURNING id"

        cursor = connection.execute(
            self._sql(insert_query),
            (full_name, university_id, email, phone, created_at),
        )
        if self.backend == "postgres":
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Expected PostgreSQL to return the inserted student ID.")
            return int(row["id"])
        return int(cursor.lastrowid)

    def _insert_course_student(
        self,
        connection,
        *,
        course_id: int,
        student_id: int,
        enrolled_at: str,
    ) -> None:
        if self.backend == "postgres":
            connection.execute(
                """
                INSERT INTO course_students (course_id, student_id, enrolled_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (course_id, student_id) DO NOTHING
                """,
                (course_id, student_id, enrolled_at),
            )
            return

        connection.execute(
            """
            INSERT OR IGNORE INTO course_students (course_id, student_id, enrolled_at)
            VALUES (?, ?, ?)
            """,
            (course_id, student_id, enrolled_at),
        )


def _detect_backend(database_target: str) -> str:
    normalized = database_target.strip().lower()
    if normalized.startswith(("postgres://", "postgresql://")):
        return "postgres"
    return "sqlite"


def _sqlite_path_from_target(database_target: str) -> str:
    if database_target.startswith("sqlite:///"):
        return database_target.removeprefix("sqlite:///")
    return database_target


def _normalize_postgres_conninfo(database_target: str) -> str:
    if not database_target.lower().startswith(("postgres://", "postgresql://")):
        return database_target

    parsed = urlsplit(database_target)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items.setdefault("sslmode", "require")
    normalized_query = urlencode(query_items)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, normalized_query, parsed.fragment))
