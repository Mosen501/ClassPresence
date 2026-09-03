# AttendancApp

AttendancApp is a Streamlit-based attendance platform for university classes. It gives academic managers a protected portal for configuring courses, defining class meeting windows, syncing official rosters, exporting Excel reports, and geofencing attendance to a configurable classroom radius.

Students register one device from the classroom using their roster ID, fresh location evidence, a WebAuthn passkey, and in-person instructor approval. After registration they can open the portal from anywhere with that authenticator, while the attendance action silently captures a fresh location and stamps attendance only during approved schedule windows. The application also flags exam ineligibility when absences reach 20% of the configured total meetings.

## Features

- Manager portal protected by a server-side username and hashed password
- Course setup with course code, course name, start date, end date, timetable windows, classroom location, and attendance radius
- Bulk student import from `.xlsx` or `.csv` with `student id`, `student name`, and `email` columns
- Roster-only enrollment workflow so students must exist on the uploaded course roster
- One-time classroom device enrollment with roster identity, fresh location, WebAuthn, and instructor approval
- Location-free portal access from the registered device after enrollment
- Strict classification for non-synchronized single-device credentials and compatibility classification for synchronized credentials
- Single attendance button that captures fresh location and stamps attendance atomically
- Initial enrollment and instructor approval expire when the active lecture window ends
- One-student-per-device enforcement for every lecture window
- Manager device resets available during live lectures with permanent audit history
- Security incident log for blocked proxy attempts with manager review and device reset
- End-to-end Excel reporting with executive summary, course details, roster and device status, timetable, attendance evidence, student performance, lecture analytics, security alerts, device audit, and OTP activity
- Geofenced attendance stamping within a configurable radius that defaults to 3 meters
- Attendance records with timestamp, device information, and location distance checks
- Student dashboard with attendance totals, absences, and exam-entry status
- PostgreSQL-ready storage for production deployments, with SQLite kept as a local fallback

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
| `WEBAUTHN_RP_ID` | Secure-device relying-party hostname; inferred from the app URL when unset | unset |
| `WEBAUTHN_ORIGIN` | Exact public app origin, such as `https://your-app.streamlit.app` | inferred |
| `WEBAUTHN_RP_NAME` | App name shown during secure device enrollment | `ClassPresence` |
| `LOCATION_MAX_AGE_SECONDS` | Maximum age of accepted location evidence | `90` |
| `LOCATION_MAX_ACCURACY_M` | Maximum accepted GPS accuracy radius | `50` |

## Operating Notes

- Device geolocation usually requires `localhost` during local development or HTTPS in deployment.
- Secure device verification requires `localhost` or HTTPS. For production, set `WEBAUTHN_ORIGIN` and `WEBAUTHN_RP_ID` if the public URL cannot be inferred correctly.
- A student enrolls one device after an in-class location check, WebAuthn creation, and in-person instructor approval. Returning portal access verifies the registered passkey but does not request location.
- Registered-device portal sessions last up to 12 hours and can be opened from any location. Course status and history remain available even when no lecture window is active.
- During an active lecture, one attendance button gathers several fresh high-accuracy readings, selects the best reading, verifies the registered device binding, checks the classroom radius, and records attendance in one server-side operation.
- WebAuthn credentials reported as non-backed-up `single_device` credentials receive strict status. Synchronized, multi-device, or unclassified credentials receive compatibility status and continue using the same classroom location checks.
- New browser-storage credentials are no longer created. Existing browser-key registrations remain usable only through each linked course's end date so students have the semester to migrate.
- If an authenticator is lost or replaced, a manager must enter a reason and reset it from Security. Every approval and reset remains in the permanent device audit history.
- Excel reports include complete report-safe activity without row caps. OTP values and hashes, device security keys, credential IDs, and raw device-binding hashes are never exported.
- The manager location picker uses OpenStreetMap tiles, so internet access helps the map render during local testing.
- GPS accuracy can drift indoors. The app enforces the configured radius, but device-reported accuracy should still be reviewed during rollout.
- The first run creates the database schema automatically for either SQLite or PostgreSQL.
- PostgreSQL connections are pooled and schema migrations run once per deployed schema version. Host the database in the same geographic region as the Streamlit app to minimize query latency.
- Stable course, roster, and timetable data stay cached between interactions. Attendance and security writes invalidate only the affected views.
- Complete Excel workbooks are generated only after the manager selects **Prepare Excel report**, keeping the Reports page responsive.
- A demo seed button is available inside the manager console to quickly populate `MAT1116`.
- Roster uploads currently support `.xlsx` and `.csv`.
- In local development, manager credentials can live in `.streamlit/secrets.toml`. In production, set them in deployment secrets instead of the repository.

## Testing

The repository includes unit and workflow tests for schedules, distance checks, WebAuthn
device registration and approval, legacy migration, reporting, and roster parsing.

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
WEBAUTHN_ORIGIN = "https://classpresence.streamlit.app"
WEBAUTHN_RP_ID = "classpresence.streamlit.app"
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
WEBAUTHN_ORIGIN = "https://classpresence.streamlit.app"
WEBAUTHN_RP_ID = "classpresence.streamlit.app"
```

With this setup:

- course settings, rosters, OTP records, and attendance data live in PostgreSQL
- data survives Streamlit app sleep, restart, and redeploy
- local development can still use `attendance.db` when no PostgreSQL URL is configured

## Production Notes

- Put Streamlit behind HTTPS
- Replace single-manager credentials with SSO or an external identity provider
