from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from attendance_app.components import geo_capture, location_picker
from attendance_app.config import load_settings
from attendance_app.database import AttendanceRepository
from attendance_app.reports import build_course_report_xlsx
from attendance_app.roster import parse_roster_file
from attendance_app.security import verify_password
from attendance_app.services import (
    StudentAccessContext,
    build_student_attendance_summary,
    find_active_schedule,
    now_in_app_timezone,
    otp_delivery_configuration_error,
    request_login_code_for_access_context,
    resolve_student_access_context,
    seed_demo_data,
    stamp_attendance,
    verify_login_code_for_access_context,
)
from attendance_app.utils import parse_hhmm, parse_iso_date, weekday_label


APP_CSS = """
<style>
    /* ── Global ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    .stApp {
        background: #f0f4f3;
    }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d3d35 0%, #0f4f45 100%);
        border-right: none;
    }
    [data-testid="stSidebar"] * {
        color: #e2f0ee !important;
    }
    [data-testid="stSidebar"] .stRadio label {
        color: #b2ccc8 !important;
    }
    [data-testid="stSidebar"] [data-baseweb="radio"] [aria-checked="true"] ~ div {
        color: #ffffff !important;
    }
    [data-testid="stSidebar"] .stCaption {
        color: #7aada6 !important;
    }

    /* ── App header bar ── */
    header[data-testid="stHeader"] {
        background: rgba(240, 244, 243, 0.95);
        backdrop-filter: blur(8px);
        border-bottom: 1px solid #d1e4e0;
    }

    /* ── Hero banner ── */
    .aa-hero {
        display: flex;
        align-items: center;
        gap: 1.2rem;
        padding: 1.4rem 1.8rem;
        border-radius: 16px;
        background: linear-gradient(135deg, #0d3d35 0%, #0f766e 100%);
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 24px rgba(15, 118, 110, 0.18);
    }
    .aa-hero-icon {
        font-size: 2.4rem;
        line-height: 1;
        filter: drop-shadow(0 2px 4px rgba(0,0,0,0.2));
    }
    .aa-hero-text h1 {
        margin: 0;
        font-size: 1.9rem;
        font-weight: 700;
        color: #ffffff;
        letter-spacing: -0.02em;
    }
    .aa-hero-text p {
        margin: 0.25rem 0 0 0;
        color: rgba(255,255,255,0.75);
        font-size: 0.9rem;
        font-weight: 400;
    }

    /* ── Section headings ── */
    .aa-section-header {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.9rem 1.2rem;
        border-radius: 12px;
        background: #ffffff;
        border-left: 4px solid #0f766e;
        margin-bottom: 1.2rem;
        box-shadow: 0 1px 6px rgba(0,0,0,0.06);
    }
    .aa-section-header .aa-sh-icon {
        font-size: 1.4rem;
    }
    .aa-section-header .aa-sh-body h2 {
        margin: 0;
        font-size: 1.15rem;
        font-weight: 700;
        color: #0d3d35;
    }
    .aa-section-header .aa-sh-body p {
        margin: 0.15rem 0 0 0;
        font-size: 0.82rem;
        color: #4a7a71;
    }

    /* ── User pill (signed-in label) ── */
    .aa-user-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        background: #e6f4f1;
        border: 1px solid #b0d8d2;
        border-radius: 999px;
        padding: 0.3rem 0.85rem;
        font-size: 0.83rem;
        font-weight: 600;
        color: #0d3d35;
    }

    /* ── Info / step cards ── */
    .portal-card {
        padding: 1.1rem 1.3rem;
        border-radius: 14px;
        border: 1px solid #d1e4e0;
        background: #ffffff;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(15, 118, 110, 0.06);
    }
    .portal-card h3 {
        margin: 0 0 0.3rem 0;
        font-size: 1rem;
        font-weight: 700;
        color: #0d3d35;
    }
    .portal-card p {
        margin: 0;
        color: #4a7a71;
        font-size: 0.88rem;
        line-height: 1.55;
    }
    .portal-kicker {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        margin: 0 0 0.5rem 0;
        background: #e6f4f1;
        border-radius: 999px;
        padding: 0.15rem 0.65rem;
        color: #0f766e;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }

    /* ── Step badge cards ── */
    .aa-step-card {
        display: flex;
        gap: 1rem;
        align-items: flex-start;
        padding: 1.1rem 1.3rem;
        border-radius: 14px;
        border: 1px solid #d1e4e0;
        background: #ffffff;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(15, 118, 110, 0.06);
    }
    .aa-step-badge {
        flex-shrink: 0;
        width: 2rem;
        height: 2rem;
        border-radius: 50%;
        background: linear-gradient(135deg, #0f766e, #0d9488);
        color: #fff;
        font-size: 0.85rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 2px 6px rgba(15,118,110,0.25);
    }
    .aa-step-body h3 {
        margin: 0 0 0.2rem 0;
        font-size: 0.98rem;
        font-weight: 700;
        color: #0d3d35;
    }
    .aa-step-body p {
        margin: 0;
        font-size: 0.85rem;
        color: #4a7a71;
        line-height: 1.5;
    }

    /* ── Sign-in card ── */
    .aa-signin-card {
        max-width: 420px;
        margin: 1rem auto;
        padding: 2rem 2rem 1.5rem;
        border-radius: 20px;
        background: #ffffff;
        border: 1px solid #d1e4e0;
        box-shadow: 0 8px 32px rgba(15, 118, 110, 0.10);
    }
    .aa-signin-card h2 {
        margin: 0 0 0.3rem 0;
        font-size: 1.3rem;
        font-weight: 700;
        color: #0d3d35;
    }
    .aa-signin-card p {
        margin: 0 0 1.4rem 0;
        font-size: 0.87rem;
        color: #4a7a71;
    }

    /* ── Attendance status banner ── */
    .aa-window-banner {
        display: flex;
        align-items: center;
        gap: 0.7rem;
        padding: 0.85rem 1.2rem;
        border-radius: 12px;
        background: linear-gradient(90deg, #ecfdf5, #d1fae5);
        border: 1px solid #6ee7b7;
        margin-bottom: 1rem;
        font-size: 0.92rem;
        font-weight: 600;
        color: #065f46;
    }
    .aa-window-banner .aa-wb-icon { font-size: 1.2rem; }

    /* ── Student info card ── */
    .aa-student-info {
        padding: 1rem 1.3rem;
        border-radius: 14px;
        background: #ffffff;
        border: 1px solid #d1e4e0;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(15, 118, 110, 0.06);
    }
    .aa-student-info .aa-si-name {
        font-size: 1.1rem;
        font-weight: 700;
        color: #0d3d35;
        margin: 0 0 0.2rem 0;
    }
    .aa-student-info .aa-si-meta {
        font-size: 0.84rem;
        color: #4a7a71;
        margin: 0;
    }
    .aa-student-info code {
        background: #e6f4f1;
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
        font-size: 0.82rem;
        color: #0d3d35;
    }

    /* ── Divider ── */
    .aa-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, #d1e4e0, transparent);
        margin: 1.5rem 0;
    }

    /* ── Override Streamlit metric ── */
    [data-testid="metric-container"] {
        background: #ffffff;
        border: 1px solid #d1e4e0;
        border-radius: 12px;
        padding: 0.8rem 1rem !important;
        box-shadow: 0 2px 6px rgba(15, 118, 110, 0.06);
    }
    [data-testid="metric-container"] [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        color: #4a7a71 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        color: #0d3d35 !important;
    }

    /* ── Override Streamlit tabs ── */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.25rem;
        background: #e6f4f1;
        padding: 0.3rem;
        border-radius: 10px;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        border-radius: 8px;
        font-weight: 600;
        font-size: 0.87rem;
        padding: 0.45rem 1rem;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background: #0f766e !important;
        color: #fff !important;
    }

    /* ── Override Streamlit buttons ── */
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
        font-size: 0.9rem;
        padding: 0.5rem 1.2rem;
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(15, 118, 110, 0.2);
    }

    /* ── Selectbox and inputs ── */
    [data-baseweb="select"] {
        border-radius: 10px !important;
    }
    [data-baseweb="input"] {
        border-radius: 10px !important;
    }

    /* ── Download button ── */
    .stDownloadButton > button {
        border-radius: 10px;
        font-weight: 600;
    }

    /* ── Form container ── */
    [data-testid="stForm"] {
        background: #ffffff;
        border: 1px solid #d1e4e0;
        border-radius: 14px;
        padding: 1.2rem 1.2rem 0.8rem;
        box-shadow: 0 2px 8px rgba(15, 118, 110, 0.06);
    }

    /* ── Roster / report section title ── */
    .aa-subsection {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #0f766e;
        margin: 1.2rem 0 0.6rem 0;
    }
</style>
"""


TIMETABLE_DAY_COLUMNS = [
    ("Sunday", 6),
    ("Monday", 0),
    ("Tuesday", 1),
    ("Wednesday", 2),
    ("Thursday", 3),
]

DEFAULT_TIMETABLE_ROWS = [
    {"label": "L1", "start_time": "07:30", "end_time": "08:20"},
    {"label": "L2", "start_time": "08:25", "end_time": "09:15"},
    {"label": "L3", "start_time": "09:20", "end_time": "10:10"},
    {"label": "L4", "start_time": "10:15", "end_time": "11:05"},
    {"label": "L5", "start_time": "11:10", "end_time": "12:00"},
    {"label": "L6", "start_time": "12:30", "end_time": "13:20"},
    {"label": "L7", "start_time": "13:25", "end_time": "14:15"},
]


def main() -> None:
    st.set_page_config(page_title="AttendancApp", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)

    settings = load_settings(_safe_secrets())
    repo = AttendanceRepository(settings.database_target)
    try:
        repo.init_schema()
    except RuntimeError as error:
        st.error(str(error))
        st.info(
            "For Streamlit Cloud, either provide `ATTENDANCE_DB_URL` as a full "
            "`postgresql://...` URL, or set separate secrets such as `ATTENDANCE_DB_HOST`, "
            "`ATTENDANCE_DB_PORT`, `ATTENDANCE_DB_NAME`, `ATTENDANCE_DB_USER`, and "
            "`ATTENDANCE_DB_PASSWORD`."
        )
        st.stop()
    _init_session_state()

    st.markdown(
        """
        <div class="aa-hero">
            <div class="aa-hero-icon">🎓</div>
            <div class="aa-hero-text">
                <h1>AttendancApp</h1>
                <p>Geofenced course attendance — manager controls, roster-linked student access,
                email OTP workflows, and Excel reporting.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown(
            """
            <div style="padding: 0.5rem 0 1.2rem 0;">
                <div style="font-size:1.3rem; font-weight:800; letter-spacing:-0.02em; color:#ffffff;">
                    AttendancApp
                </div>
                <div style="font-size:0.75rem; color:#7aada6; margin-top:0.2rem;">
                    Academic Attendance Platform
                </div>
            </div>
            <div style="height:1px; background:rgba(255,255,255,0.1); margin-bottom:1.2rem;"></div>
            <div style="font-size:0.72rem; font-weight:700; letter-spacing:0.08em;
                        text-transform:uppercase; color:#7aada6; margin-bottom:0.5rem;">
                Portal
            </div>
            """,
            unsafe_allow_html=True,
        )
        page = st.radio("Open", options=["👨‍🏫  Instructor", "🎒  Student"], label_visibility="collapsed")
        page = "Manager" if "Instructor" in page else "Student"
        st.markdown(
            f"""
            <div style="height:1px; background:rgba(255,255,255,0.1); margin:1.2rem 0 0.8rem 0;"></div>
            <div style="font-size:0.75rem; color:#7aada6;">
                🕐 Timezone<br>
                <span style="color:#b2ccc8; font-weight:600;">{settings.app_timezone}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if page == "Student":
            st.markdown(
                """
                <div style="margin-top:0.8rem; font-size:0.75rem; color:#7aada6; line-height:1.5;">
                    📧 Students authenticate via a one-time code sent to their roster email.
                </div>
                """,
                unsafe_allow_html=True,
            )

    if page == "Manager":
        if _render_manager_auth(settings):
            render_manager_page(repo, settings)
    else:
        render_student_page(repo, settings)


def render_manager_page(repo: AttendanceRepository, settings) -> None:
    st.markdown(
        """
        <div class="aa-section-header">
            <div class="aa-sh-icon">🖥️</div>
            <div class="aa-sh-body">
                <h2>Instructor Console</h2>
                <p>Configure courses, set classroom boundaries, manage rosters, and export reports.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    notice = st.session_state.pop("manager_notice", None)
    if notice:
        st.success(notice)

    top_left, top_right = st.columns([2.6, 1.0])
    with top_left:
        st.markdown(
            f'<div class="aa-user-pill">👤 {settings.manager_username}</div>',
            unsafe_allow_html=True,
        )
    with top_right:
        if st.button("Sign out", use_container_width=True):
            st.session_state["manager_auth"] = None
            st.rerun()

    courses = repo.list_courses()
    course_options = ["New course", *[str(course["code"]) for course in courses]]
    selected_code = st.selectbox(
        "Course to set up",
        options=course_options,
        key="manager_course_selector",
    )
    selected_course = repo.get_course_by_code(selected_code) if selected_code != "New course" else None

    _ensure_course_location_defaults()
    _sync_course_location_state(selected_course)

    selected_start_date = (
        parse_iso_date(selected_course["start_date"])
        if selected_course is not None
        else now_in_app_timezone(settings).date()
    )
    selected_end_date = (
        parse_iso_date(selected_course["end_date"] or selected_course["start_date"])
        if selected_course is not None
        else now_in_app_timezone(settings).date() + timedelta(days=90)
    )
    selected_radius = float(selected_course["radius_m"]) if selected_course is not None else 3.0
    selected_absence_limit = (
        float(selected_course["absence_limit_pct"]) if selected_course is not None else 20.0
    )

    left, right = st.columns([1.2, 1.0], gap="large")
    with left:
        st.markdown('<p class="aa-subsection">📋 Course Details</p>', unsafe_allow_html=True)
        with st.form("course_form", clear_on_submit=False):
            code = st.text_input(
                "Course code",
                value=str(selected_course["code"]) if selected_course is not None else "",
                placeholder="MAT1116",
            )
            title = st.text_input(
                "Course name",
                value=str(selected_course["title"]) if selected_course is not None else "",
                placeholder="Foundations of Mathematics",
            )
            start_date = st.date_input("Course start date", value=selected_start_date)
            end_date = st.date_input("Course end date", value=selected_end_date)
            radius_m = st.number_input(
                "Allowed attendance radius (meters)",
                min_value=1.0,
                value=selected_radius,
                step=0.5,
            )
            absence_limit_pct = st.number_input(
                "Absence limit (%)",
                min_value=1.0,
                max_value=100.0,
                value=selected_absence_limit,
                step=1.0,
            )
            submit_course = st.form_submit_button("Save course", use_container_width=True)

        if submit_course:
            _save_course(
                repo=repo,
                settings=settings,
                code=code,
                title=title,
                start_date=start_date,
                end_date=end_date,
                radius_m=float(radius_m),
                absence_limit_pct=float(absence_limit_pct),
                existing_course_id=int(selected_course["id"]) if selected_course is not None else None,
            )

        if settings.app_env == "development" and st.button(
            "Seed demo course MAT1116",
            use_container_width=True,
        ):
            try:
                created = seed_demo_data(
                    repo,
                    settings,
                    latitude=float(st.session_state["course_latitude"]),
                    longitude=float(st.session_state["course_longitude"]),
                )
                if created:
                    st.success("MAT1116 demo data added successfully.")
                else:
                    st.info("MAT1116 already exists in the database.")
            except Exception as error:  # pragma: no cover - Streamlit surface
                st.error(str(error))

    with right:
        st.markdown(
            """
            <div class="portal-card">
                <p class="portal-kicker">📍 Classroom Location</p>
                <h3>Pin the classroom on the map</h3>
                <p>The selected point becomes the center of the geofenced radius. Students must be
                physically inside this boundary during an active timetable window to stamp attendance.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        manager_geo = location_picker(
            latitude=float(st.session_state["course_latitude"]),
            longitude=float(st.session_state["course_longitude"]),
            radius_m=float(selected_course["radius_m"]) if selected_course is not None else 3.0,
            has_selection=_has_course_location_selection(),
            key="manager_location_picker",
        )
        _handle_location_capture(manager_geo, prefix="manager")
        _render_location_summary()
        st.info(
            "Manager access is secured with a username and a hashed password from deployment "
            "secrets. For public publishing, put this app behind organization SSO or a trusted "
            "identity provider."
        )

    active_course = selected_course
    if active_course is None and code.strip():
        active_course = repo.get_course_by_code(code.strip().upper())

    if active_course is None:
        st.info("Save a course first to configure timetable, sync the roster, and export reports.")
        return

    _render_course_summary(repo, active_course)

    if settings.app_env == "development":
        helper_left, helper_right = st.columns([1.2, 1.0], gap="large")
        with helper_left:
            st.caption(
                "Testing helper: create an attendance window that opens immediately for this course."
            )
        with helper_right:
            if st.button("Create live test window now", use_container_width=True):
                _create_live_test_window(
                    repo=repo,
                    settings=settings,
                    course_id=int(active_course["id"]),
                )

    setup_tab, roster_tab, reports_tab = st.tabs(["📅  Timetable", "👥  Roster", "📊  Reports"])

    with setup_tab:
        st.markdown('<p class="aa-subsection">🗓️ Weekly Timetable</p>', unsafe_allow_html=True)
        schedules = repo.list_schedules_for_course(int(active_course["id"]))
        st.caption(
            "Standard lecture slots are preloaded (Sun–Thu). Tick the day boxes to activate a slot. "
            "Rows with no day selected are ignored on save."
        )
        st.caption(
            "⚠️ Removing a saved row may delete linked attendance records for that window."
        )
        timetable_rows = _build_timetable_editor_rows(schedules)
        edited_timetable_rows = st.data_editor(
            timetable_rows,
            key=f"timetable_editor_{active_course['id']}",
            hide_index=True,
            num_rows="dynamic",
            use_container_width=True,
            column_order=[
                "label",
                "start_time",
                "end_time",
                "Sunday",
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
            ],
            column_config={
                "label": st.column_config.TextColumn(
                    "Slot",
                    help="Examples: L1, L2, Lab, Tutorial",
                    required=False,
                ),
                "start_time": st.column_config.TextColumn(
                    "Start",
                    help="Use 24-hour format like 07:30",
                    required=False,
                ),
                "end_time": st.column_config.TextColumn(
                    "End",
                    help="Use 24-hour format like 08:20",
                    required=False,
                ),
                "Sunday": st.column_config.CheckboxColumn("Sunday"),
                "Monday": st.column_config.CheckboxColumn("Monday"),
                "Tuesday": st.column_config.CheckboxColumn("Tuesday"),
                "Wednesday": st.column_config.CheckboxColumn("Wednesday"),
                "Thursday": st.column_config.CheckboxColumn("Thursday"),
            },
        )
        if st.button("Save timetable", use_container_width=True):
            _save_timetable(
                repo=repo,
                settings=settings,
                course_id=int(active_course["id"]),
                edited_rows=edited_timetable_rows,
            )

    with roster_tab:
        st.markdown('<p class="aa-subsection">📤 Import Roster</p>', unsafe_allow_html=True)
        st.caption(
            "Upload a `.xlsx` or `.csv` file with columns: `student id`, `student name`, `email`. "
            "The uploaded file replaces the entire roster for this course."
        )
        _render_roster_importer(repo, settings, active_course)

        students = repo.list_students_for_course(int(active_course["id"]))
        if students:
            st.dataframe(
                [
                    {
                        "Name": row["full_name"],
                        "Student ID": row["university_id"],
                        "Email": row["email"],
                    }
                    for row in students
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No students are currently linked to this course roster.")

    with reports_tab:
        _render_report_downloads(repo, settings, active_course)


def render_student_page(repo: AttendanceRepository, settings) -> None:
    st.markdown(
        """
        <div class="aa-section-header">
            <div class="aa-sh-icon">🎒</div>
            <div class="aa-sh-body">
                <h2>Student Portal</h2>
                <p>Access is only available during your active class window and from inside the classroom boundary.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_otp_delivery_notice(settings)

    auth = st.session_state.get("student_auth")
    if not auth:
        _render_student_login(repo, settings)
        return

    course = repo.get_course(int(auth["course_id"]))
    student = repo.get_student(int(auth["student_id"]))
    if course is None or student is None:
        st.session_state["student_auth"] = None
        _reset_student_access_flow(clear_student_id=False)
        st.warning("Your session is no longer valid. Please sign in again.")
        return

    schedules = repo.list_schedules_for_course(int(course["id"]))
    active_schedule = find_active_schedule(schedules, now_in_app_timezone(settings))
    if active_schedule is None:
        st.session_state["student_auth"] = None
        _reset_student_access_flow(clear_student_id=False)
        st.warning(
            "Student access is available only during the active timetable window. "
            "Please request access again during class."
        )
        return

    top_left, top_right = st.columns([2.5, 1.0])
    with top_left:
        st.markdown(
            f"""
            <div class="aa-student-info">
                <p class="aa-si-name">👋 {student['full_name']}</p>
                <p class="aa-si-meta">
                    Student ID: <code>{student['university_id']}</code> &nbsp;·&nbsp;
                    {course['title']}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with top_right:
        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        if st.button("Sign out", use_container_width=True):
            st.session_state["student_auth"] = None
            _reset_student_access_flow(clear_student_id=False)
            st.rerun()

    st.markdown(
        f"""
        <div class="aa-window-banner">
            <span class="aa-wb-icon">🟢</span>
            Attendance window open — <strong>{active_schedule['label']}</strong>
            &nbsp;({active_schedule['start_time']} – {active_schedule['end_time']})
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="portal-card">
            <p class="portal-kicker">📍 Attendance Stamp</p>
            <h3>Share your current classroom location</h3>
            <p>A fresh location check is required each time you stamp attendance, ensuring your
            live position is inside the classroom boundary.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    student_stamp_geo = geo_capture(
        button_label="Share current location to stamp attendance",
        key="student_stamp_geo_capture",
    )
    _handle_student_stamp_gate(student_stamp_geo)
    if st.session_state.get("student_stamp_geolocation") is not None:
        st.info("Current location captured. You can now stamp this attendance window.")

    if (
        st.session_state.get("student_stamp_result") is None
        and st.session_state.get("student_stamp_geolocation") is not None
        and st.button("Stamp current attendance", use_container_width=True)
    ):
        result = stamp_attendance(
            repo,
            settings,
            course=course,
            student=student,
            geolocation_payload=st.session_state["student_stamp_geolocation"],
        )
        st.session_state["student_stamp_result"] = {
            "success": result.success,
            "message": result.message,
        }
        if result.success:
            st.session_state["student_stamp_geolocation"] = None
        st.rerun()

    stamp_result = st.session_state.get("student_stamp_result")
    if stamp_result:
        if stamp_result["success"]:
            st.success(stamp_result["message"])
        else:
            st.error(stamp_result["message"])

    summary = build_student_attendance_summary(repo, settings, course=course, student=student)
    metrics = st.columns(4)
    metrics[0].metric("Attended", summary.attended_count)
    metrics[1].metric("Absences", summary.absences)
    metrics[2].metric("Meetings elapsed", summary.elapsed_meetings)
    metrics[3].metric("Total meetings", summary.total_meetings)

    status_text = "Denied Exam Entry" if summary.denied_exam_entry else "Eligible for exam entry"
    if summary.denied_exam_entry:
        st.error(status_text)
    else:
        st.success(status_text)

    st.caption(
        f"Attendance progress: {summary.attendance_pct_of_total:.1f}% of total meetings recorded. "
        f"Absence exposure: {summary.absence_pct_of_total:.1f}% of total meetings."
    )

    recent_records = repo.list_attendance(
        course_id=int(course["id"]),
        student_id=int(student["id"]),
    )
    st.markdown('<div class="aa-divider"></div>', unsafe_allow_html=True)
    st.markdown('<p class="aa-subsection">📋 Recent Attendance</p>', unsafe_allow_html=True)
    if recent_records:
        st.dataframe(
            [
                {
                    "Date": row["attendance_date"],
                    "Window": row["schedule_label"],
                    "Stamped At": row["stamped_at"],
                    "Distance (m)": round(float(row["distance_m"]), 2),
                    "Accuracy (m)": round(float(row["accuracy_m"]), 2)
                    if row["accuracy_m"] is not None
                    else None,
                }
                for row in recent_records
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("You have not stamped any attendance yet.")


def _render_student_login(repo: AttendanceRepository, settings) -> None:
    university_id = st.text_input(
        "Student ID",
        value=st.session_state.get("pending_university_id", ""),
        key="student_login_id_input",
    )
    if university_id.strip() != st.session_state.get("pending_university_id", ""):
        _reset_student_access_flow(clear_student_id=False)
        st.session_state["pending_university_id"] = university_id.strip()

    st.markdown(
        """
        <div class="aa-step-card">
            <div class="aa-step-badge">1</div>
            <div class="aa-step-body">
                <h3>Verify your classroom access</h3>
                <p>Enter your student ID and share your current location. Access is granted only if
                your roster record is found, your class is active right now, and you are inside the classroom boundary.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    student_geo = geo_capture(
        button_label="Share location to continue",
        key="student_access_geo_capture",
    )
    _handle_student_access_gate(student_geo, repo, settings, university_id)

    access_context = st.session_state.get("student_access_context")
    if access_context is None:
        return
    if not _student_access_context_is_current(repo, settings, access_context):
        _reset_student_access_flow(clear_student_id=False)
        st.info(
            "The classroom location or active timetable changed. Share your location again to "
            "continue with the current course settings."
        )
        return

    st.success(
        f"Access verified for {access_context['student_name']} in {access_context['course_title']}. "
        f"You are {access_context['distance_m']:.2f} m from class and inside the active window "
        f"{access_context['schedule_label']} ({access_context['schedule_start_time']} - "
        f"{access_context['schedule_end_time']})."
    )

    otp_notice = st.session_state.get("student_otp_notice")
    if otp_notice:
        st.success(otp_notice)
    otp_preview_code = st.session_state.get("student_otp_preview_code")
    if otp_preview_code:
        st.text_input(
            "Development OTP preview",
            value=otp_preview_code,
            key="student_otp_preview_display",
            help="This appears only in local development when OTP delivery mode is console.",
        )

    if not st.session_state.get("student_otp_requested", False):
        st.markdown(
            """
            <div class="aa-step-card">
                <div class="aa-step-badge">2</div>
                <div class="aa-step-body">
                    <h3>Request your one-time code</h3>
                    <p>A secure code will be sent to the email address stored in your official course roster.</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        configuration_error = otp_delivery_configuration_error(settings)
        if configuration_error:
            st.error(configuration_error)
            return
        if st.button("Generate OTP via email", use_container_width=True):
            try:
                result = request_login_code_for_access_context(
                    repo,
                    settings,
                    access_context=_build_access_context_object(access_context),
                )
                st.session_state["student_otp_requested"] = True
                st.session_state["student_otp_notice"] = result.message
                st.session_state["student_otp_preview_code"] = result.preview_code
                st.rerun()
            except Exception as error:  # pragma: no cover - Streamlit surface
                st.error(str(error))
        return

    st.markdown(
        """
        <div class="aa-step-card">
            <div class="aa-step-badge">3</div>
            <div class="aa-step-body">
                <h3>Enter your one-time code</h3>
                <p>Use the latest code sent to your roster email. Each login requires a fresh code.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    otp_code = st.text_input("One-time code", type="password", key="student_otp_code_input")
    if st.button("Login", use_container_width=True):
        try:
            course, student = verify_login_code_for_access_context(
                repo,
                settings,
                course_id=int(access_context["course_id"]),
                student_id=int(access_context["student_id"]),
                code=otp_code,
            )
            st.session_state["student_auth"] = {
                "course_id": int(course["id"]),
                "student_id": int(student["id"]),
            }
            st.session_state["student_stamp_result"] = None
            st.session_state["student_stamp_geolocation"] = None
            st.session_state["student_otp_notice"] = None
            st.session_state["student_otp_preview_code"] = None
            st.rerun()
        except Exception as error:  # pragma: no cover - Streamlit surface
            st.error(str(error))


def _save_course(
    *,
    repo: AttendanceRepository,
    settings,
    code: str,
    title: str,
    start_date: date,
    end_date: date,
    radius_m: float,
    absence_limit_pct: float,
    existing_course_id: int | None,
) -> None:
    normalized_code = code.strip().upper()
    if not normalized_code or not title.strip():
        st.error("Course code and course name are required.")
        return
    if end_date < start_date:
        st.error("Course end date must be on or after the course start date.")
        return
    if not _has_course_location_selection():
        st.error("A predefined classroom location must be selected on the map before saving the course.")
        return
    latitude = float(st.session_state["course_latitude"])
    longitude = float(st.session_state["course_longitude"])
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        st.error("Latitude or longitude is out of range.")
        return

    try:
        existing_course = repo.get_course_by_code(normalized_code)
        if existing_course_id is None:
            if existing_course is not None:
                repo.update_course(
                    course_id=int(existing_course["id"]),
                    code=normalized_code,
                    title=title.strip(),
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    latitude=latitude,
                    longitude=longitude,
                    radius_m=radius_m,
                    absence_limit_pct=absence_limit_pct,
                )
            else:
                repo.create_course(
                    code=normalized_code,
                    title=title.strip(),
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    total_meetings=1,
                    latitude=latitude,
                    longitude=longitude,
                    radius_m=radius_m,
                    absence_limit_pct=absence_limit_pct,
                    created_at=now_in_app_timezone(settings).isoformat(),
                )
        else:
            if existing_course is not None and int(existing_course["id"]) != existing_course_id:
                st.error("Another course already uses that course code.")
                return
            repo.update_course(
                course_id=existing_course_id,
                code=normalized_code,
                title=title.strip(),
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                latitude=latitude,
                longitude=longitude,
                radius_m=radius_m,
                absence_limit_pct=absence_limit_pct,
            )

        persisted_course = repo.get_course_by_code(normalized_code)
        if persisted_course is not None:
            _invalidate_student_access_for_course(int(persisted_course["id"]))
        st.session_state["loaded_course_location_signature"] = None
        st.session_state["manager_course_selector"] = normalized_code
        st.session_state["manager_notice"] = f"Course {normalized_code} saved successfully."
        st.rerun()
    except Exception as error:  # pragma: no cover - Streamlit surface
        st.error(str(error))


def _add_schedule(
    *,
    repo: AttendanceRepository,
    settings,
    course_id: int,
    weekday: int,
    label: str,
    start_time: str,
    end_time: str,
) -> None:
    if not label.strip():
        st.error("Schedule label is required.")
        return
    if end_time <= start_time:
        st.error("End time must be later than start time.")
        return
    try:
        repo.add_schedule(
            course_id=course_id,
            weekday=weekday,
            label=label.strip(),
            start_time=start_time,
            end_time=end_time,
            created_at=now_in_app_timezone(settings).isoformat(),
        )
        st.session_state["manager_notice"] = f"Timetable window {label.strip()} added."
        st.rerun()
    except Exception as error:  # pragma: no cover - Streamlit surface
        st.error(str(error))


def _create_live_test_window(*, repo: AttendanceRepository, settings, course_id: int) -> None:
    now = now_in_app_timezone(settings).replace(second=0, microsecond=0)
    end_time = now + timedelta(hours=2)
    if end_time.date() != now.date():
        end_time = now.replace(hour=23, minute=59)

    try:
        repo.add_schedule(
            course_id=course_id,
            weekday=now.weekday(),
            label=f"Live Test Window {now.strftime('%H:%M')}",
            start_time=now.strftime("%H:%M"),
            end_time=end_time.strftime("%H:%M"),
            created_at=now.isoformat(),
        )
        st.session_state["manager_notice"] = (
            "A live test window was created for right now. Student attendance should be open "
            "after the page refreshes."
        )
        st.rerun()
    except Exception as error:  # pragma: no cover - Streamlit surface
        st.error(str(error))


def _handle_location_capture(payload, *, prefix: str) -> None:
    if not payload:
        return
    captured_at = payload.get("captured_at")
    state_key = f"{prefix}_geo_processed_at"
    if captured_at == st.session_state.get(state_key):
        return
    st.session_state[state_key] = captured_at

    if payload.get("error"):
        st.error(str(payload["error"]))
        return

    st.session_state["course_latitude"] = float(payload["latitude"])
    st.session_state["course_longitude"] = float(payload["longitude"])
    st.session_state["course_location_selected"] = True
    st.success("Classroom location updated from the map selection.")


def _render_roster_importer(repo: AttendanceRepository, settings, course) -> None:
    upload_key = f"roster_upload_{course['id']}"
    import_key = f"import_roster_{course['id']}"
    uploaded_file = st.file_uploader(
        "Student roster",
        type=["xlsx", "csv"],
        key=upload_key,
        label_visibility="collapsed",
    )
    if uploaded_file is None:
        return

    try:
        roster_rows = parse_roster_file(uploaded_file.name, uploaded_file.getvalue())
    except Exception as error:  # pragma: no cover - Streamlit surface
        st.error(str(error))
        return

    st.dataframe(
        [
            {
                "Student ID": row["university_id"],
                "Student Name": row["full_name"],
                "Email": row["email"],
            }
            for row in roster_rows[:50]
        ],
        use_container_width=True,
        hide_index=True,
    )
    if len(roster_rows) > 50:
        st.caption(f"Preview limited to the first 50 rows out of {len(roster_rows)} students.")

    if st.button(f"Replace roster for {course['code']}", key=import_key, use_container_width=True):
        created_at = now_in_app_timezone(settings).isoformat()
        repo.sync_course_roster(
            course_id=int(course["id"]),
            roster_rows=roster_rows,
            created_at=created_at,
        )
        st.session_state["manager_notice"] = (
            f"Roster synchronized for {course['code']}. {len(roster_rows)} student records are active."
        )
        st.rerun()


def _render_report_downloads(repo: AttendanceRepository, settings, course) -> None:
    students = repo.list_students_for_course(int(course["id"]))
    schedules = repo.list_schedules_for_course(int(course["id"]))
    attendance_records = repo.list_course_attendance(course_id=int(course["id"]), limit=10000)

    eligibility_rows = []
    for student in students:
        summary = build_student_attendance_summary(repo, settings, course=course, student=student)
        eligibility_rows.append(
            {
                "Student": student["full_name"],
                "University ID": student["university_id"],
                "Attended": summary.attended_count,
                "Absences": summary.absences,
                "Elapsed Meetings": summary.elapsed_meetings,
                "Total Meetings": summary.total_meetings,
                "Threshold": summary.absence_threshold,
                "Status": "Denied Exam Entry" if summary.denied_exam_entry else "Eligible",
            }
        )

    report_bytes = build_course_report_xlsx(
        course=course,
        students=students,
        schedules=schedules,
        attendance_records=attendance_records,
        eligibility_rows=eligibility_rows,
        generated_at=now_in_app_timezone(settings),
    )
    st.download_button(
        "Download course report (.xlsx)",
        data=report_bytes,
        file_name=f"{course['code']}_attendance_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def _render_manager_auth(settings) -> bool:
    if st.session_state.get("manager_auth") is not None:
        return True

    st.markdown(
        """
        <div class="aa-signin-card">
            <h2>🔐 Instructor Sign In</h2>
            <p>Only the authorized academic instructor can configure courses and export reports.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not settings.manager_username or not settings.manager_password_hash:
        st.error(
            "Instructor credentials are not configured. Set `MANAGER_USERNAME` and "
            "`MANAGER_PASSWORD_HASH` in Streamlit secrets before using the instructor portal."
        )
        return False

    with st.form("manager_login_form"):
        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        submit = st.form_submit_button("Sign in →", use_container_width=True)
    if submit:
        if (
            username.strip() == settings.manager_username
            and verify_password(password, settings.manager_password_hash)
        ):
            st.session_state["manager_auth"] = {"username": settings.manager_username}
            st.rerun()
        st.error("Incorrect username or password. Please try again.")
    return False


def _render_otp_delivery_notice(settings) -> None:
    configuration_error = otp_delivery_configuration_error(settings)
    if configuration_error:
        st.warning(configuration_error)
        return
    if settings.otp_delivery_mode == "console":
        st.info("Development mode is showing OTP codes in-app instead of sending email.")


def _build_timetable_editor_rows(schedules) -> list[dict[str, object]]:
    rows_by_label: dict[str, dict[str, object]] = {}
    ordered_labels: list[str] = []

    for default_row in DEFAULT_TIMETABLE_ROWS:
        label = str(default_row["label"])
        row = {
            "label": label,
            "start_time": str(default_row["start_time"]),
            "end_time": str(default_row["end_time"]),
        }
        for day_name, _weekday in TIMETABLE_DAY_COLUMNS:
            row[day_name] = False
        rows_by_label[label] = row
        ordered_labels.append(label)

    for schedule in schedules:
        label = str(schedule["label"])
        row = rows_by_label.get(label)
        if row is None:
            row = {
                "label": label,
                "start_time": str(schedule["start_time"]),
                "end_time": str(schedule["end_time"]),
            }
            for day_name, _weekday in TIMETABLE_DAY_COLUMNS:
                row[day_name] = False
            rows_by_label[label] = row
            ordered_labels.append(label)

        row["start_time"] = str(schedule["start_time"])
        row["end_time"] = str(schedule["end_time"])
        day_name = _weekday_to_editor_day_name(int(schedule["weekday"]))
        if day_name is not None:
            row[day_name] = True

    return [rows_by_label[label] for label in ordered_labels]


def _save_timetable(
    *,
    repo: AttendanceRepository,
    settings,
    course_id: int,
    edited_rows,
) -> None:
    schedule_rows: list[dict[str, str | int]] = []
    used_labels: set[str] = set()

    for row in _coerce_timetable_editor_rows(edited_rows):
        label = str(row.get("label", "") or "").strip()
        start_time = str(row.get("start_time", "") or "").strip()
        end_time = str(row.get("end_time", "") or "").strip()
        selected_days = [
            (day_name, weekday)
            for day_name, weekday in TIMETABLE_DAY_COLUMNS
            if bool(row.get(day_name, False))
        ]

        if not label and not start_time and not end_time and not selected_days:
            continue
        if not selected_days:
            continue
        if not label or not start_time or not end_time:
            st.error("Each active timetable row must have a slot label, start time, and end time.")
            return
        if label in used_labels:
            st.error("Each timetable row must use a unique slot label.")
            return

        try:
            parsed_start = parse_hhmm(start_time)
            parsed_end = parse_hhmm(end_time)
        except ValueError:
            st.error(
                f"Invalid time format for `{label}`. Use 24-hour time such as `07:30` or `13:25`."
            )
            return
        if parsed_end <= parsed_start:
            st.error(f"End time must be later than start time for `{label}`.")
            return

        used_labels.add(label)
        normalized_start = parsed_start.strftime("%H:%M")
        normalized_end = parsed_end.strftime("%H:%M")
        for _day_name, weekday in selected_days:
            schedule_rows.append(
                {
                    "weekday": weekday,
                    "label": label,
                    "start_time": normalized_start,
                    "end_time": normalized_end,
                }
            )

    try:
        repo.sync_course_schedules(
            course_id=course_id,
            schedule_rows=schedule_rows,
            created_at=now_in_app_timezone(settings).isoformat(),
        )
        st.session_state["manager_notice"] = "Course timetable saved successfully."
        st.rerun()
    except Exception as error:  # pragma: no cover - Streamlit surface
        st.error(str(error))


def _weekday_to_editor_day_name(weekday: int) -> str | None:
    for day_name, mapped_weekday in TIMETABLE_DAY_COLUMNS:
        if mapped_weekday == weekday:
            return day_name
    return None


def _coerce_timetable_editor_rows(edited_rows) -> list[dict[str, object]]:
    if isinstance(edited_rows, list):
        return [dict(row) for row in edited_rows]

    to_dict = getattr(edited_rows, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict("records")
            return [dict(row) for row in records]
        except TypeError:
            pass

    to_pylist = getattr(edited_rows, "to_pylist", None)
    if callable(to_pylist):
        return [dict(row) for row in to_pylist()]

    return [dict(row) for row in edited_rows]


def _render_course_summary(repo: AttendanceRepository, course) -> None:
    students = repo.list_students_for_course(int(course["id"]))
    schedules = repo.list_schedules_for_course(int(course["id"]))
    attendance_rows = repo.list_course_attendance(course_id=int(course["id"]), limit=10000)
    summary_columns = st.columns(4)
    summary_columns[0].metric("Course", course["code"])
    summary_columns[1].metric("Roster", len(students))
    summary_columns[2].metric("Timetable windows", len(schedules))
    summary_columns[3].metric("Attendance stamps", len(attendance_rows))
    st.caption(
        f"{course['title']} | {course['start_date']} to {course['end_date']} | "
        f"Radius {float(course['radius_m']):.1f} m | Absence limit {float(course['absence_limit_pct']):.0f}%"
    )


def _render_location_summary() -> None:
    if not _has_course_location_selection():
        st.warning("No classroom point is selected yet. Click the map or use your device location.")
        return

    latitude = float(st.session_state["course_latitude"])
    longitude = float(st.session_state["course_longitude"])
    col1, col2 = st.columns(2)
    col1.metric("Latitude", f"{latitude:.6f}")
    col2.metric("Longitude", f"{longitude:.6f}")
    st.caption("This classroom point is saved with the course and enforced for student access.")


def _handle_student_access_gate(student_geo, repo: AttendanceRepository, settings, university_id: str) -> None:
    if not student_geo:
        return
    captured_at = student_geo.get("captured_at")
    if captured_at == st.session_state.get("student_access_geo_processed_at"):
        return
    st.session_state["student_access_geo_processed_at"] = captured_at

    if not university_id.strip():
        st.error("Enter your student ID before sharing your location.")
        _reset_student_access_flow(clear_student_id=False)
        return

    try:
        access_context = resolve_student_access_context(
            repo,
            settings,
            university_id=university_id.strip(),
            geolocation_payload=student_geo,
        )
    except Exception as error:  # pragma: no cover - Streamlit surface
        _reset_student_access_flow(clear_student_id=False)
        st.error(str(error))
        return

    st.session_state["student_access_context"] = access_context.__dict__.copy()
    st.session_state["student_access_geolocation"] = student_geo
    st.session_state["student_otp_requested"] = False
    st.session_state["student_stamp_result"] = None
    st.session_state["student_stamp_geolocation"] = None


def _handle_student_stamp_gate(student_geo) -> None:
    if not student_geo:
        return
    captured_at = student_geo.get("captured_at")
    if captured_at == st.session_state.get("student_stamp_geo_processed_at"):
        return
    st.session_state["student_stamp_geo_processed_at"] = captured_at

    if student_geo.get("error"):
        st.session_state["student_stamp_geolocation"] = None
        st.error(str(student_geo["error"]))
        return

    st.session_state["student_stamp_geolocation"] = student_geo
    st.session_state["student_stamp_result"] = None


def _student_access_context_is_current(
    repo: AttendanceRepository,
    settings,
    access_context: dict,
) -> bool:
    course = repo.get_course(int(access_context["course_id"]))
    if course is None:
        return False

    if abs(float(course["latitude"]) - float(access_context["course_latitude"])) > 1e-9:
        return False
    if abs(float(course["longitude"]) - float(access_context["course_longitude"])) > 1e-9:
        return False
    if abs(float(course["radius_m"]) - float(access_context["radius_m"])) > 1e-9:
        return False

    schedules = repo.list_schedules_for_course(int(course["id"]))
    active_schedule = find_active_schedule(schedules, now_in_app_timezone(settings))
    if active_schedule is None:
        return False
    return int(active_schedule["id"]) == int(access_context["schedule_id"])


def _build_access_context_object(access_context: dict) -> StudentAccessContext:
    return StudentAccessContext(**access_context)


def _invalidate_student_access_for_course(course_id: int) -> None:
    auth = st.session_state.get("student_auth")
    if auth is not None and int(auth["course_id"]) == course_id:
        st.session_state["student_auth"] = None

    access_context = st.session_state.get("student_access_context")
    if access_context is not None and int(access_context["course_id"]) == course_id:
        _reset_student_access_flow(clear_student_id=False)


def _reset_student_access_flow(*, clear_student_id: bool) -> None:
    if clear_student_id:
        st.session_state["pending_university_id"] = ""
    st.session_state["student_access_context"] = None
    st.session_state["student_access_geolocation"] = None
    st.session_state["student_otp_requested"] = False
    st.session_state["student_otp_notice"] = None
    st.session_state["student_otp_preview_code"] = None
    st.session_state["student_stamp_result"] = None
    st.session_state["student_stamp_geolocation"] = None
    st.session_state["student_access_geo_processed_at"] = None
    st.session_state["student_stamp_geo_processed_at"] = None


def _ensure_course_location_defaults() -> None:
    st.session_state.setdefault("course_latitude", 0.0)
    st.session_state.setdefault("course_longitude", 0.0)
    st.session_state.setdefault("course_location_selected", False)
    st.session_state.setdefault("manager_course_selector", "New course")


def _sync_course_location_state(selected_course) -> None:
    selected_signature = "new"
    if selected_course is not None:
        selected_signature = (
            f"{selected_course['id']}:"
            f"{repr(float(selected_course['latitude']))}:"
            f"{repr(float(selected_course['longitude']))}:"
            f"{repr(float(selected_course['radius_m']))}"
        )

    if st.session_state.get("loaded_course_location_signature") == selected_signature:
        return

    if selected_course is None:
        st.session_state["course_latitude"] = 0.0
        st.session_state["course_longitude"] = 0.0
        st.session_state["course_location_selected"] = False
    else:
        st.session_state["course_latitude"] = float(selected_course["latitude"])
        st.session_state["course_longitude"] = float(selected_course["longitude"])
        st.session_state["course_location_selected"] = True

    st.session_state["loaded_course_location_signature"] = selected_signature


def _has_course_location_selection() -> bool:
    if st.session_state.get("course_location_selected", False):
        return True
    latitude = float(st.session_state.get("course_latitude", 0.0))
    longitude = float(st.session_state.get("course_longitude", 0.0))
    return abs(latitude) > 0 or abs(longitude) > 0


def _init_session_state() -> None:
    st.session_state.setdefault("manager_auth", None)
    st.session_state.setdefault("student_auth", None)
    st.session_state.setdefault("pending_university_id", "")
    st.session_state.setdefault("student_access_context", None)
    st.session_state.setdefault("student_access_geolocation", None)
    st.session_state.setdefault("student_access_geo_processed_at", None)
    st.session_state.setdefault("student_otp_requested", False)
    st.session_state.setdefault("student_otp_notice", None)
    st.session_state.setdefault("student_otp_preview_code", None)
    st.session_state.setdefault("student_stamp_result", None)
    st.session_state.setdefault("student_stamp_geolocation", None)
    st.session_state.setdefault("student_stamp_geo_processed_at", None)


def _safe_secrets():
    try:
        return dict(st.secrets)
    except Exception:  # pragma: no cover - Streamlit surface
        return {}


if __name__ == "__main__":
    main()
