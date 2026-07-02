# AttendancApp

AttendancApp is a Streamlit-based attendance platform for university classes. It gives academic managers a protected portal for configuring courses, defining class meeting windows, syncing official rosters, exporting Excel reports, and geofencing attendance to a configurable classroom radius.

Students sign in with a one-time password tied to the email address on their course roster, stamp attendance only during approved schedule windows, and view their attendance statistics in real time. The application also flags exam ineligibility when absences reach 20% of the configured total meetings.

## Features

- Manager portal protected by a server-side username and hashed password
- Course setup with course code, course name, start date, end date, timetable windows, classroom location, and attendance radius
- Bulk student import from `.xlsx` or `.csv` with `student id`, `student name`, and `email` columns
- Roster-only enrollment workflow so students must exist on the uploaded course roster
- Student portal with roster-linked one-time password login
- Excel workbook export for course details, roster, timetable, attendance, and eligibility reports
- Email-based OTP delivery, with a development-friendly console fallback
- Geofenced attendance stamping within a configurable radius that defaults to 3 meters
- Attendance records with timestamp, device information, and location distance checks
- Student dashboard with attendance totals, absences, and exam-entry status
- SQLite storage so the app runs locally without extra infrastructure

## Why Email OTP By Default

Reliable SMS delivery is usually not free in production. Because of that, this project ships with email OTP support out of the box and keeps the student phone number field available for future paid SMS integrations such as Twilio or Africa's Talking.

## Project Structure

```text
.
├── app.py
├── attendance_app/
│   ├── components.py
│   ├── config.py
│   ├── database.py
│   ├── frontend/
│   ├── roster.py
│   ├── services.py
│   └── utils.py
├── tests/
├── .env.example
├── Makefile
├── pyproject.toml
└── requirements.txt
```

## Quick Start

1. Create a virtual environment and activate it.
2. Install the project dependencies.
3. Start the Streamlit app.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
streamlit run app.py
```

## Environment Configuration

Copy `.env.example` values into your shell environment or deployment platform.

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_ENV` | Application environment | `development` |
| `APP_TIMEZONE` | Local timezone for schedule evaluation | `America/New_York` |
| `ATTENDANCE_DB_PATH` | SQLite database file | `attendance.db` |
| `MANAGER_USERNAME` | Manager login username | unset |
| `MANAGER_PASSWORD_HASH` | PBKDF2 password hash for the manager account | unset |
| `OTP_DELIVERY_MODE` | `console` or `email` | `console` |
| `OTP_EXPIRY_MINUTES` | Login code validity | `10` |
| `OTP_PEPPER` | Hash pepper for OTP values | `change-me` |
| `SMTP_HOST` | SMTP server host | unset |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USERNAME` | SMTP username | unset |
| `SMTP_PASSWORD` | SMTP password | unset |
| `SMTP_SENDER` | From-address for email OTP | unset |
| `SMTP_USE_TLS` | Use STARTTLS | `true` |

## Operating Notes

- Browser geolocation usually requires `localhost` during local development or HTTPS in deployment.
- The manager location picker uses OpenStreetMap tiles in the browser, so internet access helps the map render during local testing.
- GPS accuracy can drift indoors. The app enforces the configured radius, but device-reported accuracy should still be reviewed during rollout.
- The first run creates the SQLite schema automatically.
- A demo seed button is available inside the manager console to quickly populate `MAT1116`.
- Roster uploads currently support `.xlsx` and `.csv`.
- In local development, manager credentials can live in `.streamlit/secrets.toml`. In production, set them in deployment secrets instead of the repository.

## Testing

The repository includes unit tests for the schedule, OTP, distance, and roster parsing utilities.

```bash
python3 -m unittest discover -s tests
```

## Next Production Steps

- Add a real SMTP account or paid SMS provider
- Put Streamlit behind HTTPS
- Replace SQLite with PostgreSQL for multi-user deployment
- Replace single-manager credentials with SSO or an external identity provider
