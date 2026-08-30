from __future__ import annotations

from datetime import date, timedelta
from html import escape

import streamlit as st

from attendance_app.components import geo_capture, location_picker
from attendance_app.config import load_settings
from attendance_app.database import AttendanceRepository
from attendance_app.reports import build_course_report_xlsx
from attendance_app.report_importer import import_attendance_report_bytes
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
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

    :root {
        --aa-bg: #f4f7fb;
        --aa-bg-glow: rgba(71, 85, 105, 0.08);
        --aa-surface: rgba(255, 255, 255, 0.88);
        --aa-surface-solid: #ffffff;
        --aa-surface-muted: #eef3f9;
        --aa-border: #d8e1ef;
        --aa-border-strong: #b9c6da;
        --aa-text: #162033;
        --aa-text-soft: #5a6b87;
        --aa-text-muted: #74839c;
        --aa-accent: #1d4ed8;
        --aa-accent-soft: #dbeafe;
        --aa-sidebar-top: #0f172a;
        --aa-sidebar-bottom: #16213a;
        --aa-success: #0f766e;
        --aa-success-soft: #dff7f2;
        --aa-warning: #b45309;
        --aa-warning-soft: #fff1d6;
        --aa-danger: #b42318;
        --aa-danger-soft: #fde7e7;
        --aa-shadow: 0 18px 42px rgba(15, 23, 42, 0.08);
        --aa-radius-xl: 24px;
        --aa-radius-lg: 18px;
        --aa-radius-md: 14px;
        --aa-radius-sm: 10px;
    }

    html, body, [class*="css"] {
        font-family: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: var(--aa-text);
    }

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(29, 78, 216, 0.10), transparent 26%),
            radial-gradient(circle at top right, rgba(15, 118, 110, 0.08), transparent 22%),
            linear-gradient(180deg, #f8fbff 0%, var(--aa-bg) 100%);
    }

    .block-container {
        max-width: 1280px;
        padding-top: 2.1rem;
        padding-bottom: 3rem;
    }

    header[data-testid="stHeader"] {
        background: rgba(248, 251, 255, 0.82);
        border-bottom: 1px solid rgba(216, 225, 239, 0.8);
        backdrop-filter: blur(10px);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, var(--aa-sidebar-top) 0%, var(--aa-sidebar-bottom) 100%);
        border-right: 1px solid rgba(255, 255, 255, 0.06);
    }

    [data-testid="stSidebar"] * {
        color: #e7edf8 !important;
    }

    [data-testid="stSidebar"] .stRadio label {
        color: #b8c4da !important;
    }

    [data-testid="stSidebar"] [data-baseweb="radio"] {
        background: transparent !important;
    }

    [data-testid="stSidebar"] [data-baseweb="radio"] [aria-checked="true"] ~ div {
        color: #ffffff !important;
        font-weight: 700 !important;
    }

    .aa-sidebar-brand {
        padding: 0.4rem 0 1.3rem 0;
    }

    .aa-sidebar-brand strong {
        display: block;
        font-size: 1.15rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        color: #ffffff;
    }

    .aa-sidebar-brand span {
        display: block;
        margin-top: 0.3rem;
        font-size: 0.78rem;
        line-height: 1.55;
        color: #a7b6d1;
    }

    .aa-sidebar-card {
        margin-top: 1rem;
        padding: 1rem 1rem 0.95rem;
        border-radius: 16px;
        background: rgba(148, 163, 184, 0.10);
        border: 1px solid rgba(148, 163, 184, 0.16);
    }

    .aa-sidebar-card strong {
        display: block;
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #c9d4e8;
        margin-bottom: 0.7rem;
    }

    .aa-sidebar-card span {
        display: block;
        font-size: 0.83rem;
        color: #f8fbff;
        font-weight: 600;
        line-height: 1.55;
        margin-top: 0.22rem;
    }

    .aa-sidebar-card em {
        display: block;
        margin-top: 0.8rem;
        font-style: normal;
        font-size: 0.78rem;
        line-height: 1.55;
        color: #b8c4da;
    }

    .aa-shell {
        display: flex;
        justify-content: space-between;
        gap: 1.5rem;
        align-items: flex-start;
        padding: 1.6rem 1.8rem;
        border-radius: var(--aa-radius-xl);
        border: 1px solid rgba(216, 225, 239, 0.95);
        background:
            linear-gradient(135deg, rgba(255, 255, 255, 0.96), rgba(243, 247, 255, 0.94));
        box-shadow: var(--aa-shadow);
        margin-bottom: 1.5rem;
    }

    .aa-shell-copy h1 {
        margin: 0.25rem 0 0 0;
        font-size: 2.1rem;
        line-height: 1.05;
        letter-spacing: -0.05em;
        color: var(--aa-text);
    }

    .aa-shell-copy p {
        max-width: 44rem;
        margin: 0.7rem 0 0 0;
        font-size: 0.98rem;
        line-height: 1.65;
        color: var(--aa-text-soft);
    }

    .aa-kicker {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.28rem 0.78rem;
        border-radius: 999px;
        border: 1px solid rgba(29, 78, 216, 0.10);
        background: rgba(29, 78, 216, 0.08);
        color: var(--aa-accent);
        font-size: 0.74rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .aa-shell-meta {
        display: grid;
        grid-template-columns: repeat(3, minmax(150px, 1fr));
        gap: 0.8rem;
        width: min(460px, 100%);
    }

    .aa-meta-chip {
        padding: 0.95rem 1rem;
        border-radius: 16px;
        border: 1px solid rgba(216, 225, 239, 0.95);
        background: rgba(255, 255, 255, 0.78);
    }

    .aa-meta-chip span {
        display: block;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--aa-text-muted);
        margin-bottom: 0.38rem;
    }

    .aa-meta-chip strong {
        display: block;
        font-size: 0.92rem;
        line-height: 1.4;
        color: var(--aa-text);
        font-weight: 700;
    }

    .aa-page-intro {
        padding: 1.3rem 1.35rem;
        margin-bottom: 1rem;
        border-radius: var(--aa-radius-lg);
        border: 1px solid rgba(216, 225, 239, 0.92);
        background: rgba(255, 255, 255, 0.84);
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
    }

    .aa-page-intro h2,
    .aa-surface h3,
    .aa-signin-card h2,
    .aa-student-hero h2 {
        margin: 0.3rem 0 0 0;
        font-size: 1.35rem;
        line-height: 1.15;
        letter-spacing: -0.03em;
        color: var(--aa-text);
    }

    .aa-page-intro p,
    .aa-surface p,
    .aa-signin-card p,
    .aa-student-hero p {
        margin: 0.55rem 0 0 0;
        font-size: 0.92rem;
        line-height: 1.65;
        color: var(--aa-text-soft);
    }

    .aa-toolbar {
        display: flex;
        justify-content: space-between;
        gap: 0.8rem;
        align-items: center;
        margin-bottom: 1rem;
    }

    .aa-user-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.45rem 0.9rem;
        border-radius: 999px;
        background: rgba(29, 78, 216, 0.08);
        border: 1px solid rgba(29, 78, 216, 0.12);
        color: var(--aa-accent);
        font-size: 0.83rem;
        font-weight: 700;
    }

    .aa-surface,
    .aa-signin-card,
    .portal-card,
    .aa-info-card,
    .aa-progress-card,
    .aa-status-card {
        padding: 1.2rem 1.25rem;
        border-radius: var(--aa-radius-lg);
        border: 1px solid rgba(216, 225, 239, 0.95);
        background: rgba(255, 255, 255, 0.90);
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
    }

    .aa-surface-muted {
        background: linear-gradient(180deg, rgba(246, 249, 253, 0.92), rgba(255, 255, 255, 0.90));
    }

    .aa-empty-state {
        padding: 1.35rem 1.4rem;
        border-radius: var(--aa-radius-lg);
        border: 1px dashed var(--aa-border-strong);
        background: rgba(255, 255, 255, 0.72);
        margin-bottom: 1rem;
    }

    .aa-empty-state strong {
        display: block;
        font-size: 1rem;
        color: var(--aa-text);
        margin-bottom: 0.35rem;
    }

    .aa-empty-state span {
        display: block;
        max-width: 42rem;
        font-size: 0.9rem;
        line-height: 1.65;
        color: var(--aa-text-soft);
    }

    .aa-course-banner,
    .aa-status-banner {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 1rem;
        padding: 1.25rem 1.35rem;
        border-radius: var(--aa-radius-lg);
        border: 1px solid rgba(216, 225, 239, 0.95);
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(239, 246, 255, 0.92));
        margin-bottom: 1rem;
        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06);
    }

    .aa-course-banner h3,
    .aa-status-banner h3 {
        margin: 0.35rem 0 0 0;
        font-size: 1.15rem;
        color: var(--aa-text);
        letter-spacing: -0.02em;
    }

    .aa-course-banner p,
    .aa-status-banner p {
        margin: 0.4rem 0 0 0;
        font-size: 0.9rem;
        line-height: 1.55;
        color: var(--aa-text-soft);
    }

    .aa-banner-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        justify-content: flex-end;
    }

    .aa-banner-tag {
        padding: 0.42rem 0.72rem;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(216, 225, 239, 0.95);
        color: var(--aa-text-soft);
        font-size: 0.78rem;
        font-weight: 700;
    }

    .aa-student-hero {
        position: relative;
        overflow: hidden;
        padding: 1.5rem 1.55rem;
        border-radius: var(--aa-radius-xl);
        border: 1px solid rgba(30, 64, 175, 0.14);
        background: linear-gradient(140deg, #172554 0%, #1d4ed8 58%, #0f766e 100%);
        color: #ffffff;
        box-shadow: 0 18px 40px rgba(23, 37, 84, 0.18);
    }

    .aa-student-hero::after {
        content: "";
        position: absolute;
        width: 280px;
        height: 280px;
        right: -100px;
        top: -130px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0) 72%);
    }

    .aa-student-hero > * {
        position: relative;
        z-index: 1;
    }

    .aa-student-hero .aa-kicker {
        background: rgba(255, 255, 255, 0.14);
        border-color: rgba(255, 255, 255, 0.18);
        color: #eff6ff;
    }

    .aa-student-hero h2,
    .aa-student-hero p {
        color: #ffffff;
    }

    .aa-student-hero p {
        max-width: 44rem;
        color: rgba(239, 246, 255, 0.84);
    }

    .aa-student-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.7rem;
        margin-top: 1rem;
    }

    .aa-student-grid div {
        padding: 0.8rem 0.9rem;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.16);
        backdrop-filter: blur(6px);
    }

    .aa-student-grid span {
        display: block;
        font-size: 0.68rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(224, 231, 255, 0.82);
        font-weight: 800;
        margin-bottom: 0.35rem;
    }

    .aa-student-grid strong {
        display: block;
        font-size: 0.93rem;
        line-height: 1.45;
        color: #ffffff;
    }

    .aa-list,
    .aa-rule-list,
    .aa-checklist {
        list-style: none;
        padding: 0;
        margin: 0.9rem 0 0 0;
        display: grid;
        gap: 0.7rem;
    }

    .aa-list li,
    .aa-rule-list li,
    .aa-checklist li {
        position: relative;
        padding-left: 1.3rem;
        font-size: 0.88rem;
        line-height: 1.55;
        color: var(--aa-text-soft);
    }

    .aa-list li::before,
    .aa-rule-list li::before,
    .aa-checklist li::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0.45rem;
        width: 0.45rem;
        height: 0.45rem;
        border-radius: 50%;
        background: var(--aa-accent);
        box-shadow: 0 0 0 4px rgba(29, 78, 216, 0.10);
    }

    .aa-detail-list {
        display: grid;
        gap: 0.75rem;
        margin-top: 0.9rem;
    }

    .aa-detail-row {
        display: flex;
        justify-content: space-between;
        gap: 0.9rem;
        padding-bottom: 0.75rem;
        border-bottom: 1px solid rgba(216, 225, 239, 0.9);
    }

    .aa-detail-row:last-child {
        border-bottom: none;
        padding-bottom: 0;
    }

    .aa-detail-row .aa-label {
        color: var(--aa-text-muted);
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .aa-detail-row .aa-value {
        color: var(--aa-text);
        font-size: 0.87rem;
        font-weight: 700;
        line-height: 1.45;
        text-align: right;
    }

    .aa-signin-card {
        max-width: 460px;
        margin: 1rem auto 1.2rem auto;
        padding: 2rem 2rem 1.5rem;
    }

    .aa-note-card {
        padding: 1rem 1.05rem;
        border-radius: 16px;
        border: 1px solid rgba(216, 225, 239, 0.95);
        margin-bottom: 1rem;
        background: rgba(255, 255, 255, 0.86);
    }

    .aa-note-card strong {
        display: block;
        font-size: 0.9rem;
        color: var(--aa-text);
        margin-bottom: 0.25rem;
    }

    .aa-note-card span {
        display: block;
        font-size: 0.85rem;
        line-height: 1.55;
        color: var(--aa-text-soft);
    }

    .aa-note-card.success {
        background: linear-gradient(180deg, rgba(223, 247, 242, 0.82), rgba(255, 255, 255, 0.90));
        border-color: rgba(15, 118, 110, 0.22);
    }

    .aa-note-card.warning {
        background: linear-gradient(180deg, rgba(255, 241, 214, 0.88), rgba(255, 255, 255, 0.92));
        border-color: rgba(180, 83, 9, 0.22);
    }

    .aa-note-card.info {
        background: linear-gradient(180deg, rgba(219, 234, 254, 0.70), rgba(255, 255, 255, 0.92));
        border-color: rgba(29, 78, 216, 0.18);
    }

    .aa-otp-card {
        padding: 1rem 1.05rem 1.1rem;
        border-radius: 16px;
        border: 1px solid rgba(29, 78, 216, 0.16);
        background: linear-gradient(180deg, rgba(239, 246, 255, 0.92), rgba(255, 255, 255, 0.94));
        margin: 0.95rem 0 1rem 0;
    }

    .aa-otp-card h3 {
        margin: 0;
        font-size: 0.98rem;
        color: var(--aa-text);
    }

    .aa-otp-card p {
        margin: 0.35rem 0 0 0;
        font-size: 0.84rem;
        line-height: 1.55;
        color: var(--aa-text-soft);
    }

    .aa-otp-code {
        display: inline-block;
        margin-top: 0.85rem;
        padding: 0.6rem 0.95rem;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(29, 78, 216, 0.14);
        color: var(--aa-text);
        font-family: 'SFMono-Regular', 'Menlo', 'Monaco', monospace;
        font-size: 1.35rem;
        font-weight: 800;
        letter-spacing: 0.18em;
    }

    .aa-status-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.35rem 0.74rem;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 0.75rem;
    }

    .aa-status-pill.aa-good {
        background: var(--aa-success-soft);
        color: var(--aa-success);
    }

    .aa-status-pill.aa-risk {
        background: var(--aa-danger-soft);
        color: var(--aa-danger);
    }

    .aa-progress-track {
        width: 100%;
        height: 0.72rem;
        border-radius: 999px;
        overflow: hidden;
        background: #e5edf9;
        margin: 0.95rem 0 0.75rem 0;
    }

    .aa-progress-fill {
        height: 100%;
        border-radius: inherit;
        background: linear-gradient(90deg, var(--aa-accent), #0f766e);
    }

    .aa-progress-meta {
        display: flex;
        justify-content: space-between;
        gap: 0.7rem;
        flex-wrap: wrap;
        font-size: 0.8rem;
        color: var(--aa-text-soft);
        font-weight: 700;
    }

    .aa-subsection {
        font-size: 0.77rem;
        font-weight: 800;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        color: var(--aa-accent);
        margin: 1.1rem 0 0.6rem 0;
    }

    [data-testid="metric-container"] {
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid rgba(216, 225, 239, 0.95);
        border-radius: 16px;
        padding: 0.95rem 1rem !important;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
    }

    [data-testid="metric-container"] [data-testid="stMetricLabel"] {
        color: var(--aa-text-muted) !important;
        font-size: 0.74rem !important;
        font-weight: 800 !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: var(--aa-text) !important;
        font-size: 1.45rem !important;
        font-weight: 800 !important;
        letter-spacing: -0.03em;
    }

    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.45rem;
        padding: 0.35rem;
        border-radius: 16px;
        background: rgba(230, 238, 250, 0.9);
        border: 1px solid rgba(216, 225, 239, 0.92);
    }

    [data-testid="stTabs"] [data-baseweb="tab"] {
        min-height: 42px;
        border-radius: 12px;
        padding: 0.5rem 0.95rem;
        font-size: 0.88rem;
        font-weight: 700;
        color: var(--aa-text-soft);
    }

    [data-testid="stTabs"] [aria-selected="true"] {
        background: rgba(255, 255, 255, 0.95) !important;
        color: var(--aa-text) !important;
        box-shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
    }

    .stButton > button,
    .stDownloadButton > button,
    div[data-testid="stFormSubmitButton"] > button {
        border-radius: 12px;
        min-height: 42px;
        border: 1px solid rgba(29, 78, 216, 0.14);
        font-weight: 700;
        font-size: 0.9rem;
        transition: transform 0.14s ease, box-shadow 0.14s ease, border-color 0.14s ease;
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 18px rgba(29, 78, 216, 0.12);
        border-color: rgba(29, 78, 216, 0.22);
    }

    [data-baseweb="input"],
    [data-baseweb="select"],
    [data-baseweb="base-input"] {
        border-radius: 12px !important;
    }

    [data-testid="stForm"],
    [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stExpander"] {
        border-radius: 18px !important;
        border-color: rgba(216, 225, 239, 0.95) !important;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
    }

    [data-testid="stFileUploader"],
    [data-testid="stDataFrame"],
    [data-testid="stDataEditor"] {
        border-radius: 16px;
    }

    [data-testid="stMarkdownContainer"] code {
        color: #0f172a;
        background: rgba(226, 232, 240, 0.65);
        border-radius: 6px;
        padding: 0.12rem 0.34rem;
    }

    .aa-route-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 1rem;
        margin-bottom: 1.35rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid rgba(216, 225, 239, 0.95);
    }

    .aa-route-copy {
        max-width: 44rem;
    }

    .aa-route-label {
        display: block;
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        color: var(--aa-text-muted);
    }

    .aa-route-title {
        margin: 0.22rem 0 0 0;
        font-size: 2rem;
        line-height: 1.05;
        letter-spacing: -0.05em;
        color: var(--aa-text);
    }

    .aa-route-description {
        margin: 0.6rem 0 0 0;
        font-size: 0.94rem;
        line-height: 1.65;
        color: var(--aa-text-soft);
    }

    .aa-route-tags {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 0.55rem;
        max-width: 26rem;
    }

    .aa-route-tag {
        padding: 0.42rem 0.74rem;
        border-radius: 999px;
        border: 1px solid rgba(216, 225, 239, 0.95);
        background: rgba(255, 255, 255, 0.82);
        color: var(--aa-text-soft);
        font-size: 0.78rem;
        font-weight: 700;
    }

    .aa-sidebar-label {
        display: block;
        margin: 1.05rem 0 0.45rem 0;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        color: #c9d4e8;
    }

    .aa-step-rail {
        display: grid;
        gap: 0.95rem;
        padding: 1.1rem 1.15rem;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid rgba(216, 225, 239, 0.95);
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
    }

    .aa-step-item {
        display: grid;
        grid-template-columns: 2.3rem 1fr;
        gap: 0.8rem;
        align-items: flex-start;
    }

    .aa-step-index {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 50%;
        background: rgba(29, 78, 216, 0.10);
        color: var(--aa-accent);
        font-size: 0.82rem;
        font-weight: 800;
    }

    .aa-step-content h4 {
        margin: 0;
        font-size: 0.96rem;
        color: var(--aa-text);
    }

    .aa-step-content p {
        margin: 0.28rem 0 0 0;
        font-size: 0.84rem;
        line-height: 1.55;
        color: var(--aa-text-soft);
    }

    .aa-compact-list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 0.7rem;
    }

    .aa-compact-list li {
        display: flex;
        justify-content: space-between;
        gap: 0.8rem;
        padding-bottom: 0.7rem;
        border-bottom: 1px solid rgba(216, 225, 239, 0.88);
        font-size: 0.85rem;
        line-height: 1.45;
        color: var(--aa-text-soft);
    }

    .aa-compact-list li:last-child {
        border-bottom: none;
        padding-bottom: 0;
    }

    .aa-compact-list strong {
        color: var(--aa-text);
    }

    @media (max-width: 980px) {
        .aa-shell,
        .aa-course-banner,
        .aa-status-banner,
        .aa-route-header {
            flex-direction: column;
        }

        .aa-shell-meta {
            grid-template-columns: 1fr;
            width: 100%;
        }

        .aa-banner-tags {
            justify-content: flex-start;
        }

        .aa-route-tags {
            justify-content: flex-start;
        }

        .aa-student-grid {
            grid-template-columns: 1fr;
        }

        .aa-detail-row {
            flex-direction: column;
        }

        .aa-detail-row .aa-value {
            text-align: left;
        }

        .aa-otp-code {
            font-size: 1.18rem;
            letter-spacing: 0.15em;
        }
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

MANAGER_SECTIONS = [
    "Today",
    "Courses",
    "Students",
    "Attendance Log",
    "Imports",
    "Reports",
    "Settings",
]

STUDENT_SECTIONS = ["Check In", "Status", "History"]


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_courses(database_target: str) -> list[dict]:
    return AttendanceRepository(database_target).list_courses()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_get_course(database_target: str, course_id: int) -> dict | None:
    return AttendanceRepository(database_target).get_course(course_id)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_get_course_by_code(database_target: str, code: str) -> dict | None:
    return AttendanceRepository(database_target).get_course_by_code(code)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_schedules_for_course(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_schedules_for_course(course_id)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_students_for_course(database_target: str, course_id: int) -> list[dict]:
    return AttendanceRepository(database_target).list_students_for_course(course_id)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_course_attendance(database_target: str, course_id: int, limit: int) -> list[dict]:
    return AttendanceRepository(database_target).list_course_attendance(course_id=course_id, limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_attendance(
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


@st.cache_data(ttl=30, show_spinner=False)
def _cached_count_attendance(database_target: str, course_id: int, student_id: int) -> int:
    return AttendanceRepository(database_target).count_attendance(
        course_id=course_id,
        student_id=student_id,
    )


@st.cache_data(ttl=30, show_spinner=False)
def _cached_count_attendance_by_student_for_course(
    database_target: str,
    course_id: int,
) -> dict[int, int]:
    return AttendanceRepository(database_target).count_attendance_by_student_for_course(
        course_id=course_id,
    )


def _clear_cached_database_reads() -> None:
    _cached_list_courses.clear()
    _cached_get_course.clear()
    _cached_get_course_by_code.clear()
    _cached_list_schedules_for_course.clear()
    _cached_list_students_for_course.clear()
    _cached_list_course_attendance.clear()
    _cached_list_attendance.clear()
    _cached_count_attendance.clear()
    _cached_count_attendance_by_student_for_course.clear()


def _otp_mode_label(settings) -> str:
    if settings.otp_delivery_mode == "email":
        return "Roster email"
    return "On-page code"


def _render_shell_header(page: str, settings, repo: AttendanceRepository) -> None:
    workspace_label = "Operations workspace" if page == "Manager" else "Student workspace"
    storage_label = "PostgreSQL" if repo.backend == "postgres" else "SQLite"
    st.markdown(
        f"""
        <section class="aa-shell">
            <div class="aa-shell-copy">
                <span class="aa-kicker">{escape(workspace_label)}</span>
                <h1>AttendancApp</h1>
                <p>
                    A focused attendance workspace for course setup, live classroom check-in,
                    roster control, and export-ready reporting.
                </p>
            </div>
            <div class="aa-shell-meta">
                <div class="aa-meta-chip">
                    <span>Timezone</span>
                    <strong>{escape(settings.app_timezone)}</strong>
                </div>
                <div class="aa-meta-chip">
                    <span>Student Access</span>
                    <strong>{escape(_otp_mode_label(settings))}</strong>
                </div>
                <div class="aa-meta-chip">
                    <span>Data Store</span>
                    <strong>{escape(storage_label)}</strong>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_page_intro(kicker: str, title: str, description: str) -> None:
    st.markdown(
        f"""
        <section class="aa-page-intro">
            <span class="aa-kicker">{escape(kicker)}</span>
            <h2>{escape(title)}</h2>
            <p>{escape(description)}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_empty_state(title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="aa-empty-state">
            <strong>{escape(title)}</strong>
            <span>{escape(description)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_note_card(title: str, description: str, *, tone: str = "info") -> None:
    st.markdown(
        f"""
        <div class="aa-note-card {escape(tone)}">
            <strong>{escape(title)}</strong>
            <span>{escape(description)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar(page: str, settings, repo: AttendanceRepository) -> None:
    student_copy = (
        "Students authenticate with a one-time code sent to their roster email."
        if settings.otp_delivery_mode == "email"
        else "Students authenticate with a one-time code shown inside the app."
    )
    portal_copy = (
        "Manage courses, classroom boundaries, rosters, and reports from a calmer operations workspace."
        if page == "Manager"
        else "Guide students through location verification, one-time access, and live attendance stamping."
    )
    storage_label = "Persistent hosted database" if repo.backend == "postgres" else "Local SQLite file"
    st.markdown(
        """
        <div class="aa-sidebar-brand">
            <strong>AttendancApp</strong>
            <span>Attendance operations for instructors and students, with room to breathe.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="aa-sidebar-card">
            <strong>Workspace</strong>
            <span>{escape(portal_copy)}</span>
            <em>{escape(student_copy if page == "Student" else storage_label)}</em>
        </div>
        <div class="aa-sidebar-card">
            <strong>Runtime</strong>
            <span>Timezone: {escape(settings.app_timezone)}</span>
            <span>OTP mode: {escape(_otp_mode_label(settings))}</span>
            <span>Storage: {escape(storage_label)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_brand() -> None:
    st.markdown(
        """
        <div class="aa-sidebar-brand">
            <strong>AttendancApp</strong>
            <span>Attendance operations split into a back office for staff and a focused check-in experience for students.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _normalize_choice_state(key: str, options: list[str], default: str) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = default


def _render_sidebar_runtime(settings, repo: AttendanceRepository, context_copy: str) -> None:
    storage_label = "Persistent hosted database" if repo.backend == "postgres" else "Local SQLite file"
    st.markdown(
        f"""
        <div class="aa-sidebar-card">
            <strong>Context</strong>
            <span>{escape(context_copy)}</span>
            <em>Timezone: {escape(settings.app_timezone)} · OTP mode: {escape(_otp_mode_label(settings))}</em>
        </div>
        <div class="aa-sidebar-card">
            <strong>Runtime</strong>
            <span>Environment: {escape(settings.app_env.capitalize())}</span>
            <span>Storage: {escape(storage_label)}</span>
            <span>Date: {escape(now_in_app_timezone(settings).strftime("%b %d, %Y"))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_manager_sidebar_navigation(settings, repo: AttendanceRepository) -> str | None:
    courses = _cached_list_courses(settings.database_target)
    course_options = ["New course", *[str(course["code"]) for course in courses]]
    _prepare_manager_course_selector(course_options)
    _normalize_choice_state("manager_section", MANAGER_SECTIONS, MANAGER_SECTIONS[0])

    st.markdown('<span class="aa-sidebar-label">Operations</span>', unsafe_allow_html=True)
    if st.session_state.get("manager_auth") is None:
        st.markdown(
            """
            <div class="aa-sidebar-card">
                <strong>Sign in required</strong>
                <span>The operations workspace unlocks after instructor authentication.</span>
                <em>Course records, imports, and reporting stay behind the protected back office.</em>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_sidebar_runtime(
            settings,
            repo,
            "Back-office pages become available after sign in.",
        )
        return None

    section = st.radio(
        "Operations navigation",
        options=MANAGER_SECTIONS,
        key="manager_section",
        label_visibility="collapsed",
    )
    st.markdown('<span class="aa-sidebar-label">Selected course</span>', unsafe_allow_html=True)
    st.selectbox(
        "Selected course",
        options=course_options,
        key="manager_course_selector",
        label_visibility="collapsed",
    )
    selected_code = st.session_state.get("manager_course_selector", "New course")
    selected_copy = (
        "You are preparing a new course draft."
        if selected_code == "New course"
        else f"Working course: {selected_code}"
    )
    _render_sidebar_runtime(settings, repo, selected_copy)
    return section


def _render_student_sidebar_navigation(settings, repo: AttendanceRepository) -> str:
    auth = st.session_state.get("student_auth")
    options = STUDENT_SECTIONS if auth is not None else ["Start"]
    _normalize_choice_state("student_section", options, options[0])
    st.markdown('<span class="aa-sidebar-label">Student app</span>', unsafe_allow_html=True)
    section = st.radio(
        "Student navigation",
        options=options,
        key="student_section",
        label_visibility="collapsed",
    )
    if auth is not None:
        course = _cached_get_course(settings.database_target, int(auth["course_id"]))
        student = repo.get_student(int(auth["student_id"]))
        context_copy = (
            f"{course['code']} · {student['full_name']}"
            if course is not None and student is not None
            else "Active student session"
        )
    else:
        context_copy = "Use the guided flow to verify location, request a code, and sign in."
    _render_sidebar_runtime(settings, repo, context_copy)
    return section


def _selected_manager_course(settings) -> dict | None:
    selected_code = st.session_state.get("manager_course_selector", "New course")
    if selected_code == "New course":
        return None
    return _cached_get_course_by_code(settings.database_target, selected_code)


def _render_route_header(label: str, title: str, description: str, *, tags: list[str] | None = None) -> None:
    tag_markup = ""
    if tags:
        tag_markup = '<div class="aa-route-tags">' + "".join(
            f'<span class="aa-route-tag">{escape(tag)}</span>' for tag in tags
        ) + "</div>"

    st.markdown(
        f"""
        <section class="aa-route-header">
            <div class="aa-route-copy">
                <span class="aa-route-label">{escape(label)}</span>
                <h1 class="aa-route-title">{escape(title)}</h1>
                <p class="aa-route-description">{escape(description)}</p>
            </div>
            {tag_markup}
        </section>
        """,
        unsafe_allow_html=True,
    )


def _course_covers_date(course, target_date: date) -> bool:
    start = parse_iso_date(course["start_date"])
    end = parse_iso_date(course["end_date"] or course["start_date"])
    return start <= target_date <= end


def main() -> None:
    st.set_page_config(page_title="AttendancApp", page_icon="A", layout="wide")
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

    with st.sidebar:
        _render_sidebar_brand()
        st.markdown('<span class="aa-sidebar-label">Workspace</span>', unsafe_allow_html=True)
        portal = st.radio(
            "Workspace",
            options=["Operations", "Student"],
            label_visibility="collapsed",
        )
        page = "Manager" if portal == "Operations" else "Student"
        manager_section = None
        student_section = "Start"
        if page == "Manager":
            manager_section = _render_manager_sidebar_navigation(settings, repo)
        else:
            student_section = _render_student_sidebar_navigation(settings, repo)

    if page == "Manager":
        if _render_manager_auth(settings):
            render_manager_page(
                repo,
                settings,
                manager_section or st.session_state.get("manager_section", MANAGER_SECTIONS[0]),
            )
    else:
        render_student_page(repo, settings, student_section)


def render_manager_page(repo: AttendanceRepository, settings, section: str) -> None:
    notice = st.session_state.pop("manager_notice", None)
    if notice:
        st.success(notice)

    courses = _cached_list_courses(settings.database_target)
    selected_course = _selected_manager_course(settings)
    _ensure_course_location_defaults()
    _sync_course_location_state(selected_course)

    titles = {
        "Today": "Today",
        "Courses": "Courses",
        "Students": "Students",
        "Attendance Log": "Attendance log",
        "Imports": "Imports",
        "Reports": "Reports",
        "Settings": "Settings",
    }
    descriptions = {
        "Today": "Monitor live teaching windows, next sessions opening today, and recent classroom activity across the system.",
        "Courses": "Manage course records as a working directory, then open one course at a time for setup and schedule maintenance.",
        "Students": "Review enrolled students across courses in a single directory instead of jumping course by course.",
        "Attendance Log": "Inspect recent attendance events as raw operational data with course-level filtering.",
        "Imports": "Handle roster uploads and workbook restores in one operational intake area.",
        "Reports": "Export the selected course and review diagnostics after the live data is in place.",
        "Settings": "Review runtime configuration, delivery mode, and basic operational health from one place.",
    }
    route_tags = [settings.app_timezone, now_in_app_timezone(settings).strftime("%b %d, %Y")]
    if selected_course is not None and section in {"Courses", "Imports", "Reports"}:
        route_tags.append(f"Course {selected_course['code']}")

    header_left, header_right = st.columns([3.0, 1.0], gap="large")
    with header_left:
        _render_route_header(
            "Operations back office",
            titles[section],
            descriptions[section],
            tags=route_tags,
        )
    with header_right:
        st.markdown(
            f'<div class="aa-user-pill">Instructor {escape(settings.manager_username)}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Sign out", key="manager_signout", use_container_width=True):
            st.session_state["manager_auth"] = None
            st.rerun()

    if section == "Today":
        _render_manager_today_view(repo, settings, courses)
        return
    if section == "Courses":
        _render_manager_courses_view(repo, settings, courses, selected_course)
        return
    if section == "Students":
        _render_manager_students_view(settings, courses, selected_course)
        return
    if section == "Attendance Log":
        _render_manager_attendance_log_view(settings, courses, selected_course)
        return
    if section == "Imports":
        _render_manager_imports_view(repo, settings, selected_course)
        return
    if section == "Reports":
        _render_manager_reports_view(repo, settings, selected_course)
        return
    _render_manager_settings_view(repo, settings, courses)


def _build_today_session_rows(settings, courses: list[dict]) -> list[dict]:
    now = now_in_app_timezone(settings)
    rows: list[dict] = []
    for course in courses:
        if not _course_covers_date(course, now.date()):
            continue
        schedules = _cached_list_schedules_for_course(settings.database_target, int(course["id"]))
        roster_size = len(_cached_list_students_for_course(settings.database_target, int(course["id"])))
        for schedule in schedules:
            if int(schedule["weekday"]) != now.weekday():
                continue
            start_time = parse_hhmm(str(schedule["start_time"]))
            end_time = parse_hhmm(str(schedule["end_time"]))
            if now.time() > end_time:
                continue
            status = "Live" if start_time <= now.time() <= end_time else "Upcoming"
            rows.append(
                {
                    "Status": status,
                    "Course": str(course["code"]),
                    "Title": str(course["title"]),
                    "Window": str(schedule["label"]),
                    "Start": str(schedule["start_time"]),
                    "End": str(schedule["end_time"]),
                    "Roster": roster_size,
                    "_sort_status": 0 if status == "Live" else 1,
                    "_sort_time": str(schedule["start_time"]),
                }
            )
    rows.sort(key=lambda row: (row["_sort_status"], row["_sort_time"], row["Course"]))
    return rows


def _build_course_directory_rows(settings, courses: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for course in courses:
        course_id = int(course["id"])
        rows.append(
            {
                "Course": str(course["code"]),
                "Title": str(course["title"]),
                "Dates": f"{course['start_date']} to {course['end_date']}",
                "Roster": len(_cached_list_students_for_course(settings.database_target, course_id)),
                "Windows": len(_cached_list_schedules_for_course(settings.database_target, course_id)),
                "Radius (m)": round(float(course["radius_m"]), 1),
            }
        )
    return rows


def _build_student_directory_rows(settings, courses: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for course in courses:
        course_id = int(course["id"])
        attendance_counts = _cached_count_attendance_by_student_for_course(
            settings.database_target,
            course_id,
        )
        for student in _cached_list_students_for_course(settings.database_target, course_id):
            rows.append(
                {
                    "Course": str(course["code"]),
                    "Student": str(student["full_name"]),
                    "Student ID": str(student["university_id"]),
                    "Email": str(student["email"]),
                    "Attendance": attendance_counts.get(int(student["id"]), 0),
                }
            )
    rows.sort(key=lambda row: (row["Student"], row["Course"]))
    return rows


def _build_attendance_log_rows(settings, courses: list[dict], *, per_course_limit: int = 250) -> list[dict]:
    rows: list[dict] = []
    for course in courses:
        course_id = int(course["id"])
        for record in _cached_list_course_attendance(settings.database_target, course_id, per_course_limit):
            rows.append(
                {
                    "Course": str(course["code"]),
                    "Student": str(record["full_name"]),
                    "Student ID": str(record["university_id"]),
                    "Date": str(record["attendance_date"]),
                    "Window": str(record["schedule_label"]),
                    "Stamped At": str(record["stamped_at"]),
                    "Distance (m)": round(float(record["distance_m"]), 2),
                }
            )
    rows.sort(key=lambda row: row["Stamped At"], reverse=True)
    return rows


def _build_eligibility_rows(repo: AttendanceRepository, settings, course) -> list[dict]:
    students = _cached_list_students_for_course(settings.database_target, int(course["id"]))
    schedules = _cached_list_schedules_for_course(settings.database_target, int(course["id"]))
    attendance_counts = _cached_count_attendance_by_student_for_course(
        settings.database_target,
        int(course["id"]),
    )

    rows: list[dict] = []
    for student in students:
        student_id = int(student["id"])
        summary = build_student_attendance_summary(
            repo,
            settings,
            course=course,
            student=student,
            schedules=schedules,
            attended_count=attendance_counts.get(student_id, 0),
        )
        rows.append(
            {
                "Student": student["full_name"],
                "Student ID": student["university_id"],
                "Attended": summary.attended_count,
                "Absences": summary.absences,
                "Elapsed": summary.elapsed_meetings,
                "Total": summary.total_meetings,
                "Status": "At Risk" if summary.denied_exam_entry else "Eligible",
            }
        )
    return rows


def _render_manager_today_view(repo: AttendanceRepository, settings, courses: list[dict]) -> None:
    session_rows = _build_today_session_rows(settings, courses)
    attendance_rows = _build_attendance_log_rows(settings, courses, per_course_limit=120)
    today_key = now_in_app_timezone(settings).date().isoformat()
    today_attendance = [row for row in attendance_rows if row["Date"] == today_key]
    live_rows = [row for row in session_rows if row["Status"] == "Live"]
    upcoming_rows = [row for row in session_rows if row["Status"] == "Upcoming"]
    active_courses = {row["Course"] for row in session_rows}

    metrics = st.columns(4)
    metrics[0].metric("Live windows", len(live_rows))
    metrics[1].metric("Upcoming today", len(upcoming_rows))
    metrics[2].metric("Courses running today", len(active_courses))
    metrics[3].metric("Attendance today", len(today_attendance))

    left, right = st.columns([1.2, 0.95], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Live right now")
            if live_rows:
                st.dataframe(
                    [{key: value for key, value in row.items() if not key.startswith("_")} for row in live_rows],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No course window is live right now.")

        with st.container(border=True):
            st.subheader("Opening later today")
            if upcoming_rows:
                st.dataframe(
                    [{key: value for key, value in row.items() if not key.startswith("_")} for row in upcoming_rows],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("There are no more scheduled windows opening later today.")

    with right:
        with st.container(border=True):
            st.subheader("Recent classroom activity")
            if today_attendance:
                st.dataframe(
                    today_attendance[:12],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No attendance stamps have been recorded yet today.")
        _render_note_card(
            "Operating model",
            "Treat this page as the daily desk: live windows first, recent attendance second, and deep configuration only when you need it.",
            tone="info",
        )


def _render_manager_courses_view(
    repo: AttendanceRepository,
    settings,
    courses: list[dict],
    selected_course,
) -> None:
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

    left, right = st.columns([0.95, 1.45], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Course directory")
            directory_rows = _build_course_directory_rows(settings, courses)
            if directory_rows:
                st.dataframe(directory_rows, use_container_width=True, hide_index=True)
            else:
                st.caption("No course records exist yet.")
            if st.button("Create new course", key="manager_new_course", use_container_width=True):
                st.session_state["manager_course_selector"] = "New course"
                st.session_state["loaded_course_location_signature"] = None
                st.rerun()

        if selected_course is not None:
            with st.container(border=True):
                st.subheader("Working record")
                st.write(f"**{selected_course['code']}**")
                st.caption(selected_course["title"])
                st.caption(
                    f"Dates: {selected_course['start_date']} to {selected_course['end_date']} · "
                    f"Radius {float(selected_course['radius_m']):.1f} m"
                )
        else:
            _render_note_card(
                "New course draft",
                "You are in create mode. Save the course details first, then continue with timetable maintenance and roster imports from the other sections.",
                tone="success",
            )

    with right:
        form_key = f"course_form_{selected_course['id'] if selected_course is not None else 'new'}"
        form_left, form_right = st.columns([1.05, 0.95], gap="large")
        with form_left:
            with st.container(border=True):
                st.subheader("Course record")
                with st.form(form_key, clear_on_submit=False):
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
                    key="seed_demo_course",
                    use_container_width=True,
                ):
                    try:
                        created = seed_demo_data(
                            repo,
                            settings,
                            latitude=float(st.session_state["course_latitude"]),
                            longitude=float(st.session_state["course_longitude"]),
                        )
                        _clear_cached_database_reads()
                        if created:
                            st.success("MAT1116 demo data added successfully.")
                        else:
                            st.info("MAT1116 already exists in the database.")
                    except Exception as error:  # pragma: no cover - Streamlit surface
                        st.error(str(error))

        with form_right:
            with st.container(border=True):
                st.subheader("Classroom location")
                st.caption("Pin the room once. Every student check-in uses this saved boundary.")
                manager_geo = location_picker(
                    latitude=float(st.session_state["course_latitude"]),
                    longitude=float(st.session_state["course_longitude"]),
                    radius_m=float(selected_course["radius_m"]) if selected_course is not None else 3.0,
                    has_selection=_has_course_location_selection(),
                    key=f"manager_location_picker_{selected_course['id'] if selected_course is not None else 'new'}",
                )
                _handle_location_capture(manager_geo, prefix="manager")
                _render_location_summary()

        if selected_course is None:
            _render_empty_state(
                "Save the course to continue",
                "Once the course exists, this page will show its timetable snapshot and roster preview, while the dedicated imports and reports sections unlock the rest of the workflow.",
            )
            return

        lower_left, lower_right = st.columns([1.0, 1.0], gap="large")
        schedules = _cached_list_schedules_for_course(settings.database_target, int(selected_course["id"]))
        students = _cached_list_students_for_course(settings.database_target, int(selected_course["id"]))
        with lower_left:
            with st.container(border=True):
                st.subheader("Weekly windows")
                if schedules:
                    st.dataframe(
                        [
                            {
                                "Day": weekday_label(int(schedule["weekday"])),
                                "Window": schedule["label"],
                                "Start": schedule["start_time"],
                                "End": schedule["end_time"],
                            }
                            for schedule in schedules
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("No timetable windows are configured yet. Use the dedicated Timetable work in this section by continuing below.")
                edited_timetable_rows = st.data_editor(
                    _build_timetable_editor_rows(
                        schedules,
                        show_default_rows=_should_show_default_timetable_rows(
                            int(selected_course["id"]),
                            schedules,
                        ),
                    ),
                    key=_timetable_editor_key(int(selected_course["id"])),
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
                        "remove",
                    ],
                )
                action_left, action_right = st.columns(2, gap="large")
                with action_left:
                    if st.button("Save timetable", key="save_timetable_courses_view", use_container_width=True):
                        _save_timetable(
                            repo=repo,
                            settings=settings,
                            course_id=int(selected_course["id"]),
                            edited_rows=edited_timetable_rows,
                        )
                with action_right:
                    if st.button(
                        "Load L1-L7 defaults",
                        key="load_default_timetable_courses_view",
                        use_container_width=True,
                    ):
                        _show_default_timetable_rows(int(selected_course["id"]))
                        _bump_timetable_editor_version(int(selected_course["id"]))
                        st.session_state["manager_notice"] = "Standard L1-L7 templates are visible in the editor."
                        st.rerun()

        with lower_right:
            with st.container(border=True):
                st.subheader("Roster preview")
                if students:
                    st.dataframe(
                        [
                            {
                                "Student": row["full_name"],
                                "Student ID": row["university_id"],
                                "Email": row["email"],
                            }
                            for row in students[:20]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    if len(students) > 20:
                        st.caption(f"Showing the first 20 roster records out of {len(students)}.")
                else:
                    st.caption("No roster has been imported for this course yet.")
                _render_note_card(
                    "Next step",
                    "Use Imports for full roster intake and Reports when you are ready to export the course workbook.",
                    tone="info",
                )


def _render_manager_students_view(settings, courses: list[dict], selected_course) -> None:
    rows = _build_student_directory_rows(settings, courses)
    filter_options = ["All courses", *[str(course["code"]) for course in courses]]
    preferred_course = selected_course["code"] if selected_course is not None else "All courses"
    if st.session_state.get("students_course_filter") not in filter_options:
        st.session_state["students_course_filter"] = preferred_course

    controls_left, controls_right = st.columns([0.85, 0.5], gap="large")
    with controls_left:
        query = st.text_input("Search students", key="students_search_query", placeholder="Name, ID, or email")
    with controls_right:
        selected_filter = st.selectbox(
            "Course filter",
            options=filter_options,
            key="students_course_filter",
        )

    filtered = rows
    if selected_filter != "All courses":
        filtered = [row for row in filtered if row["Course"] == selected_filter]
    if query.strip():
        query_text = query.strip().lower()
        filtered = [
            row
            for row in filtered
            if query_text in row["Student"].lower()
            or query_text in row["Student ID"].lower()
            or query_text in row["Email"].lower()
        ]

    unique_students = {row["Student ID"] for row in filtered}
    metrics = st.columns(3)
    metrics[0].metric("Enrollments shown", len(filtered))
    metrics[1].metric("Unique students", len(unique_students))
    metrics[2].metric("Courses represented", len({row["Course"] for row in filtered}))

    with st.container(border=True):
        st.subheader("Student directory")
        if filtered:
            st.dataframe(filtered, use_container_width=True, hide_index=True)
        else:
            st.caption("No students match the current filters.")


def _render_manager_attendance_log_view(settings, courses: list[dict], selected_course) -> None:
    rows = _build_attendance_log_rows(settings, courses, per_course_limit=250)
    filter_options = ["All courses", *[str(course["code"]) for course in courses]]
    preferred_course = selected_course["code"] if selected_course is not None else "All courses"
    if st.session_state.get("attendance_course_filter") not in filter_options:
        st.session_state["attendance_course_filter"] = preferred_course

    controls_left, controls_center, controls_right = st.columns([0.65, 0.55, 0.55], gap="large")
    with controls_left:
        selected_filter = st.selectbox(
            "Course filter",
            options=filter_options,
            key="attendance_course_filter",
        )
    with controls_center:
        st.checkbox("Show only today", key="attendance_today_only")
    with controls_right:
        search = st.text_input(
            "Search log",
            key="attendance_log_search",
            placeholder="Student name or ID",
        )

    filtered = rows
    if selected_filter != "All courses":
        filtered = [row for row in filtered if row["Course"] == selected_filter]
    if st.session_state.get("attendance_today_only", False):
        today_key = now_in_app_timezone(settings).date().isoformat()
        filtered = [row for row in filtered if row["Date"] == today_key]
    if search.strip():
        search_text = search.strip().lower()
        filtered = [
            row
            for row in filtered
            if search_text in row["Student"].lower() or search_text in row["Student ID"].lower()
        ]

    metrics = st.columns(3)
    metrics[0].metric("Events shown", len(filtered))
    metrics[1].metric("Students represented", len({row["Student ID"] for row in filtered}))
    metrics[2].metric("Courses represented", len({row["Course"] for row in filtered}))

    with st.container(border=True):
        st.subheader("Recent attendance events")
        if filtered:
            st.dataframe(filtered, use_container_width=True, hide_index=True)
        else:
            st.caption("No attendance events match the current filters.")


def _render_manager_imports_view(repo: AttendanceRepository, settings, selected_course) -> None:
    left, right = st.columns([1.05, 0.95], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Roster intake")
            if selected_course is None:
                st.caption("Select an existing course from the sidebar before replacing its roster.")
            else:
                st.caption(f"Current target course: {selected_course['code']} • {selected_course['title']}")
                _render_roster_importer(repo, settings, selected_course)
                students = _cached_list_students_for_course(settings.database_target, int(selected_course["id"]))
                st.caption(f"Active roster size: {len(students)}")
    with right:
        with st.container(border=True):
            st.subheader("Restore from workbook")
            st.caption("Upload a previously exported workbook to recreate the course, timetable, roster, and attendance history.")
            _render_report_restore_uploader(repo, settings, key_suffix="imports_workspace")
        _render_note_card(
            "Import strategy",
            "Use roster replacement for everyday enrollment updates. Use workbook restore only when rebuilding a course from a prior export.",
            tone="warning",
        )


def _render_manager_report_export_panel(repo: AttendanceRepository, settings, course) -> None:
    eligibility_rows = _build_eligibility_rows(repo, settings, course)
    students = _cached_list_students_for_course(settings.database_target, int(course["id"]))
    schedules = _cached_list_schedules_for_course(settings.database_target, int(course["id"]))
    attendance_records = _cached_list_course_attendance(
        settings.database_target,
        int(course["id"]),
        10000,
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
    st.dataframe(eligibility_rows, use_container_width=True, hide_index=True)


def _render_manager_reports_view(repo: AttendanceRepository, settings, selected_course) -> None:
    if selected_course is None:
        _render_empty_state(
            "Select a course to export",
            "Reports are generated per course. Pick a course from the sidebar, then return here to download the workbook and review diagnostics.",
        )
        return

    report_left, report_right = st.columns([1.12, 0.88], gap="large")
    with report_left:
        with st.container(border=True):
            st.subheader("Export")
            st.caption(f"Generate the workbook for {selected_course['code']} after reviewing the current roster and attendance records.")
            _render_manager_report_export_panel(repo, settings, selected_course)
    with report_right:
        with st.container(border=True):
            st.subheader("Course diagnostics")
            st.caption("Run safe checks on the selected course before exporting or after a restore.")
            _render_diagnostics_panel(repo, settings, selected_course)


def _render_manager_settings_view(repo: AttendanceRepository, settings, courses: list[dict]) -> None:
    metrics = st.columns(4)
    metrics[0].metric("Courses", len(courses))
    metrics[1].metric("Environment", settings.app_env.capitalize())
    metrics[2].metric("OTP mode", _otp_mode_label(settings))
    metrics[3].metric("Database", repo.backend.upper())

    left, right = st.columns([1.0, 1.0], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Configuration")
            settings_rows = [
                {"Setting": "Timezone", "Value": settings.app_timezone},
                {"Setting": "Environment", "Value": settings.app_env},
                {"Setting": "OTP delivery", "Value": settings.otp_delivery_mode},
                {"Setting": "Manager username", "Value": settings.manager_username or "Not configured"},
                {"Setting": "SMTP host", "Value": settings.smtp_host or "Not configured"},
                {"Setting": "Database backend", "Value": repo.backend},
            ]
            st.dataframe(settings_rows, use_container_width=True, hide_index=True)
    with right:
        with st.container(border=True):
            st.subheader("Operational checks")
            st.caption("This is a lightweight health pass over the configured data sources.")
            if st.button("Run system health check", key="run_system_health_check", use_container_width=True):
                try:
                    repo.list_courses()
                    if courses:
                        course_id = int(courses[0]["id"])
                        repo.list_schedules_for_course(course_id)
                        repo.list_students_for_course(course_id)
                    st.success("System health check passed.")
                except Exception as error:  # pragma: no cover - Streamlit surface
                    st.error(_safe_health_error(error))
        _render_note_card(
            "Security note",
            "This app still uses a single protected instructor account. For a fully production-grade rollout, place the back office behind organization identity and audit controls.",
            tone="warning",
        )


def _render_manager_overview_tab(
    repo: AttendanceRepository,
    settings,
    courses: list[dict],
    active_course,
) -> None:
    _render_page_intro(
        "Overview",
        "See the course at a glance",
        "This workspace keeps the selected course healthy while the detailed work happens in the dedicated setup, timetable, roster, and reports screens.",
    )

    if active_course is None:
        _render_empty_state(
            "Start with a course",
            "Use Course Setup to create one from scratch, or restore a previously exported workbook below.",
        )
        _render_report_restore_uploader(repo, settings, key_suffix="overview_bootstrap")
        return

    recent_attendance = _cached_list_course_attendance(
        settings.database_target,
        int(active_course["id"]),
        12,
    )
    left, right = st.columns([1.3, 1.0], gap="large")

    with left:
        with st.container(border=True):
            st.subheader("Course snapshot")
            st.caption(
                f"{active_course['code']} • {active_course['title']} • "
                f"{active_course['start_date']} to {active_course['end_date']}"
            )
            _render_location_summary()

        with st.container(border=True):
            st.subheader("Recent attendance activity")
            if recent_attendance:
                st.dataframe(
                    [
                        {
                            "Date": row["attendance_date"],
                            "Student": row["full_name"],
                            "Window": row["schedule_label"],
                            "Stamped At": row["stamped_at"],
                        }
                        for row in recent_attendance
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No attendance stamps have been recorded for this course yet.")

    with right:
        _render_note_card(
            "Recommended flow",
            "Keep course details current first, then maintain the timetable, import the roster, and only export reports after the live data looks healthy.",
            tone="success",
        )
        _render_note_card(
            "Reporting workspace",
            "The Reports workspace now groups export, restore, and diagnostics so operational checks live in one place instead of interrupting setup.",
            tone="info",
        )
        if settings.app_env == "development":
            _render_note_card(
                "Development helper",
                "Need a quick end-to-end test? Create a live class window for the selected course and verify the student flow right away.",
                tone="warning",
            )
            if st.button("Create live test window now", use_container_width=True):
                _create_live_test_window(
                    repo=repo,
                    settings=settings,
                    course_id=int(active_course["id"]),
                )

        st.metric("Courses in system", len(courses))
        st.metric("Environment", settings.app_env.capitalize())


def _render_manager_course_tab(
    repo: AttendanceRepository,
    settings,
    selected_course,
    selected_start_date: date,
    selected_end_date: date,
    selected_radius: float,
    selected_absence_limit: float,
) -> None:
    _render_page_intro(
        "Course setup",
        "Define the academic container",
        "Save the course profile, classroom radius, and map-based geofence here. Once this is stable, the other workspaces stay cleaner.",
    )

    left, right = st.columns([1.15, 1.0], gap="large")
    with left:
        st.markdown('<p class="aa-subsection">Course profile</p>', unsafe_allow_html=True)
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
                _clear_cached_database_reads()
                if created:
                    st.success("MAT1116 demo data added successfully.")
                else:
                    st.info("MAT1116 already exists in the database.")
            except Exception as error:  # pragma: no cover - Streamlit surface
                st.error(str(error))

    with right:
        _render_note_card(
            "Classroom location",
            "Pin the room on the map and the selected point becomes the center of the attendance boundary used for student access and stamping.",
            tone="info",
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
        _render_note_card(
            "Security reminder",
            "For public deployments, keep instructor access in secrets and place the app behind a trusted identity layer instead of relying only on a single shared password.",
            tone="warning",
        )


def _render_manager_timetable_tab(repo: AttendanceRepository, settings, active_course) -> None:
    _render_page_intro(
        "Timetable",
        "Control when attendance is live",
        "Students can request access and stamp attendance only during active timetable windows, so this workspace becomes the live control center.",
    )

    if active_course is None:
        _render_empty_state(
            "A saved course is required",
            "Create or select a course in Course Setup before you manage live attendance windows here.",
        )
        return

    schedules = _cached_list_schedules_for_course(settings.database_target, int(active_course["id"]))
    _render_note_card(
        "Editing rules",
        "Build or revise timetable rows in the grid below. Rows marked for removal are deleted on save, and linked attendance for removed windows may be affected.",
        tone="info",
    )

    timetable_rows = _build_timetable_editor_rows(
        schedules,
        show_default_rows=_should_show_default_timetable_rows(
            int(active_course["id"]),
            schedules,
        ),
    )
    edited_timetable_rows = st.data_editor(
        timetable_rows,
        key=_timetable_editor_key(int(active_course["id"])),
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
            "remove",
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
            "remove": st.column_config.CheckboxColumn(
                "Remove",
                help="Tick this row and save timetable to remove it.",
                default=False,
            ),
        },
    )
    action_left, action_right = st.columns(2, gap="large")
    with action_left:
        if st.button("Save timetable", use_container_width=True):
            _save_timetable(
                repo=repo,
                settings=settings,
                course_id=int(active_course["id"]),
                edited_rows=edited_timetable_rows,
            )
    with action_right:
        if st.button("Load standard L1-L7 templates", use_container_width=True):
            _show_default_timetable_rows(int(active_course["id"]))
            _bump_timetable_editor_version(int(active_course["id"]))
            st.session_state["manager_notice"] = "Standard L1-L7 templates are visible in the editor."
            st.rerun()


def _render_manager_roster_tab(repo: AttendanceRepository, settings, active_course) -> None:
    _render_page_intro(
        "Roster",
        "Keep the enrolled students accurate",
        "This workspace is only for the class list. Upload a clean roster and review the active student records without timetable or reporting noise around it.",
    )

    if active_course is None:
        _render_empty_state(
            "A saved course is required",
            "Create or select a course first, then import the class roster for that course here.",
        )
        return

    st.markdown('<p class="aa-subsection">Roster import</p>', unsafe_allow_html=True)
    st.caption(
        "Upload a `.xlsx` or `.csv` file with columns: `student id`, `student name`, `email`. The uploaded file replaces the entire roster for this course."
    )
    _render_roster_importer(repo, settings, active_course)

    students = _cached_list_students_for_course(settings.database_target, int(active_course["id"]))
    with st.container(border=True):
        st.subheader("Active students")
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


def _render_manager_reports_tab(repo: AttendanceRepository, settings, active_course) -> None:
    _render_page_intro(
        "Reports",
        "Export, restore, and verify the course",
        "Operational exports, workbook restores, and safe health checks now live together so the reporting workflow feels like a finishing step instead of an interruption.",
    )

    if active_course is None:
        _render_empty_state(
            "Nothing to report yet",
            "Select a saved course to export a report, or restore a course from a workbook below.",
        )
        _render_report_restore_uploader(repo, settings, key_suffix="reports_bootstrap")
        return

    _render_report_downloads(repo, settings, active_course)


def render_student_page(repo: AttendanceRepository, settings, section: str) -> None:
    auth = st.session_state.get("student_auth")

    if not auth:
        st.session_state["student_section"] = "Start"
        _render_route_header(
            "Student check-in",
            "Start",
            "Verify classroom presence, request a one-time code, and sign in before you submit attendance.",
            tags=[_otp_mode_label(settings), settings.app_timezone],
        )
        left, right = st.columns([0.9, 1.15], gap="large")
        with left:
            _render_student_step_rail(settings)
            _render_otp_delivery_notice(settings)
        with right:
            _render_student_login(repo, settings)
        return

    course = _cached_get_course(settings.database_target, int(auth["course_id"]))
    student = repo.get_student(int(auth["student_id"]))
    if course is None or student is None:
        st.session_state["student_auth"] = None
        st.session_state["student_section"] = "Start"
        _reset_student_access_flow(clear_student_id=False)
        st.warning("Your session is no longer valid. Please sign in again.")
        return

    schedules = _cached_list_schedules_for_course(settings.database_target, int(course["id"]))
    active_schedule = find_active_schedule(schedules, now_in_app_timezone(settings))
    if active_schedule is None:
        st.session_state["student_auth"] = None
        st.session_state["student_section"] = "Start"
        _reset_student_access_flow(clear_student_id=False)
        st.warning(
            "Student access is available only during the active timetable window. "
            "Please request access again during class."
        )
        return

    summary = build_student_attendance_summary(
        repo,
        settings,
        course=course,
        student=student,
        schedules=schedules,
        attended_count=_cached_count_attendance(
            settings.database_target,
            int(course["id"]),
            int(student["id"]),
        ),
    )
    recent_records = _cached_list_attendance(
        settings.database_target,
        int(course["id"]),
        int(student["id"]),
        30,
    )

    header_left, header_right = st.columns([2.9, 0.95], gap="large")
    with header_left:
        descriptions = {
            "Check In": "Use this screen during class to capture location and submit attendance before the active window closes.",
            "Status": "Review attendance standing, absence exposure, and eligibility without leaving the student app.",
            "History": "Review your recent attendance records and confirm what has already been stamped.",
        }
        _render_route_header(
            "Student check-in app",
            section,
            descriptions.get(section, descriptions["Check In"]),
            tags=[course["code"], active_schedule["label"], settings.app_timezone],
        )
    with header_right:
        st.markdown(
            f'<div class="aa-user-pill">{escape(student["full_name"])}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Sign out", key="student_signout", use_container_width=True):
            st.session_state["student_auth"] = None
            st.session_state["student_section"] = "Start"
            _reset_student_access_flow(clear_student_id=False)
            _clear_cached_database_reads()
            st.rerun()

    metrics = st.columns(4)
    metrics[0].metric("Attended", summary.attended_count)
    metrics[1].metric("Absences", summary.absences)
    metrics[2].metric("Meetings elapsed", summary.elapsed_meetings)
    metrics[3].metric("Total meetings", summary.total_meetings)

    if section == "Status":
        _render_student_status_workspace(summary, course, settings, active_schedule)
        return
    if section == "History":
        _render_student_history_workspace(recent_records)
        return
    _render_student_check_in_workspace(repo, settings, course, student, active_schedule)


def _render_student_step_rail(settings) -> None:
    otp_text = "shown inside the app" if settings.otp_delivery_mode == "console" else "sent to your roster email"
    st.markdown(
        f"""
        <div class="aa-step-rail">
            <div class="aa-step-item">
                <div class="aa-step-index">1</div>
                <div class="aa-step-content">
                    <h4>Identify yourself</h4>
                    <p>Enter the student ID that appears on your enrolled course roster.</p>
                </div>
            </div>
            <div class="aa-step-item">
                <div class="aa-step-index">2</div>
                <div class="aa-step-content">
                    <h4>Verify classroom location</h4>
                    <p>Access opens only while a course window is active and only inside the saved classroom boundary.</p>
                </div>
            </div>
            <div class="aa-step-item">
                <div class="aa-step-index">3</div>
                <div class="aa-step-content">
                    <h4>Request a one-time code</h4>
                    <p>The latest access code is {escape(otp_text)}.</p>
                </div>
            </div>
            <div class="aa-step-item">
                <div class="aa-step-index">4</div>
                <div class="aa-step-content">
                    <h4>Confirm attendance</h4>
                    <p>After sign-in, capture your location again and submit the attendance stamp before the window closes.</p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_student_check_in_workspace(
    repo: AttendanceRepository,
    settings,
    course,
    student,
    active_schedule,
) -> None:
    left, right = st.columns([1.12, 0.88], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Submit attendance")
            st.caption(
                f"{course['code']} • {course['title']} • Window {active_schedule['label']} "
                f"({active_schedule['start_time']} - {active_schedule['end_time']})"
            )
            student_stamp_geo = geo_capture(
                button_label="Share current location to stamp attendance",
                key="student_stamp_geo_capture",
            )
            _handle_student_stamp_gate(student_stamp_geo)
            if st.session_state.get("student_stamp_geolocation") is not None:
                st.info("Location captured. Submit the attendance stamp while the class window remains open.")

            if (
                st.session_state.get("student_stamp_result") is None
                and st.session_state.get("student_stamp_geolocation") is not None
                and st.button("Submit attendance", key="student_submit_attendance", use_container_width=True)
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
                    _clear_cached_database_reads()
                st.rerun()

            stamp_result = st.session_state.get("student_stamp_result")
            if stamp_result:
                if stamp_result["success"]:
                    st.success(stamp_result["message"])
                else:
                    st.error(stamp_result["message"])

    with right:
        with st.container(border=True):
            st.subheader("Session details")
            st.markdown(
                f"""
                <ul class="aa-compact-list">
                    <li><strong>Student</strong><span>{escape(student["full_name"])} · {escape(str(student["university_id"]))}</span></li>
                    <li><strong>Course</strong><span>{escape(course["code"])} · {escape(course["title"])}</span></li>
                    <li><strong>Open window</strong><span>{escape(active_schedule["label"])} · {escape(active_schedule["start_time"])} - {escape(active_schedule["end_time"])}</span></li>
                    <li><strong>Radius</strong><span>{float(course["radius_m"]):.1f} meters</span></li>
                    <li><strong>Timezone</strong><span>{escape(settings.app_timezone)}</span></li>
                </ul>
                """,
                unsafe_allow_html=True,
            )
        _render_note_card(
            "Check-in rule",
            "Attendance is accepted only while this course window is active and your reported location is inside the saved classroom boundary.",
            tone="info",
        )


def _render_student_status_workspace(summary, course, settings, active_schedule) -> None:
    left, right = st.columns([1.0, 0.95], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Attendance standing")
            if summary.denied_exam_entry:
                st.error("Exam entry is currently denied because you reached the absence threshold.")
            else:
                st.success(
                    f"You are still eligible for exam entry. Safe absences remaining: {summary.remaining_safe_absences}."
                )
            st.progress(
                int(round(max(0.0, min(summary.attendance_pct_of_total, 100.0)))),
                text=f"Attendance recorded: {summary.attendance_pct_of_total:.1f}% of total meetings",
            )
            st.caption(
                f"Absence threshold: {summary.absence_threshold} meetings • "
                f"Absence exposure: {summary.absence_pct_of_total:.1f}% of total meetings"
            )
    with right:
        with st.container(border=True):
            st.subheader("Course policy")
            st.markdown(
                f"""
                <ul class="aa-compact-list">
                    <li><strong>Course</strong><span>{escape(course["code"])} · {escape(course["title"])}</span></li>
                    <li><strong>Absence limit</strong><span>{float(course["absence_limit_pct"]):.0f}%</span></li>
                    <li><strong>Current window</strong><span>{escape(active_schedule["label"])} · {escape(active_schedule["start_time"])} - {escape(active_schedule["end_time"])}</span></li>
                    <li><strong>Timezone</strong><span>{escape(settings.app_timezone)}</span></li>
                </ul>
                """,
                unsafe_allow_html=True,
            )


def _render_student_history_workspace(recent_records: list[dict]) -> None:
    with st.container(border=True):
        st.subheader("Recent attendance records")
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


def _render_student_checkin_tab(
    repo: AttendanceRepository,
    settings,
    course,
    student,
    active_schedule,
) -> None:
    _render_page_intro(
        "Check in",
        "Stamp attendance while the window is active",
        "Capture your classroom location first, then submit the stamp before the current time window closes.",
    )
    left, right = st.columns([1.25, 0.9], gap="large")

    with left:
        with st.container(border=True):
            st.subheader("Live attendance stamp")
            st.write(
                "Share your current classroom location, then submit the attendance stamp while this class window is open."
            )
            student_stamp_geo = geo_capture(
                button_label="Share current location to stamp attendance",
                key="student_stamp_geo_capture",
            )
            _handle_student_stamp_gate(student_stamp_geo)
            if st.session_state.get("student_stamp_geolocation") is not None:
                st.info(
                    "Location captured. Submit your attendance stamp while this class window is still open."
                )

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
                    _clear_cached_database_reads()
                st.rerun()

            stamp_result = st.session_state.get("student_stamp_result")
            if stamp_result:
                if stamp_result["success"]:
                    st.success(stamp_result["message"])
                else:
                    st.error(stamp_result["message"])

    with right:
        _render_note_card(
            "Current session",
            f"{active_schedule['label']} is open from {active_schedule['start_time']} to {active_schedule['end_time']} in {settings.app_timezone}.",
            tone="success",
        )
        _render_note_card(
            "Attendance rules",
            f"You must be inside the saved classroom boundary of {float(course['radius_m']):.1f} meters for this course.",
            tone="info",
        )
        st.markdown(
            f"""
            <div class="aa-surface aa-surface-muted">
                <h3>Session details</h3>
                <div class="aa-detail-list">
                    <div class="aa-detail-row">
                        <span class="aa-label">Course</span>
                        <span class="aa-value">{escape(course["code"])} · {escape(course["title"])}</span>
                    </div>
                    <div class="aa-detail-row">
                        <span class="aa-label">Window</span>
                        <span class="aa-value">{escape(active_schedule["label"])}</span>
                    </div>
                    <div class="aa-detail-row">
                        <span class="aa-label">Time</span>
                        <span class="aa-value">{escape(active_schedule["start_time"])} - {escape(active_schedule["end_time"])}</span>
                    </div>
                    <div class="aa-detail-row">
                        <span class="aa-label">Timezone</span>
                        <span class="aa-value">{escape(settings.app_timezone)}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_student_attendance_tab(recent_records: list[dict]) -> None:
    _render_page_intro(
        "Attendance history",
        "Review your recent classroom records",
        "Use this table to confirm your recent stamps, recorded windows, and the location accuracy stored with each attendance event.",
    )
    with st.container(border=True):
        st.subheader("Recent attendance")
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


def _render_student_status_tab(summary, course, settings, active_schedule) -> None:
    _render_page_intro(
        "Standing",
        "Track exam eligibility and attendance health",
        "This workspace keeps the attendance percentage, absence exposure, and course policy together so students understand their status clearly.",
    )
    left, right = st.columns([1.15, 0.95], gap="large")

    with left:
        with st.container(border=True):
            st.subheader("Exam standing")
            if summary.denied_exam_entry:
                st.error("Exam entry is currently denied because you reached the absence threshold.")
            else:
                st.success(
                    f"You are still eligible for exam entry. Safe absences remaining: {summary.remaining_safe_absences}."
                )
            st.progress(
                int(round(max(0.0, min(summary.attendance_pct_of_total, 100.0)))),
                text=f"Attendance recorded: {summary.attendance_pct_of_total:.1f}% of total meetings",
            )
            st.caption(
                f"Absence threshold: {summary.absence_threshold} meetings • "
                f"Absence exposure: {summary.absence_pct_of_total:.1f}% of total meetings"
            )

    with right:
        pill_class = "aa-risk" if summary.denied_exam_entry else "aa-good"
        pill_label = "Action required" if summary.denied_exam_entry else "Eligible"
        st.markdown(
            f"""
            <div class="aa-surface aa-surface-muted">
                <span class="aa-status-pill {pill_class}">{escape(pill_label)}</span>
                <h3>Course rules</h3>
                <div class="aa-detail-list">
                    <div class="aa-detail-row">
                        <span class="aa-label">Course</span>
                        <span class="aa-value">{escape(course["code"])}</span>
                    </div>
                    <div class="aa-detail-row">
                        <span class="aa-label">Absence limit</span>
                        <span class="aa-value">{float(course["absence_limit_pct"]):.0f}%</span>
                    </div>
                    <div class="aa-detail-row">
                        <span class="aa-label">Current window</span>
                        <span class="aa-value">{escape(active_schedule["label"])} · {escape(active_schedule["start_time"])} - {escape(active_schedule["end_time"])}</span>
                    </div>
                    <div class="aa-detail-row">
                        <span class="aa-label">Timezone</span>
                        <span class="aa-value">{escape(settings.app_timezone)}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_student_login(repo: AttendanceRepository, settings) -> None:
    with st.container(border=True):
        st.subheader("1. Verify classroom access")
        st.write(
            "Enter your student ID and share your current location. Access works only during a live class window and only inside the saved classroom boundary."
        )
        university_id = st.text_input(
            "Student ID",
            value=st.session_state.get("pending_university_id", ""),
            key="student_login_id_input",
        )
        if university_id.strip() != st.session_state.get("pending_university_id", ""):
            _reset_student_access_flow(clear_student_id=False)
            st.session_state["pending_university_id"] = university_id.strip()

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
            "The classroom location or active timetable changed. Share your location again to continue with the current course settings."
        )
        return

    st.success(
        f"Access verified for {access_context['student_name']}. You are "
        f"{access_context['distance_m']:.2f} m from class and inside "
        f"{access_context['schedule_label']} "
        f"({access_context['schedule_start_time']} - {access_context['schedule_end_time']})."
    )
    access_cols = st.columns(3)
    access_cols[0].metric("Course", access_context["course_code"])
    access_cols[1].metric("Window", access_context["schedule_label"])
    access_cols[2].metric("Distance", f"{access_context['distance_m']:.2f} m")
    st.caption(access_context["course_title"])

    with st.container(border=True):
        st.subheader("2. Request one-time code")
        if settings.otp_delivery_mode == "console":
            st.write("Generate a code and use the latest value shown on this page.")
            otp_button_label = "Generate code"
        else:
            st.write("Generate a code and check the email address saved on your roster.")
            otp_button_label = "Generate code via email"

        configuration_error = otp_delivery_configuration_error(settings)
        if configuration_error:
            st.error(configuration_error)
            return

        if st.button(otp_button_label, use_container_width=True):
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

        otp_notice = st.session_state.get("student_otp_notice")
        if otp_notice:
            st.info(otp_notice)

        otp_preview_code = st.session_state.get("student_otp_preview_code")
        if otp_preview_code:
            st.markdown(
                f"""
                <div class="aa-otp-card">
                    <h3>Latest code</h3>
                    <p>Use this code in the login form below before it expires.</p>
                    <div class="aa-otp-code">{escape(str(otp_preview_code))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if not st.session_state.get("student_otp_requested", False):
        return

    with st.container(border=True):
        st.subheader("3. Log in")
        st.write(_otp_entry_help_text(settings))
        with st.form("student_otp_login_form"):
            otp_code = st.text_input(
                "One-time code",
                type="password",
                key="student_otp_code_input",
            )
            submit_login = st.form_submit_button("Log in", use_container_width=True)

        if submit_login:
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
                st.session_state["student_section"] = "Check In"
                st.session_state["student_stamp_result"] = None
                st.session_state["student_stamp_geolocation"] = None
                st.session_state["student_otp_notice"] = None
                st.session_state["student_otp_preview_code"] = None
                st.rerun()
            except Exception as error:  # pragma: no cover - Streamlit surface
                st.error(str(error))


def _render_student_portal_intro(settings) -> None:
    otp_mode_label = "on-page preview" if settings.otp_delivery_mode == "console" else "roster email"
    st.markdown(
        f"""
        <div class="aa-surface aa-surface-muted">
            <span class="aa-kicker">How it works</span>
            <h3>Students move through one clear sequence</h3>
            <p>
                Access only works during an active class window and only inside the classroom boundary saved by the instructor.
                The current one-time code delivery mode is {escape(otp_mode_label)}.
            </p>
            <ul class="aa-list">
                <li>Verify classroom access with student ID and live location.</li>
                <li>Request the latest one-time login code.</li>
                <li>Sign in and stamp attendance before the window closes.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
        _clear_cached_database_reads()
        st.session_state["loaded_course_location_signature"] = None
        st.session_state["pending_manager_course_selector"] = normalized_code
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
        _clear_cached_database_reads()
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
        _clear_cached_database_reads()
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
        _clear_cached_database_reads()
        st.session_state["manager_notice"] = (
            f"Roster synchronized for {course['code']}. {len(roster_rows)} student records are active."
        )
        st.rerun()


def _render_report_downloads(repo: AttendanceRepository, settings, course) -> None:
    _render_report_restore_uploader(repo, settings, key_suffix=str(course["id"]))
    _render_diagnostics_panel(repo, settings, course)
    st.markdown('<p class="aa-subsection">📊 Export Current Report</p>', unsafe_allow_html=True)
    students = _cached_list_students_for_course(settings.database_target, int(course["id"]))
    schedules = _cached_list_schedules_for_course(settings.database_target, int(course["id"]))
    attendance_records = _cached_list_course_attendance(
        settings.database_target,
        int(course["id"]),
        10000,
    )
    attendance_counts = _cached_count_attendance_by_student_for_course(
        settings.database_target,
        int(course["id"]),
    )

    eligibility_rows = []
    for student in students:
        student_id = int(student["id"])
        summary = build_student_attendance_summary(
            repo,
            settings,
            course=course,
            student=student,
            schedules=schedules,
            attended_count=attendance_counts.get(student_id, 0),
        )
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


def _render_diagnostics_panel(repo: AttendanceRepository, settings, course) -> None:
    st.markdown('<p class="aa-subsection">🩺 App Diagnostics</p>', unsafe_allow_html=True)
    with st.expander("View safe health checks", expanded=False):
        course_id = int(course["id"])
        students = _cached_list_students_for_course(settings.database_target, course_id)
        schedules = _cached_list_schedules_for_course(settings.database_target, course_id)
        attendance_rows = _cached_list_course_attendance(settings.database_target, course_id, 10000)
        all_courses = _cached_list_courses(settings.database_target)

        health_rows = [
            {"Check": "Database backend", "Status": repo.backend.upper(), "Details": _database_backend_label(repo)},
            {"Check": "App environment", "Status": settings.app_env, "Details": "Runtime mode"},
            {"Check": "Timezone", "Status": settings.app_timezone, "Details": "Used for schedules and stamps"},
            {"Check": "OTP mode", "Status": settings.otp_delivery_mode, "Details": _otp_diagnostics_detail(settings)},
            {"Check": "Manager credentials", "Status": "Configured" if settings.manager_username and settings.manager_password_hash else "Missing", "Details": "Username/password hash only"},
            {"Check": "Courses", "Status": str(len(all_courses)), "Details": "Configured course records"},
            {"Check": "Selected roster", "Status": str(len(students)), "Details": f"{course['code']} enrolled students"},
            {"Check": "Selected timetable", "Status": str(len(schedules)), "Details": f"{course['code']} active windows"},
            {"Check": "Selected attendance", "Status": str(len(attendance_rows)), "Details": "Report export rows currently loaded"},
            {"Check": "Last health check", "Status": now_in_app_timezone(settings).strftime("%Y-%m-%d %H:%M:%S"), "Details": "Riyadh app time"},
        ]
        st.dataframe(health_rows, use_container_width=True, hide_index=True)

        if st.button("Run database health check", use_container_width=True):
            try:
                repo.list_courses()
                repo.list_schedules_for_course(course_id)
                repo.list_students_for_course(course_id)
                st.success("Database health check passed.")
            except Exception as error:  # pragma: no cover - Streamlit surface
                st.error(_safe_health_error(error))


def _database_backend_label(repo: AttendanceRepository) -> str:
    if repo.backend == "postgres":
        return "Persistent hosted database"
    return "Local SQLite file"


def _otp_diagnostics_detail(settings) -> str:
    if settings.otp_delivery_mode == "email":
        return "SMTP configured" if settings.smtp_host and settings.smtp_sender else "SMTP incomplete"
    if settings.otp_delivery_mode == "console":
        return "Codes are shown in the app"
    return "Unsupported mode"


def _safe_health_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "Health check failed. See Streamlit logs for details."
    return message[:500]


def _prepare_manager_course_selector(course_options: list[str]) -> None:
    pending_course = st.session_state.pop("pending_manager_course_selector", None)
    if pending_course is not None:
        st.session_state["manager_course_selector"] = (
            pending_course if pending_course in course_options else "New course"
        )
        return

    current_course = st.session_state.get("manager_course_selector", "New course")
    if current_course not in course_options:
        st.session_state["manager_course_selector"] = "New course"


def _render_report_restore_uploader(repo: AttendanceRepository, settings, *, key_suffix: str) -> None:
    st.markdown('<p class="aa-subsection">📥 Restore From Report</p>', unsafe_allow_html=True)
    st.caption(
        "Upload a previously exported attendance report workbook to restore a course, roster, "
        "timetable, and attendance history into the current database."
    )
    restore_file = st.file_uploader(
        "Attendance report workbook",
        type=["xlsx"],
        key=f"restore_report_{key_suffix}",
        label_visibility="collapsed",
    )
    if restore_file is None:
        return

    if st.button(
        "Restore course from report",
        key=f"restore_report_button_{key_suffix}",
        use_container_width=True,
    ):
        try:
            summary = import_attendance_report_bytes(
                repo=repo,
                settings=settings,
                source_name=restore_file.name,
                content=restore_file.getvalue(),
            )
            _clear_cached_database_reads()
            st.session_state["pending_manager_course_selector"] = str(summary["course_code"])
            st.session_state["manager_notice"] = (
                f"Restored {summary['course_code']} with {summary['roster_rows']} roster rows, "
                f"{summary['schedule_rows']} timetable rows, and {summary['imported_attendance']} "
                "attendance records."
            )
            st.rerun()
        except Exception as error:  # pragma: no cover - Streamlit surface
            st.error(str(error))


def _render_manager_auth(settings) -> bool:
    if st.session_state.get("manager_auth") is not None:
        return True

    st.markdown(
        """
        <div class="aa-signin-card">
            <span class="aa-kicker">Protected access</span>
            <h2>Instructor sign in</h2>
            <p>Only the authorized academic operator can configure courses, update rosters, and export reports.</p>
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
        _render_note_card("Delivery setup needs attention", configuration_error, tone="warning")
        return
    if settings.otp_delivery_mode == "console":
        _render_note_card(
            "Development shortcut",
            "Console OTP mode is active, so students see the latest login code inside the app during testing.",
            tone="info",
        )


def _otp_entry_help_text(settings) -> str:
    if settings.otp_delivery_mode == "console":
        return "Use the latest code shown above. Each login requires a fresh code."
    return "Use the latest code sent to your roster email. Each login requires a fresh code."


def _otp_workflow_label(settings) -> str:
    if settings.otp_delivery_mode == "email":
        return "email OTP workflows"
    return "one-time code workflows"


def _student_sidebar_otp_text(settings) -> str:
    if settings.otp_delivery_mode == "email":
        return "Students authenticate via a one-time code sent to their roster email."
    return "Students authenticate via a one-time code shown inside the app."


def _build_timetable_editor_rows(schedules, *, show_default_rows: bool) -> list[dict[str, object]]:
    rows_by_label: dict[str, dict[str, object]] = {}
    ordered_labels: list[str] = []

    if show_default_rows:
        for default_row in DEFAULT_TIMETABLE_ROWS:
            label = str(default_row["label"])
            row = _empty_timetable_editor_row(
                label=label,
                start_time=str(default_row["start_time"]),
                end_time=str(default_row["end_time"]),
            )
            rows_by_label[label] = row
            ordered_labels.append(label)

    for schedule in schedules:
        label = str(schedule["label"])
        row = rows_by_label.get(label)
        if row is None:
            row = _empty_timetable_editor_row(
                label=label,
                start_time=str(schedule["start_time"]),
                end_time=str(schedule["end_time"]),
            )
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
        if bool(row.get("remove", False)):
            continue
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
        _hide_default_timetable_rows(course_id)
        _bump_timetable_editor_version(course_id)
        _clear_cached_database_reads()
        st.session_state["manager_notice"] = "Course timetable saved successfully."
        st.rerun()
    except Exception as error:  # pragma: no cover - Streamlit surface
        st.error(str(error))


def _weekday_to_editor_day_name(weekday: int) -> str | None:
    for day_name, mapped_weekday in TIMETABLE_DAY_COLUMNS:
        if mapped_weekday == weekday:
            return day_name
    return None


def _empty_timetable_editor_row(*, label: str, start_time: str, end_time: str) -> dict[str, object]:
    row: dict[str, object] = {
        "label": label,
        "start_time": start_time,
        "end_time": end_time,
        "remove": False,
    }
    for day_name, _weekday in TIMETABLE_DAY_COLUMNS:
        row[day_name] = False
    return row


def _should_show_default_timetable_rows(course_id: int, schedules) -> bool:
    return not schedules or bool(st.session_state.get(_show_default_timetable_key(course_id), False))


def _show_default_timetable_rows(course_id: int) -> None:
    st.session_state[_show_default_timetable_key(course_id)] = True


def _hide_default_timetable_rows(course_id: int) -> None:
    st.session_state[_show_default_timetable_key(course_id)] = False


def _show_default_timetable_key(course_id: int) -> str:
    return f"show_default_timetable_rows_{course_id}"


def _timetable_editor_key(course_id: int) -> str:
    version = st.session_state.get(_timetable_editor_version_key(course_id), 0)
    return f"timetable_editor_{course_id}_{version}"


def _bump_timetable_editor_version(course_id: int) -> None:
    key = _timetable_editor_version_key(course_id)
    st.session_state[key] = int(st.session_state.get(key, 0)) + 1


def _timetable_editor_version_key(course_id: int) -> str:
    return f"timetable_editor_version_{course_id}"


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


def _render_course_summary(repo: AttendanceRepository, settings, course) -> None:
    students = _cached_list_students_for_course(settings.database_target, int(course["id"]))
    schedules = _cached_list_schedules_for_course(settings.database_target, int(course["id"]))
    attendance_rows = _cached_list_course_attendance(
        settings.database_target,
        int(course["id"]),
        10000,
    )
    st.markdown(
        f"""
        <div class="aa-course-banner">
            <div>
                <span class="aa-kicker">Selected course</span>
                <h3>{escape(course["code"])} · {escape(course["title"])}</h3>
                <p>
                    Runs from {escape(course["start_date"])} to {escape(course["end_date"])} with a
                    {float(course["radius_m"]):.1f} meter classroom boundary and a
                    {float(course["absence_limit_pct"]):.0f}% absence limit.
                </p>
            </div>
            <div class="aa-banner-tags">
                <span class="aa-banner-tag">{len(students)} students</span>
                <span class="aa-banner-tag">{len(schedules)} timetable windows</span>
                <span class="aa-banner-tag">{len(attendance_rows)} attendance stamps</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    summary_columns = st.columns(4)
    summary_columns[0].metric("Course", course["code"])
    summary_columns[1].metric("Roster", len(students))
    summary_columns[2].metric("Timetable windows", len(schedules))
    summary_columns[3].metric("Attendance stamps", len(attendance_rows))


def _render_location_summary() -> None:
    if not _has_course_location_selection():
        _render_note_card(
            "No classroom location selected yet",
            "Choose a point on the map or use your device location before saving the course.",
            tone="warning",
        )
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
    course = _cached_get_course(settings.database_target, int(access_context["course_id"]))
    if course is None:
        return False

    if abs(float(course["latitude"]) - float(access_context["course_latitude"])) > 1e-9:
        return False
    if abs(float(course["longitude"]) - float(access_context["course_longitude"])) > 1e-9:
        return False
    if abs(float(course["radius_m"]) - float(access_context["radius_m"])) > 1e-9:
        return False

    schedules = _cached_list_schedules_for_course(settings.database_target, int(course["id"]))
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
    st.session_state.setdefault("manager_section", MANAGER_SECTIONS[0])
    st.session_state.setdefault("student_auth", None)
    st.session_state.setdefault("student_section", "Start")
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
