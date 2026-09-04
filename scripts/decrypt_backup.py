from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from attendance_app.backups import decrypt_backup_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Decrypt a ClassPresence .cpbackup file to JSON.")
    parser.add_argument("input", type=Path, help="Encrypted .cpbackup file")
    parser.add_argument("output", type=Path, help="Destination JSON file")
    args = parser.parse_args()
    password = getpass.getpass("Backup password: ")
    payload = decrypt_backup_payload(args.input.read_bytes(), password)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Decrypted backup written to {args.output}")


if __name__ == "__main__":
    main()
