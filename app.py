from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from html import escape
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from attendance_app.browser_keys import build_browser_key_options
from attendance_app.components import geo_capture, location_picker, passkey_action
from attendance_app.config import load_settings
from attendance_app.database import AttendanceRepository
from attendance_app.passkeys import build_authentication_options, build_registration_options
from attendance_app.report_importer import import_attendance_report_bytes
from attendance_app.reports import build_course_report_xlsx
from attendance_app.roster import parse_roster_file
from attendance_app.security import verify_password
from attendance_app.services import (
    StudentAccessContext,
    authenticate_student_browser_key,
    authenticate_student_passkey,
    build_student_attendance_summary,
    now_in_app_timezone,
    otp_delivery_configuration_error,
    register_student_passkey,
    request_login_code_for_access_context,
    request_student_browser_key_enrollment,
    reset_student_device,
    resolve_active_student_session,
    resolve_student_access_context,
    seed_demo_data,
    stamp_attendance,
    verify_login_code_for_access_context,
)
from attendance_app.utils import parse_hhmm, parse_iso_date, weekday_label

APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Kufi+Arabic:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');

:root {
    --cp-bg: #080b10;
    --cp-panel: #0f141c;
    --cp-panel-2: #131a24;
    --cp-panel-3: #18212d;
    --cp-line: #253140;
    --cp-line-soft: rgba(148, 163, 184, 0.13);
    --cp-text: #f4f7fb;
    --cp-soft: #a5b0c0;
    --cp-muted: #6f7d90;
    --cp-accent: #c7f36b;
    --cp-accent-ink: #121807;
    --cp-blue: #78b8ff;
    --cp-success: #58d6a8;
    --cp-warning: #f3bd63;
    --cp-danger: #ff7d87;
    --cp-radius: 18px;
    --cp-shadow: 0 24px 80px rgba(0, 0, 0, 0.28);
}

html, body, [class*="css"] {
    font-family: 'Space Grotesk', 'Noto Kufi Arabic', sans-serif;
    color: var(--cp-text);
}

.cp-topbar *,
.cp-hero *,
.cp-role-card *,
.cp-page-head *,
.cp-course-strip *,
.cp-session *,
.cp-day *,
.cp-access-card *,
.cp-metric * {
    font-family: 'Space Grotesk', sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 8% -10%, rgba(199, 243, 107, 0.09), transparent 28rem),
        radial-gradient(circle at 92% 0%, rgba(120, 184, 255, 0.07), transparent 32rem),
        var(--cp-bg);
}

.block-container {
    width: min(100%, 1420px);
    max-width: 1420px;
    padding: 1.25rem 2rem 4rem;
}

header[data-testid="stHeader"],
[data-testid="stSidebar"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
footer {
    display: none !important;
}

h1, h2, h3, h4, p { color: var(--cp-text); }
h1, h2, h3 { letter-spacing: -0.035em; }

.cp-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    min-height: 64px;
    margin-bottom: 1.5rem;
    padding: 0 0.15rem 1rem;
    border-bottom: 1px solid var(--cp-line-soft);
}

.cp-brand {
    display: flex;
    align-items: center;
    gap: 0.78rem;
}

.cp-mark {
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: var(--cp-accent);
    color: var(--cp-accent-ink);
    font-family: 'DM Mono', monospace;
    font-size: 0.9rem;
    font-weight: 500;
    box-shadow: 0 0 0 5px rgba(199, 243, 107, 0.08);
}

.cp-brand strong {
    display: block;
    font-size: 0.98rem;
    letter-spacing: -0.02em;
}

.cp-brand span,
.cp-top-meta {
    color: var(--cp-muted);
    font-family: 'DM Mono', monospace;
    font-size: 0.69rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

.cp-top-meta { text-align: right; }

.cp-page-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 2rem;
    margin: 1.7rem 0 1.25rem;
}

.cp-eyebrow {
    display: block;
    margin-bottom: 0.55rem;
    color: var(--cp-accent);
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    font-weight: 500;
    letter-spacing: 0.11em;
    text-transform: uppercase;
}

.cp-page-head h1 {
    margin: 0;
    font-size: clamp(2rem, 4vw, 3.35rem);
    line-height: 0.98;
}

.cp-page-head p {
    max-width: 560px;
    margin: 0.72rem 0 0;
    color: var(--cp-soft);
    font-size: 0.96rem;
    line-height: 1.55;
}

.cp-date-block {
    min-width: 200px;
    padding: 0.85rem 1rem;
    border: 1px solid var(--cp-line);
    border-radius: 14px;
    background: rgba(15, 20, 28, 0.72);
    color: var(--cp-soft);
    font-family: 'DM Mono', monospace;
    font-size: 0.74rem;
    line-height: 1.65;
    text-align: right;
}

.cp-hero {
    position: relative;
    overflow: hidden;
    min-height: 330px;
    margin: 3.2rem 0 1.35rem;
    padding: clamp(2rem, 6vw, 5rem);
    border: 1px solid var(--cp-line);
    border-radius: 28px;
    background:
        linear-gradient(120deg, rgba(199, 243, 107, 0.07), transparent 42%),
        linear-gradient(150deg, #111821, #0c1118);
    box-shadow: var(--cp-shadow);
}

.cp-hero::after {
    content: '';
    position: absolute;
    width: 290px;
    height: 290px;
    right: -70px;
    top: -95px;
    border: 1px solid rgba(199, 243, 107, 0.25);
    border-radius: 50%;
    box-shadow: 0 0 0 55px rgba(199, 243, 107, 0.025), 0 0 0 110px rgba(120, 184, 255, 0.02);
}

.cp-hero h1 {
    position: relative;
    z-index: 1;
    max-width: 760px;
    margin: 0;
    font-size: clamp(3rem, 8vw, 6.7rem);
    line-height: 0.88;
    letter-spacing: -0.075em;
}

.cp-hero h1 em {
    color: var(--cp-accent);
    font-style: normal;
}

.cp-hero p {
    position: relative;
    z-index: 1;
    max-width: 500px;
    margin: 1.4rem 0 0;
    color: var(--cp-soft);
    font-size: 1rem;
}

.cp-role-card,
.cp-card,
div[data-testid="stForm"],
div[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--cp-line) !important;
    border-radius: var(--cp-radius) !important;
    background: rgba(15, 20, 28, 0.92) !important;
    box-shadow: none !important;
}

.cp-role-card {
    min-height: 150px;
    padding: 1.45rem 1.5rem 1.25rem;
}

.cp-role-card .cp-role-index {
    color: var(--cp-accent);
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
}

.cp-role-card h3 {
    margin: 1.55rem 0 0.35rem;
    font-size: 1.45rem;
}

.cp-role-card p {
    margin: 0;
    color: var(--cp-muted);
    font-size: 0.88rem;
}

.cp-role-card-ar {
    direction: rtl;
    text-align: right;
}

.cp-role-card-ar *,
.cp-role-card-ar .cp-role-index {
    font-family: 'Noto Kufi Arabic', 'Tahoma', sans-serif;
    letter-spacing: 0;
}

.cp-toolbar {
    margin-bottom: 1.25rem;
    padding: 0.75rem;
    border: 1px solid var(--cp-line);
    border-radius: var(--cp-radius);
    background: rgba(15, 20, 28, 0.9);
}

.cp-metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.8rem;
    margin: 0.8rem 0 1.3rem;
}

.cp-metrics.compact { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.cp-metric {
    min-height: 112px;
    padding: 1.15rem 1.2rem;
    border: 1px solid var(--cp-line);
    border-radius: 16px;
    background: linear-gradient(145deg, rgba(19, 26, 36, 0.94), rgba(13, 18, 25, 0.94));
}

.cp-metric span {
    color: var(--cp-muted);
    font-family: 'DM Mono', monospace;
    font-size: 0.67rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.cp-metric strong {
    display: block;
    margin-top: 0.72rem;
    color: var(--cp-text);
    font-size: 2rem;
    line-height: 1;
    letter-spacing: -0.05em;
}

.cp-metric small {
    display: block;
    margin-top: 0.55rem;
    color: var(--cp-soft);
    font-size: 0.75rem;
}

.cp-section-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    margin: 1.65rem 0 0.85rem;
}

.cp-section-title h2 {
    margin: 0;
    font-size: 1.25rem;
}

.cp-section-title span {
    color: var(--cp-muted);
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    text-transform: uppercase;
}

.cp-session-list { display: grid; gap: 0.7rem; }

.cp-session {
    display: grid;
    grid-template-columns: 88px minmax(190px, 1fr) minmax(140px, 0.7fr) 90px 90px;
    align-items: center;
    gap: 1rem;
    padding: 1rem 1.1rem;
    border: 1px solid var(--cp-line-soft);
    border-radius: 14px;
    background: rgba(15, 20, 28, 0.72);
}

.cp-session.live { border-color: rgba(199, 243, 107, 0.35); background: rgba(199, 243, 107, 0.045); }
.cp-session .time { font-family: 'DM Mono', monospace; font-size: 0.82rem; color: var(--cp-text); }
.cp-session strong { display: block; font-size: 0.92rem; }
.cp-session small { color: var(--cp-muted); font-size: 0.75rem; }
.cp-session .count { color: var(--cp-soft); font-family: 'DM Mono', monospace; font-size: 0.75rem; text-align: right; }

.cp-status {
    display: inline-flex;
    justify-content: center;
    padding: 0.32rem 0.55rem;
    border-radius: 999px;
    background: var(--cp-panel-3);
    color: var(--cp-soft);
    font-family: 'DM Mono', monospace;
    font-size: 0.64rem;
    text-transform: uppercase;
}

.cp-status.live { background: var(--cp-accent); color: var(--cp-accent-ink); }
.cp-status.done { background: rgba(88, 214, 168, 0.1); color: var(--cp-success); }
.cp-status.closed { background: rgba(255, 125, 135, 0.1); color: var(--cp-danger); }

.cp-week {
    display: grid;
    grid-template-columns: repeat(7, minmax(130px, 1fr));
    gap: 0.65rem;
    overflow-x: auto;
    padding-bottom: 0.35rem;
}

.cp-day {
    min-height: 190px;
    padding: 0.9rem;
    border: 1px solid var(--cp-line);
    border-radius: 15px;
    background: rgba(15, 20, 28, 0.85);
}

.cp-day.today { border-color: rgba(199, 243, 107, 0.42); }
.cp-day h4 { display: flex; justify-content: space-between; gap: 0.4rem; margin: 0 0 0.8rem; font-size: 0.82rem; }
.cp-day h4 span { color: var(--cp-muted); font-family: 'DM Mono', monospace; font-size: 0.62rem; font-weight: 400; }

.cp-slot {
    margin-top: 0.55rem;
    padding: 0.65rem;
    border-left: 2px solid var(--cp-blue);
    border-radius: 4px 9px 9px 4px;
    background: rgba(120, 184, 255, 0.07);
}

.cp-slot.live { border-left-color: var(--cp-accent); background: rgba(199, 243, 107, 0.07); }
.cp-slot strong { display: block; font-size: 0.75rem; }
.cp-slot span { color: var(--cp-soft); font-family: 'DM Mono', monospace; font-size: 0.63rem; }
.cp-empty { color: var(--cp-muted); font-size: 0.75rem; }

.cp-course-strip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
    padding: 1rem 1.15rem;
    border: 1px solid var(--cp-line);
    border-radius: 15px;
    background: rgba(15, 20, 28, 0.8);
}

.cp-course-strip strong { font-size: 1rem; }
.cp-course-strip span { color: var(--cp-soft); font-size: 0.78rem; }
.cp-course-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.45rem; }
.cp-course-tags b { padding: 0.35rem 0.55rem; border-radius: 8px; background: var(--cp-panel-3); color: var(--cp-soft); font-family: 'DM Mono', monospace; font-size: 0.64rem; font-weight: 400; }

.cp-empty-state {
    padding: 3.5rem 1.2rem;
    border: 1px dashed var(--cp-line);
    border-radius: var(--cp-radius);
    color: var(--cp-muted);
    text-align: center;
}

.cp-access-card {
    padding: 1.3rem 1.4rem;
    border: 1px solid rgba(199, 243, 107, 0.28);
    border-radius: var(--cp-radius);
    background: linear-gradient(135deg, rgba(199, 243, 107, 0.07), rgba(15, 20, 28, 0.95));
}

.cp-access-card h3 { margin: 0.35rem 0 0.3rem; font-size: 1.35rem; }
.cp-access-card p { margin: 0; color: var(--cp-soft); font-size: 0.82rem; }
.cp-access-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.65rem; margin-top: 1rem; }
.cp-access-grid div { padding: 0.7rem; border-radius: 10px; background: rgba(0,0,0,0.18); }
.cp-access-grid span { display: block; color: var(--cp-muted); font-size: 0.62rem; text-transform: uppercase; }
.cp-access-grid strong { display: block; margin-top: 0.25rem; font-family: 'DM Mono', monospace; font-size: 0.76rem; }

.cp-code {
    margin: 0.8rem 0;
    padding: 1rem;
    border: 1px solid rgba(199, 243, 107, 0.26);
    border-radius: 12px;
    background: rgba(199, 243, 107, 0.055);
    color: var(--cp-accent);
    font-family: 'DM Mono', monospace;
    font-size: 1.6rem;
    letter-spacing: 0.22em;
    text-align: center;
}

.cp-result-ok,
.cp-result-bad {
    padding: 1.1rem 1.2rem;
    border-radius: 14px;
    font-size: 0.88rem;
}

.cp-result-ok { border: 1px solid rgba(88, 214, 168, 0.3); background: rgba(88, 214, 168, 0.07); color: var(--cp-success); }
.cp-result-bad { border: 1px solid rgba(255, 125, 135, 0.3); background: rgba(255, 125, 135, 0.07); color: var(--cp-danger); }

div[data-testid="stForm"],
div[data-testid="stVerticalBlockBorderWrapper"] { padding: 1rem !important; }

div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div,
div[data-baseweb="base-input"],
[data-testid="stDateInput"] > div > div,
[data-testid="stNumberInput"] > div > div {
    background: var(--cp-panel-2) !important;
    border-color: var(--cp-line) !important;
    color: var(--cp-text) !important;
}

input, textarea { color: var(--cp-text) !important; caret-color: var(--cp-accent) !important; }
label, [data-testid="stWidgetLabel"] p { color: var(--cp-soft) !important; font-size: 0.78rem !important; }

.stButton > button,
.stDownloadButton > button,
button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button {
    min-height: 42px;
    border: 1px solid var(--cp-line) !important;
    border-radius: 11px !important;
    background: var(--cp-panel-3) !important;
    color: var(--cp-text) !important;
    font-family: 'Space Grotesk', 'Noto Kufi Arabic', sans-serif !important;
    font-weight: 600 !important;
    transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
}

.stButton > button:hover,
.stDownloadButton > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover {
    transform: translateY(-1px);
    border-color: rgba(199, 243, 107, 0.55) !important;
    color: var(--cp-accent) !important;
}

button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background: var(--cp-accent) !important;
    border-color: var(--cp-accent) !important;
    color: var(--cp-accent-ink) !important;
}

button[kind="primary"] p,
div[data-testid="stFormSubmitButton"] > button[kind="primary"] p {
    color: var(--cp-accent-ink) !important;
}

[data-testid="stButtonGroup"] {
    padding: 0.2rem;
    border-radius: 12px;
    background: var(--cp-bg);
}

[data-testid="stButtonGroup"] button {
    border-radius: 9px !important;
    color: var(--cp-soft) !important;
    font-size: 0.78rem !important;
}

[data-testid="stButtonGroup"] button[aria-pressed="true"] {
    background: var(--cp-panel-3) !important;
    color: var(--cp-text) !important;
}

[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    overflow: hidden;
    border: 1px solid var(--cp-line);
    border-radius: 14px;
}

[data-testid="stFileUploaderDropzone"] {
    border: 1px dashed var(--cp-line) !important;
    border-radius: 14px !important;
    background: var(--cp-panel-2) !important;
}

[data-testid="stAlert"] {
    border-radius: 13px !important;
    background: var(--cp-panel-2) !important;
    color: var(--cp-text) !important;
}

hr { border-color: var(--cp-line-soft) !important; }

@media (max-width: 900px) {
    .block-container { padding: 0.8rem 1rem 3rem; }
    .cp-topbar { margin-bottom: 1rem; }
    .cp-top-meta, .cp-date-block { display: none; }
    .cp-page-head { align-items: flex-start; margin-top: 1rem; }
    .cp-page-head h1 { font-size: 2.35rem; }
    .cp-hero { min-height: 280px; margin-top: 1.4rem; padding: 2rem 1.4rem; }
    .cp-hero h1 { font-size: clamp(2.8rem, 12vw, 3.2rem); }
    .cp-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .cp-session { grid-template-columns: 74px 1fr 72px; }
    .cp-session .window, .cp-session .count { display: none; }
    .cp-course-strip { align-items: flex-start; flex-direction: column; }
    .cp-course-tags { justify-content: flex-start; }
}

@media (max-width: 520px) {
    .cp-metrics { grid-template-columns: 1fr 1fr; gap: 0.55rem; }
    .cp-metric { min-height: 94px; padding: 0.9rem; }
    .cp-metric strong { font-size: 1.55rem; }
    .cp-access-grid { grid-template-columns: 1fr; }
}
</style>
"""

STUDENT_RTL_CSS = """
<style>
.block-container {
    direction: rtl;
    text-align: right;
}

.block-container,
.block-container button,
.block-container input,
.block-container label,
.block-container p,
.block-container h1,
.block-container h2,
.block-container h3,
.block-container h4,
.block-container span,
.block-container small {
    font-family: 'Noto Kufi Arabic', 'Tahoma', sans-serif !important;
}

.block-container h1,
.block-container h2,
.block-container h3,
.block-container h4,
.block-container .cp-eyebrow,
.block-container .cp-metric span,
.block-container .cp-section-title span {
    letter-spacing: 0;
}

.cp-top-meta,
.cp-date-block {
    text-align: left;
}

.cp-ltr,
.cp-code,
.block-container input,
.block-container textarea {
    direction: ltr;
    unicode-bidi: isolate;
}

.block-container input,
.block-container textarea {
    text-align: left;
}

[data-testid="stWidgetLabel"],
[data-testid="stAlert"],
[data-testid="stDataFrame"],
[data-testid="stButtonGroup"] {
    direction: rtl;
    text-align: right;
}
</style>
<span class="cp-student-ui" lang="ar" dir="rtl" aria-hidden="true"></span>
"""


TIMETABLE_DAY_COLUMNS = [
    ("Monday", 0),
    ("Tuesday", 1),
    ("Wednesday", 2),
    ("Thursday", 3),
    ("Friday", 4),
    ("Saturday", 5),
    ("Sunday", 6),
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

MANAGER_SECTIONS = [
    "Today",
    "Timetable",
    "Courses",
    "Students",
    "Attendance",
    "Security",
    "Reports",
]
STUDENT_SECTIONS = ["Check in", "Status", "History"]
STUDENT_SECTION_LABELS = {
    "Check in": "تسجيل الحضور",
    "Status": "الحالة",
    "History": "السجل",
}
ARABIC_WEEKDAYS = [
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
]
ARABIC_MONTHS = [
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
]
STUDENT_MESSAGE_TRANSLATIONS = {
    "Student ID was not found in any course roster.": "الرقم الجامعي غير موجود في قوائم المقررات.",
    "This device is already registered to another student.": "هذا الجهاز مسجل لطالب آخر.",
    "Use your registered device or ask the manager to reset it.": "استخدم جهازك المسجل أو اطلب من المسؤول إعادة تعيينه.",
    "Student access context is no longer valid.": "انتهت صلاحية طلب الدخول. ابدأ من جديد.",
    "Verify the registered device before requesting a code.": "تحقق من الجهاز المسجل قبل طلب الرمز.",
    "The verified passkey does not match this student device.": "مفتاح المرور لا يطابق جهاز الطالب المسجل.",
    "Verify the passkey again for this lecture window.": "أعد التحقق من مفتاح المرور لهذه المحاضرة.",
    "This verification belongs to a different lecture window.": "هذا التحقق مرتبط بمحاضرة أخرى.",
    "No active login code was found. Generate a new code.": "لا يوجد رمز تحقق فعال. اطلب رمزاً جديداً.",
    "This code belongs to a different lecture window. Request a new code.": "هذا الرمز مرتبط بمحاضرة أخرى. اطلب رمزاً جديداً.",
    "This code must be verified on the device that requested it.": "يجب إدخال الرمز على الجهاز الذي طلبه.",
    "This code is not bound to the verified passkey.": "الرمز غير مرتبط بمفتاح المرور الذي تم التحقق منه.",
    "The one-time code is invalid.": "رمز التحقق غير صحيح.",
    "Device identity changed. Start the check-in again.": "تغيرت هوية الجهاز. ابدأ تسجيل الحضور من جديد.",
    "This student already has a registered device.": "يوجد جهاز مسجل لهذا الطالب بالفعل.",
    "No registered device was found for this student.": "لم يتم العثور على جهاز مسجل لهذا الطالب.",
    "This is not the registered browser for this student.": "هذا المتصفح غير مسجل لهذا الطالب.",
    "This student uses registered-browser verification instead of a passkey.": "يستخدم هذا الطالب التحقق من المتصفح المسجل بدلاً من مفتاح المرور.",
    "This student must verify using the registered passkey.": "يجب التحقق باستخدام مفتاح المرور المسجل.",
    "The browser credential does not match the registered device.": "مفتاح المتصفح لا يطابق الجهاز المسجل.",
    "The registered browser signature is invalid.": "تعذر التحقق من توقيع المتصفح المسجل.",
    "The browser credential data is incomplete.": "بيانات مفتاح المتصفح غير مكتملة.",
    "The browser credential data is invalid.": "بيانات مفتاح المتصفح غير صالحة.",
    "The browser public key is invalid.": "مفتاح المتصفح العام غير صالح.",
    "The browser credential identifier is invalid.": "معرف مفتاح المتصفح غير صالح.",
    "This browser could not provide a valid device identity.": "تعذر التحقق من هوية هذا الجهاز.",
    "The passkey does not match the registered device.": "مفتاح المرور لا يطابق الجهاز المسجل.",
    "Location verification data is incomplete. Capture location again.": "بيانات الموقع غير مكتملة. أعد تحديد الموقع.",
    "The device returned invalid location coordinates.": "تعذر التحقق من إحداثيات الموقع.",
    "The location timestamp is invalid. Capture location again.": "بيانات وقت الموقع غير صالحة. أعد تحديد الموقع.",
    "The location timestamp must include a timezone.": "بيانات وقت الموقع غير مكتملة. أعد تحديد الموقع.",
    "Location expired. Capture a fresh classroom location.": "انتهت صلاحية الموقع. حدد موقعك داخل القاعة مرة أخرى.",
    "Attendance is not available because this course is outside its active dates.": "تسجيل الحضور غير متاح خارج فترة المقرر.",
    "Attendance is closed right now. Try again during an approved schedule window.": "تسجيل الحضور مغلق الآن.",
    "Verify your registered passkey before submitting attendance.": "تحقق من مفتاح المرور قبل تسجيل الحضور.",
    "Your lecture verification has expired. Verify passkey and OTP again.": "انتهت صلاحية التحقق للمحاضرة. أعد التحقق من الجهاز والرمز.",
    "Attendance must be submitted from the verified device.": "يجب تسجيل الحضور من الجهاز الذي تم التحقق منه.",
    "Attendance has already been stamped for this schedule window.": "تم تسجيل حضورك لهذه المحاضرة مسبقاً.",
    "This device has already been used for another student in this lecture.": "تم استخدام هذا الجهاز لطالب آخر في هذه المحاضرة.",
    "This device has already been used in this lecture.": "تم استخدام هذا الجهاز في هذه المحاضرة مسبقاً.",
    "A one-time code has been generated and shown on this page.": "تم إنشاء رمز التحقق وعرضه في هذه الصفحة.",
}


@st.cache_data(
    ttl=15,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_list_courses(database_target: str) -> list[dict]:
    return AttendanceRepository(database_target).list_courses()


@st.cache_data(
    ttl=15,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_get_course(database_target: str, course_id: int) -> dict | None:
    return AttendanceRepository(database_target).get_course(course_id)


@st.cache_data(
    ttl=15,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_get_student(database_target: str, student_id: int) -> dict | None:
    return AttendanceRepository(database_target).get_student(student_id)


@st.cache_data(
    ttl=15,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_list_students(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_students_for_course(course_id)


@st.cache_data(
    ttl=15,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_list_schedules(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_schedules_for_course(course_id)


@st.cache_data(
    ttl=10,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_list_course_attendance(
    database_target: str,
    course_id: int,
    limit: int,
) -> list[dict]:
    return AttendanceRepository(database_target).list_course_attendance(
        course_id=course_id,
        limit=limit,
    )


@st.cache_data(
    ttl=10,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_list_student_attendance(
    database_target: str,
    course_id: int,
    student_id: int,
    limit: int,
) -> list[dict]:
    return AttendanceRepository(database_target).list_attendance(
        course_id=course_id,
        student_id=student_id,
        limit=limit,
    )


@st.cache_data(
    ttl=10,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_attendance_counts(database_target: str, course_id: int) -> dict[int, int]:
    return AttendanceRepository(database_target).count_attendance_by_student_for_course(
        course_id=course_id
    )


@st.cache_data(
    ttl=5,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_attendance_exists(
    database_target: str,
    course_id: int,
    student_id: int,
    schedule_id: int,
    attendance_date: str,
) -> bool:
    return AttendanceRepository(database_target).attendance_exists(
        course_id=course_id,
        student_id=student_id,
        schedule_id=schedule_id,
        attendance_date=attendance_date,
    )


@st.cache_data(
    ttl=10,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_list_proxy_alerts(
    database_target: str,
    course_id: int,
    limit: int,
) -> list[dict]:
    return AttendanceRepository(database_target).list_proxy_alerts(
        course_id=course_id,
        limit=limit,
    )


@st.cache_data(
    ttl=10,
    max_entries=512,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_list_device_audit_events(
    database_target: str,
    course_id: int,
    limit: int,
) -> list[dict]:
    return AttendanceRepository(database_target).list_device_audit_events(
        course_id=course_id,
        limit=limit,
    )


@st.cache_data(
    ttl=30,
    max_entries=128,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_report_attendance(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_course_attendance_for_report(
        course_id=course_id
    )


@st.cache_data(
    ttl=30,
    max_entries=128,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_report_security_alerts(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_proxy_alerts_for_report(
        course_id=course_id
    )


@st.cache_data(
    ttl=30,
    max_entries=128,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_report_device_audit(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_device_audit_events_for_report(
        course_id=course_id
    )


@st.cache_data(
    ttl=30,
    max_entries=128,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_report_otp_activity(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_otp_activity_for_report(course_id=course_id)


@st.cache_data(
    ttl=300,
    max_entries=64,
    show_spinner="Preparing complete Excel report...",
    refresh_mode="background",
)
def _cached_course_report(
    *,
    course: dict,
    students: list[dict],
    schedules: list[dict],
    attendance_records: list[dict],
    eligibility_rows: list[dict[str, object]],
    security_alerts: list[dict],
    device_audit_events: list[dict],
    otp_activity: list[dict],
    timezone_name: str,
) -> bytes:
    return build_course_report_xlsx(
        course=course,
        students=students,
        schedules=schedules,
        attendance_records=attendance_records,
        eligibility_rows=eligibility_rows,
        security_alerts=security_alerts,
        device_audit_events=device_audit_events,
        otp_activity=otp_activity,
        generated_at=datetime.now(ZoneInfo(timezone_name)),
    )


@st.cache_data(
    ttl=30,
    max_entries=128,
    show_spinner=False,
    refresh_mode="background",
)
def _cached_eligibility_rows(
    *,
    database_target: str,
    timezone_name: str,
    course: dict,
    students: list[dict],
    schedules: list[dict],
    attendance_counts: dict[int, int],
) -> list[dict[str, object]]:
    repo = AttendanceRepository(database_target)
    settings = SimpleNamespace(app_timezone=timezone_name)
    rows = []
    for student in students:
        summary = build_student_attendance_summary(
            repo,
            settings,
            course=course,
            student=student,
            schedules=schedules,
            attended_count=attendance_counts.get(int(student["id"]), 0),
        )
        rows.append(
            {
                "Student": student["full_name"],
                "University ID": student["university_id"],
                "Attended": summary.attended_count,
                "Absences": summary.absences,
                "Elapsed Meetings": summary.elapsed_meetings,
                "Total Meetings": summary.total_meetings,
                "Threshold": summary.absence_threshold,
                "Status": "Not eligible" if summary.denied_exam_entry else "Eligible",
            }
        )
    return rows


def _invalidate_read_caches() -> None:
    st.cache_data.clear()


def main() -> None:
    st.set_page_config(
        page_title="ClassPresence",
        page_icon="CP",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(APP_CSS, unsafe_allow_html=True)

    settings = load_settings(_safe_secrets())
    repo = AttendanceRepository(settings.database_target)
    try:
        repo.init_schema()
    except RuntimeError as error:
        st.error(str(error))
        st.stop()

    _init_session_state()
    role = st.session_state["active_role"]
    if role is None:
        _render_role_home(settings)
    elif role == "manager":
        _render_manager_entry(repo, settings)
    else:
        _render_student_entry(repo, settings)


def _render_role_home(settings) -> None:
    _render_topbar(settings, context="Attendance platform")
    st.markdown(
        """
        <section class="cp-hero">
            <span class="cp-eyebrow">ClassPresence</span>
            <h1>Attendance,<br><em>verified.</em></h1>
            <p>Live timetable windows, roster access, one-time codes, and classroom location.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    student_col, manager_col = st.columns([1.25, 0.75], gap="medium")
    with student_col:
        st.markdown(
            """
            <div class="cp-role-card cp-role-card-ar" lang="ar" dir="rtl">
                <span class="cp-role-index">٠١ / بوابة الطالب</span>
                <h3>تسجيل الحضور</h3>
                <p>الرقم الجامعي والموقع ورمز التحقق.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("الدخول إلى بوابة الطالب", key="open_student", type="primary", width="stretch"):
            st.session_state["active_role"] = "student"
            st.rerun()
    with manager_col:
        st.markdown(
            """
            <div class="cp-role-card">
                <span class="cp-role-index">02 / MANAGER</span>
                <h3>Manage classes</h3>
                <p>Timetables, rosters, attendance, and reports.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Manager access", key="open_manager", width="stretch"):
            st.session_state["active_role"] = "manager"
            st.rerun()


def _render_manager_entry(repo: AttendanceRepository, settings) -> None:
    if st.session_state.get("manager_auth") is None:
        _render_manager_login(settings)
        return
    _render_manager_workspace(repo, settings)


def _render_manager_login(settings) -> None:
    _render_topbar(settings, context="Manager access")
    left, center, right = st.columns([0.35, 0.7, 0.35], gap="large")
    with center:
        _render_page_head("Secure access", "Manager sign in", "")
        if not settings.manager_username or not settings.manager_password_hash:
            st.error("Manager credentials are not configured.")
        else:
            with st.form("manager_login_form", border=True):
                username = st.text_input("Username", placeholder="Username")
                password = st.text_input("Password", type="password", placeholder="Password")
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
            if submitted:
                if (
                    username.strip() == settings.manager_username
                    and verify_password(password, settings.manager_password_hash)
                ):
                    st.session_state["manager_auth"] = {"username": settings.manager_username}
                    st.rerun()
                st.error("Incorrect username or password.")
        if st.button("Back", key="manager_login_back", width="stretch"):
            st.session_state["active_role"] = None
            st.rerun()


def _render_manager_workspace(repo: AttendanceRepository, settings) -> None:
    _render_topbar(settings, context="Manager workspace")
    notice = st.session_state.pop("manager_notice", None)
    if notice:
        st.success(notice)

    courses = _cached_list_courses(settings.database_target)
    section = _normalize_state_choice("manager_section", MANAGER_SECTIONS)
    _normalize_course_choice(courses)

    with st.container(border=True):
        nav_col, course_col, exit_col = st.columns([2.5, 0.9, 0.34], gap="small")
        with nav_col:
            selected = st.pills(
                "Manager navigation",
                MANAGER_SECTIONS,
                key="manager_section",
                label_visibility="collapsed",
                width="stretch",
            )
            section = selected or MANAGER_SECTIONS[0]
        with course_col:
            options = [str(course["code"]) for course in courses] or ["No courses"]
            st.selectbox(
                "Course",
                options,
                key="manager_course_code",
                label_visibility="collapsed",
                disabled=not courses,
            )
        with exit_col:
            if st.button("Exit", key="manager_exit", width="stretch"):
                st.session_state["manager_auth"] = None
                st.session_state["active_role"] = None
                st.rerun()

    course = _selected_course(courses)
    if section == "Today":
        _render_manager_today(repo, settings, courses)
    elif section == "Timetable":
        _render_manager_timetable(repo, settings, course)
    elif section == "Courses":
        _render_manager_courses(repo, settings, courses, course)
    elif section == "Students":
        _render_manager_students(repo, settings, course)
    elif section == "Attendance":
        _render_manager_attendance(repo, settings, course)
    elif section == "Security":
        _render_manager_security(repo, settings, course)
    else:
        _render_manager_reports(repo, settings, course)


def _render_manager_today(repo: AttendanceRepository, settings, courses) -> None:
    now = now_in_app_timezone(settings)
    sessions = _today_sessions(repo, settings, courses)
    all_students = sum(
        len(_cached_list_students(settings.database_target, int(course["id"])))
        for course in courses
    )
    records_today = 0
    for course in courses:
        records_today += sum(
            str(row["attendance_date"]) == now.date().isoformat()
            for row in _cached_list_course_attendance(
                settings.database_target,
                int(course["id"]),
                10000,
            )
        )
    live_count = sum(row["status"] == "Live" for row in sessions)
    upcoming_count = sum(row["status"] == "Upcoming" for row in sessions)

    _render_page_head("Live operations", "Today", "Courses and attendance windows for the current day.", settings)
    _render_metrics(
        [
            ("Live now", live_count, "active windows"),
            ("Later today", upcoming_count, "upcoming windows"),
            ("Check-ins", records_today, "recorded today"),
            ("Students", all_students, "across all courses"),
        ]
    )
    _render_section_title("Lecture timeline", f"{len(sessions)} windows")
    if not sessions:
        _empty_state("No lectures are scheduled today.")
        return
    cards = []
    for row in sessions:
        status_class = "live" if row["status"] == "Live" else "done" if row["status"] == "Complete" else ""
        cards.append(
            f'<div class="cp-session {status_class}">'
            f'<div class="time">{escape(row["start"])}</div>'
            f'<div><strong>{escape(row["course"])}</strong><small>{escape(row["title"])}</small></div>'
            f'<div class="window"><strong>{escape(row["label"])}</strong>'
            f'<small>{escape(row["start"])}–{escape(row["end"])}</small></div>'
            f'<div><span class="cp-status {status_class}">{escape(row["status"])}</span></div>'
            f'<div class="count">{row["checked_in"]} / {row["roster"]}</div>'
            "</div>"
        )
    st.markdown(f'<div class="cp-session-list">{"".join(cards)}</div>', unsafe_allow_html=True)


@st.fragment
def _render_manager_timetable(repo: AttendanceRepository, settings, course) -> None:
    _render_page_head("Core schedule", "Timetable", "Weekly lecture windows control student access.", settings)
    if course is None:
        _empty_state("Create a course before adding lecture windows.")
        return

    schedules = _cached_list_schedules(settings.database_target, int(course["id"]))
    _render_course_strip(repo, course)
    _render_week_board(settings, schedules)
    _render_section_title("Edit timetable", "Seven-day schedule")

    course_id = int(course["id"])
    show_templates = bool(st.session_state.get(f"show_templates_{course_id}", False))
    rows = _build_timetable_editor_rows(schedules, show_default_rows=show_templates)
    version = st.session_state.get(f"timetable_version_{course_id}", 0)
    with st.form(f"timetable_form_{course_id}_{version}", border=False):
        edited = st.data_editor(
            rows,
            key=f"timetable_editor_{course_id}_{version}",
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_order=[
                "label",
                "start_time",
                "end_time",
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ],
            column_config={
                "label": st.column_config.TextColumn("Window", width="medium", required=True),
                "start_time": st.column_config.TextColumn("Start", width="small", required=True),
                "end_time": st.column_config.TextColumn("End", width="small", required=True),
                **{
                    day_name: st.column_config.CheckboxColumn(day_name[:3], width="small")
                    for day_name, _ in TIMETABLE_DAY_COLUMNS
                },
            },
        )
        save_timetable = st.form_submit_button(
            "Save timetable",
            type="primary",
            width="stretch",
        )
    if save_timetable:
        _save_timetable(repo, settings, course_id, edited)
    template_col, test_col = st.columns(2, gap="small")
    with template_col:
        if st.button("Load L1–L7", key=f"load_templates_{course_id}", width="stretch"):
            st.session_state[f"show_templates_{course_id}"] = True
            st.session_state[f"timetable_version_{course_id}"] = version + 1
            st.rerun(scope="fragment")
    with test_col:
        if settings.app_env == "development" and st.button(
            "Open test window", key=f"test_window_{course_id}", width="stretch"
        ):
            _create_live_test_window(repo, settings, course_id)


@st.fragment
def _render_manager_courses(repo: AttendanceRepository, settings, courses, course) -> None:
    _render_page_head("Course setup", "Courses", "Course dates, attendance rules, and classroom location.", settings)
    create_new = st.session_state.get("course_editor_mode") == "new" or course is None
    top_left, top_right = st.columns([1, 0.32], gap="small")
    with top_left:
        if course is not None and not create_new:
            _render_course_strip(repo, course)
    with top_right:
        if st.button("New course", key="new_course", width="stretch"):
            st.session_state["course_editor_mode"] = "new"
            _reset_course_location(None)
            st.rerun(scope="fragment")

    editing = None if create_new else course
    _sync_course_location(editing)
    identity = "new" if editing is None else str(editing["id"])
    details_col, map_col = st.columns([0.8, 1.2], gap="large")
    with details_col:
        with st.container(border=True):
            st.subheader("Course record")
            with st.form(f"course_form_{identity}", border=False):
                code = st.text_input(
                    "Course code",
                    value="" if editing is None else str(editing["code"]),
                    key=f"course_code_{identity}",
                )
                title = st.text_input(
                    "Course name",
                    value="" if editing is None else str(editing["title"]),
                    key=f"course_title_{identity}",
                )
                date_left, date_right = st.columns(2)
                with date_left:
                    start_date = st.date_input(
                        "Start date",
                        value=date.today()
                        if editing is None
                        else parse_iso_date(str(editing["start_date"])),
                        key=f"course_start_{identity}",
                    )
                with date_right:
                    end_date = st.date_input(
                        "End date",
                        value=date.today() + timedelta(days=90)
                        if editing is None
                        else parse_iso_date(str(editing["end_date"] or editing["start_date"])),
                        key=f"course_end_{identity}",
                    )
                rule_left, rule_right = st.columns(2)
                with rule_left:
                    radius = st.number_input(
                        "Radius (m)",
                        min_value=1.0,
                        max_value=1000.0,
                        value=3.0 if editing is None else float(editing["radius_m"]),
                        step=1.0,
                        key=f"course_radius_{identity}",
                    )
                with rule_right:
                    absence_limit = st.number_input(
                        "Absence limit (%)",
                        min_value=1.0,
                        max_value=100.0,
                        value=20.0 if editing is None else float(editing["absence_limit_pct"]),
                        step=1.0,
                        key=f"course_absence_{identity}",
                    )
                if _has_course_location():
                    st.caption(
                        f"{float(st.session_state['course_latitude']):.6f}, "
                        f"{float(st.session_state['course_longitude']):.6f}"
                    )
                save_course = st.form_submit_button(
                    "Save course",
                    type="primary",
                    width="stretch",
                )
            if save_course:
                _save_course(
                    repo,
                    settings,
                    code=code,
                    title=title,
                    start_date=start_date,
                    end_date=end_date,
                    radius_m=float(radius),
                    absence_limit_pct=float(absence_limit),
                    existing_course_id=None if editing is None else int(editing["id"]),
                )
            if editing is None and settings.app_env == "development" and not courses:
                if st.button("Create demo course", key="seed_demo", width="stretch"):
                    if seed_demo_data(repo, settings, latitude=24.7136, longitude=46.6753):
                        _invalidate_read_caches()
                        st.session_state["manager_notice"] = "Demo course created."
                        st.session_state["course_editor_mode"] = "existing"
                        st.rerun()

    with map_col:
        with st.container(border=True):
            st.subheader("Classroom location")
            payload = location_picker(
                latitude=float(st.session_state.get("course_latitude", 0.0)),
                longitude=float(st.session_state.get("course_longitude", 0.0)),
                radius_m=float(radius),
                has_selection=_has_course_location(),
                key=f"course_map_{identity}",
            )
            _handle_course_location(payload)


@st.fragment
def _render_manager_students(repo: AttendanceRepository, settings, course) -> None:
    _render_page_head("Official roster", "Students", "Only enrolled students can request attendance access.", settings)
    if course is None:
        _empty_state("Select a course to manage its roster.")
        return
    _render_course_strip(repo, course)
    students = _cached_list_students(settings.database_target, int(course["id"]))
    _render_metrics(
        [
            ("Enrolled", len(students), "active roster"),
            ("With email", sum(bool(row["email"]) for row in students), "OTP ready"),
            ("With phone", sum(bool(row["phone"]) for row in students), "contact records"),
            ("Course", course["code"], "selected roster"),
        ]
    )
    roster_col, add_col = st.columns([1.3, 0.7], gap="large")
    with roster_col:
        _render_section_title("Roster", f"{len(students)} students")
        if students:
            st.dataframe(
                [
                    {
                        "Student": row["full_name"],
                        "Student ID": row["university_id"],
                        "Email": row["email"] or "—",
                        "Phone": row["phone"] or "—",
                        "Device": "Registered" if row.get("registered_device_id") else "Not registered",
                        "Method": str(row.get("device_auth_method") or "—")
                        .replace("_", " ")
                        .title(),
                    }
                    for row in students
                ],
                width="stretch",
                hide_index=True,
                lazy=True,
            )
        else:
            _empty_state("The roster is empty.")
    with add_col:
        _render_section_title("Add student", "Single record")
        with st.form(f"add_student_{course['id']}", border=True, clear_on_submit=True):
            full_name = st.text_input("Full name")
            university_id = st.text_input("Student ID")
            email = st.text_input("Email")
            phone = st.text_input("Phone")
            add_student = st.form_submit_button("Add student", type="primary", width="stretch")
        if add_student:
            if not full_name.strip() or not university_id.strip():
                st.error("Full name and student ID are required.")
            else:
                try:
                    repo.add_student_to_course(
                        course_id=int(course["id"]),
                        full_name=full_name.strip(),
                        university_id=university_id.strip(),
                        email=email.strip(),
                        phone=phone.strip(),
                        created_at=now_in_app_timezone(settings).isoformat(),
                    )
                    _invalidate_read_caches()
                    st.session_state["manager_notice"] = f"{full_name.strip()} added to {course['code']}."
                    st.rerun()
                except Exception as error:
                    st.error(str(error))

        _render_section_title("Import roster", "CSV or XLSX")
        uploaded = st.file_uploader(
            "Roster file",
            type=["csv", "xlsx"],
            key=f"roster_upload_{course['id']}",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            try:
                roster_rows = parse_roster_file(uploaded.name, uploaded.getvalue())
                st.caption(f"{len(roster_rows)} valid students")
                if st.button("Replace roster", key=f"sync_roster_{course['id']}", width="stretch"):
                    repo.sync_course_roster(
                        course_id=int(course["id"]),
                        roster_rows=roster_rows,
                        created_at=now_in_app_timezone(settings).isoformat(),
                    )
                    _invalidate_read_caches()
                    st.session_state["manager_notice"] = f"Roster replaced for {course['code']}."
                    st.rerun()
            except Exception as error:
                st.error(str(error))


@st.fragment
def _render_manager_attendance(repo: AttendanceRepository, settings, course) -> None:
    _render_page_head("Verified records", "Attendance", "Location-validated lecture check-ins.", settings)
    if course is None:
        _empty_state("Select a course to view attendance.")
        return
    _render_course_strip(repo, course)
    records = _cached_list_course_attendance(
        settings.database_target,
        int(course["id"]),
        10000,
    )
    today = now_in_app_timezone(settings).date().isoformat()
    unique_students = len({str(row["university_id"]) for row in records})
    average_distance = (
        sum(float(row["distance_m"]) for row in records) / len(records) if records else 0.0
    )
    _render_metrics(
        [
            ("Total stamps", len(records), "all lecture windows"),
            ("Today", sum(str(row["attendance_date"]) == today for row in records), "current day"),
            ("Students", unique_students, "with attendance"),
            ("Avg. distance", f"{average_distance:.1f}m", "from classroom"),
        ]
    )
    if not records:
        _empty_state("No attendance has been recorded for this course.")
        return
    st.dataframe(
        [
            {
                "Date": row["attendance_date"],
                "Student": row["full_name"],
                "Student ID": row["university_id"],
                "Window": row["schedule_label"],
                "Time": str(row["stamped_at"])[11:16],
                "Distance": f"{float(row['distance_m']):.2f} m",
                "Device": "Verified" if row.get("device_binding_hash") else "Legacy",
            }
            for row in records
        ],
        width="stretch",
        hide_index=True,
        lazy=True,
    )


@st.fragment
def _render_manager_security(repo: AttendanceRepository, settings, course) -> None:
    _render_page_head("Proxy protection", "Security", "Device verification and blocked attempts.", settings)
    if course is None:
        _empty_state("Select a course to review security.")
        return

    _render_course_strip(repo, course)
    course_id = int(course["id"])
    alerts = _cached_list_proxy_alerts(settings.database_target, course_id, 1000)
    audit_events = _cached_list_device_audit_events(
        settings.database_target,
        course_id,
        1000,
    )
    pending_enrollments = repo.list_pending_browser_enrollments(course_id=course_id)
    students = _cached_list_students(settings.database_target, course_id)
    open_alerts = [row for row in alerts if not row.get("resolved_at")]
    protected_students = sum(bool(row.get("registered_device_id")) for row in students)
    _render_metrics(
        [
            ("Open alerts", len(open_alerts), "requires review"),
            (
                "Critical",
                sum(str(row["severity"]) == "critical" for row in open_alerts),
                "blocked proxy attempts",
            ),
            ("Protected", protected_students, f"of {len(students)} students"),
            ("Pending", len(pending_enrollments), "browser approvals"),
            ("Device events", len(audit_events), "permanent audit"),
        ]
    )

    alerts_col, controls_col = st.columns([1.45, 0.55], gap="large")
    with alerts_col:
        _render_section_title("Incident log", f"{len(open_alerts)} open")
        if not alerts:
            _empty_state("No proxy incidents have been recorded.")
        else:
            st.dataframe(
                [
                    {
                        "Status": "Resolved" if row.get("resolved_at") else "Open",
                        "Severity": str(row["severity"]).title(),
                        "Date": str(row.get("attendance_date") or ""),
                        "Time": str(row["created_at"])[11:16],
                        "Student": row.get("full_name") or "Unknown",
                        "Student ID": row.get("university_id") or "",
                        "Window": row.get("schedule_label") or "",
                        "Event": str(row["alert_type"]).replace("_", " ").title(),
                        "Details": row["message"],
                    }
                    for row in alerts
                ],
                width="stretch",
                hide_index=True,
                lazy=True,
            )

    with controls_col:
        _render_section_title("Review", "Manager action")
        if open_alerts:
            alert_labels = {
                f"#{row['id']} · {row.get('university_id') or 'Unknown'} · "
                f"{str(row['alert_type']).replace('_', ' ')}": int(row["id"])
                for row in open_alerts
            }
            with st.form(f"resolve_alert_{course_id}", border=True):
                selected_alert = st.selectbox("Open incident", list(alert_labels))
                resolve_alert = st.form_submit_button("Mark resolved", width="stretch")
            if resolve_alert:
                repo.resolve_proxy_alert(
                    alert_id=alert_labels[selected_alert],
                    resolved_at=now_in_app_timezone(settings).isoformat(),
                )
                _invalidate_read_caches()
                st.rerun(scope="fragment")
        else:
            st.info("No open incidents.")

        _render_section_title("Browser enrollment", "Physical identity check")
        if pending_enrollments:
            pending_labels = {
                f"#{row['id']} · {row['university_id']} · {row['full_name']}": int(row["id"])
                for row in pending_enrollments
            }
            with st.form(f"pending_browser_enrollment_{course_id}", border=True):
                selected_pending = st.selectbox("Pending request", list(pending_labels))
                identity_verified = st.checkbox(
                    "I verified this student's identity in person",
                )
                approve_pending = st.form_submit_button(
                    "Approve browser",
                    type="primary",
                    width="stretch",
                )
                reject_pending = st.form_submit_button(
                    "Reject request",
                    width="stretch",
                )
            actor_identifier = str(
                (st.session_state.get("manager_auth") or {}).get("username", "manager")
            )
            if approve_pending:
                if not identity_verified:
                    st.error("Confirm that you verified the student in person before approval.")
                else:
                    try:
                        repo.approve_pending_browser_enrollment(
                            pending_id=pending_labels[selected_pending],
                            actor_identifier=actor_identifier,
                            reviewed_at=now_in_app_timezone(settings).isoformat(),
                        )
                        _invalidate_read_caches()
                        st.session_state["manager_notice"] = "Registered browser approved."
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))
            if reject_pending:
                if repo.reject_pending_browser_enrollment(
                    pending_id=pending_labels[selected_pending],
                    actor_identifier=actor_identifier,
                    reviewed_at=now_in_app_timezone(settings).isoformat(),
                ):
                    _invalidate_read_caches()
                    st.session_state["manager_notice"] = "Browser enrollment rejected."
                    st.rerun()
        else:
            st.info("No browser enrollment requests are waiting for approval.")

        protected = [row for row in students if row.get("registered_device_id")]
        _render_section_title("Registered device", "Reset access")
        if protected:
            student_labels = {
                f"{row['university_id']} · {row['full_name']}": int(row["id"])
                for row in protected
            }
            with st.form(f"reset_device_{course_id}", border=True):
                selected_student = st.selectbox("Student", list(student_labels))
                reset_device = st.form_submit_button("Reset device", width="stretch")
            if reset_device:
                try:
                    reset_student_device(
                        repo,
                        settings,
                        student_id=student_labels[selected_student],
                        course_id=course_id,
                        actor_identifier=str(
                            (st.session_state.get("manager_auth") or {}).get(
                                "username",
                                "manager",
                            )
                        ),
                    )
                    _invalidate_read_caches()
                    st.session_state["manager_notice"] = "Student device reset."
                    st.rerun()
                except Exception as error:
                    st.error(str(error))
        else:
            st.info("No registered devices.")

    _render_section_title("Device history", f"{len(audit_events)} permanent events")
    if audit_events:
        st.dataframe(
            [
                {
                    "Date": str(row["created_at"])[:10],
                    "Time": str(row["created_at"])[11:16],
                    "Student": row["student_name"],
                    "Student ID": row["university_id"],
                    "Event": str(row["event_type"]).replace("_", " ").title(),
                    "Actor": row["actor_identifier"],
                    "Course": row.get("course_code") or "",
                    "Previous device": str(row["previous_device_id"])
                    if row.get("previous_device_id") is not None
                    else "",
                    "New device": str(row["new_device_id"])
                    if row.get("new_device_id") is not None
                    else "",
                }
                for row in audit_events
            ],
            width="stretch",
            hide_index=True,
            lazy=True,
        )
    else:
        _empty_state("No device changes have been recorded.")


@st.fragment
def _render_manager_reports(repo: AttendanceRepository, settings, course) -> None:
    _render_page_head(
        "Course records",
        "Reports",
        "Complete course, attendance, and security export.",
        settings,
    )
    if course is None:
        _empty_state("Select a course to generate reports.")
        return
    _render_course_strip(repo, course)
    course_id = int(course["id"])
    students = _cached_list_students(settings.database_target, course_id)
    schedules = _cached_list_schedules(settings.database_target, course_id)
    attendance_records = _cached_report_attendance(
        settings.database_target,
        course_id,
    )
    security_alerts = _cached_report_security_alerts(settings.database_target, course_id)
    device_audit_events = _cached_report_device_audit(settings.database_target, course_id)
    otp_activity = _cached_report_otp_activity(settings.database_target, course_id)
    attendance_counts = _cached_attendance_counts(settings.database_target, course_id)
    eligibility_rows = _cached_eligibility_rows(
        database_target=settings.database_target,
        timezone_name=settings.app_timezone,
        course=course,
        students=students,
        schedules=schedules,
        attendance_counts=attendance_counts,
    )
    denied = sum(row["Status"] == "Not eligible" for row in eligibility_rows)
    _render_metrics(
        [
            ("Students", len(students), "in this report"),
            ("Eligible", len(students) - denied, "exam entry"),
            ("Not eligible", denied, "absence threshold"),
            ("Windows", len(schedules), "weekly timetable"),
        ]
    )
    report_col, restore_col = st.columns([1.25, 0.75], gap="large")
    with report_col:
        _render_section_title("Eligibility", f"{len(eligibility_rows)} students")
        if eligibility_rows:
            st.dataframe(eligibility_rows, width="stretch", hide_index=True, lazy=True)
        else:
            _empty_state("No students are available for reporting.")
        report_bytes = _cached_course_report(
            course=course,
            students=students,
            schedules=schedules,
            attendance_records=attendance_records,
            eligibility_rows=eligibility_rows,
            security_alerts=security_alerts,
            device_audit_events=device_audit_events,
            otp_activity=otp_activity,
            timezone_name=settings.app_timezone,
        )
        st.download_button(
            "Download complete Excel report",
            data=report_bytes,
            file_name=f"{course['code']}_complete_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            on_click="ignore",
        )
    with restore_col:
        _render_section_title("Restore", "Excel workbook")
        restore_file = st.file_uploader(
            "Attendance workbook",
            type=["xlsx"],
            key=f"restore_{course['id']}",
            label_visibility="collapsed",
        )
        if restore_file is not None and st.button(
            "Restore workbook", key=f"restore_button_{course['id']}", width="stretch"
        ):
            try:
                result = import_attendance_report_bytes(
                    repo=repo,
                    settings=settings,
                    source_name=restore_file.name,
                    content=restore_file.getvalue(),
                )
                _invalidate_read_caches()
                st.session_state["pending_manager_course_code"] = str(result["course_code"])
                st.session_state["manager_notice"] = f"{result['course_code']} restored."
                st.rerun()
            except Exception as error:
                st.error(str(error))


def _render_student_entry(repo: AttendanceRepository, settings) -> None:
    st.markdown(STUDENT_RTL_CSS, unsafe_allow_html=True)
    if st.session_state.get("student_auth") is None:
        _render_student_access(repo, settings)
        return
    _render_student_portal(repo, settings)


@st.fragment
def _render_student_access(repo: AttendanceRepository, settings) -> None:
    _apply_pending_student_id_reset()
    _render_topbar(settings, context="بوابة الطالب", arabic=True)
    _left, center, _right = st.columns([0.2, 1, 0.2], gap="large")
    with center:
        notice = st.session_state.pop("student_access_notice", None)
        if notice:
            st.warning(_student_message(notice))
        _render_page_head(
            "دخول الطالب",
            "تسجيل الحضور",
            "أدخل رقمك الجامعي ثم تحقق من موقع القاعة.",
            settings,
            arabic=True,
        )
        delivery_error = otp_delivery_configuration_error(settings)
        if delivery_error:
            st.warning(_student_message(delivery_error))

        access_context = st.session_state.get("student_access_context")
        if access_context is None:
            with st.container(border=True):
                university_id = st.text_input(
                    "الرقم الجامعي",
                    key="pending_university_id",
                    placeholder="أدخل الرقم الجامعي",
                )
                student_geo = geo_capture(
                    "التحقق من موقع القاعة",
                    key="student_access_location",
                )
                _handle_student_access_location(student_geo, repo, settings, university_id)
        else:
            _render_access_card(access_context)
            if (
                access_context["device_enrolled"]
                and st.session_state.get("student_passkey_verified") is None
            ):
                _render_student_device_verification_step(
                    repo,
                    settings,
                    access_context,
                )
                if st.button("استخدام رقم جامعي آخر", key="reset_student_access", width="stretch"):
                    _reset_student_access(clear_id=True)
                    st.rerun(scope="fragment")
            elif not st.session_state.get("student_otp_requested", False):
                if not access_context["device_enrolled"]:
                    _render_student_credential_capability(access_context)
                if st.button("إرسال رمز التحقق", key="request_student_otp", type="primary", width="stretch"):
                    _request_student_otp(repo, settings, access_context)
                if st.button("استخدام رقم جامعي آخر", key="reset_student_access", width="stretch"):
                    _reset_student_access(clear_id=True)
                    st.rerun(scope="fragment")
            elif not st.session_state.get("student_otp_verified", False):
                notice = st.session_state.get("student_otp_notice")
                if notice:
                    st.success(_student_message(notice))
                preview = st.session_state.get("student_otp_preview_code")
                if preview:
                    st.markdown(f'<div class="cp-code">{escape(preview)}</div>', unsafe_allow_html=True)
                with st.form("student_otp_form", border=True):
                    code = st.text_input("رمز التحقق", max_chars=6, placeholder="000000")
                    verify = st.form_submit_button("متابعة", type="primary", width="stretch")
                if verify:
                    _verify_student_otp(repo, settings, access_context, code)
                if st.button("البدء من جديد", key="student_start_again", width="stretch"):
                    _reset_student_access(clear_id=True)
                    st.rerun(scope="fragment")
            else:
                _render_student_device_registration_step(repo, settings, access_context)
                if st.button("البدء من جديد", key="student_registration_restart", width="stretch"):
                    _reset_student_access(clear_id=True)
                    st.rerun(scope="fragment")

        if st.button("رجوع", key="student_access_back", width="stretch"):
            _reset_student_access(clear_id=True)
            st.session_state["active_role"] = None
            st.rerun()


def _render_student_portal(repo: AttendanceRepository, settings) -> None:
    auth = st.session_state.get("student_auth") or {}
    try:
        course, student, active_schedule = resolve_active_student_session(
            repo,
            settings,
            auth=auth,
        )
    except ValueError:
        _expire_student_session()
        st.rerun()

    _render_topbar(settings, context=f"{course['code']} · {student['full_name']}", arabic=True)
    section = _normalize_state_choice("student_section", STUDENT_SECTIONS)
    nav_col, exit_col = st.columns([1, 0.16], gap="small")
    with nav_col:
        selected = st.pills(
            "تنقل الطالب",
            STUDENT_SECTIONS,
            key="student_section",
            format_func=lambda value: STUDENT_SECTION_LABELS[value],
            label_visibility="collapsed",
            width="stretch",
        )
        section = selected or STUDENT_SECTIONS[0]
    with exit_col:
        if st.button("خروج", key="student_exit", width="stretch"):
            _sign_out_student()
            st.rerun()

    if section == "Check in":
        _render_student_check_in(repo, settings, course, student, active_schedule)
    elif section == "Status":
        _render_student_status(repo, settings, course, student, active_schedule)
    else:
        _render_student_history(repo, settings, course, student)


@st.fragment
def _render_student_check_in(repo, settings, course, student, active_schedule) -> None:
    auth = st.session_state.get("student_auth") or {}
    try:
        course, student, active_schedule = resolve_active_student_session(
            repo,
            settings,
            auth=auth,
        )
    except ValueError:
        _expire_student_session()
        st.rerun()
    _render_page_head(
        "نافذة الحضور",
        "تسجيل الحضور",
        f"{course['code']} · {course['title']}",
        settings,
        arabic=True,
    )
    if active_schedule is None:
        _closed_check_in(repo, settings, course)
        return

    st.markdown(
        f"""
        <div class="cp-access-card" lang="ar" dir="rtl">
            <span class="cp-eyebrow">نافذة الحضور متاحة</span>
            <h3><bdi>{escape(str(active_schedule['label']))}</bdi></h3>
            <p class="cp-ltr">{escape(str(active_schedule['start_time']))}–{escape(str(active_schedule['end_time']))}</p>
            <div class="cp-access-grid">
                <div><span>المقرر</span><strong class="cp-ltr">{escape(str(course['code']))}</strong></div>
                <div><span>الطالب</span><strong class="cp-ltr">{escape(str(student['university_id']))}</strong></div>
                <div><span>النطاق</span><strong><bdi>{float(course['radius_m']):.0f} متر</bdi></strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    check_col, info_col = st.columns([1, 0.65], gap="large")
    with check_col:
        _render_section_title("تأكيد الموقع", "مطلوب")
        stamp_geo = geo_capture(
            "تحديد موقعي الحالي",
            key="student_stamp_location",
        )
        _handle_stamp_location(stamp_geo)
        if st.session_state.get("student_stamp_geolocation") is not None and st.button(
            "تسجيل الحضور",
            key="submit_attendance",
            type="primary",
            width="stretch",
        ):
            result = stamp_attendance(
                repo,
                settings,
                course=course,
                student=student,
                geolocation_payload=st.session_state["student_stamp_geolocation"],
                verified_device={
                    "device_id": auth.get("device_id"),
                    "credential_id": auth.get("credential_id"),
                    "device_binding_hash": auth.get("device_binding_hash"),
                    "schedule_id": auth.get("schedule_id"),
                    "attendance_date": auth.get("attendance_date"),
                    "session_expires_at": auth.get("session_expires_at"),
                },
            )
            st.session_state["student_stamp_result"] = {
                "success": result.success,
                "message": result.message,
            }
            if result.success:
                _invalidate_read_caches()
                st.session_state["student_stamp_geolocation"] = None
            st.rerun()
        result = st.session_state.get("student_stamp_result")
        if result:
            css_class = "cp-result-ok" if result["success"] else "cp-result-bad"
            st.markdown(
                f'<div class="{css_class}">{escape(_student_message(result["message"]))}</div>',
                unsafe_allow_html=True,
            )
    with info_col:
        _render_section_title("اليوم", "الحالة الحالية")
        existing = _cached_attendance_exists(
            settings.database_target,
            int(course["id"]),
            int(student["id"]),
            int(active_schedule["id"]),
            now_in_app_timezone(settings).date().isoformat(),
        )
        _render_metrics(
            [
                ("الحالة", "حاضر" if existing else "بانتظار التسجيل", active_schedule["label"]),
                ("ينتهي", active_schedule["end_time"], settings.app_timezone),
            ],
            compact=True,
        )


def _render_student_status(repo, settings, course, student, active_schedule) -> None:
    _render_page_head(
        "حالة المقرر",
        "الحالة",
        f"{course['code']} · {student['full_name']}",
        settings,
        arabic=True,
    )
    course_id = int(course["id"])
    schedules = _cached_list_schedules(settings.database_target, course_id)
    attendance_counts = _cached_attendance_counts(settings.database_target, course_id)
    summary = build_student_attendance_summary(
        repo,
        settings,
        course=course,
        student=student,
        schedules=schedules,
        attended_count=attendance_counts.get(int(student["id"]), 0),
    )
    _render_metrics(
        [
            ("مرات الحضور", summary.attended_count, "محاضرات موثقة"),
            ("الغيابات", summary.absences, "من المحاضرات المنتهية"),
            ("المحاضرات", summary.total_meetings, "إجمالي المقرر"),
            (
                "أهلية الاختبار",
                "غير مؤهل" if summary.denied_exam_entry else "مؤهل",
                f"حد الغياب {summary.absence_threshold}",
            ),
        ]
    )
    _render_section_title(
        "تقدم الحضور",
        f"{summary.attendance_pct_of_total:.0f}% من المقرر",
    )
    st.progress(min(max(summary.attendance_pct_of_total / 100, 0.0), 1.0))
    if summary.denied_exam_entry:
        st.error("تم بلوغ حد الغياب.")
    elif active_schedule is not None:
        st.success(f"نافذة {active_schedule['label']} متاحة الآن.")
    else:
        st.info("لا توجد نافذة حضور متاحة الآن.")


def _render_student_history(repo, settings, course, student) -> None:
    _render_page_head(
        "السجل الموثق",
        "سجل الحضور",
        f"{course['code']} · {student['full_name']}",
        settings,
        arabic=True,
    )
    records = _cached_list_student_attendance(
        settings.database_target,
        int(course["id"]),
        int(student["id"]),
        1000,
    )
    if not records:
        _empty_state("لا توجد سجلات حضور حتى الآن.")
        return
    st.dataframe(
        [
            {
                "التاريخ": row["attendance_date"],
                "المحاضرة": row["schedule_label"],
                "الوقت": str(row["stamped_at"])[11:16],
                "المسافة": f"{float(row['distance_m']):.2f} متر",
            }
            for row in records
        ],
        width="stretch",
        hide_index=True,
        lazy=True,
    )


def _closed_check_in(repo, settings, course) -> None:
    schedules = _cached_list_schedules(settings.database_target, int(course["id"]))
    now = now_in_app_timezone(settings)
    upcoming = []
    for day_offset in range(8):
        candidate = now.date() + timedelta(days=day_offset)
        for schedule in schedules:
            if int(schedule["weekday"]) != candidate.weekday():
                continue
            if day_offset == 0 and parse_hhmm(str(schedule["start_time"])) <= now.time():
                continue
            upcoming.append((candidate, schedule))
        if upcoming:
            break
    st.markdown(
        """
        <div class="cp-result-bad">تسجيل الحضور مغلق الآن. يمكنك مراجعة الحالة والسجل.</div>
        """,
        unsafe_allow_html=True,
    )
    if upcoming:
        next_date, next_schedule = min(
            upcoming,
            key=lambda item: str(item[1]["start_time"]),
        )
        _render_metrics(
            [
                ("النافذة التالية", next_schedule["label"], _arabic_weekday(next_date.weekday())),
                ("تبدأ", next_schedule["start_time"], _arabic_short_date(next_date)),
            ],
            compact=True,
        )


def _render_topbar(settings, *, context: str, arabic: bool = False) -> None:
    now = now_in_app_timezone(settings)
    language_attributes = ' lang="ar" dir="rtl"' if arabic else ""
    timestamp = (
        f"{_arabic_weekday(now.weekday())} · {now.day:02d} "
        f"{ARABIC_MONTHS[now.month - 1]} {now.year} · {now.strftime('%H:%M')}"
        if arabic
        else now.strftime("%a · %d %b %Y · %H:%M")
    )
    st.markdown(
        f"""
        <header class="cp-topbar"{language_attributes}>
            <div class="cp-brand">
                <div class="cp-mark">CP</div>
                <div><strong>ClassPresence</strong><span><bdi>{escape(context)}</bdi></span></div>
            </div>
            <div class="cp-top-meta"><bdi>{escape(timestamp)}</bdi><br><bdi>{escape(settings.app_timezone)}</bdi></div>
        </header>
        """,
        unsafe_allow_html=True,
    )


def _render_page_head(
    kicker: str,
    title: str,
    description: str,
    settings=None,
    *,
    arabic: bool = False,
) -> None:
    date_block = ""
    if settings is not None:
        now = now_in_app_timezone(settings)
        weekday = _arabic_weekday(now.weekday()) if arabic else now.strftime("%A")
        date_label = (
            f"{now.day:02d} {ARABIC_MONTHS[now.month - 1]} {now.year}"
            if arabic
            else now.strftime("%d %B %Y")
        )
        date_block = f'<div class="cp-date-block"><bdi>{escape(weekday)}</bdi><br><bdi>{escape(date_label)}</bdi></div>'
    description_html = f'<p dir="auto">{escape(description)}</p>' if description else ""
    language_attributes = ' lang="ar" dir="rtl"' if arabic else ""
    st.markdown(
        f"""
        <section class="cp-page-head"{language_attributes}>
            <div><span class="cp-eyebrow">{escape(kicker)}</span><h1>{escape(title)}</h1>{description_html}</div>
            {date_block}
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_metrics(items, *, compact: bool = False) -> None:
    size_class = " compact" if compact else ""
    cells = "".join(
        f'<div class="cp-metric"><span>{escape(str(label))}</span>'
        f'<strong><bdi>{escape(str(value))}</bdi></strong>'
        f'<small><bdi>{escape(str(detail))}</bdi></small></div>'
        for label, value, detail in items
    )
    st.markdown(
        f'<div class="cp-metrics{size_class}">{cells}</div>',
        unsafe_allow_html=True,
    )


def _render_section_title(title: str, meta: str) -> None:
    st.markdown(
        f'<div class="cp-section-title"><h2>{escape(title)}</h2><span>{escape(meta)}</span></div>',
        unsafe_allow_html=True,
    )


def _empty_state(message: str) -> None:
    st.markdown(f'<div class="cp-empty-state">{escape(message)}</div>', unsafe_allow_html=True)


def _arabic_weekday(weekday: int) -> str:
    return ARABIC_WEEKDAYS[weekday]


def _arabic_short_date(value: date) -> str:
    return f"{value.day:02d} {ARABIC_MONTHS[value.month - 1]}"


def _student_message(message: object) -> str:
    text = str(message).strip()
    if any("\u0600" <= character <= "\u06ff" for character in text):
        return text
    translated = STUDENT_MESSAGE_TRANSLATIONS.get(text)
    if translated:
        return translated
    if text.startswith("A one-time code has been sent to "):
        recipient = text.removeprefix("A one-time code has been sent to ").rstrip(".")
        return f"تم إرسال رمز التحقق إلى {recipient}."
    if text.startswith("Attendance stamped successfully"):
        return "تم تسجيل حضورك بنجاح."
    if text.startswith("You are not in class"):
        return "أنت خارج نطاق القاعة المسموح به."
    if text.startswith("Location accuracy must be within"):
        return "دقة الموقع غير كافية. اقترب من نافذة ثم أعد المحاولة."
    if text.startswith("No class is active for your student ID"):
        return "لا توجد محاضرة متاحة لهذا الرقم الجامعي الآن."
    if text.startswith(("Unsupported OTP delivery mode", "Email OTP is enabled")):
        return "خدمة رمز التحقق غير مهيأة. تواصل مع المسؤول."
    return "تعذر إكمال الطلب. حاول مرة أخرى."


def _render_course_strip(repo: AttendanceRepository, course) -> None:
    course_id = int(course["id"])
    students = _cached_list_students(repo.database_target, course_id)
    schedules = _cached_list_schedules(repo.database_target, course_id)
    records = _cached_list_course_attendance(repo.database_target, course_id, 10000)
    st.markdown(
        f"""
        <div class="cp-course-strip">
            <div><strong>{escape(str(course['code']))} · {escape(str(course['title']))}</strong><br>
            <span>{escape(str(course['start_date']))} — {escape(str(course['end_date'] or course['start_date']))}</span></div>
            <div class="cp-course-tags">
                <b>{len(students)} students</b><b>{len(schedules)} windows</b><b>{len(records)} stamps</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_week_board(settings, schedules) -> None:
    now = now_in_app_timezone(settings)
    day_cards = []
    for day_name, weekday in TIMETABLE_DAY_COLUMNS:
        daily = [row for row in schedules if int(row["weekday"]) == weekday]
        slots = []
        for row in daily:
            live = weekday == now.weekday() and parse_hhmm(str(row["start_time"])) <= now.time() <= parse_hhmm(str(row["end_time"]))
            live_class = " live" if live else ""
            slots.append(
                f'<div class="cp-slot{live_class}"><strong>{escape(str(row["label"]))}</strong>'
                f'<span>{escape(str(row["start_time"]))}–{escape(str(row["end_time"]))}</span></div>'
            )
        today_class = " today" if weekday == now.weekday() else ""
        content = "".join(slots) or '<span class="cp-empty">No lectures</span>'
        day_cards.append(
            f'<div class="cp-day{today_class}"><h4>{escape(day_name)}<span>{len(daily):02d}</span></h4>{content}</div>'
        )
    st.markdown(f'<div class="cp-week">{"".join(day_cards)}</div>', unsafe_allow_html=True)


def _today_sessions(repo, settings, courses) -> list[dict]:
    now = now_in_app_timezone(settings)
    rows = []
    for course in courses:
        if not _course_is_active(course, now.date()):
            continue
        course_id = int(course["id"])
        roster = _cached_list_students(settings.database_target, course_id)
        attendance = _cached_list_course_attendance(
            settings.database_target,
            course_id,
            10000,
        )
        for schedule in _cached_list_schedules(settings.database_target, course_id):
            if int(schedule["weekday"]) != now.weekday():
                continue
            start = parse_hhmm(str(schedule["start_time"]))
            end = parse_hhmm(str(schedule["end_time"]))
            status = "Live" if start <= now.time() <= end else "Upcoming" if now.time() < start else "Complete"
            checked_in = sum(
                str(row["attendance_date"]) == now.date().isoformat()
                and str(row["schedule_label"]) == str(schedule["label"])
                for row in attendance
            )
            rows.append(
                {
                    "status": status,
                    "course": str(course["code"]),
                    "title": str(course["title"]),
                    "label": str(schedule["label"]),
                    "start": str(schedule["start_time"]),
                    "end": str(schedule["end_time"]),
                    "checked_in": checked_in,
                    "roster": len(roster),
                }
            )
    status_order = {"Live": 0, "Upcoming": 1, "Complete": 2}
    return sorted(rows, key=lambda row: (status_order[row["status"]], row["start"], row["course"]))


def _build_timetable_editor_rows(schedules, *, show_default_rows: bool) -> list[dict[str, object]]:
    rows_by_label: dict[str, dict[str, object]] = {}
    ordered_labels: list[str] = []
    if show_default_rows:
        for template in DEFAULT_TIMETABLE_ROWS:
            label = str(template["label"])
            rows_by_label[label] = _empty_timetable_row(
                label, str(template["start_time"]), str(template["end_time"])
            )
            ordered_labels.append(label)
    for schedule in schedules:
        label = str(schedule["label"])
        if label not in rows_by_label:
            rows_by_label[label] = _empty_timetable_row(
                label, str(schedule["start_time"]), str(schedule["end_time"])
            )
            ordered_labels.append(label)
        row = rows_by_label[label]
        row["start_time"] = str(schedule["start_time"])
        row["end_time"] = str(schedule["end_time"])
        row[weekday_label(int(schedule["weekday"]))] = True
    return [rows_by_label[label] for label in ordered_labels]


def _empty_timetable_row(label: str, start_time: str, end_time: str) -> dict[str, object]:
    row: dict[str, object] = {
        "label": label,
        "start_time": start_time,
        "end_time": end_time,
    }
    for day_name, _ in TIMETABLE_DAY_COLUMNS:
        row[day_name] = False
    return row


def _save_timetable(repo, settings, course_id: int, edited_rows) -> None:
    rows = _coerce_editor_rows(edited_rows)
    schedule_rows = []
    labels = set()
    for row in rows:
        label = str(row.get("label", "") or "").strip()
        start_text = str(row.get("start_time", "") or "").strip()
        end_text = str(row.get("end_time", "") or "").strip()
        selected_days = [(name, index) for name, index in TIMETABLE_DAY_COLUMNS if bool(row.get(name, False))]
        if not label and not start_text and not end_text and not selected_days:
            continue
        if not selected_days:
            continue
        if not label or not start_text or not end_text:
            st.error("Every active row needs a window name, start time, and end time.")
            return
        if label in labels:
            st.error("Window names must be unique.")
            return
        try:
            start = parse_hhmm(start_text)
            end = parse_hhmm(end_text)
        except ValueError:
            st.error(f"Use 24-hour time for {label}, for example 09:30.")
            return
        if end <= start:
            st.error(f"The end time for {label} must be later than the start time.")
            return
        labels.add(label)
        for _, weekday in selected_days:
            schedule_rows.append(
                {
                    "weekday": weekday,
                    "label": label,
                    "start_time": start.strftime("%H:%M"),
                    "end_time": end.strftime("%H:%M"),
                }
            )
    try:
        repo.sync_course_schedules(
            course_id=course_id,
            schedule_rows=schedule_rows,
            created_at=now_in_app_timezone(settings).isoformat(),
        )
        _invalidate_read_caches()
        st.session_state[f"show_templates_{course_id}"] = False
        st.session_state[f"timetable_version_{course_id}"] = st.session_state.get(
            f"timetable_version_{course_id}", 0
        ) + 1
        st.session_state["manager_notice"] = "Timetable saved."
        st.rerun()
    except Exception as error:
        st.error(str(error))


def _coerce_editor_rows(edited_rows) -> list[dict[str, object]]:
    if edited_rows is None:
        return []
    to_dict = getattr(edited_rows, "to_dict", None)
    if callable(to_dict):
        try:
            return [dict(row) for row in to_dict(orient="records")]
        except TypeError:
            pass
    to_pylist = getattr(edited_rows, "to_pylist", None)
    if callable(to_pylist):
        return [dict(row) for row in to_pylist()]
    return [dict(row) for row in edited_rows]


def _create_live_test_window(repo, settings, course_id: int) -> None:
    now = now_in_app_timezone(settings).replace(second=0, microsecond=0)
    ends_at = min(now + timedelta(hours=2), now.replace(hour=23, minute=59))
    try:
        repo.add_schedule(
            course_id=course_id,
            weekday=now.weekday(),
            label=f"Test {now.strftime('%H:%M')}",
            start_time=now.strftime("%H:%M"),
            end_time=ends_at.strftime("%H:%M"),
            created_at=now.isoformat(),
        )
        _invalidate_read_caches()
        st.session_state["manager_notice"] = "Test window opened."
        st.rerun()
    except Exception as error:
        st.error(str(error))


def _save_course(
    repo,
    settings,
    *,
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
        st.error("End date must be on or after the start date.")
        return
    if not _has_course_location():
        st.error("Select the classroom location before saving.")
        return
    existing_code = repo.get_course_by_code(normalized_code)
    if existing_code is not None and int(existing_code["id"]) != int(existing_course_id or 0):
        st.error("Another course already uses this code.")
        return
    latitude = float(st.session_state["course_latitude"])
    longitude = float(st.session_state["course_longitude"])
    try:
        if existing_course_id is None:
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
        _invalidate_read_caches()
        st.session_state["pending_manager_course_code"] = normalized_code
        st.session_state["course_editor_mode"] = "existing"
        st.session_state["loaded_course_location"] = None
        st.session_state["manager_notice"] = f"{normalized_code} saved."
        st.rerun()
    except Exception as error:
        st.error(str(error))


def _handle_course_location(payload) -> None:
    if not payload:
        return
    captured_at = payload.get("captured_at")
    if captured_at == st.session_state.get("course_location_processed"):
        return
    st.session_state["course_location_processed"] = captured_at
    if payload.get("error"):
        st.error(str(payload["error"]))
        return
    st.session_state["course_latitude"] = float(payload["latitude"])
    st.session_state["course_longitude"] = float(payload["longitude"])
    st.session_state["course_location_selected"] = True
    st.rerun(scope="fragment")


def _sync_course_location(course) -> None:
    signature = "new" if course is None else f"{course['id']}:{course['latitude']}:{course['longitude']}"
    if st.session_state.get("loaded_course_location") == signature:
        return
    _reset_course_location(course)
    st.session_state["loaded_course_location"] = signature


def _reset_course_location(course) -> None:
    st.session_state["course_latitude"] = 0.0 if course is None else float(course["latitude"])
    st.session_state["course_longitude"] = 0.0 if course is None else float(course["longitude"])
    st.session_state["course_location_selected"] = course is not None
    st.session_state["loaded_course_location"] = None


def _has_course_location() -> bool:
    return bool(st.session_state.get("course_location_selected", False))


def _render_access_card(context: dict) -> None:
    st.markdown(
        f"""
        <div class="cp-access-card" lang="ar" dir="rtl">
            <span class="cp-eyebrow">تم التحقق من الوصول</span>
            <h3><bdi>{escape(str(context['course_code']))} · {escape(str(context['schedule_label']))}</bdi></h3>
            <p><bdi>{escape(str(context['student_name']))}</bdi></p>
            <div class="cp-access-grid">
                <div><span>النافذة</span><strong class="cp-ltr">{escape(str(context['schedule_start_time']))}–{escape(str(context['schedule_end_time']))}</strong></div>
                <div><span>المسافة</span><strong><bdi>{float(context['distance_m']):.1f} متر</bdi></strong></div>
                <div><span>النطاق</span><strong><bdi>{float(context['radius_m']):.0f} متر</bdi></strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _handle_student_access_location(payload, repo, settings, university_id: str) -> None:
    if not payload:
        return
    captured_at = payload.get("captured_at")
    if captured_at == st.session_state.get("student_access_processed"):
        return
    st.session_state["student_access_processed"] = captured_at
    if not university_id.strip():
        st.error("أدخل الرقم الجامعي أولاً.")
        return
    try:
        context = resolve_student_access_context(
            repo,
            settings,
            university_id=university_id.strip(),
            geolocation_payload=payload,
        )
        st.session_state["student_access_context"] = context.__dict__.copy()
        st.session_state["student_otp_requested"] = False
        st.session_state["student_otp_verified"] = False
        st.session_state["student_passkey_verified"] = None
        st.session_state["student_passkey_operation"] = None
        st.session_state["student_passkey_processed"] = None
        st.session_state["student_passkey_error"] = None
        st.session_state["student_browser_key_operation"] = None
        st.session_state["student_browser_key_processed"] = None
        st.session_state["student_browser_key_error"] = None
        st.session_state["student_pending_enrollment_id"] = None
        st.session_state["student_registration_method"] = None
        st.session_state["student_credential_capability"] = None
        st.session_state["student_credential_capability_operation"] = None
        st.rerun(scope="fragment")
    except Exception as error:
        st.error(_student_message(error))


def _request_student_otp(repo, settings, context: dict) -> None:
    try:
        result = request_login_code_for_access_context(
            repo,
            settings,
            access_context=StudentAccessContext(**context),
            verified_device=st.session_state.get("student_passkey_verified"),
        )
        st.session_state["student_otp_requested"] = True
        st.session_state["student_otp_notice"] = result.message
        st.session_state["student_otp_preview_code"] = result.preview_code
        st.rerun(scope="fragment")
    except Exception as error:
        st.error(_student_message(error))


def _verify_student_otp(repo, settings, context: dict, code: str) -> None:
    try:
        verified_device = st.session_state.get("student_passkey_verified")
        course, student = verify_login_code_for_access_context(
            repo,
            settings,
            course_id=int(context["course_id"]),
            student_id=int(context["student_id"]),
            code=code,
            device_binding_hash=str(context["device_binding_hash"]),
            credential_id=(
                str(verified_device["credential_id"])
                if verified_device is not None
                else None
            ),
            schedule_id=int(context["schedule_id"]),
            attendance_date=str(context["attendance_date"]),
        )
        if context["device_enrolled"]:
            _start_student_session(course, student, verified_device, context)
            st.rerun()
        st.session_state["student_otp_verified"] = True
        st.session_state["student_passkey_operation"] = None
        st.session_state["student_browser_key_operation"] = None
        st.rerun(scope="fragment")
    except Exception as error:
        st.error(_student_message(error))


def _render_student_credential_capability(context: dict) -> None:
    signature = (
        int(context["student_id"]),
        str(context["device_binding_hash"]),
    )
    capability = st.session_state.get("student_credential_capability")
    if capability is not None and tuple(capability.get("signature", ())) == signature:
        passkey_status = (
            "متاح على هذا الجهاز"
            if capability.get("platform_available")
            else "قد يحتاج إعداداً أو جهاز مصادقة خارجي"
        )
        fallback_status = (
            "متاح بموافقة المسؤول"
            if capability.get("browser_key_supported")
            else "غير متاح في هذا المتصفح"
        )
        st.caption(f"مفتاح المرور: {passkey_status} · تسجيل المتصفح البديل: {fallback_status}")
        return

    operation = st.session_state.get("student_credential_capability_operation")
    if operation is None or tuple(operation.get("signature", ())) != signature:
        operation = {"id": uuid4().hex, "signature": signature}
        st.session_state["student_credential_capability_operation"] = operation
    payload = passkey_action(
        action="capability",
        options_json="{}",
        operation_id=operation["id"],
        key=f"student_credential_capability_{operation['id']}",
    )
    if not payload or payload.get("operation_id") != operation["id"]:
        return
    st.session_state["student_credential_capability"] = {
        "signature": signature,
        "passkey_supported": bool(payload.get("passkey_supported")),
        "platform_available": bool(payload.get("platform_available")),
        "browser_key_supported": bool(payload.get("browser_key_supported")),
    }
    st.rerun(scope="fragment")


def _render_student_device_verification_step(repo, settings, context: dict) -> None:
    device = repo.get_registered_device_for_student(int(context["student_id"]))
    if device is None:
        st.error(_student_message("No registered device was found for this student."))
        return
    if str(device.get("auth_method") or "passkey") == "browser_key":
        _render_student_browser_key_step(repo, settings, context, action="authenticate")
        return
    _render_student_passkey_step(repo, settings, context, action="authenticate")


def _render_student_device_registration_step(repo, settings, context: dict) -> None:
    pending_id = st.session_state.get("student_pending_enrollment_id")
    if pending_id is not None:
        pending = repo.get_pending_browser_enrollment(int(pending_id))
        if pending is None:
            st.session_state["student_pending_enrollment_id"] = None
        elif str(pending["status"]) == "approved":
            st.success("وافق المسؤول على تسجيل هذا المتصفح.")
            if st.button("متابعة باستخدام المتصفح المسجل", type="primary", width="stretch"):
                _reset_student_access(clear_id=False)
                st.session_state["student_access_notice"] = (
                    "تم تسجيل المتصفح. تحقق من الموقع مرة أخرى للمتابعة."
                )
                st.rerun(scope="fragment")
            return
        elif str(pending["status"]) == "pending":
            _render_section_title("طلب تسجيل المتصفح", "بانتظار موافقة المسؤول")
            st.info("تحقق المسؤول من هويتك حضورياً ثم يوافق على الطلب من صفحة الأمان.")
            if st.button("التحقق من حالة الموافقة", width="stretch"):
                st.rerun(scope="fragment")
            return
        else:
            st.error("انتهى طلب تسجيل المتصفح أو تم رفضه.")
            if st.button("إنشاء طلب جديد", width="stretch"):
                st.session_state["student_pending_enrollment_id"] = None
                st.session_state["student_browser_key_operation"] = None
                st.session_state["student_browser_key_processed"] = None
                st.rerun(scope="fragment")
            return

    capability = st.session_state.get("student_credential_capability") or {}
    default_method = "passkey" if capability.get("passkey_supported", True) else "browser_key"
    method = st.session_state.get("student_registration_method") or default_method
    st.session_state["student_registration_method"] = method

    if method == "browser_key":
        st.warning(
            "سيُسجل هذا المتصفح بدلاً من مفتاح المرور. يجب أن يتحقق المسؤول من هويتك "
            "ويوافق على الطلب، وسيؤدي حذف بيانات المتصفح إلى الحاجة لإعادة التعيين."
        )
        _render_student_browser_key_step(repo, settings, context, action="register")
        if st.button("المحاولة باستخدام مفتاح المرور", width="stretch"):
            st.session_state["student_registration_method"] = "passkey"
            st.session_state["student_browser_key_operation"] = None
            st.rerun(scope="fragment")
        return

    _render_student_passkey_step(repo, settings, context, action="register")
    if capability.get("browser_key_supported", True) and st.button(
        "لا يمكنني استخدام مفتاح المرور — طلب تسجيل المتصفح",
        width="stretch",
    ):
        st.session_state["student_registration_method"] = "browser_key"
        st.session_state["student_passkey_operation"] = None
        st.rerun(scope="fragment")


def _render_student_browser_key_step(repo, settings, context: dict, *, action: str) -> None:
    error = st.session_state.pop("student_browser_key_error", None)
    if error:
        st.error(_student_message(error))
    title = "التحقق من المتصفح المسجل" if action == "authenticate" else "تسجيل هذا المتصفح"
    status = "مفتاح المتصفح مطلوب" if action == "authenticate" else "يتطلب موافقة المسؤول"
    _render_section_title(title, status)
    try:
        operation = _ensure_browser_key_operation(repo, settings, context, action=action)
    except Exception as error:
        st.error(_student_message(error))
        return
    component_action = "browser_authenticate" if action == "authenticate" else "browser_register"
    payload = passkey_action(
        action=component_action,
        options_json=operation["options_json"],
        operation_id=operation["id"],
        key=f"student_browser_key_{operation['id']}",
    )
    if not payload or payload.get("operation_id") != operation["id"]:
        return
    if st.session_state.get("student_browser_key_processed") == operation["id"]:
        return
    st.session_state["student_browser_key_processed"] = operation["id"]
    if payload.get("error"):
        st.session_state["student_browser_key_error"] = str(payload["error"])
        st.session_state["student_browser_key_operation"] = None
        st.rerun(scope="fragment")
    try:
        if action == "authenticate":
            verified_device = authenticate_student_browser_key(
                repo,
                settings,
                access_context=StudentAccessContext(**context),
                credential_id=str(payload["credential_id"]),
                signature=str(payload["signature"]),
                message=operation["message"],
                device_token=str(payload["device_token"]),
            )
            st.session_state["student_passkey_verified"] = verified_device
            st.session_state["student_browser_key_operation"] = None
            st.rerun(scope="fragment")

        pending_id = request_student_browser_key_enrollment(
            repo,
            settings,
            access_context=StudentAccessContext(**context),
            credential_id=str(payload["credential_id"]),
            public_key=str(payload["public_key"]),
            device_token=str(payload["device_token"]),
        )
        st.session_state["student_pending_enrollment_id"] = pending_id
        st.session_state["student_browser_key_operation"] = None
        _invalidate_read_caches()
        st.rerun(scope="fragment")
    except Exception as error:
        st.session_state["student_browser_key_error"] = str(error)
        st.session_state["student_browser_key_operation"] = None
        st.rerun(scope="fragment")


def _ensure_browser_key_operation(repo, settings, context: dict, *, action: str) -> dict:
    rp_id, _origin = _passkey_relying_party(settings)
    signature = (
        action,
        int(context["student_id"]),
        str(context["device_binding_hash"]),
        int(context["schedule_id"]),
        str(context["attendance_date"]),
        rp_id,
    )
    existing = st.session_state.get("student_browser_key_operation")
    if existing is not None and tuple(existing.get("signature", ())) == signature:
        return existing
    if action == "authenticate":
        device = repo.get_registered_device_for_student(int(context["student_id"]))
        if device is None:
            raise ValueError("No registered device was found for this student.")
        if str(device.get("auth_method") or "passkey") != "browser_key":
            raise ValueError("This student must verify using the registered passkey.")
        credential_id = str(device["credential_id"])
        options_json, challenge = build_browser_key_options(
            rp_id=rp_id,
            student_id=int(context["student_id"]),
            course_id=int(context["course_id"]),
            schedule_id=int(context["schedule_id"]),
            attendance_date=str(context["attendance_date"]),
            credential_id=credential_id,
        )
        message = str(json.loads(options_json)["message"])
    else:
        options_json, challenge, message = "{}", "", ""
    operation = {
        "id": uuid4().hex,
        "signature": signature,
        "action": action,
        "options_json": options_json,
        "challenge": challenge,
        "message": message,
    }
    st.session_state["student_browser_key_operation"] = operation
    return operation


def _render_student_passkey_step(repo, settings, context: dict, *, action: str) -> None:
    error = st.session_state.pop("student_passkey_error", None)
    if error:
        st.error(_student_message(error))
    title = "التحقق من الجهاز المسجل" if action == "authenticate" else "تسجيل هذا الجهاز"
    status = "مفتاح المرور مطلوب" if action == "authenticate" else "إعداد لمرة واحدة"
    _render_section_title(title, status)

    try:
        operation = _ensure_passkey_operation(repo, settings, context, action=action)
    except Exception as error:
        st.error(_student_message(error))
        return

    payload = passkey_action(
        action=action,
        options_json=operation["options_json"],
        operation_id=operation["id"],
        key=f"student_passkey_{operation['id']}",
    )
    if not payload or payload.get("operation_id") != operation["id"]:
        return
    if st.session_state.get("student_passkey_processed") == operation["id"]:
        return
    st.session_state["student_passkey_processed"] = operation["id"]

    if payload.get("error"):
        st.session_state["student_passkey_error"] = str(payload["error"])
        st.session_state["student_passkey_operation"] = None
        st.rerun(scope="fragment")

    try:
        if action == "authenticate":
            verified_device = authenticate_student_passkey(
                repo,
                settings,
                access_context=StudentAccessContext(**context),
                credential=payload["credential"],
                device_token=str(payload["device_token"]),
                expected_challenge=operation["challenge"],
                expected_rp_id=operation["rp_id"],
                expected_origin=operation["origin"],
            )
            st.session_state["student_passkey_verified"] = verified_device
            st.session_state["student_passkey_operation"] = None
            st.rerun(scope="fragment")

        verified_device = register_student_passkey(
            repo,
            settings,
            access_context=StudentAccessContext(**context),
            credential=payload["credential"],
            device_token=str(payload["device_token"]),
            expected_challenge=operation["challenge"],
            expected_rp_id=operation["rp_id"],
            expected_origin=operation["origin"],
        )
        course = repo.get_course(int(context["course_id"]))
        student = repo.get_student(int(context["student_id"]))
        if course is None or student is None:
            raise ValueError("Student access context is no longer valid.")
        _invalidate_read_caches()
        _start_student_session(course, student, verified_device, context)
        st.rerun()
    except Exception as error:
        st.session_state["student_passkey_error"] = str(error)
        st.session_state["student_passkey_operation"] = None
        st.rerun(scope="fragment")


def _ensure_passkey_operation(repo, settings, context: dict, *, action: str) -> dict:
    rp_id, origin = _passkey_relying_party(settings)
    signature = (
        action,
        int(context["student_id"]),
        str(context["device_binding_hash"]),
        rp_id,
        origin,
    )
    existing = st.session_state.get("student_passkey_operation")
    if existing is not None and tuple(existing.get("signature", ())) == signature:
        return existing

    if action == "authenticate":
        device = repo.get_registered_device_for_student(int(context["student_id"]))
        if device is None:
            raise ValueError("No registered device was found for this student.")
        options_json, challenge = build_authentication_options(
            rp_id=rp_id,
            credential_id=str(device["credential_id"]),
        )
    else:
        options_json, challenge = build_registration_options(
            rp_id=rp_id,
            rp_name=settings.webauthn_rp_name,
            student_id=int(context["student_id"]),
            university_id=str(context["student_university_id"]),
            student_name=str(context["student_name"]),
        )

    operation = {
        "id": uuid4().hex,
        "signature": signature,
        "action": action,
        "options_json": options_json,
        "challenge": challenge,
        "rp_id": rp_id,
        "origin": origin,
    }
    st.session_state["student_passkey_operation"] = operation
    return operation


def _passkey_relying_party(settings) -> tuple[str, str]:
    configured_origin = settings.webauthn_origin
    context_url = str(getattr(st.context, "url", "") or "")
    raw_url = configured_origin or context_url or "http://localhost:8501"
    parsed = urlsplit(raw_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("Passkey origin is not configured correctly.")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp_id = settings.webauthn_rp_id or parsed.hostname
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Passkeys require HTTPS.")
    return rp_id, origin


def _start_student_session(
    course,
    student,
    verified_device: dict | None,
    context: dict,
) -> None:
    if verified_device is None:
        raise ValueError("A verified device is required.")
    st.session_state["student_auth"] = {
        "course_id": int(course["id"]),
        "student_id": int(student["id"]),
        "device_id": int(verified_device["device_id"]),
        "credential_id": str(verified_device["credential_id"]),
        "device_binding_hash": str(verified_device["device_binding_hash"]),
        "schedule_id": int(context["schedule_id"]),
        "attendance_date": str(context["attendance_date"]),
        "session_expires_at": str(context["session_expires_at"]),
    }
    st.session_state["student_section"] = STUDENT_SECTIONS[0]
    st.session_state["student_stamp_result"] = None


def _handle_stamp_location(payload) -> None:
    if not payload:
        return
    captured_at = payload.get("captured_at")
    if captured_at == st.session_state.get("student_stamp_processed"):
        return
    st.session_state["student_stamp_processed"] = captured_at
    if payload.get("error"):
        st.session_state["student_stamp_geolocation"] = None
        st.error(_student_message(payload["error"]))
        return
    st.session_state["student_stamp_geolocation"] = payload
    st.session_state["student_stamp_result"] = None
    st.rerun(scope="fragment")


def _reset_student_access(*, clear_id: bool) -> None:
    if clear_id:
        st.session_state["clear_pending_university_id"] = True
    st.session_state["student_access_context"] = None
    st.session_state["student_otp_requested"] = False
    st.session_state["student_otp_notice"] = None
    st.session_state["student_otp_preview_code"] = None
    st.session_state["student_otp_verified"] = False
    st.session_state["student_access_processed"] = None
    st.session_state["student_passkey_verified"] = None
    st.session_state["student_passkey_operation"] = None
    st.session_state["student_passkey_processed"] = None
    st.session_state["student_passkey_error"] = None
    st.session_state["student_browser_key_operation"] = None
    st.session_state["student_browser_key_processed"] = None
    st.session_state["student_browser_key_error"] = None
    st.session_state["student_pending_enrollment_id"] = None
    st.session_state["student_registration_method"] = None
    st.session_state["student_credential_capability"] = None
    st.session_state["student_credential_capability_operation"] = None


def _apply_pending_student_id_reset() -> None:
    if st.session_state.pop("clear_pending_university_id", False):
        st.session_state["pending_university_id"] = ""


def _sign_out_student() -> None:
    st.session_state["student_auth"] = None
    st.session_state["active_role"] = None
    st.session_state["student_stamp_geolocation"] = None
    st.session_state["student_stamp_result"] = None
    _reset_student_access(clear_id=True)


def _expire_student_session() -> None:
    st.session_state["student_auth"] = None
    st.session_state["student_stamp_geolocation"] = None
    st.session_state["student_stamp_result"] = None
    st.session_state["student_access_notice"] = (
        "انتهت صلاحية التحقق. أعد التحقق من الجهاز ورمز الدخول للمحاضرة الحالية."
    )
    _reset_student_access(clear_id=False)


def _course_is_active(course, target_date: date) -> bool:
    start = parse_iso_date(str(course["start_date"]))
    end = parse_iso_date(str(course["end_date"] or course["start_date"]))
    return start <= target_date <= end


def _selected_course(courses):
    code = st.session_state.get("manager_course_code")
    return next((course for course in courses if str(course["code"]) == code), None)


def _normalize_course_choice(courses) -> None:
    options = [str(course["code"]) for course in courses]
    pending = st.session_state.pop("pending_manager_course_code", None)
    if pending in options:
        st.session_state["manager_course_code"] = pending
    current = st.session_state.get("manager_course_code")
    if options and current not in options:
        st.session_state["manager_course_code"] = options[0]
    elif not options:
        st.session_state["manager_course_code"] = "No courses"


def _normalize_state_choice(key: str, options: list[str]) -> str:
    current = st.session_state.get(key)
    if current not in options:
        st.session_state[key] = options[0]
    return str(st.session_state[key])


def _init_session_state() -> None:
    defaults = {
        "active_role": None,
        "manager_auth": None,
        "manager_section": MANAGER_SECTIONS[0],
        "manager_course_code": "No courses",
        "pending_manager_course_code": None,
        "course_editor_mode": "existing",
        "course_latitude": 0.0,
        "course_longitude": 0.0,
        "course_location_selected": False,
        "loaded_course_location": None,
        "course_location_processed": None,
        "student_auth": None,
        "student_access_notice": None,
        "student_section": STUDENT_SECTIONS[0],
        "pending_university_id": "",
        "clear_pending_university_id": False,
        "student_access_context": None,
        "student_access_processed": None,
        "student_otp_requested": False,
        "student_otp_notice": None,
        "student_otp_preview_code": None,
        "student_otp_verified": False,
        "student_passkey_verified": None,
        "student_passkey_operation": None,
        "student_passkey_processed": None,
        "student_passkey_error": None,
        "student_browser_key_operation": None,
        "student_browser_key_processed": None,
        "student_browser_key_error": None,
        "student_pending_enrollment_id": None,
        "student_registration_method": None,
        "student_credential_capability": None,
        "student_credential_capability_operation": None,
        "student_stamp_geolocation": None,
        "student_stamp_processed": None,
        "student_stamp_result": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _safe_secrets():
    try:
        return dict(st.secrets)
    except Exception:
        return {}


if __name__ == "__main__":
    main()
