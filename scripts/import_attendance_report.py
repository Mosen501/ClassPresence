from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from attendance_app.config import load_settings
from attendance_app.database import AttendanceRepository
from attendance_app.report_importer import import_attendance_report_bytes


def main() -> int:
    args = _parse_args()
    workbook_path = Path(args.workbook).expanduser().resolve()
    if not workbook_path.exists():
        print(f"Workbook not found: {workbook_path}", file=sys.stderr)
        return 1

    secrets = _load_local_streamlit_secrets()
    settings = load_settings(secrets)
    database_target = args.database_target or settings.database_target
    repo = AttendanceRepository(database_target)
    repo.init_schema()

    summary = import_attendance_report_bytes(
        repo=repo,
        settings=settings,
        source_name=workbook_path.name,
        content=workbook_path.read_bytes(),
    )
    summary["database_target"] = database_target_label(repo)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def database_target_label(repo: AttendanceRepository) -> str:
    if repo.backend == "postgres":
        return "postgres"
    if repo.db_path is None:
        return "sqlite"
    return str(repo.db_path)


def _load_local_streamlit_secrets() -> dict[str, str]:
    secrets_path = Path(".streamlit/secrets.toml")
    if not secrets_path.exists():
        return {}
    with secrets_path.open("rb") as handle:
        raw = tomllib.load(handle)
    return {str(key): str(value) for key, value in raw.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import an attendance report workbook into the configured database."
    )
    parser.add_argument("workbook", help="Path to the attendance report .xlsx file")
    parser.add_argument(
        "--database-target",
        help="Override the database target or PostgreSQL URL for this import only.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
