from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_timezone: str
    database_target: str
    manager_username: str
    manager_password_hash: str
    otp_delivery_mode: str
    otp_expiry_minutes: int
    otp_pepper: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_sender: str
    smtp_use_tls: bool

    @property
    def is_development(self) -> bool:
        return self.app_env.strip().lower() == "development"

    @property
    def database_path(self) -> str:
        return self.database_target


def load_settings(secrets: Mapping[str, Any] | None = None) -> Settings:
    app_env = _get_value("APP_ENV", "development", secrets)
    default_otp_delivery_mode = "console" if app_env.strip().lower() == "development" else "email"
    return Settings(
        app_env=app_env,
        app_timezone=_get_value("APP_TIMEZONE", "Asia/Riyadh", secrets),
        database_target=_load_database_target(secrets),
        manager_username=_get_value("MANAGER_USERNAME", "", secrets),
        manager_password_hash=_get_value("MANAGER_PASSWORD_HASH", "", secrets),
        otp_delivery_mode=_get_value("OTP_DELIVERY_MODE", default_otp_delivery_mode, secrets).lower(),
        otp_expiry_minutes=int(_get_value("OTP_EXPIRY_MINUTES", "10", secrets)),
        otp_pepper=_get_value("OTP_PEPPER", "change-me", secrets),
        smtp_host=_get_value("SMTP_HOST", "", secrets),
        smtp_port=int(_get_value("SMTP_PORT", "587", secrets)),
        smtp_username=_get_value("SMTP_USERNAME", "", secrets),
        smtp_password=_get_value("SMTP_PASSWORD", "", secrets),
        smtp_sender=_get_value("SMTP_SENDER", "", secrets),
        smtp_use_tls=_get_bool("SMTP_USE_TLS", True, secrets),
    )


def _get_value(key: str, default: str, secrets: Mapping[str, Any] | None) -> str:
    if key in os.environ:
        return os.environ[key]
    if secrets is not None and key in secrets:
        return str(secrets[key])
    return default


def _get_bool(key: str, default: bool, secrets: Mapping[str, Any] | None) -> bool:
    raw_value = _get_value(key, str(default).lower(), secrets)
    return raw_value.strip().lower() in TRUE_VALUES


def _load_database_target(secrets: Mapping[str, Any] | None) -> str:
    database_url = _get_value("ATTENDANCE_DB_URL", "", secrets).strip()
    if not database_url:
        database_url = _get_value("DATABASE_URL", "", secrets).strip()
    if database_url:
        return database_url
    database_url = _build_database_url_from_parts(secrets)
    if database_url:
        return database_url
    return _resolve_database_path(_get_value("ATTENDANCE_DB_PATH", "attendance.db", secrets))


def _resolve_database_path(raw_path: str) -> str:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    project_root = Path(__file__).resolve().parent.parent
    return str((project_root / candidate).resolve())


def _build_database_url_from_parts(secrets: Mapping[str, Any] | None) -> str:
    host = _first_non_empty(
        _get_value("ATTENDANCE_DB_HOST", "", secrets),
        _get_value("PGHOST", "", secrets),
    )
    database = _first_non_empty(
        _get_value("ATTENDANCE_DB_NAME", "", secrets),
        _get_value("PGDATABASE", "", secrets),
    )
    user = _first_non_empty(
        _get_value("ATTENDANCE_DB_USER", "", secrets),
        _get_value("PGUSER", "", secrets),
    )
    password = _first_non_empty(
        _get_value("ATTENDANCE_DB_PASSWORD", "", secrets),
        _get_value("PGPASSWORD", "", secrets),
    )
    port = _first_non_empty(
        _get_value("ATTENDANCE_DB_PORT", "", secrets),
        _get_value("PGPORT", "", secrets),
        "5432",
    )
    sslmode = _first_non_empty(
        _get_value("ATTENDANCE_DB_SSLMODE", "", secrets),
        _get_value("PGSSLMODE", "", secrets),
        "require",
    )

    if not host or not database or not user:
        return ""

    encoded_user = quote(user, safe="")
    encoded_password = quote(password, safe="")
    encoded_database = quote(database, safe="")
    auth = encoded_user
    if password:
        auth = f"{auth}:{encoded_password}"
    return (
        f"postgresql://{auth}@{host}:{port}/{encoded_database}"
        f"?sslmode={quote(sslmode, safe='')}"
    )


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""
