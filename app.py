import os
import glob
import json
import datetime
from urllib.parse import quote
import html as _html

import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import streamlit.components.v1 as components

# Optional: Server-side PDF generation if WeasyPrint is available
try:
    from weasyprint import HTML, CSS
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False

# ----------------------------------------------------------------------
# 1. Page Configuration & Setup
# ----------------------------------------------------------------------
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 Dynamic Engineering Resource Planner - ACKD")

BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

TEAMS = {
    "Tech Team": {
        "sheet_id": "1RUqihUZreld3OY9M2cuPWtpxtuCS9p-2ut0FCFFwFvQ",
        "gid": None,
        "mode": "hours",
        "count_sheet": "team count",
        "count_gid": None,
        "disciplines": ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"],
        "engineers": [17, 12, 5, 6, 12],
    },
    "Design Team": {
        "sheet_id": "15AR4hB_q1JZ1SIwegy2ieusDkPQAMSXFG5uG7Y2zaFg",
        "gid": None,
        "mode": "team_count",
        "disciplines": ["Arch Design Team"],
        "engineers": [21],
    },
    "BIM Team": {
        "sheet_id": "1g9lFbLem738PcQ3FOWGjXZJopwWnf2g5-ncS6dUwNn8",
        "gid": None,
        "mode": "team_count",
        "disciplines": ["BIM Team"],
        "engineers": [3],
    },
    "QC Team": {
        "sheet_id": "1g0carFHs1RSN4MWtVFdt8kWfTnEmCFrMiicEznft8Bc",
        "gid": None,
        "mode": "hours",
        "disciplines": ["Arch", "Structural", "MEP", "Electrical"],
        "engineers": [2, 1, 1, 2],
    },
}

MAIN_OPTION = "Main"
GANTT_OPTION = "Gantt Chart"
WBS_SHEET_ID = "1kjQtf7UkFNrgn0imyqAlYEzTPzUbR5evY5lQ8alZUIQ"

def build_csv_url(sheet_id, gid=None):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid is not None:
        url += f"&gid={gid}"
    return url

def build_sheet_name_url(sheet_id, sheet_name):
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={quote(sheet_name)}"
    )

DATA_COLS = list({
    f"{d} (Hrs)"
    for cfg in TEAMS.values()
    for d in cfg["disciplines"]
}) + ["Calculated Hours"]

NP_WEEKMASK = "1111001"
PD_WEEKMASK = "Sun Mon Tue Wed Thu"
HOURS_PER_DAY = 8

# ----------------------------------------------------------------------
# 1b. Backup Management System
# ----------------------------------------------------------------------
def _get_safe_team_name(team_name):
    return "".join(c for c in team_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")

def save_daily_backup(team_name, df, counts=None, date_str=None):
    if date_str is None:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_team = _get_safe_team_name(team_name)
    csv_path = os.path.join(BACKUP_DIR, f"{safe_team}_{date_str}.csv")
    df.to_csv(csv_path, index=False)
    if counts is not None:
        json_path = os.path.join(BACKUP_DIR, f"{safe_team}_{date_str}_counts.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(counts, f, ensure_ascii=False, indent=2)
    return csv_path

def list_backups(team_name):
    safe_team = _get_safe_team_name(team_name)
    pattern = os.path.join(BACKUP_DIR, f"{safe_team}_*.csv")
    files = glob.glob(pattern)
    dates = []
    for f in files:
        base = os.path.basename(f)
        date_part = base.replace(f"{safe_team}_", "").replace(".csv", "")
        dates.append(date_part)
    return sorted(list(set(dates)), reverse=True)

def load_backup(team_name, date_str):
    safe_team = _get_safe_team_name(team_name)
    csv_path = os.path.join(BACKUP_DIR, f"{safe_team}_{date_str}.csv")
    json_path = os.path.join(BACKUP_DIR, f"{safe_team}_{date_str}_counts.json")
    if not os.path.exists(csv_path):
        return None, {}
    df = pd.read_csv(csv_path)
    df.columns = df.columns.astype(str).str.strip()
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce").dt.date
    df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce").dt.date
    for c in df.columns:
        if c in DATA_COLS or "(hrs)" in c.lower() or "hours" in c.lower() or "count" in c.lower():
            df[c] = pd.to_numeric(df[c], errors="coerce")
    counts = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                counts = json.load(f)
        except Exception:
            pass
    return df, counts

# ----------------------------------------------------------------------
# 2. Data Loading & Cleaning
# ----------------------------------------------------------------------
def _pick_col(df, *keywords):
    for kw in keywords:
        for c in df.columns:
            if kw in c.lower():
                return c
    return None

def clean_data(df, cfg):
    df.columns = df.columns.astype(str).str.strip()
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df.dropna(how="all").reset_index(drop=True)

    no_col = _pick_col(df, "no.", "no")
    proj_col = _pick_col(df, "project name", "project", "name")
    s_col = _pick_col(df, "start date", "start")
    e_col = _pick_col(df, "end date", "end")

    rename_map = {}
    if no_col: rename_map[no_col] = "No."
    if proj_col: rename_map[proj_col] = "Project Name"
    if s_col: rename_map[s_col] = "Start Date"
    if e_col: rename_map[e_col] = "End Date"
    df = df.rename(columns=rename_map)

    if "Start Date" in df.columns:
        df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce").dt.date
    if "End Date" in df.columns:
        df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce").dt.date

    for c in df.columns:
        if c in DATA_COLS or "(hrs)" in c.lower() or "hours" in c.lower() or "count" in c.lower():
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df

@st.cache_data(ttl=600)
def load_data(url, cfg, team_name="Team"):
    df_raw = pd.read_csv(url)
    df = clean_data(df_raw, cfg)
    try:
        save_daily_backup(team_name, df)
    except Exception:
        pass
    return df

@st.cache_data(ttl=600)
def load_team_counts(url):
    df = pd.read_csv(url)
    df.columns = df.columns.astype(str).str.strip()
    df = df.dropna(how="all")
    first_row = df.iloc[0]
    out = {}
    for col in df.columns:
        val = pd.to_numeric(first_row[col], errors="coerce")
        if pd.notnull(val) and val > 0:
            out[col] = float(val)
    return out

@st.cache_data(ttl=600)
def load_wbs(url):
    df = pd.read_csv(url)
    df.columns = df.columns.astype(str).str.strip()
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df.dropna(how="all").reset_index(drop=True)

    s_col = _pick_col(df, "start")
    e_col = _pick_col(df, "end")
    df = df.rename(columns={s_col: "Start Date", e_col: "End Date"})
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce")
    df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce")
    df = df.dropna(subset=["Start Date", "End Date"]).reset_index(drop=True)
    return df

# ----------------------------------------------------------------------
# 2b. High-Fidelity A3 Vector Gantt HTML & PDF Generator
# ----------------------------------------------------------------------
STAGE_COLORS = [
    "#2f6fb3", "#e07b39", "#3a9d6b", "#8e5ea2", "#c9a227",
    "#c0504d", "#3b9aa8", "#7a8b3c", "#b5649a", "#6c7a89",
]

def build_a3_single_page_html(df):
    """
    Builds a vector-crisp A3 Landscape HTML document calibrated strictly to fit
    onto 1 single page with zero overflow or trailing pages.
    Faithfully mirrors the on-screen UI with phases/stages, summary brackets,
    and grouped task rows.
    """
    esc = lambda v: _html.escape(str(v), quote=True)
    today = datetime.date.today()

    if df is None or df.empty:
        return "<html><body><h3>No tasks to display</h3></body></html>"

    # Timeline bounds
    origin = df["Start Date"].min().normalize()
    origin = origin - pd.Timedelta(days=(origin.dayofweek + 1) % 7)  # Sunday
    last = df["End Date"].max().normalize() + pd.Timedelta(days=1)
    days_to_add = (4 - last.dayofweek) % 7
    last = last + pd.Timedelta(days=max(days_to_add, 3))
    total_days = max(7, int((last - origin).days))

    def get_pos(dt):
        d = (pd.Timestamp(dt).normalize() - origin).days
        return round((d / total_days) * 100, 3)

    def get_width(s, e):
        d = (pd.Timestamp(e).normalize() - pd.Timestamp(s).normalize()).days + 1
        return max(round((d / total_days) * 100, 3), 0.7)

    stage_order = df.groupby("Stage")["Start"].min().sort_values().index.tolist() if "Stage" in df.columns else ["Default"]
    color_of = {s: STAGE_COLORS[i % len(STAGE_COLORS)] for i, s in enumerate(stage_order)}

    total_visual_rows = len(stage_order) + len(df)
    avail_h = 960
    row_h = max(13, min(24, int(avail_h / max(1, total_visual_rows))))
    bar_h = max(7, row_h - 7)
    font_sz = max(7.5, min(10.5, round(row_h * 0.45, 1)))
    sub_font_sz = max(6.5, font_sz - 1.0)
    sw_sz = max(7, min(10, row_h - 10))

    # Month blocks
    current = origin
    month_blocks = []
    while current < last:
        next_month = (current.replace(day=1) + pd.Timedelta(days=32)).replace(day=1)
        m_end = min(next_month - pd.Timedelta(days=1), last - pd.Timedelta(days=1))
        m_days = (m_end - current).days + 1
        m_pct = round((m_days / total_days) * 100, 3)
        month_blocks.append((current.strftime("%B %Y"), m_pct))
        current = m_end + pd.Timedelta(days=1)

    # Week blocks
    week_blocks = []
    current = origin
    while current < last:
        w_end = min(current + pd.Timedelta(days=6), last - pd.Timedelta(days=1))
        w_days = (w_end - current).days + 1
        w_pct = round((w_days / total_days) * 100, 3)
        week_blocks.append((current.strftime("%d %b"), w_pct))
        current = current + pd.Timedelta(days=7)

    grid_underlay_html = "".join([f'<div class="grid-col" style="width:{pct}%;"></div>' for _, pct in week_blocks])
    fmt_d = lambda t: pd.Timestamp(t).strftime("%a %d-%b-%y")

    table_rows_html = ""
    for stage in stage_order:
        g = df[df["Stage"] == stage].sort_values(["Start", "End"])
        col = color_of[stage]
        s_all, e_all = g["Start Date"].min(), g["End Date"].max()
        wd_all = int(np.busday_count(s_all.date(), e_all.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
        if s_all.date() == e_all.date() and wd_all == 0:
            wd_all = 1

        ps = g["Start"].min() if "Start" in g and pd.notnull(g["Start"].min()) else s_all
        pe = g["End"].max() if "End" in g and pd.notnull(g["End"].max()) else e_all
        stage_l_pct = get_pos(ps)
        stage_w_pct = get_width(ps, pe)

        # Stage Header Row
        table_rows_html += f"""
        <div class="g-row stage-row">
            <div class="c-col c-wbs"></div>
            <div class="c-col c-task stage-task-cell" title="{esc(stage)}">
                <span class="sw" style="background:{col}; width:{sw_sz}px; height:{sw_sz}px;"></span>{esc(stage)}
            </div>
            <div class="c-col c-date stage-bold">{fmt_d(s_all)}</div>
            <div class="c-col c-date stage-bold">{fmt_d(e_all)}</div>
            <div class="c-col c-days stage-bold">{wd_all}</div>
            <div class="c-col c-dept"></div>
            <div class="c-timeline-cell">
                <div class="grid-underlay">{grid_underlay_html}</div>
                <div class="sum-bar" style="left:{stage_l_pct}%; width:{stage_w_pct}%;"></div>
            </div>
        </div>
        """

        # Task Item Rows
        for _, r in g.iterrows():
            s_val = r["Start"] if "Start" in r and pd.notnull(r["Start"]) else r["Start Date"]
            e_val = r["End"] if "End" in r and pd.notnull(r["End"]) else r["End Date"]
            left_pct = get_pos(s_val)
            w_pct = get_width(s_val, e_val)
            s_str = fmt_d(r["Start Date"])
            e_str = fmt_d(r["End Date"])
            code_str = str(r.get("Code", ""))
            task_str = str(r.get("Task", "Task"))
            disc_str = str(r.get("Disc", "-"))
            days_str = str(r.get("WorkDays", ""))
            resp_str = str(r.get("Resp", ""))

            table_rows_html += f"""
            <div class="g-row">
                <div class="c-col c-wbs">{esc(code_str)}</div>
                <div class="c-col c-task" title="{esc(task_str)}"><span class="indent"></span>{esc(task_str)}</div>
                <div class="c-col c-date">{s_str}</div>
                <div class="c-col c-date">{e_str}</div>
                <div class="c-col c-days">{days_str}</div>
                <div class="c-col c-dept">{esc(disc_str)}</div>
                <div class="c-timeline-cell">
                    <div class="grid-underlay">{grid_underlay_html}</div>
                    <div class="task-bar" style="left:{left_pct}%; width:{w_pct}%; background:{col}; height:{bar_h}px; top:{max(2, (row_h - bar_h)//2)}px;">
                        <span class="bar-lbl">{esc(resp_str)}</span>
                    </div>
                </div>
            </div>
            """

    m_hdr_html = "".join([f'<div class="hdr-cell" style="width:{pct}%;">{lbl}</div>' for lbl, pct in month_blocks])
    w_hdr_html = "".join([f'<div class="hdr-cell" style="width:{pct}%; font-size:{sub_font_sz}px;">{lbl}</div>' for lbl, pct in week_blocks])

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>WBS Gantt Chart - A3 Landscape Vector PDF</title>
<style>
    @page {{
        size: 420mm 297mm;
        margin: 6mm 8mm;
    }}
    *, *:before, *:after {{
        box-sizing: border-box;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }}
    html, body {{
        font-family: "Segoe UI", Arial, sans-serif;
        color: #1f2933;
        background: #fff;
        margin: 0;
        padding: 0;
        width: 100%;
        height: 285mm;
        max-height: 285mm;
        overflow: hidden;
        page-break-after: avoid;
        page-break-inside: avoid;
        font-size: {font_sz}px;
    }}
    .no-print {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #f1f5f9;
        border: 1px solid #cbd5e1;
        padding: 8px 16px;
        border-radius: 6px;
        margin-bottom: 8px;
    }}
    .header-box {{
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-bottom: 2px solid #2f6fb3;
        padding-bottom: 4px;
        margin-bottom: 5px;
        height: 32px;
    }}
    .main-title {{
        font-size: 16px;
        font-weight: 700;
        color: #1e3a8a;
        line-height: 1.1;
    }}
    .sub-title {{
        font-size: 9px;
        color: #64748b;
    }}
    .stats-box {{
        font-size: 9px;
        color: #334155;
        text-align: right;
    }}
    .g-container {{
        width: 100%;
        border: 1px solid #c9ced6;
        border-radius: 4px;
        background: #fff;
        page-break-inside: avoid;
    }}
    .g-header {{
        display: flex;
        background: #eef1f5;
        border-bottom: 1px solid #9aa4b2;
        font-weight: 600;
        color: #374151;
        height: 32px;
    }}
    .c-col {{
        padding: 0 5px;
        border-right: 1px solid #d3d8df;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: none;
        display: flex;
        align-items: center;
    }}
    .c-wbs {{ width: 50px; justify-content: center; color: #52606d; font-size: {sub_font_sz}px; }}
    .c-task {{ width: 230px; color: #1f2933; }}
    .c-date {{ width: 80px; }}
    .c-days {{ width: 38px; justify-content: flex-end; padding-right: 6px; }}
    .c-dept {{ width: 85px; }}
    .stage-row {{
        background: #e8edf3 !important;
        font-weight: 700;
        border-bottom: 1px solid #cbd5e1;
    }}
    .stage-task-cell {{
        font-weight: 700 !important;
        color: #1f2933 !important;
    }}
    .stage-bold {{
        font-weight: 700 !important;
    }}
    .sw {{
        display: inline-block;
        border-radius: 2px;
        margin-right: 6px;
        vertical-align: -1px;
        flex: none;
    }}
    .indent {{
        display: inline-block;
        width: 14px;
        flex: none;
    }}
    .c-timeline-hdr {{
        flex: 1;
        display: flex;
        flex-direction: column;
    }}
    .hdr-row {{
        display: flex;
        width: 100%;
        border-bottom: 1px solid #d3d8df;
        height: 16px;
        align-items: center;
    }}
    .hdr-row:last-child {{ border-bottom: none; }}
    .hdr-cell {{
        text-align: center;
        border-right: 1px solid #d3d8df;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        height: 100%;
        line-height: 16px;
        font-size: {sub_font_sz}px;
    }}
    .g-row {{
        display: flex;
        border-bottom: 1px solid #e3e7ec;
        height: {row_h}px;
        align-items: center;
        page-break-inside: avoid;
    }}
    .c-timeline-cell {{
        flex: 1;
        height: 100%;
        position: relative;
        background-color: #fff;
    }}
    .grid-underlay {{
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        display: flex;
        pointer-events: none;
    }}
    .grid-col {{
        height: 100%;
        border-right: 1px solid #edf1f7;
        box-sizing: border-box;
    }}
    .task-bar {{
        position: absolute;
        border-radius: 3px;
        box-shadow: inset 0 -1.5px 0 rgba(0,0,0,0.18);
        white-space: nowrap;
        z-index: 2;
    }}
    .bar-lbl {{
        position: absolute;
        left: calc(100% + 5px);
        top: 0;
        line-height: {bar_h}px;
        font-size: {sub_font_sz}px;
        color: #52606d;
        font-weight: 500;
    }}
    .sum-bar {{
        position: absolute;
        top: {max(2, (row_h - 6)//2)}px;
        height: 5px;
        background: #1f2933;
        z-index: 2;
    }}
    .sum-bar:before, .sum-bar:after {{
        content: "";
        position: absolute;
        top: 5px;
        border-top: 5px solid #1f2933;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
    }}
    .sum-bar:before {{ left: -1px; }}
    .sum-bar:after {{ right: -1px; }}
    @media print {{
        .no-print {{ display: none !important; }}
    }}
</style>
</head>
<body>
    <div class="no-print">
        <div style="font-weight:600; font-size:13px; color:#1e3a8a;">
            🗓️ WBS Gantt Chart - A3 Landscape Vector Print Preview (1-Page Fit)
        </div>
        <button onclick="window.print()" style="background:#2563eb; color:#fff; border:none; padding:7px 18px; border-radius:4px; font-weight:600; cursor:pointer; font-size:12px;">
            🖨️ Print to A3 PDF
        </button>
    </div>
    <div class="header-box">
        <div>
            <div class="main-title">Project Schedule & Work Breakdown Structure (WBS)</div>
            <div class="sub-title">Engineering Resource Planner | Single Page A3 Landscape Vector PDF | Generated: {today.strftime('%d-%b-%Y')}</div>
        </div>
        <div class="stats-box">
            Phases: <strong>{len(stage_order)}</strong> &nbsp;|&nbsp; Tasks: <strong>{len(df)}</strong> &nbsp;|&nbsp; Timeline: <strong>{origin.strftime('%d-%b-%Y')}</strong> to <strong>{last.strftime('%d-%b-%Y')}</strong>
        </div>
    </div>
    <div class="g-container">
        <div class="g-header">
            <div class="c-col c-wbs">WBS</div>
            <div class="c-col c-task">Task Name</div>
            <div class="c-col c-date">Start</div>
            <div class="c-col c-date">End</div>
            <div class="c-col c-days">Days</div>
            <div class="c-col c-dept">Department</div>
            <div class="c-timeline-hdr">
                <div class="hdr-row">{m_hdr_html}</div>
                <div class="hdr-row">{w_hdr_html}</div>
            </div>
        </div>
        {table_rows_html}
    </div>
</body>
</html>
"""
    return html

def export_a3_pdf(html_content):
    if not HAS_WEASYPRINT:
        return None
    try:
        return HTML(string=html_content).write_pdf()
    except Exception:
        return None

# ----------------------------------------------------------------------
# 2c. WBS Gantt Chart Interactive Renderer & Print Integration
# ----------------------------------------------------------------------
WBS_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",Arial,sans-serif;font-size:12px;color:#1f2933;background:#fff}
.wrap{overflow:auto;height:__H__px;border:1px solid #c9ced6;border-radius:4px;position:relative;background:#fff}
.grid{display:flex;width:__GW__px}
.left{position:sticky;left:0;z-index:6;width:__LW__px;flex:none;background:#fff;border-right:2px solid #9aa4b2}
.right{position:relative;width:__RW__px;flex:none}
.hdr{position:sticky;top:0;z-index:5;height:__HH__px;background:#eef1f5;border-bottom:1px solid #9aa4b2}
.lhdr{display:flex;align-items:flex-end;height:100%}
.lhdr div,.lrow div{padding:0 6px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;flex:none}
.lhdr div{font-weight:600;height:26px;line-height:26px;border-left:1px solid #d3d8df;color:#374151}
.lhdr div:first-child{border-left:none}
.lrow{display:flex;height:__RH__px;border-bottom:1px solid #e3e7ec;align-items:center}
.lrow div{line-height:__RH__px;border-left:1px solid #eef0f3}
.lrow div:first-child{border-left:none}
.lrow.stage{background:#e8edf3;font-weight:700}
.lrow:hover,.rrow:hover{background:#fff8dc}
.lrow.stage:hover{background:#dde5ee}
.c-wbs{width:__W0__px;color:#52606d}
.c-task{width:__W1__px}
.c-date{width:__W2__px;text-align:left}
.c-days{width:__W3__px;text-align:right}
.c-dept{width:__W4__px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.indent{display:inline-block;width:14px}
.trow{display:flex;height:20px;border-bottom:1px solid #d3d8df}
.trow:last-child{border-bottom:none}
.cell{flex:none;text-align:center;line-height:20px;overflow:hidden;white-space:nowrap;border-left:1px solid #d3d8df;font-size:11px;color:#374151}
.mh{font-weight:600;text-align:left;padding-left:6px}
.wh{text-align:left;padding-left:4px}
.dh{font-size:9px;color:#52606d}
.dh.wk{background:#d9dde3}
.body{position:relative;height:__BH__px;background-image:linear-gradient(to right,transparent 0,transparent __D5__px,rgba(140,150,165,.20) __D5__px,rgba(140,150,165,.20) __D7__px),linear-gradient(to right,#cfd5dd 1px,transparent 1px);background-size:__D7__px 100%,__D7__px 100%;background-repeat:repeat-x}
.rrow{position:relative;height:__RH__px;border-bottom:1px solid #e3e7ec}
.bar{position:absolute;top:6px;height:14px;border-radius:3px;box-shadow:inset 0 -2px 0 rgba(0,0,0,.18)}
.lbl{position:absolute;top:0;line-height:__RH__px;font-size:10.5px;color:#52606d;white-space:nowrap}
.sum{position:absolute;top:7px;height:6px;background:#1f2933}
.sum:before,.sum:after{content:"";position:absolute;top:6px;border-top:6px solid #1f2933;border-left:5px solid transparent;border-right:5px solid transparent}
.sum:before{left:-1px}
.sum:after{right:-1px}
.today{position:absolute;top:0;bottom:0;width:0;border-left:2px dashed #e03131;z-index:3;pointer-events:none}
"""

def build_wbs_html(df, dw, today):
    esc = lambda v: _html.escape(str(v), quote=True)
    ROW_H, HDR_H = 26, 60
    W = [64, 300, 98, 98, 46, 100]
    LW = sum(W)

    origin = df["Start"].min().normalize() - pd.Timedelta(days=2)
    origin = origin - pd.Timedelta(days=(origin.dayofweek + 1) % 7)
    last = df["EndPlus"].max().normalize() + pd.Timedelta(days=12)
    n_days = int((last - origin).days)
    n_days += (-n_days) % 7
    days = pd.date_range(origin, periods=n_days, freq="D")
    RW = n_days * dw

    def x_of(ts):
        return int((pd.Timestamp(ts).normalize() - origin).days * dw)

    def w_of(s, e):
        return max(int(((pd.Timestamp(e).normalize() - pd.Timestamp(s).normalize()).days + 1) * dw), 6)

    fmt = lambda t: pd.Timestamp(t).strftime("%a %d-%b-%y")

    months, i = "", 0
    while i < n_days:
        j = i
        while j < n_days and days[j].month == days[i].month:
            j += 1
        label = f"{days[i]:%B %Y}" if (j - i) * dw >= 90 else f"{days[i]:%b %y}"
        months += f'<div class="cell mh" style="width:{(j - i) * dw}px">{label}</div>'
        i = j
    weeks = "".join(
        f'<div class="cell wh" style="width:{7 * dw}px">{days[w]:%d %b}</div>' for w in range(0, n_days, 7)
    )
    show_num = dw >= 14
    day_cells = "".join(
        f'<div class="cell dh{" wk" if d.dayofweek in (4, 5) else ""}" style="width:{dw}px">'
        f'{d.day if show_num else ""}</div>'
        for d in days
    )

    stage_order = df.groupby("Stage")["Start"].min().sort_values().index.tolist()
    color_of = {s: STAGE_COLORS[i % len(STAGE_COLORS)] for i, s in enumerate(stage_order)}

    left_rows, right_rows = [], []
    for stage in stage_order:
        g = df[df["Stage"] == stage].sort_values(["Start", "End"])
        col = color_of[stage]
        s_all, e_all = g["Start Date"].min(), g["End Date"].max()
        wd_all = int(np.busday_count(s_all.date(), e_all.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
        if s_all.date() == e_all.date() and wd_all == 0:
            wd_all = 1

        left_rows.append(
            f'<div class="lrow stage">'
            f'<div class="c-wbs"></div>'
            f'<div class="c-task" style="width:{W[1]}px" title="{esc(stage)}">'
            f'<span class="sw" style="background:{col}"></span>{esc(stage)}</div>'
            f'<div class="c-date">{fmt(s_all)}</div><div class="c-date">{fmt(e_all)}</div>'
            f'<div class="c-days">{wd_all}</div><div class="c-dept"></div></div>'
        )
        ps, pe = g["Start"].min(), g["End"].max()
        right_rows.append(
            f'<div class="rrow"><div class="sum" style="left:{x_of(ps)}px;width:{w_of(ps, pe)}px" '
            f'title="{esc(stage)}: {fmt(s_all)} → {fmt(e_all)}"></div></div>'
        )

        for _, r in g.iterrows():
            tip = (f"{r['Code']}  {r['Task']}\n{fmt(r['Start Date'])} → {fmt(r['End Date'])}\n"
                   f"{r['WorkDays']} working days (Sun-Thu)\nDept: {r['Disc']}\nResponsible: {r['Resp']}")
            left_rows.append(
                f'<div class="lrow">'
                f'<div class="c-wbs" title="{esc(r["Code"])}">{esc(r["Code"])}</div>'
                f'<div class="c-task" title="{esc(r["Task"])}"><span class="indent"></span>{esc(r["Task"])}</div>'
                f'<div class="c-date">{fmt(r["Start Date"])}</div><div class="c-date">{fmt(r["End Date"])}</div>'
                f'<div class="c-days">{r["WorkDays"]}</div>'
                f'<div class="c-dept" title="{esc(r["Disc"])}">{esc(r["Disc"])}</div></div>'
            )
            bx, bw = x_of(r["Start"]), w_of(r["Start"], r["End"])
            right_rows.append(
                f'<div class="rrow"><div class="bar" style="left:{bx}px;width:{bw}px;background:{col}" '
                f'title="{esc(tip)}"></div>'
                f'<div class="lbl" style="left:{bx + bw + 6}px">{esc(r["Resp"])}</div></div>'
            )

    n_rows = len(left_rows)
    body_h = n_rows * ROW_H
    comp_h = min(HDR_H + body_h + 4, 720)

    today_html, scroll_x = "", 0
    if origin <= today < last:
        tx = x_of(today) + dw // 2
        today_html = f'<div class="today" style="left:{tx}px"></div>'
        scroll_x = max(0, tx - 250)

    col_titles = ["WBS", "Task Name", "Start", "End", "Days", "Department"]
    col_classes = ["c-wbs", "c-task", "c-date", "c-date", "c-days", "c-dept"]
    lhdr = "".join(
        f'<div class="{c}" style="width:{W[k]}px">{t}</div>'
        for k, (t, c) in enumerate(zip(col_titles, col_classes))
    )

    css = (WBS_CSS.replace("__H__", str(comp_h)).replace("__GW__", str(LW + RW))
           .replace("__LW__", str(LW)).replace("__RW__", str(RW)).replace("__HH__", str(HDR_H))
           .replace("__RH__", str(ROW_H)).replace("__BH__", str(body_h))
           .replace("__D5__", str(5 * dw)).replace("__D7__", str(7 * dw))
           .replace("__W0__", str(W[0])).replace("__W1__", str(W[1])).replace("__W2__", str(W[2]))
           .replace("__W3__", str(W[4])).replace("__W4__", str(W[5])))

    html_doc = (
        f"<style>{css}</style><div class='wrap' id='wrap'><div class='grid'>"
        f"<div class='left'><div class='hdr'><div class='lhdr'>{lhdr}</div></div>{''.join(left_rows)}</div>"
        f"<div class='right'><div class='hdr'>"
        f"<div class='trow'>{months}</div><div class='trow'>{weeks}</div><div class='trow'>{day_cells}</div></div>"
        f"<div class='body'>{''.join(right_rows)}{today_html}</div></div>"
        f"</div></div><script>document.getElementById('wrap').scrollLeft={scroll_x};</script>"
    )
    return html_doc, comp_h + 8

def render_wbs_gantt():
    wbs_url = build_csv_url(WBS_SHEET_ID)
    st.subheader("🗓️ WBS Gantt Chart")

    try:
        df = load_wbs(wbs_url)
    except Exception as e:
        st.error(f"Could not read the WBS Google Sheet ({e}).")
        return

    if df is None or df.empty:
        st.error("No WBS data available.")
        return

    code_col = _pick_col(df, "wbs code", "code")
    stage_col = _pick_col(df, "stage")
    task_col = _pick_col(df, "task", "work package")
    disc_col = _pick_col(df, "discipline")
    resp_col = _pick_col(df, "responsible")

    df = df[df["End Date"] >= df["Start Date"]].copy()

    # ---- Filters ----
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1.4])
    with f1:
        if stage_col:
            stages = sorted(df[stage_col].dropna().astype(str).unique())
            sel_stages = st.multiselect("Project Stage", stages, default=stages)
            df = df[df[stage_col].astype(str).isin(sel_stages)]
    with f2:
        if disc_col:
            discs = sorted(df[disc_col].dropna().astype(str).unique())
            sel_discs = st.multiselect("Discipline", discs, default=discs)
            df = df[df[disc_col].astype(str).isin(sel_discs)]
    with f3:
        hide_done = st.checkbox("Filter completed", value=False)
        snap = st.checkbox(
            "Snap bars to working days (Sun-Thu)", value=True,
            help="If a task starts or ends on Friday/Saturday, the bar is moved to the nearest working day.",
        )
    with f4:
        zoom = st.select_slider("Zoom (px/day)", options=[8, 12, 16, 20, 26, 32], value=16)

    today = pd.Timestamp.today().normalize()
    if hide_done:
        df = df[df["End Date"] >= today]

    if df.empty:
        st.info("No tasks to display with the current filters.")
        return

    plot_start, plot_end, work_days, weekend_flag = [], [], [], []
    for s, e in zip(df["Start Date"], df["End Date"]):
        s_d, e_d = s.date(), e.date()
        wd = int(np.busday_count(s_d, e_d + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
        if s_d == e_d and wd == 0:
            wd = 1
        s_fix = pd.Timestamp(np.busday_offset(s_d, 0, roll="forward", weekmask=NP_WEEKMASK))
        e_fix = pd.Timestamp(np.busday_offset(e_d, 0, roll="backward", weekmask=NP_WEEKMASK))
        on_weekend = (s.dayofweek in (4, 5)) or (e.dayofweek in (4, 5))
        if snap and s_fix <= e_fix:
            plot_start.append(s_fix)
            plot_end.append(e_fix)
        else:
            plot_start.append(s)
            plot_end.append(e)
        work_days.append(wd)
        weekend_flag.append(on_weekend)

    df["Start"] = plot_start
    df["End"] = plot_end
    df["EndPlus"] = df["End"] + pd.Timedelta(days=1)
    df["WorkDays"] = work_days
    df["CalendarDays"] = (df["End Date"] - df["Start Date"]).dt.days + 1
    df["OnWeekend"] = weekend_flag

    code = df[code_col].astype(str) if code_col else pd.Series([""] * len(df), index=df.index)
    task = df[task_col].astype(str) if task_col else pd.Series(["Task"] * len(df), index=df.index)
    df["Code"] = code
    df["Task"] = (code + " · " + task).str.strip(" ·")
    df["Stage"] = df[stage_col].astype(str) if stage_col else "-"
    df["Disc"] = df[disc_col].astype(str) if disc_col else "-"
    df["Resp"] = df[resp_col].astype(str) if resp_col else "-"

    df = df.sort_values(["Start", "End"]).reset_index(drop=True)

    # ---- Action Toolbar: Guaranteed A3 PDF Print / Download Button ----
    col_a, col_b, col_c = st.columns([1.5, 2.8, 2.0])
    with col_a:
        if st.button("🔄 Refresh Live Sheet", use_container_width=True):
            load_wbs.clear()
            st.rerun()

    a3_html = build_a3_single_page_html(df)
    pdf_bytes = export_a3_pdf(a3_html) if HAS_WEASYPRINT else None

    with col_b:
        if pdf_bytes:
            st.download_button(
                "📥 Download A3 PDF (Single Page Fit)",
                data=pdf_bytes,
                file_name=f"WBS_Gantt_A3_SinglePage_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                help="Download exact-fit A3 Landscape Vector PDF fitted strictly onto 1 single page with all project phases"
            )
        else:
            escaped_html = json.dumps(a3_html)
            components.html(f"""
                <button onclick="printA3Doc()" style="
                    width: 100%;
                    height: 38px;
                    background-color: #2563eb;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 13.5px;
                    font-weight: 600;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 6px;
                    box-shadow: 0 1px 2px rgba(0,0,0,0.1);
                ">
                    🖨️ Print / Save as A3 PDF (1-Page Fit)
                </button>
                <script>
                function printA3Doc() {{
                    var docContent = {escaped_html};
                    var win = window.open('', '_blank');
                    win.document.open();
                    win.document.write(docContent);
                    win.document.close();
                    win.focus();
                    setTimeout(function() {{
                        win.print();
                    }}, 400);
                }}
                </script>
            """, height=44)

    with col_c:
        st.link_button("🔗 Open Google Sheet", f"https://docs.google.com/spreadsheets/d/{WBS_SHEET_ID}/edit", use_container_width=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tasks", len(df))
    m2.metric("First start", f"{df['Start Date'].min():%d-%b-%Y}")
    m3.metric("Last end", f"{df['End Date'].max():%d-%b-%Y}")
    m4.metric(
        "Working days (Sun-Thu)",
        max(1, int(np.busday_count(df["Start Date"].min().date(),
                                   df["End Date"].max().date() + datetime.timedelta(days=1),
                                   weekmask=NP_WEEKMASK))),
    )

    html_doc, comp_h = build_wbs_html(df, zoom, today)
    components.html(html_doc, height=comp_h, scrolling=False)
