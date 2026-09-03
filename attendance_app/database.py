from __future__ import annotations

import json
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

try:  # pragma: no cover - exercised in deployments with Postgres configured
    from psycopg_pool import ConnectionPool, PoolTimeout
except ImportError:  # pragma: no cover - sqlite-only local/test environments
    ConnectionPool = None
    PoolTimeout = None


Record = dict[str, Any]
SCHEMA_VERSION = "2026-09-03-1"
BROWSER_KEY_RECOVERY_REASON = "registered_browser_credential_missing"


class DatabaseUnavailableError(RuntimeError):
    """Raised when PostgreSQL is temporarily unreachable or drops a connection."""


DATA_RESET_ACTIONS = frozenset(
    {
        "course_attendance",
        "course_timetable",
        "course_roster",
        "course_activity",
        "delete_course",
        "student_attendance",
        "student_device",
        "delete_student",
        "reset_all_students",
        "reset_all_course_activity",
        "full_system",
    }
)

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
        auth_method TEXT NOT NULL DEFAULT 'browser_key',
        sign_count INTEGER NOT NULL DEFAULT 0,
        transports TEXT NOT NULL DEFAULT '[]',
        aaguid TEXT NOT NULL DEFAULT '',
        credential_device_type TEXT NOT NULL DEFAULT '',
        credential_backed_up INTEGER NOT NULL DEFAULT 0,
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
        reason TEXT NOT NULL DEFAULT '',
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
    """
    CREATE TABLE IF NOT EXISTS data_reset_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_identifier TEXT NOT NULL,
        action TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_identifier TEXT NOT NULL,
        counts_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS location_attempt_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        schedule_id INTEGER REFERENCES course_schedules(id) ON DELETE SET NULL,
        attendance_date TEXT NOT NULL,
        attempt_type TEXT NOT NULL,
        outcome TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        message TEXT NOT NULL,
        latitude REAL,
        longitude REAL,
        accuracy_m REAL,
        distance_m REAL,
        radius_m REAL NOT NULL,
        captured_at TEXT,
        sample_count INTEGER,
        platform TEXT NOT NULL DEFAULT '',
        browser_family TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        recovered_at TEXT,
        coordinates_redacted_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS classroom_location_calibrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        previous_latitude REAL NOT NULL,
        previous_longitude REAL NOT NULL,
        new_latitude REAL NOT NULL,
        new_longitude REAL NOT NULL,
        reading_count INTEGER NOT NULL,
        median_accuracy_m REAL NOT NULL,
        actor_identifier TEXT NOT NULL,
        created_at TEXT NOT NULL
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
        auth_method TEXT NOT NULL DEFAULT 'browser_key',
        sign_count BIGINT NOT NULL DEFAULT 0,
        transports TEXT NOT NULL DEFAULT '[]',
        aaguid TEXT NOT NULL DEFAULT '',
        credential_device_type TEXT NOT NULL DEFAULT '',
        credential_backed_up INTEGER NOT NULL DEFAULT 0,
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
        reason TEXT NOT NULL DEFAULT '',
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
    """
    CREATE TABLE IF NOT EXISTS data_reset_audit (
        id BIGSERIAL PRIMARY KEY,
        actor_identifier TEXT NOT NULL,
        action TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_identifier TEXT NOT NULL,
        counts_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS location_attempt_events (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        schedule_id BIGINT REFERENCES course_schedules(id) ON DELETE SET NULL,
        attendance_date TEXT NOT NULL,
        attempt_type TEXT NOT NULL,
        outcome TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        message TEXT NOT NULL,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        accuracy_m DOUBLE PRECISION,
        distance_m DOUBLE PRECISION,
        radius_m DOUBLE PRECISION NOT NULL,
        captured_at TEXT,
        sample_count INTEGER,
        platform TEXT NOT NULL DEFAULT '',
        browser_family TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        recovered_at TEXT,
        coordinates_redacted_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS classroom_location_calibrations (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        previous_latitude DOUBLE PRECISION NOT NULL,
        previous_longitude DOUBLE PRECISION NOT NULL,
        new_latitude DOUBLE PRECISION NOT NULL,
        new_longitude DOUBLE PRECISION NOT NULL,
        reading_count INTEGER NOT NULL,
        median_accuracy_m DOUBLE PRECISION NOT NULL,
        actor_identifier TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)


class AttendanceRepository:
    def __init__(self, database_target: str, *, use_pool: bool = False) -> None:
        self.database_target = database_target.strip()
        self.backend = _detect_backend(self.database_target)
        self.db_path = (
            Path(_sqlite_path_from_target(self.database_target))
            if self.backend == "sqlite"
            else None
        )
        self._pool = None
        if self.backend == "postgres" and use_pool:
            self._pool = self._create_pool()

    def _create_pool(self):
        if ConnectionPool is None or dict_row is None:
            raise RuntimeError(
                "PostgreSQL pooling requires `psycopg[binary,pool]`. Install dependencies "
                "before running the app with ATTENDANCE_DB_URL."
            )
        pool = ConnectionPool(
            conninfo=_normalize_postgres_conninfo(self.database_target),
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            check=ConnectionPool.check_connection,
            timeout=10,
            max_idle=300,
            max_lifetime=1800,
            reconnect_timeout=10,
            name="classpresence",
            open=True,
        )
        try:
            pool.wait(timeout=10)
        except Exception as error:
            pool.close()
            raise DatabaseUnavailableError(
                "The database is temporarily unavailable. Check the database service and retry."
            ) from error
        return pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def check_connections(self) -> None:
        if self._pool is not None:
            self._pool.check()

    def init_schema(self) -> None:
        if self.backend == "sqlite" and self.db_path is not None and str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            schema_version = connection.execute(
                self._sql("SELECT value FROM app_metadata WHERE key = ?"),
                ("schema_version",),
            ).fetchone()
            if schema_version is not None and str(schema_version["value"]) == SCHEMA_VERSION:
                return
            for statement in self._schema_statements():
                connection.execute(statement)
            self._migrate_schema(connection)
            connection.execute(
                self._sql(
                    """
                    INSERT INTO app_metadata (key, value)
                    VALUES (?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value
                    """
                ),
                ("schema_version", SCHEMA_VERSION),
            )

    def prepare_data_reset(
        self,
        *,
        action: str,
        course_id: int | None = None,
        student_id: int | None = None,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            return self._build_data_reset_snapshot(
                connection,
                action=action,
                course_id=course_id,
                student_id=student_id,
            )

    def execute_data_reset(
        self,
        *,
        action: str,
        actor_identifier: str,
        created_at: str,
        course_id: int | None = None,
        student_id: int | None = None,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            snapshot = self._build_data_reset_snapshot(
                connection,
                action=action,
                course_id=course_id,
                student_id=student_id,
            )
            exclusive_student_ids = [
                int(row["id"])
                for row in snapshot["tables"].get("students", [])
            ]

            if action == "course_attendance":
                connection.execute(
                    self._sql("DELETE FROM attendance_records WHERE course_id = ?"),
                    (course_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM location_attempt_events WHERE course_id = ?"),
                    (course_id,),
                )
            elif action == "course_timetable":
                connection.execute(
                    self._sql("DELETE FROM attendance_records WHERE course_id = ?"),
                    (course_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM otp_codes WHERE course_id = ?"),
                    (course_id,),
                )
                connection.execute(
                    self._sql(
                        "DELETE FROM pending_browser_enrollments WHERE course_id = ?"
                    ),
                    (course_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM location_attempt_events WHERE course_id = ?"),
                    (course_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM course_schedules WHERE course_id = ?"),
                    (course_id,),
                )
            elif action == "course_roster":
                connection.execute(
                    self._sql("DELETE FROM course_students WHERE course_id = ?"),
                    (course_id,),
                )
            elif action == "course_activity":
                for table_name in (
                    "attendance_records",
                    "otp_codes",
                    "pending_browser_enrollments",
                    "proxy_alerts",
                    "location_attempt_events",
                    "course_schedules",
                    "device_audit_events",
                ):
                    connection.execute(
                        self._sql(f"DELETE FROM {table_name} WHERE course_id = ?"),
                        (course_id,),
                    )
            elif action == "delete_course":
                connection.execute(
                    self._sql("DELETE FROM device_audit_events WHERE course_id = ?"),
                    (course_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM courses WHERE id = ?"),
                    (course_id,),
                )
                if exclusive_student_ids:
                    placeholders = ", ".join("?" for _ in exclusive_student_ids)
                    connection.execute(
                        self._sql(
                            f"""
                            DELETE FROM students
                            WHERE id IN ({placeholders})
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM course_students cs
                                  WHERE cs.student_id = students.id
                              )
                            """
                        ),
                        exclusive_student_ids,
                    )
            elif action == "student_attendance":
                connection.execute(
                    self._sql(
                        "DELETE FROM attendance_records WHERE course_id = ? AND student_id = ?"
                    ),
                    (course_id, student_id),
                )
                connection.execute(
                    self._sql(
                        "DELETE FROM location_attempt_events "
                        "WHERE course_id = ? AND student_id = ?"
                    ),
                    (course_id, student_id),
                )
            elif action == "student_device":
                device_rows = snapshot["tables"].get("registered_devices", [])
                if device_rows:
                    device = device_rows[0]
                    self._insert_device_audit_event(
                        connection,
                        student_id=int(student_id),
                        university_id=str(snapshot["student_university_id"]),
                        student_name=str(snapshot["student_name"]),
                        course_id=course_id,
                        course_code=str(snapshot["course_code"]),
                        event_type="manager_device_reset",
                        actor_type="manager",
                        actor_identifier=actor_identifier,
                        previous_device_id=int(device["id"]),
                        previous_device_binding_hash=str(device["device_binding_hash"]),
                        new_device_id=None,
                        new_device_binding_hash=None,
                        created_at=created_at,
                    )
                connection.execute(
                    self._sql(
                        "DELETE FROM pending_browser_enrollments WHERE student_id = ?"
                    ),
                    (student_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM otp_codes WHERE student_id = ?"),
                    (student_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM registered_devices WHERE student_id = ?"),
                    (student_id,),
                )
            elif action == "delete_student":
                connection.execute(
                    self._sql("DELETE FROM device_audit_events WHERE student_id = ?"),
                    (student_id,),
                )
                connection.execute(
                    self._sql("DELETE FROM students WHERE id = ?"),
                    (student_id,),
                )
            elif action == "reset_all_students":
                connection.execute("DELETE FROM device_audit_events")
                connection.execute("DELETE FROM students")
            elif action == "reset_all_course_activity":
                for table_name in (
                    "attendance_records",
                    "otp_codes",
                    "pending_browser_enrollments",
                    "proxy_alerts",
                    "location_attempt_events",
                    "course_schedules",
                    "device_audit_events",
                ):
                    connection.execute(f"DELETE FROM {table_name}")
            elif action == "full_system":
                for table_name in (
                    "attendance_records",
                    "otp_codes",
                    "pending_browser_enrollments",
                    "proxy_alerts",
                    "location_attempt_events",
                    "classroom_location_calibrations",
                    "course_students",
                    "course_schedules",
                    "registered_devices",
                    "device_audit_events",
                    "courses",
                    "students",
                    "data_reset_audit",
                ):
                    connection.execute(f"DELETE FROM {table_name}")

            self._insert_data_reset_audit(
                connection,
                actor_identifier=actor_identifier,
                action=action,
                scope_type=str(snapshot["scope_type"]),
                scope_identifier=str(snapshot["scope_identifier"]),
                counts=snapshot["counts"],
                created_at=created_at,
            )
            return {
                "action": action,
                "scope_type": snapshot["scope_type"],
                "scope_identifier": snapshot["scope_identifier"],
                "counts": snapshot["counts"],
            }

    def record_data_management_audit(
        self,
        *,
        actor_identifier: str,
        action: str,
        scope_type: str,
        scope_identifier: str,
        counts: dict[str, int],
        created_at: str,
    ) -> None:
        with self._connection() as connection:
            self._insert_data_reset_audit(
                connection,
                actor_identifier=actor_identifier,
                action=action,
                scope_type=scope_type,
                scope_identifier=scope_identifier,
                counts=counts,
                created_at=created_at,
            )

    def list_data_reset_audit(self, *, limit: int = 100) -> list[Record]:
        rows = self._fetchall(
            """
            SELECT *
            FROM data_reset_audit
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        for row in rows:
            try:
                row["counts"] = json.loads(str(row["counts_json"]))
            except json.JSONDecodeError:
                row["counts"] = {}
        return rows

    def _build_data_reset_snapshot(
        self,
        connection,
        *,
        action: str,
        course_id: int | None,
        student_id: int | None,
    ) -> dict[str, Any]:
        if action not in DATA_RESET_ACTIONS:
            raise ValueError("Unsupported data reset action.")

        def fetch(query: str, parameters: Iterable[Any] = ()) -> list[Record]:
            rows = connection.execute(self._sql(query), parameters).fetchall()
            return [dict(row) for row in rows]

        course_actions = {
            "course_attendance",
            "course_timetable",
            "course_roster",
            "course_activity",
            "delete_course",
            "student_attendance",
        }
        student_actions = {
            "student_attendance",
            "student_device",
            "delete_student",
        }
        course = None
        student = None
        if action in course_actions:
            if course_id is None:
                raise ValueError("Select a course before preparing this reset.")
            course_rows = fetch("SELECT * FROM courses WHERE id = ?", (course_id,))
            if not course_rows:
                raise ValueError("Course was not found.")
            course = course_rows[0]
        if action in student_actions:
            if student_id is None:
                raise ValueError("Select a student before preparing this reset.")
            student_rows = fetch("SELECT * FROM students WHERE id = ?", (student_id,))
            if not student_rows:
                raise ValueError("Student was not found.")
            student = student_rows[0]
            if course is None and course_id is not None:
                course_rows = fetch("SELECT * FROM courses WHERE id = ?", (course_id,))
                if course_rows:
                    course = course_rows[0]
        if action == "student_attendance":
            enrollment = fetch(
                "SELECT id FROM course_students WHERE course_id = ? AND student_id = ?",
                (course_id, student_id),
            )
            if not enrollment:
                raise ValueError("Student is not enrolled in the selected course.")

        tables: dict[str, list[Record]] = {}
        if action == "course_attendance":
            tables = {
                "attendance_records": fetch(
                    "SELECT * FROM attendance_records WHERE course_id = ?",
                    (course_id,),
                ),
                "location_attempt_events": fetch(
                    "SELECT * FROM location_attempt_events WHERE course_id = ?",
                    (course_id,),
                ),
            }
        elif action == "course_timetable":
            tables = {
                "attendance_records": fetch(
                    "SELECT * FROM attendance_records WHERE course_id = ?", (course_id,)
                ),
                "otp_codes": fetch(
                    "SELECT * FROM otp_codes WHERE course_id = ?", (course_id,)
                ),
                "pending_browser_enrollments": fetch(
                    "SELECT * FROM pending_browser_enrollments WHERE course_id = ?",
                    (course_id,),
                ),
                "location_attempt_events": fetch(
                    "SELECT * FROM location_attempt_events WHERE course_id = ?",
                    (course_id,),
                ),
                "course_schedules": fetch(
                    "SELECT * FROM course_schedules WHERE course_id = ?", (course_id,)
                ),
            }
        elif action == "course_roster":
            tables["course_students"] = fetch(
                "SELECT * FROM course_students WHERE course_id = ?",
                (course_id,),
            )
        elif action == "course_activity":
            for table_name in (
                "attendance_records",
                "otp_codes",
                "pending_browser_enrollments",
                "proxy_alerts",
                "location_attempt_events",
                "course_schedules",
                "device_audit_events",
            ):
                tables[table_name] = fetch(
                    f"SELECT * FROM {table_name} WHERE course_id = ?",
                    (course_id,),
                )
        elif action == "delete_course":
            tables = {
                "courses": [dict(course)],
                "course_students": fetch(
                    "SELECT * FROM course_students WHERE course_id = ?", (course_id,)
                ),
                "course_schedules": fetch(
                    "SELECT * FROM course_schedules WHERE course_id = ?", (course_id,)
                ),
                "otp_codes": fetch(
                    "SELECT * FROM otp_codes WHERE course_id = ?", (course_id,)
                ),
                "pending_browser_enrollments": fetch(
                    "SELECT * FROM pending_browser_enrollments WHERE course_id = ?",
                    (course_id,),
                ),
                "attendance_records": fetch(
                    "SELECT * FROM attendance_records WHERE course_id = ?", (course_id,)
                ),
                "proxy_alerts": fetch(
                    "SELECT * FROM proxy_alerts WHERE course_id = ?", (course_id,)
                ),
                "device_audit_events": fetch(
                    "SELECT * FROM device_audit_events WHERE course_id = ?", (course_id,)
                ),
                "location_attempt_events": fetch(
                    "SELECT * FROM location_attempt_events WHERE course_id = ?",
                    (course_id,),
                ),
                "classroom_location_calibrations": fetch(
                    "SELECT * FROM classroom_location_calibrations WHERE course_id = ?",
                    (course_id,),
                ),
                "students": fetch(
                    """
                    SELECT s.*
                    FROM students s
                    INNER JOIN course_students cs ON cs.student_id = s.id
                    WHERE cs.course_id = ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM course_students other
                          WHERE other.student_id = s.id AND other.course_id <> ?
                      )
                    """,
                    (course_id, course_id),
                ),
            }
            exclusive_ids = [int(row["id"]) for row in tables["students"]]
            if exclusive_ids:
                placeholders = ", ".join("?" for _ in exclusive_ids)
                tables["registered_devices"] = fetch(
                    f"SELECT * FROM registered_devices WHERE student_id IN ({placeholders})",
                    exclusive_ids,
                )
            else:
                tables["registered_devices"] = []
        elif action == "student_attendance":
            tables = {
                "attendance_records": fetch(
                    """
                    SELECT *
                    FROM attendance_records
                    WHERE course_id = ? AND student_id = ?
                    """,
                    (course_id, student_id),
                ),
                "location_attempt_events": fetch(
                    """
                    SELECT *
                    FROM location_attempt_events
                    WHERE course_id = ? AND student_id = ?
                    """,
                    (course_id, student_id),
                ),
            }
        elif action == "student_device":
            tables = {
                "registered_devices": fetch(
                    "SELECT * FROM registered_devices WHERE student_id = ?", (student_id,)
                ),
                "pending_browser_enrollments": fetch(
                    "SELECT * FROM pending_browser_enrollments WHERE student_id = ?",
                    (student_id,),
                ),
                "otp_codes": fetch(
                    "SELECT * FROM otp_codes WHERE student_id = ?", (student_id,)
                ),
            }
        elif action == "delete_student":
            tables = {
                "students": [dict(student)],
                "course_students": fetch(
                    "SELECT * FROM course_students WHERE student_id = ?", (student_id,)
                ),
                "attendance_records": fetch(
                    "SELECT * FROM attendance_records WHERE student_id = ?", (student_id,)
                ),
                "otp_codes": fetch(
                    "SELECT * FROM otp_codes WHERE student_id = ?", (student_id,)
                ),
                "registered_devices": fetch(
                    "SELECT * FROM registered_devices WHERE student_id = ?", (student_id,)
                ),
                "pending_browser_enrollments": fetch(
                    "SELECT * FROM pending_browser_enrollments WHERE student_id = ?",
                    (student_id,),
                ),
                "proxy_alerts": fetch(
                    "SELECT * FROM proxy_alerts WHERE student_id = ?", (student_id,)
                ),
                "device_audit_events": fetch(
                    "SELECT * FROM device_audit_events WHERE student_id = ?", (student_id,)
                ),
                "location_attempt_events": fetch(
                    "SELECT * FROM location_attempt_events WHERE student_id = ?",
                    (student_id,),
                ),
            }
        elif action in {"reset_all_students", "reset_all_course_activity", "full_system"}:
            table_names = (
                (
                    "students",
                    "course_students",
                    "otp_codes",
                    "registered_devices",
                    "pending_browser_enrollments",
                    "device_audit_events",
                    "attendance_records",
                    "proxy_alerts",
                    "location_attempt_events",
                )
                if action == "reset_all_students"
                else (
                    "course_schedules",
                    "otp_codes",
                    "pending_browser_enrollments",
                    "device_audit_events",
                    "attendance_records",
                    "proxy_alerts",
                    "location_attempt_events",
                )
                if action == "reset_all_course_activity"
                else (
                    "courses",
                    "students",
                    "course_students",
                    "course_schedules",
                    "otp_codes",
                    "registered_devices",
                    "pending_browser_enrollments",
                    "device_audit_events",
                    "attendance_records",
                    "proxy_alerts",
                    "location_attempt_events",
                    "classroom_location_calibrations",
                    "data_reset_audit",
                )
            )
            for table_name in table_names:
                tables[table_name] = fetch(f"SELECT * FROM {table_name}")

        if action in {"reset_all_students", "reset_all_course_activity", "full_system"}:
            scope_type = "system"
            scope_identifier = "SYSTEM"
        elif action in student_actions:
            scope_type = "student"
            scope_identifier = str(student["university_id"])
        else:
            scope_type = "course"
            scope_identifier = str(course["code"])
        return {
            "action": action,
            "scope_type": scope_type,
            "scope_identifier": scope_identifier,
            "course_id": course_id,
            "course_code": str(course["code"]) if course is not None else "",
            "student_id": student_id,
            "student_university_id": (
                str(student["university_id"]) if student is not None else ""
            ),
            "student_name": str(student["full_name"]) if student is not None else "",
            "counts": {table_name: len(rows) for table_name, rows in tables.items()},
            "tables": tables,
        }

    def _insert_data_reset_audit(
        self,
        connection,
        *,
        actor_identifier: str,
        action: str,
        scope_type: str,
        scope_identifier: str,
        counts: dict[str, int],
        created_at: str,
    ) -> None:
        connection.execute(
            self._sql(
                """
                INSERT INTO data_reset_audit (
                    actor_identifier, action, scope_type, scope_identifier,
                    counts_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """
            ),
            (
                actor_identifier,
                action,
                scope_type,
                scope_identifier,
                json.dumps(counts, sort_keys=True),
                created_at,
            ),
        )

    def create_location_attempt_event(
        self,
        *,
        course_id: int,
        student_id: int,
        schedule_id: int | None,
        attendance_date: str,
        attempt_type: str,
        outcome: str,
        reason_code: str,
        message: str,
        latitude: float | None,
        longitude: float | None,
        accuracy_m: float | None,
        distance_m: float | None,
        radius_m: float,
        captured_at: str | None,
        sample_count: int | None,
        platform: str,
        browser_family: str,
        created_at: str,
        coordinate_cutoff_iso: str | None = None,
    ) -> int:
        with self._connection() as connection:
            if coordinate_cutoff_iso:
                connection.execute(
                    self._sql(
                        """
                        UPDATE location_attempt_events
                        SET latitude = NULL,
                            longitude = NULL,
                            coordinates_redacted_at = ?
                        WHERE created_at < ?
                          AND coordinates_redacted_at IS NULL
                          AND (latitude IS NOT NULL OR longitude IS NOT NULL)
                        """
                    ),
                    (created_at, coordinate_cutoff_iso),
                )
            if outcome == "accepted":
                connection.execute(
                    self._sql(
                        """
                        UPDATE location_attempt_events
                        SET recovered_at = ?
                        WHERE course_id = ?
                          AND student_id = ?
                          AND attendance_date = ?
                          AND outcome <> 'accepted'
                          AND recovered_at IS NULL
                          AND created_at <= ?
                          AND (schedule_id = ? OR schedule_id IS NULL OR ? IS NULL)
                        """
                    ),
                    (
                        created_at,
                        course_id,
                        student_id,
                        attendance_date,
                        created_at,
                        schedule_id,
                        schedule_id,
                    ),
                )
            query = """
                INSERT INTO location_attempt_events (
                    course_id, student_id, schedule_id, attendance_date,
                    attempt_type, outcome, reason_code, message, latitude,
                    longitude, accuracy_m, distance_m, radius_m, captured_at,
                    sample_count, platform, browser_family, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgres":
                query += " RETURNING id"
            cursor = connection.execute(
                self._sql(query),
                (
                    course_id,
                    student_id,
                    schedule_id,
                    attendance_date,
                    attempt_type,
                    outcome,
                    reason_code,
                    message[:500],
                    latitude,
                    longitude,
                    accuracy_m,
                    distance_m,
                    radius_m,
                    captured_at,
                    sample_count,
                    platform[:100],
                    browser_family[:50],
                    created_at,
                ),
            )
            if self.backend == "postgres":
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Expected a location-event row ID.")
                return int(row["id"])
            return int(cursor.lastrowid)

    def list_location_attempt_events(
        self,
        *,
        course_id: int,
        created_after: str | None = None,
        limit: int = 20000,
    ) -> list[Record]:
        parameters: list[Any] = [course_id]
        date_filter = ""
        if created_after:
            date_filter = "AND la.created_at >= ?"
            parameters.append(created_after)
        parameters.append(limit)
        return self._fetchall(
            f"""
            SELECT
                la.*,
                s.full_name,
                s.university_id,
                cs.label AS schedule_label,
                cs.start_time AS schedule_start_time,
                cs.end_time AS schedule_end_time
            FROM location_attempt_events la
            INNER JOIN students s ON s.id = la.student_id
            LEFT JOIN course_schedules cs ON cs.id = la.schedule_id
            WHERE la.course_id = ?
              {date_filter}
            ORDER BY la.created_at DESC, la.id DESC
            LIMIT ?
            """,
            parameters,
        )

    def anonymize_location_coordinates_before(
        self,
        *,
        cutoff_iso: str,
        redacted_at: str,
    ) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql(
                    """
                    UPDATE location_attempt_events
                    SET latitude = NULL,
                        longitude = NULL,
                        coordinates_redacted_at = ?
                    WHERE created_at < ?
                      AND coordinates_redacted_at IS NULL
                      AND (latitude IS NOT NULL OR longitude IS NOT NULL)
                    """
                ),
                (redacted_at, cutoff_iso),
            )
            return int(cursor.rowcount or 0)

    def apply_course_location_calibration(
        self,
        *,
        course_id: int,
        latitude: float,
        longitude: float,
        reading_count: int,
        median_accuracy_m: float,
        actor_identifier: str,
        created_at: str,
    ) -> None:
        with self._connection() as connection:
            course = connection.execute(
                self._sql("SELECT latitude, longitude FROM courses WHERE id = ?"),
                (course_id,),
            ).fetchone()
            if course is None:
                raise ValueError("Course was not found.")
            connection.execute(
                self._sql(
                    "UPDATE courses SET latitude = ?, longitude = ? WHERE id = ?"
                ),
                (latitude, longitude, course_id),
            )
            connection.execute(
                self._sql(
                    """
                    INSERT INTO classroom_location_calibrations (
                        course_id, previous_latitude, previous_longitude,
                        new_latitude, new_longitude, reading_count,
                        median_accuracy_m, actor_identifier, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    course_id,
                    float(course["latitude"]),
                    float(course["longitude"]),
                    latitude,
                    longitude,
                    reading_count,
                    median_accuracy_m,
                    actor_identifier,
                    created_at,
                ),
            )

    def list_course_location_calibrations(
        self,
        *,
        course_id: int,
        limit: int = 100,
    ) -> list[Record]:
        return self._fetchall(
            """
            SELECT *
            FROM classroom_location_calibrations
            WHERE course_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (course_id, limit),
        )

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
                s.phone,
                rd.id AS registered_device_id,
                rd.device_binding_hash AS registered_device_binding_hash
            FROM students s
            INNER JOIN course_students cs ON cs.student_id = s.id
            INNER JOIN courses c ON c.id = cs.course_id
            LEFT JOIN registered_devices rd ON rd.student_id = s.id
            WHERE s.university_id = ?
            ORDER BY c.code
            """,
            (university_id,),
        )

    def get_student_course_snapshot(
        self,
        *,
        course_id: int,
        student_id: int | None = None,
        university_id: str | None = None,
    ) -> dict[str, Any] | None:
        if (student_id is None) == (university_id is None):
            raise ValueError("Provide exactly one student identifier.")
        selector = "s.id" if student_id is not None else "s.university_id"
        selector_value = student_id if student_id is not None else university_id
        with self._connection() as connection:
            row = connection.execute(
                self._sql(
                    f"""
                    SELECT
                        c.id AS course_id,
                        c.code AS course_code,
                        c.title AS course_title,
                        c.start_date AS course_start_date,
                        c.end_date AS course_end_date,
                        c.total_meetings AS course_total_meetings,
                        c.latitude AS course_latitude,
                        c.longitude AS course_longitude,
                        c.radius_m AS course_radius_m,
                        c.absence_limit_pct AS course_absence_limit_pct,
                        c.created_at AS course_created_at,
                        s.id AS student_id,
                        s.full_name AS student_full_name,
                        s.university_id AS student_university_id,
                        s.email AS student_email,
                        s.phone AS student_phone,
                        s.created_at AS student_created_at,
                        rd.id AS registered_device_id,
                        rd.credential_id AS registered_device_credential_id,
                        rd.public_key AS registered_device_public_key,
                        rd.sign_count AS registered_device_sign_count,
                        rd.device_binding_hash AS registered_device_binding_hash,
                        rd.transports AS registered_device_transports,
                        rd.aaguid AS registered_device_aaguid,
                        rd.credential_device_type AS registered_device_type,
                        rd.credential_backed_up AS registered_device_backed_up,
                        rd.auth_method AS registered_device_auth_method,
                        rd.created_at AS registered_device_created_at,
                        rd.last_used_at AS registered_device_last_used_at
                    FROM courses c
                    INNER JOIN course_students cs ON cs.course_id = c.id
                    INNER JOIN students s ON s.id = cs.student_id
                    LEFT JOIN registered_devices rd ON rd.student_id = s.id
                    WHERE c.id = ? AND {selector} = ?
                    LIMIT 1
                    """
                ),
                (course_id, selector_value),
            ).fetchone()
            if row is None:
                return None
            schedules = connection.execute(
                self._sql(
                    """
                    SELECT *
                    FROM course_schedules
                    WHERE course_id = ?
                    ORDER BY weekday, start_time, label
                    """
                ),
                (course_id,),
            ).fetchall()

        row = dict(row)
        device = None
        if row.get("registered_device_id") is not None:
            device = {
                "id": int(row["registered_device_id"]),
                "student_id": int(row["student_id"]),
                "credential_id": str(row["registered_device_credential_id"]),
                "public_key": str(row["registered_device_public_key"]),
                "sign_count": int(row["registered_device_sign_count"]),
                "device_binding_hash": str(row["registered_device_binding_hash"]),
                "transports": str(row["registered_device_transports"]),
                "aaguid": str(row["registered_device_aaguid"]),
                "credential_device_type": str(row["registered_device_type"]),
                "credential_backed_up": int(row["registered_device_backed_up"]),
                "auth_method": str(row["registered_device_auth_method"]),
                "created_at": row["registered_device_created_at"],
                "last_used_at": row["registered_device_last_used_at"],
            }
        return {
            "course": {
                "id": int(row["course_id"]),
                "code": row["course_code"],
                "title": row["course_title"],
                "start_date": row["course_start_date"],
                "end_date": row["course_end_date"],
                "total_meetings": int(row["course_total_meetings"]),
                "latitude": float(row["course_latitude"]),
                "longitude": float(row["course_longitude"]),
                "radius_m": float(row["course_radius_m"]),
                "absence_limit_pct": float(row["course_absence_limit_pct"]),
                "created_at": row["course_created_at"],
            },
            "student": {
                "id": int(row["student_id"]),
                "full_name": row["student_full_name"],
                "university_id": row["student_university_id"],
                "email": row["student_email"],
                "phone": row["student_phone"],
                "created_at": row["student_created_at"],
            },
            "device": device,
            "schedules": [dict(schedule) for schedule in schedules],
        }

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

    def list_schedules_for_courses(self, course_ids: list[int]) -> dict[int, list[Record]]:
        if not course_ids:
            return {}
        placeholders = ", ".join("?" for _ in course_ids)
        rows = self._fetchall(
            f"""
            SELECT *
            FROM course_schedules
            WHERE course_id IN ({placeholders})
            ORDER BY course_id, weekday, start_time, label
            """,
            course_ids,
        )
        schedules_by_course = {course_id: [] for course_id in course_ids}
        for row in rows:
            schedules_by_course.setdefault(int(row["course_id"]), []).append(row)
        return schedules_by_course

    def get_manager_today_snapshot(
        self,
        *,
        course_ids: list[int],
        attendance_date: str,
    ) -> dict[str, Any]:
        if not course_ids:
            return {
                "student_counts": {},
                "schedules_by_course": {},
                "attendance_counts": {},
                "records_today": 0,
            }

        placeholders = ", ".join("?" for _ in course_ids)
        with self._connection() as connection:
            student_rows = connection.execute(
                self._sql(
                    f"""
                    SELECT course_id, COUNT(*) AS student_count
                    FROM course_students
                    WHERE course_id IN ({placeholders})
                    GROUP BY course_id
                    """
                ),
                course_ids,
            ).fetchall()
            schedule_rows = connection.execute(
                self._sql(
                    f"""
                    SELECT *
                    FROM course_schedules
                    WHERE course_id IN ({placeholders})
                    ORDER BY course_id, weekday, start_time, label
                    """
                ),
                course_ids,
            ).fetchall()
            attendance_rows = connection.execute(
                self._sql(
                    f"""
                    SELECT course_id, schedule_id, COUNT(*) AS attendance_count
                    FROM attendance_records
                    WHERE attendance_date = ?
                      AND course_id IN ({placeholders})
                    GROUP BY course_id, schedule_id
                    """
                ),
                (attendance_date, *course_ids),
            ).fetchall()

        student_counts = {
            int(row["course_id"]): int(row["student_count"])
            for row in student_rows
        }
        schedules_by_course = {course_id: [] for course_id in course_ids}
        for row in schedule_rows:
            schedules_by_course.setdefault(int(row["course_id"]), []).append(dict(row))
        attendance_counts = {
            (int(row["course_id"]), int(row["schedule_id"])): int(
                row["attendance_count"]
            )
            for row in attendance_rows
        }
        return {
            "student_counts": student_counts,
            "schedules_by_course": schedules_by_course,
            "attendance_counts": attendance_counts,
            "records_today": sum(attendance_counts.values()),
        }

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

    def list_registered_device_conflicts(
        self,
        *,
        student_id: int,
        device_binding_hash: str,
    ) -> list[Record]:
        return self._fetchall(
            """
            SELECT *
            FROM registered_devices
            WHERE student_id = ? OR device_binding_hash = ?
            """,
            (student_id, device_binding_hash),
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

    def create_pending_device_enrollment(
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
        auth_method: str = "browser_key",
        sign_count: int = 0,
        transports: str = "[]",
        aaguid: str = "",
        credential_device_type: str = "",
        credential_backed_up: bool = False,
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
                    fallback_reason, auth_method, sign_count, transports, aaguid,
                    credential_device_type, credential_backed_up, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
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
                    auth_method,
                    sign_count,
                    transports,
                    aaguid,
                    credential_device_type,
                    int(credential_backed_up),
                    created_at,
                ),
            )
            if self.backend == "postgres":
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Expected a pending enrollment ID.")
                return int(row["id"])
            return int(cursor.lastrowid)

    def create_pending_browser_enrollment(self, **kwargs) -> int:
        """Compatibility wrapper for legacy browser-key migrations."""
        return self.create_pending_device_enrollment(**kwargs)

    def get_pending_device_enrollment(self, pending_id: int) -> Record | None:
        return self._fetchone(
            "SELECT * FROM pending_browser_enrollments WHERE id = ?",
            (pending_id,),
        )

    def get_pending_browser_enrollment(self, pending_id: int) -> Record | None:
        return self.get_pending_device_enrollment(pending_id)

    def list_pending_device_enrollments(self, *, course_id: int) -> list[Record]:
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

    def list_pending_browser_enrollments(self, *, course_id: int) -> list[Record]:
        return self.list_pending_device_enrollments(course_id=course_id)

    def approve_pending_device_enrollment(
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
                raise ValueError("This device enrollment request is no longer pending.")
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
                raise ValueError("This device enrollment request has expired.")

            registered_device = connection.execute(
                self._sql(
                    """
                    SELECT * FROM registered_devices
                    WHERE student_id = ?
                    LIMIT 1
                    """
                ),
                (int(pending["student_id"]),),
            ).fetchone()
            conflicting_device = connection.execute(
                self._sql(
                    """
                    SELECT * FROM registered_devices
                    WHERE student_id <> ?
                      AND (device_binding_hash = ? OR credential_id = ?)
                    LIMIT 1
                    """
                ),
                (
                    int(pending["student_id"]),
                    str(pending["device_binding_hash"]),
                    str(pending["credential_id"]),
                ),
            ).fetchone()
            if conflicting_device is not None:
                raise ValueError("The student or device already has a registered device.")

            is_recovery = (
                str(pending["fallback_reason"] or "")
                == BROWSER_KEY_RECOVERY_REASON
            )
            auth_method = str(pending["auth_method"] or "browser_key")
            if is_recovery:
                if (
                    registered_device is None
                    or str(registered_device["auth_method"] or "passkey")
                    != "browser_key"
                    or str(registered_device["device_binding_hash"])
                    != str(pending["device_binding_hash"])
                ):
                    raise ValueError(
                        "The registered device no longer matches this recovery request."
                    )
                device_id = int(registered_device["id"])
                connection.execute(
                    self._sql(
                        """
                        UPDATE registered_devices
                        SET credential_id = ?, public_key = ?, sign_count = 0,
                            transports = '[]', aaguid = '',
                            credential_device_type = 'device_credential',
                            credential_backed_up = 0, auth_method = 'browser_key',
                            last_used_at = ?
                        WHERE id = ?
                        """
                    ),
                    (
                        str(pending["credential_id"]),
                        str(pending["public_key"]),
                        reviewed_at,
                        device_id,
                    ),
                )
            else:
                if registered_device is not None:
                    raise ValueError("The student or device already has a registered device.")
                insert_query = """
                    INSERT INTO registered_devices (
                        student_id, credential_id, public_key, sign_count,
                        device_binding_hash, transports, aaguid,
                        credential_device_type, credential_backed_up, auth_method,
                        created_at, last_used_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                if self.backend == "postgres":
                    insert_query += " RETURNING id"
                cursor = connection.execute(
                    self._sql(insert_query),
                    (
                        int(pending["student_id"]),
                        str(pending["credential_id"]),
                        str(pending["public_key"]),
                        int(pending["sign_count"] or 0),
                        str(pending["device_binding_hash"]),
                        str(pending["transports"] or "[]"),
                        str(pending["aaguid"] or ""),
                        str(pending["credential_device_type"] or ""),
                        int(pending["credential_backed_up"] or 0),
                        auth_method,
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
                event_type=(
                    "manager_browser_key_recovered"
                    if is_recovery
                    else (
                        "manager_passkey_approved"
                        if auth_method == "passkey"
                        else "manager_device_approved"
                    )
                ),
                actor_type="manager",
                actor_identifier=actor_identifier,
                previous_device_id=(
                    int(registered_device["id"])
                    if is_recovery and registered_device is not None
                    else None
                ),
                previous_device_binding_hash=(
                    str(registered_device["device_binding_hash"])
                    if is_recovery and registered_device is not None
                    else None
                ),
                new_device_id=device_id,
                new_device_binding_hash=str(pending["device_binding_hash"]),
                created_at=reviewed_at,
            )
            return device_id

    def approve_pending_browser_enrollment(self, **kwargs) -> int:
        return self.approve_pending_device_enrollment(**kwargs)

    def reject_pending_device_enrollment(
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

    def reject_pending_browser_enrollment(self, **kwargs) -> bool:
        return self.reject_pending_device_enrollment(**kwargs)

    def reset_registered_device_with_audit(
        self,
        *,
        student_id: int,
        course_id: int,
        actor_identifier: str,
        reason: str,
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
                reason=reason,
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

    def get_attendance_stamp_state(
        self,
        *,
        course_id: int,
        student_id: int,
        schedule_id: int,
        attendance_date: str,
        device_binding_hash: str,
    ) -> dict[str, Record | None]:
        with self._connection() as connection:
            registered_device = connection.execute(
                self._sql("SELECT * FROM registered_devices WHERE student_id = ?"),
                (student_id,),
            ).fetchone()
            existing_attendance = connection.execute(
                self._sql(
                    """
                    SELECT id
                    FROM attendance_records
                    WHERE course_id = ?
                      AND student_id = ?
                      AND schedule_id = ?
                      AND attendance_date = ?
                    LIMIT 1
                    """
                ),
                (course_id, student_id, schedule_id, attendance_date),
            ).fetchone()
            existing_device_stamp = connection.execute(
                self._sql(
                    """
                    SELECT ar.*, s.full_name, s.university_id
                    FROM attendance_records ar
                    INNER JOIN students s ON s.id = ar.student_id
                    WHERE ar.course_id = ?
                      AND ar.schedule_id = ?
                      AND ar.attendance_date = ?
                      AND ar.device_binding_hash = ?
                    LIMIT 1
                    """
                ),
                (course_id, schedule_id, attendance_date, device_binding_hash),
            ).fetchone()
        return {
            "registered_device": (
                dict(registered_device) if registered_device is not None else None
            ),
            "existing_attendance": (
                dict(existing_attendance) if existing_attendance is not None else None
            ),
            "existing_device_stamp": (
                dict(existing_device_stamp) if existing_device_stamp is not None else None
            ),
        }

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
            raise DatabaseUnavailableError(
                "The database is temporarily unavailable. Check the database service and retry."
            ) from error

    @contextmanager
    def _connection(self):
        if self._pool is not None:
            try:
                with self._pool.connection() as connection:
                    yield connection
            except Exception as error:
                if self._is_transient_database_error(error):
                    raise DatabaseUnavailableError(
                        "The database connection was interrupted. Please retry."
                    ) from error
                raise
            return

        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception as error:
            connection.rollback()
            if self._is_transient_database_error(error):
                raise DatabaseUnavailableError(
                    "The database connection was interrupted. Please retry."
                ) from error
            raise
        finally:
            connection.close()

    def _is_transient_database_error(self, error: Exception) -> bool:
        if self.backend != "postgres":
            return False
        if PoolTimeout is not None and isinstance(error, PoolTimeout):
            return True
        if psycopg is None:
            return False
        return isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))

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
            audit_columns = self._postgres_columns(connection, "device_audit_events")
            if "reason" not in audit_columns:
                connection.execute(
                    "ALTER TABLE device_audit_events ADD COLUMN reason TEXT "
                    "NOT NULL DEFAULT ''"
                )
            pending_columns = self._postgres_columns(connection, "pending_browser_enrollments")
            if "fallback_reason" not in pending_columns:
                connection.execute(
                    "ALTER TABLE pending_browser_enrollments ADD COLUMN fallback_reason TEXT "
                    "NOT NULL DEFAULT ''"
                )
            pending_additions = {
                "auth_method": "TEXT NOT NULL DEFAULT 'browser_key'",
                "sign_count": "BIGINT NOT NULL DEFAULT 0",
                "transports": "TEXT NOT NULL DEFAULT '[]'",
                "aaguid": "TEXT NOT NULL DEFAULT ''",
                "credential_device_type": "TEXT NOT NULL DEFAULT ''",
                "credential_backed_up": "INTEGER NOT NULL DEFAULT 0",
            }
            for column_name, definition in pending_additions.items():
                if column_name not in pending_columns:
                    connection.execute(
                        f"ALTER TABLE pending_browser_enrollments "
                        f"ADD COLUMN {column_name} {definition}"
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
        audit_columns = self._sqlite_columns(connection, "device_audit_events")
        if "reason" not in audit_columns:
            connection.execute(
                "ALTER TABLE device_audit_events ADD COLUMN reason TEXT "
                "NOT NULL DEFAULT ''"
            )
        pending_columns = self._sqlite_columns(connection, "pending_browser_enrollments")
        if "fallback_reason" not in pending_columns:
            connection.execute(
                "ALTER TABLE pending_browser_enrollments ADD COLUMN fallback_reason TEXT "
                "NOT NULL DEFAULT ''"
            )
        pending_additions = {
            "auth_method": "TEXT NOT NULL DEFAULT 'browser_key'",
            "sign_count": "INTEGER NOT NULL DEFAULT 0",
            "transports": "TEXT NOT NULL DEFAULT '[]'",
            "aaguid": "TEXT NOT NULL DEFAULT ''",
            "credential_device_type": "TEXT NOT NULL DEFAULT ''",
            "credential_backed_up": "INTEGER NOT NULL DEFAULT 0",
        }
        for column_name, definition in pending_additions.items():
            if column_name not in pending_columns:
                connection.execute(
                    f"ALTER TABLE pending_browser_enrollments "
                    f"ADD COLUMN {column_name} {definition}"
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
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_data_reset_audit_created
            ON data_reset_audit (created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_location_attempt_course_created
            ON location_attempt_events (course_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_location_attempt_course_reason
            ON location_attempt_events (course_id, reason_code, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_location_attempt_student_window
            ON location_attempt_events (
                student_id, course_id, attendance_date, schedule_id, created_at
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_location_calibration_course_created
            ON classroom_location_calibrations (course_id, created_at)
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
        reason: str = "",
    ) -> None:
        connection.execute(
            self._sql(
                """
                INSERT INTO device_audit_events (
                    student_id, university_id, student_name, course_id, course_code,
                    event_type, actor_type, actor_identifier, previous_device_id,
                    previous_device_binding_hash, new_device_id, new_device_binding_hash,
                    reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                reason,
                created_at,
            ),
        )

    def _fetchone(self, query: str, parameters: Iterable[Any] = ()) -> Record | None:
        sql = self._sql(query)
        values = tuple(parameters)
        for attempt in range(2):
            try:
                with self._connection() as connection:
                    row = connection.execute(sql, values).fetchone()
                break
            except DatabaseUnavailableError:
                if attempt == 1:
                    raise
        if row is None:
            return None
        return dict(row)

    def _fetchall(self, query: str, parameters: Iterable[Any] = ()) -> list[Record]:
        sql = self._sql(query)
        values = tuple(parameters)
        for attempt in range(2):
            try:
                with self._connection() as connection:
                    rows = connection.execute(sql, values).fetchall()
                break
            except DatabaseUnavailableError:
                if attempt == 1:
                    raise
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
