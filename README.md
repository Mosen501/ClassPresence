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
- PostgreSQL-ready storage for production deployments, with SQLite kept as a local fallback

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
| `APP_TIMEZONE` | Local timezone for schedule evaluation | `Asia/Riyadh` |
| `ATTENDANCE_DB_URL` | PostgreSQL connection string for production | unset |
| `DATABASE_URL` | Standard PostgreSQL connection string fallback | unset |
| `ATTENDANCE_DB_HOST` | PostgreSQL host alternative to a full URL | unset |
| `ATTENDANCE_DB_PORT` | PostgreSQL port alternative to a full URL | `5432` |
| `ATTENDANCE_DB_NAME` | PostgreSQL database name alternative to a full URL | unset |
| `ATTENDANCE_DB_USER` | PostgreSQL username alternative to a full URL | unset |
| `ATTENDANCE_DB_PASSWORD` | PostgreSQL password alternative to a full URL | unset |
| `ATTENDANCE_DB_SSLMODE` | PostgreSQL SSL mode alternative to a full URL | `require` |
| `ATTENDANCE_DB_PATH` | SQLite database file used only when no PostgreSQL URL is set | `attendance.db` |
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
- The first run creates the database schema automatically for either SQLite or PostgreSQL.
- A demo seed button is available inside the manager console to quickly populate `MAT1116`.
- Roster uploads currently support `.xlsx` and `.csv`.
- In local development, manager credentials can live in `.streamlit/secrets.toml`. In production, set them in deployment secrets instead of the repository.

## Testing

The repository includes unit tests for the schedule, OTP, distance, and roster parsing utilities.

```bash
python3 -m unittest discover -s tests
```

## PostgreSQL Deployment

For Streamlit Community Cloud or any public deployment, use PostgreSQL instead of the default local SQLite file.

1. Create a hosted PostgreSQL database.
2. Copy its connection string.
3. Add it to Streamlit secrets as `ATTENDANCE_DB_URL`, or provide the individual PostgreSQL fields instead.
4. Keep `ATTENDANCE_DB_PATH` unset in production so the app does not fall back to a local file.

Example:

```toml
ATTENDANCE_DB_URL = "postgresql://attendance_user:strong-password@db-host.example.com:5432/attendance?sslmode=require"
APP_ENV = "production"
APP_TIMEZONE = "Asia/Riyadh"
OTP_DELIVERY_MODE = "email"
```

If your password contains special URL characters, it is often easier to use separate secrets instead of a single URL:

```toml
ATTENDANCE_DB_HOST = "db-host.example.com"
ATTENDANCE_DB_PORT = "5432"
ATTENDANCE_DB_NAME = "attendance"
ATTENDANCE_DB_USER = "attendance_user"
ATTENDANCE_DB_PASSWORD = "your real raw password here"
ATTENDANCE_DB_SSLMODE = "require"
APP_ENV = "production"
APP_TIMEZONE = "Asia/Riyadh"
OTP_DELIVERY_MODE = "email"
```

With this setup:

- course settings, rosters, OTP records, and attendance data live in PostgreSQL
- data survives Streamlit app sleep, restart, and redeploy
- local development can still use `attendance.db` when no PostgreSQL URL is configured

## Production Notes

- Add a real SMTP account or paid SMS provider
- Put Streamlit behind HTTPS
- Replace single-manager credentials with SSO or an external identity provider
