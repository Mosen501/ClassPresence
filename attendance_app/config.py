from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_timezone: str
    database_path: str
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


def load_settings(secrets: Mapping[str, Any] | None = None) -> Settings:
    app_env = _get_value("APP_ENV", "development", secrets)
    default_otp_delivery_mode = "console" if app_env.strip().lower() == "development" else "email"
    return Settings(
        app_env=app_env,
        app_timezone=_get_value("APP_TIMEZONE", "Asia/Riyadh", secrets),
        database_path=_resolve_database_path(_get_value("ATTENDANCE_DB_PATH", "attendance.db", secrets)),
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


def _resolve_database_path(raw_path: str) -> str:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    project_root = Path(__file__).resolve().parent.parent
    return str((project_root / candidate).resolve())
