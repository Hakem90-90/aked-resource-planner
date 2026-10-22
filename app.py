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

# Optional WeasyPrint for direct server-side PDF generation
try:
    import weasyprint
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False


def export_a3_pdf(html_content):
    """Generates A3 PDF bytes from HTML if weasyprint is installed."""
    if not HAS_WEASYPRINT:
        return None
    try:
        return weasyprint.HTML(string=html_content).write_pdf()
    except Exception:
        return None


# ----------------------------------------------------------------------
# 1. Page Configuration & Setup
# ----------------------------------------------------------------------
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 Dynamic Engineering Resource Planner - ACKD")

BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

# ----- Teams: each team has its own Google Sheet and default number of engineers -----
TEAMS = {
    "Tech Team": {
        "sheet_id": "1RUqihUZreld3OY9M2cuPWtpxtuCS9p-2ut0FCFFwFvQ",
        "gid": None,
        "mode": "hours",
        "count_sheet": "team count",
        "count_gid": None,
        "disciplines": ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"],
        "engineers": [17, 12, 5, 6, 12],  # Fallback defaults (Total = 52)
    },
    "Design Team": {
        "sheet_id": "15AR4hB_q1JZ1SIwegy2ieusDkPQAMSXFG5uG7Y2zaFg",
        "gid": None,
        "mode": "team_count",
        "disciplines": ["Arch Design Team"],
        "engineers": [21],  # Fallback default from sheet (Total = 21)
    },
    "BIM Team": {
        "sheet_id": "1g9lFbLem738PcQ3FOWGjXZJopwWnf2g5-ncS6dUwNn8",
        "gid": None,
        "mode": "team_count",
        "disciplines": ["BIM Team"],
        "engineers": [3],  # Fallback default from sheet (Total = 3)
    },
    "QC Team": {
        "sheet_id": "1g0carFHs1RSN4MWtVFdt8kWfTnEmCFrMiicEznft8Bc",
        "gid": None,
        "mode": "hours",
        "disciplines": ["Arch", "Structural", "MEP", "Electrical"],
        "engineers": [2, 1, 1, 2],  # Fallback defaults (Total = 6)
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
    """CSV of a specific tab, selected by its name."""
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={quote(sheet_name)}"
    )


# Collect all possible hours columns across all teams
DATA_COLS = list({
    f"{d} (Hrs)"
    for cfg in TEAMS.values()
    for d in cfg["disciplines"]
}) + ["Calculated Hours"]

# Working week: Sunday to Thursday (Friday & Saturday are the weekend)
NP_WEEKMASK = "1111001"
PD_WEEKMASK = "Sun Mon Tue Wed Thu"
HOURS_PER_DAY = 8


# ----------------------------------------------------------------------
# 1b. Backup Management System (Timestamped Snapshots & Differences)
# ----------------------------------------------------------------------
def _get_safe_team_name(team_name):
    return "".join(c for c in team_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")


def save_backup(team_name, df, counts=None, timestamp_str=None):
    """Saves a backup CSV (and optional JSON counts) with timestamp."""
    if df is None or df.empty:
        return None
    if timestamp_str is None:
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_team = _get_safe_team_name(team_name)
    csv_path = os.path.join(BACKUP_DIR, f"{safe_team}_{timestamp_str}.csv")
    df.to_csv(csv_path, index=False)
    if counts is not None:
        json_path = os.path.join(BACKUP_DIR, f"{safe_team}_{timestamp_str}_counts.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(counts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return timestamp_str


save_daily_backup = save_backup


def list_backups(team_name):
    """Lists available backup identifiers in descending order (newest first)."""
    safe_team = _get_safe_team_name(team_name)
    prefix = f"{safe_team}_"
    pattern = os.path.join(BACKUP_DIR, f"{prefix}*.csv")
    files = glob.glob(pattern)
    dates = []
    for f in files:
        base = os.path.basename(f)
        if base.startswith(prefix) and base.endswith(".csv"):
            date_part = base[len(prefix):-4]
            if not date_part.endswith("_counts"):
                dates.append(date_part)
    return sorted(list(set(dates)), reverse=True)


def format_backup_label(b_str):
    """Nicely formats backup timestamp string for selectboxes."""
    if not b_str:
        return ""
    if "_" in b_str and len(b_str) >= 19:
        parts = b_str.split("_", 1)
        time_part = parts[1].replace("-", ":")
        return f"{parts[0]}  at  {time_part}"
    return b_str


def load_backup(team_name, date_str):
    """Loads dataframe and counts from a specified backup identifier."""
    if not date_str:
        return None, {}
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


def compare_datasets(current_df, backup_df, disciplines):
    """Identifies added, removed, and modified projects between current and backup data."""
    def _make_key(row):
        no_val = str(row.get("No.", "")).strip() if pd.notnull(row.get("No.")) else ""
        name_val = ""
        for k in ("project name", "project", "name", "task"):
            col = next((c for c in row.index if k in str(c).lower()), None)
            if col and pd.notnull(row.get(col)):
                name_val = str(row.get(col)).strip()
                break
        if no_val and no_val not in ("nan", ""):
            return f"No. {no_val} | {name_val}" if name_val else f"No. {no_val}"
        return name_val or "Unnamed"

    curr = current_df.copy()
    back = backup_df.copy()
    curr["_key"] = curr.apply(_make_key, axis=1)
    back["_key"] = back.apply(_make_key, axis=1)

    curr_dict = {r["_key"]: r for _, r in curr.iterrows()}
    back_dict = {r["_key"]: r for _, r in back.iterrows()}

    curr_keys = set(curr_dict.keys())
    back_keys = set(back_dict.keys())

    added_keys = sorted(list(curr_keys - back_keys))
    removed_keys = sorted(list(back_keys - curr_keys))
    common_keys = sorted(list(curr_keys & back_keys))

    changes = []
    hrs_cols = [f"{d} (Hrs)" for d in disciplines]

    for k in common_keys:
        r_curr = curr_dict[k]
        r_back = back_dict[k]
        diffs = []

        # Check dates
        s_old, s_new = r_back.get("Start Date"), r_curr.get("Start Date")
        e_old, e_new = r_back.get("End Date"), r_curr.get("End Date")

        if pd.notnull(s_old) and pd.notnull(s_new) and str(s_old) != str(s_new):
            diffs.append(f"Start: {s_old} ➔ {s_new}")
        elif pd.isnull(s_old) != pd.isnull(s_new):
            diffs.append(f"Start: {s_old} ➔ {s_new}")

        if pd.notnull(e_old) and pd.notnull(e_new) and str(e_old) != str(e_new):
            diffs.append(f"End: {e_old} ➔ {e_new}")
        elif pd.isnull(e_old) != pd.isnull(e_new):
            diffs.append(f"End: {e_old} ➔ {e_new}")

        # Check hours
        for h_col in hrs_cols:
            if h_col in r_curr and h_col in r_back:
                v_old = pd.to_numeric(r_back[h_col], errors="coerce") or 0.0
                v_new = pd.to_numeric(r_curr[h_col], errors="coerce") or 0.0
                if abs(v_old - v_new) > 0.01:
                    disc_name = h_col.replace(" (Hrs)", "")
                    diffs.append(f"{disc_name} Hrs: {v_old:g} ➔ {v_new:g}")

        # Check Team Count / Calculated Hours if present
        for spec_col in ["Team Count", "Calculated Hours"]:
            if spec_col in r_curr and spec_col in r_back:
                v_old = pd.to_numeric(r_back[spec_col], errors="coerce") or 0.0
                v_new = pd.to_numeric(r_curr[spec_col], errors="coerce") or 0.0
                if abs(v_old - v_new) > 0.01:
                    diffs.append(f"{spec_col}: {v_old:g} ➔ {v_new:g}")

        if diffs:
            changes.append({
                "Project": k,
                "Differences Detected": " | ".join(diffs)
            })

    return added_keys, removed_keys, changes


# ----------------------------------------------------------------------
# 2. Load data from Google Sheet
# ----------------------------------------------------------------------
def get_empty_template(mode="hours", disciplines=None):
    today = datetime.date.today()
    if mode == "team_count":
        return pd.DataFrame({
            "No.": [1],
            "Project Name": ["Example Project"],
            "Start Date": [today],
            "End Date": [today + datetime.timedelta(days=30)],
            "Team Count": [2],
            "Calculated Hours": [160.0],
        })
    data = {
        "No.": [1],
        "Project Name": ["Example Project"],
        "Start Date": [today],
        "End Date": [today + datetime.timedelta(days=30)],
    }
    for d in (disciplines or ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"]):
        data[f"{d} (Hrs)"] = [40.0]
    return pd.DataFrame(data)


def match_discipline_name(raw_name, disciplines):
    raw_low = str(raw_name).strip().lower()
    if not raw_low or "total" in raw_low:
        return None

    for d in disciplines:
        d_low = d.lower()
        if d_low == raw_low or d_low in raw_low or raw_low in d_low:
            return d
        if "arch" in raw_low and "arch" in d_low:
            return d
        if "struct" in raw_low and "struct" in d_low:
            return d
        if "plumb" in raw_low and "plumb" in d_low:
            return d
        if "hvac" in raw_low and "hvac" in d_low:
            return d
        if ("mech" in raw_low or "mep" in raw_low) and ("mep" in d_low or "mech" in d_low):
            return d
        if "elec" in raw_low and "elec" in d_low:
            return d
    return None


def _to_int(v):
    try:
        if pd.isnull(v):
            return None
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return None


def extract_counts_from_grid(grid, disciplines):
    counts = {}
    n_rows, n_cols = grid.shape
    for r in range(n_rows):
        for c in range(n_cols):
            cell = grid.iat[r, c]
            if pd.isnull(cell) or _to_int(cell) is not None:
                continue
            disc = match_discipline_name(cell, disciplines)
            if disc is None or disc in counts:
                continue

            val = None
            for c2 in range(c + 1, n_cols):
                nxt = grid.iat[r, c2]
                if pd.isnull(nxt):
                    continue
                if _to_int(nxt) is not None:
                    val = _to_int(nxt)
                    break
                if match_discipline_name(nxt, disciplines):
                    break

            if val is None:
                for r2 in range(r + 1, n_rows):
                    nxt = grid.iat[r2, c]
                    if pd.isnull(nxt):
                        continue
                    if _to_int(nxt) is not None:
                        val = _to_int(nxt)
                        break
                    if match_discipline_name(nxt, disciplines):
                        break

            if val is not None:
                counts[disc] = val
    return counts


@st.cache_data(ttl=60, show_spinner="Loading engineers count...")
def load_team_counts(url, disciplines):
    grid = pd.read_csv(url, header=None, dtype=str)
    return extract_counts_from_grid(grid, disciplines)


@st.cache_data(ttl=60, show_spinner="Loading data from Google Sheet...")
def load_from_gsheet(url, disciplines):
    raw_df = pd.read_csv(url)
    raw_df.columns = raw_df.columns.astype(str).str.strip()

    eng_counts = {}
    cols_to_drop = []

    col_list = list(raw_df.columns)
    for idx, c in enumerate(col_list):
        c_low = c.lower()
        if "total team" in c_low or ("total" in c_low and "count" in c_low):
            cols_to_drop.append(c)
            if idx + 1 < len(col_list):
                next_col = col_list[idx + 1]
                cols_to_drop.append(next_col)
                try:
                    val = int(float(next_col))
                    if len(disciplines) == 1:
                        eng_counts[disciplines[0]] = val
                except (ValueError, TypeError):
                    non_na = raw_df[next_col].dropna()
                    if not non_na.empty:
                        try:
                            val = int(float(non_na.iloc[0]))
                            if len(disciplines) == 1:
                                eng_counts[disciplines[0]] = val
                        except (ValueError, TypeError):
                            pass
            if not eng_counts and len(disciplines) == 1:
                non_na_self = raw_df[c].dropna()
                if not non_na_self.empty:
                    try:
                        eng_counts[disciplines[0]] = int(float(non_na_self.iloc[0]))
                    except (ValueError, TypeError):
                        pass

    raw_df = raw_df.drop(columns=[c for c in cols_to_drop if c in raw_df.columns])
    raw_df = raw_df.loc[:, ~raw_df.columns.str.startswith("Unnamed")]

    disc_col_name = None
    eng_col_name = None
    for c in raw_df.columns:
        c_low = c.lower()
        if "discipline" in c_low:
            disc_col_name = c
        elif "engineer" in c_low or "no. of eng" in c_low:
            eng_col_name = c

    if disc_col_name is not None:
        if eng_col_name is None:
            idx = list(raw_df.columns).index(disc_col_name)
            if idx + 1 < len(raw_df.columns):
                eng_col_name = raw_df.columns[idx + 1]

        if eng_col_name is not None:
            for _, r in raw_df[[disc_col_name, eng_col_name]].dropna(how="all").iterrows():
                d_val, c_val = r[disc_col_name], r[eng_col_name]
                if pd.notnull(d_val) and pd.notnull(c_val):
                    matched_disc = match_discipline_name(d_val, disciplines)
                    if matched_disc:
                        try:
                            eng_counts[matched_disc] = int(float(c_val))
                        except (ValueError, TypeError):
                            pass

        side_cols = [c for c in [disc_col_name, eng_col_name] if c is not None and c in raw_df.columns]
        df = raw_df.drop(columns=side_cols).copy()
    else:
        raw_df = raw_df.dropna(how="all").reset_index(drop=True)
        split_idx = None
        disc_col_idx = None
        cnt_col_idx = None

        for idx, row in raw_df.iterrows():
            for col_i, val in enumerate(row):
                if pd.notnull(val) and "discipline" in str(val).lower():
                    split_idx = idx
                    disc_col_idx = col_i
                    for c_j in range(col_i + 1, len(row)):
                        if pd.notnull(row.iloc[c_j]):
                            cnt_col_idx = c_j
                            break
                    if cnt_col_idx is None and col_i + 1 < len(row):
                        cnt_col_idx = col_i + 1
                    break
            if split_idx is not None:
                break

        if split_idx is not None:
            eng_rows = raw_df.iloc[split_idx + 1:]
            df = raw_df.iloc[:split_idx].copy()
            for _, r in eng_rows.iterrows():
                d_val = r.iloc[disc_col_idx] if disc_col_idx < len(r) else None
                c_val = r.iloc[cnt_col_idx] if (cnt_col_idx is not None and cnt_col_idx < len(r)) else None
                if pd.notnull(d_val) and pd.notnull(c_val):
                    matched_disc = match_discipline_name(d_val, disciplines)
                    if matched_disc:
                        try:
                            eng_counts[matched_disc] = int(float(c_val))
                        except (ValueError, TypeError):
                            pass
        else:
            df = raw_df.copy()

    df = df.dropna(how="all").reset_index(drop=True)
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce").dt.date
    df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce").dt.date
    for c in df.columns:
        if c in DATA_COLS or "(hrs)" in c.lower() or "hours" in c.lower() or "count" in c.lower():
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df, eng_counts


# ----------------------------------------------------------------------
# 2b. WBS Gantt Chart: Interactive View & Dedicated A3 Vector PDF Generator
# ----------------------------------------------------------------------
def _pick_col(df, *keys):
    for c in df.columns:
        low = str(c).lower()
        if any(k in low for k in keys):
            return c
    return None


@st.cache_data(ttl=60, show_spinner="Loading WBS from Google Sheet...")
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


STAGE_COLORS = [
    "#2f6fb3", "#e07b39", "#3a9d6b", "#8e5ea2", "#c9a227",
    "#c0504d", "#3b9aa8", "#7a8b3c", "#b5649a", "#6c7a89",
]

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


def generate_a3_vector_gantt_html(df):
    """
    Builds a vector-crisp A3 Landscape HTML document.
    Calculates exact percentage-based timeline bars and month/week blocks
    so the entire schedule fits 100% within the A3 page boundaries with sharp readable typography.
    """
    esc = lambda v: _html.escape(str(v), quote=True)
    today = datetime.date.today()

    origin = df["Start Date"].min().normalize()
    origin = origin - pd.Timedelta(days=(origin.dayofweek + 1) % 7)  # Align to Sunday
    last = df["End Date"].max().normalize() + pd.Timedelta(days=1)
    days_to_add = (4 - last.dayofweek) % 7
    last = last + pd.Timedelta(days=max(days_to_add, 3))

    total_days = max(7, int((last - origin).days))

    def get_pos(dt):
        d = (pd.Timestamp(dt).normalize() - origin).days
        return round((d / total_days) * 100, 2)

    def get_width(s, e):
        d = (pd.Timestamp(e).normalize() - pd.Timestamp(s).normalize()).days + 1
        return max(round((d / total_days) * 100, 2), 0.8)

    # Monthly headers
    current = origin
    month_blocks = []
    while current < last:
        next_month = (current.replace(day=1) + pd.Timedelta(days=32)).replace(day=1)
        m_end = min(next_month - pd.Timedelta(days=1), last - pd.Timedelta(days=1))
        m_days = (m_end - current).days + 1
        m_pct = round((m_days / total_days) * 100, 2)
        month_blocks.append((current.strftime("%B %Y"), m_pct))
        current = m_end + pd.Timedelta(days=1)

    # Weekly headers
    week_blocks = []
    current = origin
    while current < last:
        w_end = min(current + pd.Timedelta(days=6), last - pd.Timedelta(days=1))
        w_days = (w_end - current).days + 1
        w_pct = round((w_days / total_days) * 100, 2)
        week_blocks.append((current.strftime("%d %b"), w_pct))
        current = current + pd.Timedelta(days=7)

    stage_order = df.groupby("Stage")["Start"].min().sort_values().index.tolist()
    color_of = {s: STAGE_COLORS[i % len(STAGE_COLORS)] for i, s in enumerate(stage_order)}

    table_rows_html = ""
    for stage in stage_order:
        g = df[df["Stage"] == stage].sort_values(["Start", "End"])
        col = color_of[stage]
        s_all, e_all = g["Start Date"].min(), g["End Date"].max()
        wd_all = int(np.busday_count(s_all.date(), e_all.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
        if s_all.date() == e_all.date() and wd_all == 0:
            wd_all = 1

        stage_l_pct = get_pos(s_all)
        stage_w_pct = get_width(s_all, e_all)

        # Stage Header Row
        table_rows_html += f"""
        <div class="g-row stage-row">
            <div class="c-col c-code"></div>
            <div class="c-col c-name" style="font-weight:700; color:#1e3a8a;">
                <span class="stg-badge" style="background:{col};"></span>{esc(stage)}
            </div>
            <div class="c-col c-date" style="font-weight:600;">{s_all.strftime('%d-%b-%Y')}</div>
            <div class="c-col c-date" style="font-weight:600;">{e_all.strftime('%d-%b-%Y')}</div>
            <div class="c-col c-days" style="font-weight:700;">{wd_all}</div>
            <div class="c-col c-disc"></div>
            <div class="c-timeline-cell">
                <div class="g-sum-bar" style="left:{stage_l_pct}%; width:{stage_w_pct}%;"></div>
            </div>
        </div>
        """

        # Task Item Rows
        for _, r in g.iterrows():
            left_pct = get_pos(r["Start Date"])
            w_pct = get_width(r["Start Date"], r["End Date"])
            s_str = r["Start Date"].strftime("%d-%b-%Y")
            e_str = r["End Date"].strftime("%d-%b-%Y")
            code_str = str(r.get("Code", ""))
            task_str = str(r.get("Task", "Task"))
            disc_str = str(r.get("Disc", "-"))
            days_str = str(r.get("WorkDays", ""))
            resp_str = str(r.get("Resp", ""))

            table_rows_html += f"""
            <div class="g-row">
                <div class="c-col c-code">{esc(code_str)}</div>
                <div class="c-col c-name"><span class="indent"></span>{esc(task_str)}</div>
                <div class="c-col c-date">{s_str}</div>
                <div class="c-col c-date">{e_str}</div>
                <div class="c-col c-days">{days_str}</div>
                <div class="c-col c-disc">{esc(disc_str)}</div>
                <div class="c-timeline-cell">
                    <div class="g-bar" style="left:{left_pct}%; width:{w_pct}%; background:{col};">
                        <span class="g-bar-label">{esc(resp_str)}</span>
                    </div>
                </div>
            </div>
            """

    m_hdr_html = "".join([f'<div class="hdr-cell" style="width:{pct}%;">{lbl}</div>' for lbl, pct in month_blocks])
    w_hdr_html = "".join([f'<div class="hdr-cell" style="width:{pct}%; font-size:9px;">{lbl}</div>' for lbl, pct in week_blocks])

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>WBS Gantt Chart - A3 Vector PDF</title>
<style>
    @page {{
        size: 420mm 297mm; /* Exact A3 Landscape */
        margin: 8mm 10mm 10mm 10mm;
    }}
    *, *:before, *:after {{
        box-sizing: border-box;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        color: #1e293b;
        background: #fff;
        margin: 0;
        padding: 0;
        width: 100%;
        font-size: 10px;
    }}
    .no-print {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #f1f5f9;
        border: 1px solid #cbd5e1;
        padding: 8px 16px;
        border-radius: 6px;
        margin-bottom: 12px;
    }}
    .header-box {{
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-bottom: 2.5px solid #1e3a8a;
        padding-bottom: 6px;
        margin-bottom: 8px;
    }}
    .main-title {{
        font-size: 19px;
        font-weight: 700;
        color: #1e3a8a;
        letter-spacing: -0.3px;
    }}
    .sub-title {{
        font-size: 10px;
        color: #64748b;
        margin-top: 2px;
    }}
    .stats-box {{
        font-size: 10px;
        color: #334155;
        text-align: right;
    }}
    .g-container {{
        width: 100%;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        overflow: hidden;
        background: #fff;
    }}
    .g-header {{
        display: flex;
        background: #f8fafc;
        border-bottom: 1.5px solid #94a3b8;
        font-weight: 600;
        color: #334155;
    }}
    .c-col {{
        padding: 4px 6px;
        border-right: 1px solid #e2e8f0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: none;
    }}
    .c-code {{ width: 50px; text-align: center; color: #64748b; }}
    .c-name {{ width: 230px; font-weight: 600; color: #0f172a; }}
    .c-date {{ width: 72px; text-align: center; }}
    .c-days {{ width: 42px; text-align: center; }}
    .c-disc {{ width: 85px; }}
    .c-timeline-hdr {{
        flex: 1;
        display: flex;
        flex-direction: column;
    }}
    .hdr-row {{
        display: flex;
        width: 100%;
        border-bottom: 1px solid #e2e8f0;
        height: 18px;
        align-items: center;
    }}
    .hdr-row:last-child {{ border-bottom: none; }}
    .hdr-cell {{
        text-align: center;
        border-right: 1px solid #e2e8f0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        height: 100%;
        line-height: 18px;
        font-size: 10px;
    }}
    .g-row {{
        display: flex;
        border-bottom: 1px solid #f1f5f9;
        height: 23px;
        align-items: center;
        page-break-inside: avoid;
    }}
    .g-row:nth-child(even) {{ background: #fafafa; }}
    .stage-row {{
        background: #eef2f6 !important;
        font-weight: 700;
        border-top: 1px solid #cbd5e1;
    }}
    .stg-badge {{
        display: inline-block;
        width: 9px;
        height: 9px;
        border-radius: 2px;
        margin-right: 6px;
        vertical-align: -1px;
    }}
    .indent {{
        display: inline-block;
        width: 14px;
    }}
    .c-timeline-cell {{
        flex: 1;
        height: 100%;
        position: relative;
        background-image: repeating-linear-gradient(to right, transparent, transparent 14.28%, rgba(226, 232, 240, 0.4) 14.28%, rgba(226, 232, 240, 0.4) 14.4%);
    }}
    .g-bar {{
        position: absolute;
        top: 4px;
        height: 14px;
        border-radius: 3px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.12);
        white-space: nowrap;
    }}
    .g-bar-label {{
        position: absolute;
        left: calc(100% + 5px);
        top: 0;
        line-height: 14px;
        font-size: 9px;
        color: #475569;
        font-weight: 500;
    }}
    .g-sum-bar {{
        position: absolute;
        top: 8px;
        height: 6px;
        background: #1e293b;
    }}
    .g-sum-bar:before, .g-sum-bar:after {{
        content: "";
        position: absolute;
        top: 6px;
        border-top: 5px solid #1e293b;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
    }}
    .g-sum-bar:before {{ left: -1px; }}
    .g-sum-bar:after {{ right: -1px; }}
    @media print {{
        .no-print {{ display: none !important; }}
    }}
</style>
</head>
<body>
    <div class="no-print">
        <div style="font-weight:600; font-size:13px; color:#1e3a8a;">
            🗓️ WBS Gantt Chart - A3 Landscape Vector Print Preview
        </div>
        <button onclick="window.print()" style="background:#2563eb; color:#fff; border:none; padding:7px 18px; border-radius:4px; font-weight:600; cursor:pointer; font-size:12px;">
            🖨️ Print to A3 PDF
        </button>
    </div>
    <div class="header-box">
        <div>
            <div class="main-title">Project Schedule & Work Breakdown Structure (WBS)</div>
            <div class="sub-title">Engineering Resource Planner | Format: Exact A3 Landscape (Vector PDF) | Generated: {today.strftime('%d-%b-%Y')}</div>
        </div>
        <div class="stats-box">
            Total Tasks: <strong>{len(df)}</strong> &nbsp;|&nbsp; Timeline: <strong>{origin.strftime('%d-%b-%Y')}</strong> to <strong>{last.strftime('%d-%b-%Y')}</strong>
        </div>
    </div>
    <div class="g-container">
        <div class="g-header">
            <div class="c-col c-code">WBS</div>
            <div class="c-col c-name">Task Name</div>
            <div class="c-col c-date">Start Date</div>
            <div class="c-col c-date">End Date</div>
            <div class="c-col c-days">Days</div>
            <div class="c-col c-disc">Department</div>
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


def render_wbs_gantt():
    wbs_url = build_csv_url(WBS_SHEET_ID)
    st.subheader("🗓️ WBS Gantt Chart")

    # Load Data directly from Google Sheet
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

    # ---- Working days (Sun-Thu) ----
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

    # ---- Summary metrics & High-Resolution Vector Print Toolbar ----
    col_a, col_b, col_c = st.columns([1.5, 2.2, 2.3])
    with col_a:
        if st.button("🔄 Refresh Live Sheet", use_container_width=True):
            load_wbs.clear()
            st.rerun()

    # Pre-generate exact-fit A3 Vector PDF HTML
    a3_vector_html = generate_a3_vector_gantt_html(df)
    pdf_bytes = export_a3_pdf(a3_vector_html)

    with col_b:
        if pdf_bytes:
            st.download_button(
                "📥 Download A3 Vector PDF",
                data=pdf_bytes,
                file_name=f"WBS_Gantt_A3_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                help="Download exact-fit A3 Landscape Vector PDF with crisp readable fonts"
            )
        else:
            st.download_button(
                "📄 Download A3 Printable HTML",
                data=a3_vector_html,
                file_name=f"WBS_Gantt_A3_{datetime.date.today().strftime('%Y%m%d')}.html",
                mime="text/html",
                use_container_width=True,
                help="Open in browser and choose Print -> Save as PDF (A3 Landscape)"
            )

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

    # Interactive Web View Gantt
    html_doc, comp_h = build_wbs_html(df, zoom, today)
    components.html(html_doc, height=comp_h, scrolling=False)


# ----------------------------------------------------------------------
# 2c. Helper Functions for Team Gantt Charts & A3 Printing
# ----------------------------------------------------------------------
def find_count_col(df):
    for c in df.columns:
        if "count" in str(c).lower():
            return c
    for c in df.columns:
        if "team" in str(c).lower():
            return c
    return None


def find_calc_hrs_col(df):
    for c in df.columns:
        if "calculated" in str(c).lower() or "hours" in str(c).lower() or "(hrs)" in str(c).lower():
            return c
    return None


def find_name_col(df):
    skip = {"No.", "Start Date", "End Date"} | set(DATA_COLS)
    for c in df.columns:
        low = str(c).lower()
        if c not in skip and any(k in low for k in ("name", "project", "contract", "task")):
            return c
    for c in df.columns:
        if c not in skip and df[c].dtype == object:
            return c
    return None


def make_project_label(r, name_col):
    name = r.get(name_col) if name_col is not None else None
    name = str(name).strip() if pd.notnull(name) and str(name).strip() != "" else "Unnamed"
    no = r.get("No.")
    if pd.notnull(no) and str(no).strip() != "":
        try:
            no = int(float(no))
        except (ValueError, TypeError):
            pass
        return f"{no}. {name}"
    return name


def prepare_calc_df(df, team_mode, disciplines, hours_per_day=HOURS_PER_DAY):
    calc_df = df.copy()
    count_col = find_count_col(calc_df)

    # Ensure Start and End Date are safe date objects and handle missing dates
    calc_df["Start Date"] = pd.to_datetime(calc_df["Start Date"], errors="coerce").dt.date
    calc_df["End Date"] = pd.to_datetime(calc_df["End Date"], errors="coerce").dt.date
    calc_df["End Date"] = calc_df["End Date"].fillna(calc_df["Start Date"])
    calc_df["Start Date"] = calc_df["Start Date"].fillna(calc_df["End Date"])

    if team_mode == "team_count":
        hrs_col_name = f"{disciplines[0]} (Hrs)"
        sheet_hrs_col = find_calc_hrs_col(calc_df)

        calc_from_count = False
        if sheet_hrs_col is not None and sheet_hrs_col in calc_df.columns:
            calc_df[hrs_col_name] = pd.to_numeric(calc_df[sheet_hrs_col], errors="coerce")
            # If values in Calculated Hours are missing or 0, calculate dynamically
            if calc_df[hrs_col_name].isna().all() or (calc_df[hrs_col_name] == 0).all():
                calc_from_count = True
            else:
                calc_df[hrs_col_name] = calc_df[hrs_col_name].fillna(0)
        else:
            calc_from_count = True

        if calc_from_count and count_col is not None and count_col in calc_df.columns:
            calc_df[count_col] = pd.to_numeric(calc_df[count_col], errors="coerce").fillna(0)
            work_days = []
            for s_d, e_d in zip(calc_df["Start Date"], calc_df["End Date"]):
                if pd.isnull(s_d) or pd.isnull(e_d):
                    work_days.append(0)
                else:
                    wd = int(np.busday_count(s_d, e_d + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
                    if s_d == e_d and wd == 0:
                        wd = 1
                    work_days.append(max(0, wd))
            calc_df[hrs_col_name] = calc_df[count_col] * pd.Series(work_days, index=calc_df.index) * hours_per_day

    return calc_df, count_col


def generate_team_a3_vector_gantt_html(calc_df, team_name, disciplines):
    """
    Builds a vector-crisp A3 Landscape HTML document for a specific team.
    Fits 100% within A3 boundaries with proportional vector timeline bars.
    """
    esc = lambda v: _html.escape(str(v), quote=True)
    today = datetime.date.today()
    name_col = find_name_col(calc_df)

    df = calc_df.copy()
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce")
    df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce")
    df = df.dropna(subset=["Start Date", "End Date"])
    df = df[df["End Date"] >= df["Start Date"]].sort_values(["Start Date", "End Date"]).reset_index(drop=True)

    if df.empty:
        return f"<html><body><h3>No tasks to display for {esc(team_name)}</h3></body></html>"

    origin = df["Start Date"].min().normalize()
    origin = origin - pd.Timedelta(days=(origin.dayofweek + 1) % 7)  # Sunday
    last = df["End Date"].max().normalize() + pd.Timedelta(days=1)
    days_to_add = (4 - last.dayofweek) % 7
    last = last + pd.Timedelta(days=max(days_to_add, 3))
    total_days = max(7, int((last - origin).days))

    def get_pos(dt):
        d = (pd.Timestamp(dt).normalize() - origin).days
        return round((d / total_days) * 100, 2)

    def get_width(s, e):
        d = (pd.Timestamp(e).normalize() - pd.Timestamp(s).normalize()).days + 1
        return max(round((d / total_days) * 100, 2), 0.8)

    # Month blocks
    current = origin
    month_blocks = []
    while current < last:
        next_month = (current.replace(day=1) + pd.Timedelta(days=32)).replace(day=1)
        m_end = min(next_month - pd.Timedelta(days=1), last - pd.Timedelta(days=1))
        m_days = (m_end - current).days + 1
        m_pct = round((m_days / total_days) * 100, 2)
        month_blocks.append((current.strftime("%B %Y"), m_pct))
        current = m_end + pd.Timedelta(days=1)

    # Week blocks
    week_blocks = []
    current = origin
    while current < last:
        w_end = min(current + pd.Timedelta(days=6), last - pd.Timedelta(days=1))
        w_days = (w_end - current).days + 1
        w_pct = round((w_days / total_days) * 100, 2)
        week_blocks.append((current.strftime("%d %b"), w_pct))
        current = current + pd.Timedelta(days=7)

    color_palette = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626", "#4f46e5"]

    rows_html = ""
    for idx, r in df.iterrows():
        col = color_palette[idx % len(color_palette)]
        left_pct = get_pos(r["Start Date"])
        w_pct = get_width(r["Start Date"], r["End Date"])

        s_str = r["Start Date"].strftime("%d-%b-%Y")
        e_str = r["End Date"].strftime("%d-%b-%Y")
        p_name = str(make_project_label(r, name_col))
        no_val = str(r.get("No.", idx + 1))
        wd = int(np.busday_count(r["Start Date"].date(), r["End Date"].date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))

        rows_html += f"""
        <div class="g-row">
            <div class="c-col c-no">{esc(no_val)}</div>
            <div class="c-col c-pname" title="{esc(p_name)}">{esc(p_name)}</div>
            <div class="c-col c-date">{s_str}</div>
            <div class="c-col c-date">{e_str}</div>
            <div class="c-col c-days">{wd}d</div>
            <div class="c-timeline-cell">
                <div class="g-bar" style="left:{left_pct}%; width:{w_pct}%; background:{col};" title="{esc(p_name)}">
                    <span class="g-bar-label">{s_str} → {e_str}</span>
                </div>
            </div>
        </div>
        """

    m_hdr_html = "".join([f'<div class="hdr-cell" style="width:{pct}%;">{lbl}</div>' for lbl, pct in month_blocks])
    w_hdr_html = "".join([f'<div class="hdr-cell" style="width:{pct}%; font-size:9px;">{lbl}</div>' for lbl, pct in week_blocks])

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{esc(team_name)} - A3 Vector Gantt</title>
<style>
    @page {{
        size: 420mm 297mm;
        margin: 8mm 10mm 10mm 10mm;
    }}
    *, *:before, *:after {{
        box-sizing: border-box;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        color: #1e293b;
        background: #fff;
        margin: 0;
        padding: 0;
        font-size: 10px;
    }}
    .no-print {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #f1f5f9;
        border: 1px solid #cbd5e1;
        padding: 8px 16px;
        border-radius: 6px;
        margin-bottom: 12px;
    }}
    .header-box {{
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-bottom: 2.5px solid #1e3a8a;
        padding-bottom: 6px;
        margin-bottom: 8px;
    }}
    .main-title {{
        font-size: 19px;
        font-weight: 700;
        color: #1e3a8a;
    }}
    .sub-title {{
        font-size: 10px;
        color: #64748b;
        margin-top: 2px;
    }}
    .stats-box {{
        font-size: 10px;
        color: #334155;
        text-align: right;
    }}
    .g-container {{
        width: 100%;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        overflow: hidden;
        background: #fff;
    }}
    .g-header {{
        display: flex;
        background: #f8fafc;
        border-bottom: 1.5px solid #94a3b8;
        font-weight: 600;
        color: #334155;
    }}
    .c-col {{
        padding: 4px 6px;
        border-right: 1px solid #e2e8f0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: none;
    }}
    .c-no {{ width: 45px; text-align: center; color: #64748b; }}
    .c-pname {{ width: 280px; font-weight: 600; color: #0f172a; }}
    .c-date {{ width: 75px; text-align: center; }}
    .c-days {{ width: 50px; text-align: center; }}
    .c-timeline-hdr {{
        flex: 1;
        display: flex;
        flex-direction: column;
    }}
    .hdr-row {{
        display: flex;
        width: 100%;
        border-bottom: 1px solid #e2e8f0;
        height: 18px;
        align-items: center;
    }}
    .hdr-row:last-child {{ border-bottom: none; }}
    .hdr-cell {{
        text-align: center;
        border-right: 1px solid #e2e8f0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        height: 100%;
        line-height: 18px;
        font-size: 10px;
    }}
    .g-row {{
        display: flex;
        border-bottom: 1px solid #f1f5f9;
        height: 24px;
        align-items: center;
        page-break-inside: avoid;
    }}
    .g-row:nth-child(even) {{ background: #fafafa; }}
    .c-timeline-cell {{
        flex: 1;
        height: 100%;
        position: relative;
    }}
    .g-bar {{
        position: absolute;
        top: 4px;
        height: 15px;
        border-radius: 3px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.12);
        white-space: nowrap;
    }}
    .g-bar-label {{
        position: absolute;
        left: calc(100% + 5px);
        top: 0;
        line-height: 15px;
        font-size: 8.5px;
        color: #475569;
        font-weight: 500;
    }}
    @media print {{
        .no-print {{ display: none !important; }}
    }}
</style>
</head>
<body>
    <div class="no-print">
        <div style="font-weight:600; font-size:13px; color:#1e3a8a;">
            👥 {esc(team_name)} - A3 Landscape Vector Print Preview
        </div>
        <button onclick="window.print()" style="background:#2563eb; color:#fff; border:none; padding:7px 18px; border-radius:4px; font-weight:600; cursor:pointer; font-size:12px;">
            🖨️ Print to A3 PDF
        </button>
    </div>
    <div class="header-box">
        <div>
            <div class="main-title">👥 {esc(team_name)} - Project Timeline Schedule</div>
            <div class="sub-title">Engineering Resource Planner | Format: Exact A3 Landscape (Vector PDF) | Generated: {today.strftime('%d-%b-%Y')}</div>
        </div>
        <div class="stats-box">
            Total Projects: <strong>{len(df)}</strong> &nbsp;|&nbsp; Timeline: <strong>{origin.strftime('%d-%b-%Y')}</strong> to <strong>{last.strftime('%d-%b-%Y')}</strong>
        </div>
    </div>
    <div class="g-container">
        <div class="g-header">
            <div class="c-col c-no">No.</div>
            <div class="c-col c-pname">Project Name</div>
            <div class="c-col c-date">Start Date</div>
            <div class="c-col c-date">End Date</div>
            <div class="c-col c-days">Days</div>
            <div class="c-timeline-hdr">
                <div class="hdr-row">{m_hdr_html}</div>
                <div class="hdr-row">{w_hdr_html}</div>
            </div>
        </div>
        {rows_html}
    </div>
</body>
</html>
"""
    return html


def render_project_gantt_chart(calc_df, disciplines, team_mode, count_col, hide_completed=True):
    name_col = find_name_col(calc_df)
    gantt_df = calc_df.copy()
    gantt_df["Start"] = pd.to_datetime(gantt_df["Start Date"], errors="coerce")
    gantt_df["End"] = pd.to_datetime(gantt_df["End Date"], errors="coerce")

    # If End Date was omitted or empty, set to Start Date
    gantt_df["End"] = gantt_df["End"].fillna(gantt_df["Start"])
    gantt_df["Start"] = gantt_df["Start"].fillna(gantt_df["End"])

    gantt_df = gantt_df.dropna(subset=["Start", "End"])
    gantt_df = gantt_df[gantt_df["End"] >= gantt_df["Start"]]

    today = pd.Timestamp.today().normalize()
    if hide_completed:
        gantt_df = gantt_df[gantt_df["End"] >= today]

    if gantt_df.empty:
        st.info("No ongoing or upcoming projects with valid dates to display.")
        return

    hrs_cols = [f"{d} (Hrs)" for d in disciplines if f"{d} (Hrs)" in gantt_df.columns]
    gantt_df["Project"] = gantt_df.apply(lambda r: make_project_label(r, name_col), axis=1)

    # Prevent Altair from grouping projects with identical names onto the same row
    if gantt_df["Project"].duplicated().any():
        seen = {}
        unique_labels = []
        for p in gantt_df["Project"]:
            count = seen.get(p, 0) + 1
            seen[p] = count
            unique_labels.append(f"{p} ({count})" if count > 1 else p)
        gantt_df["Project"] = unique_labels

    # 1-day tasks must have EndPlus = End + 1 day so the bar spans the full day
    gantt_df["EndPlus"] = gantt_df["End"] + pd.Timedelta(days=1)
    gantt_df["TotalHrs"] = gantt_df[hrs_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1) if hrs_cols else 0.0

    def _calc_workdays(s, e):
        try:
            wd = int(np.busday_count(s.date(), e.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
            return max(wd, 1) if s.date() == e.date() else wd
        except Exception:
            return 1

    gantt_df["WorkDays"] = [_calc_workdays(s, e) for s, e in zip(gantt_df["Start"], gantt_df["End"])]
    gantt_df = gantt_df.sort_values(["Start", "End"])
    gantt_df["DateRange"] = [
        f"{s:%d-%b-%Y}" if s.date() == e.date() else f"{s:%d-%b-%Y}  →  {e:%d-%b-%Y}"
        for s, e in zip(gantt_df["Start"], gantt_df["End"])
    ]
    project_order = gantt_df["Project"].tolist()

    x_min = gantt_df["Start"].min() - pd.Timedelta(days=2)
    span_days = max(1, (gantt_df["EndPlus"].max() - gantt_df["Start"].min()).days)
    x_max = gantt_df["EndPlus"].max() + pd.Timedelta(days=max(14, int(span_days * 0.25)))
    x_scale = alt.Scale(domain=[x_min.isoformat(), x_max.isoformat()])

    extra_tooltips = []
    if team_mode == "team_count" and count_col is not None and count_col in gantt_df.columns:
        gantt_df["TeamCount"] = pd.to_numeric(gantt_df[count_col], errors="coerce")
        extra_tooltips.append(alt.Tooltip("TeamCount:Q", title="Team count"))

    tooltip_items = [
        alt.Tooltip("Project:N", title="Project"),
        alt.Tooltip("Start:T", title="Start", format="%a %d-%b-%Y"),
        alt.Tooltip("End:T", title="End", format="%a %d-%b-%Y"),
        alt.Tooltip("WorkDays:Q", title="Working days (Sun-Thu)"),
        alt.Tooltip("TotalHrs:Q", title="Total hours", format=",.0f"),
        *extra_tooltips,
    ]

    # Main horizontal bar layer
    bars = alt.Chart(gantt_df).mark_bar(cornerRadius=3).encode(
        y=alt.Y("Project:N", sort=project_order, title=None, axis=alt.Axis(labelLimit=250)),
        x=alt.X("Start:T", scale=x_scale, title="Date", axis=alt.Axis(format="%d-%b", labelAngle=-45)),
        x2="EndPlus:T",
        color=alt.Color("Project:N", legend=None),
        tooltip=tooltip_items,
    )

    # Highlight same-day tasks with diamond marker so they stand out clearly regardless of timeline zoom
    same_day_df = gantt_df[gantt_df["Start"].dt.date == gantt_df["End"].dt.date]
    point_layer = None
    if not same_day_df.empty:
        point_layer = alt.Chart(same_day_df).mark_point(
            size=120, shape="diamond", filled=True, color="#d9480f"
        ).encode(
            y=alt.Y("Project:N", sort=project_order),
            x=alt.X("Start:T", scale=x_scale),
            tooltip=tooltip_items,
        )

    date_labels = alt.Chart(gantt_df).mark_text(
        align="left", baseline="middle", dx=6, fontSize=11
    ).encode(
        y=alt.Y("Project:N", sort=project_order),
        x=alt.X("EndPlus:T", scale=x_scale),
        text="DateRange:N",
    )

    layers = [bars]
    if point_layer is not None:
        layers.append(point_layer)
    layers.append(date_labels)

    if gantt_df["Start"].min() <= today <= gantt_df["EndPlus"].max():
        today_rule = alt.Chart(pd.DataFrame({"Today": [today]})).mark_rule(
            color="red", strokeDash=[5, 4], strokeWidth=2
        ).encode(x=alt.X("Today:T", scale=x_scale))
        layers.append(today_rule)

    gantt_chart = alt.layer(*layers).properties(height=max(150, 34 * len(gantt_df) + 60))
    st.altair_chart(gantt_chart, use_container_width=True)


# ----------------------------------------------------------------------
# 2d. Main View: All 4 Teams Gantt Charts in One Page (2 Side-by-Side)
# ----------------------------------------------------------------------
def render_main_overview():
    st.subheader("🗓️ Project Timelines - Main Overview (All Teams)")

    col_f1, col_f2 = st.columns([2, 2])
    with col_f1:
        hide_comp = st.checkbox("Filter completed", value=False, key="main_hide_comp")
    with col_f2:
        if st.button("🔄 Refresh All Sheets", use_container_width=True):
            load_from_gsheet.clear()
            load_team_counts.clear()
            st.session_state["refresh_all_backup"] = True
            st.rerun()

    do_backup_all = st.session_state.pop("refresh_all_backup", False)
    if do_backup_all:
        st.toast("🔄 Refreshing all sheets and archiving backups...")

    team_order = ["BIM Team", "Tech Team", "Design Team", "QC Team"]
    valid_teams = [t for t in team_order if t in TEAMS]

    all_completed_projects = []
    today = datetime.date.today()

    # Render pairs of 2 teams side-by-side
    for i in range(0, len(valid_teams), 2):
        pair = valid_teams[i:i + 2]
        cols = st.columns(2)
        for col_idx, t_name in enumerate(pair):
            with cols[col_idx]:
                cfg = TEAMS[t_name]
                st.markdown(f"### 👥 {t_name}")
                try:
                    csv_url = build_csv_url(cfg["sheet_id"], cfg["gid"])
                    team_df, team_counts = load_from_gsheet(csv_url, cfg["disciplines"])
                    
                    # Also fetch team counts tab if configured
                    if cfg.get("count_sheet") or cfg.get("count_gid") is not None:
                        if cfg.get("count_gid") is not None:
                            c_url = build_csv_url(cfg["sheet_id"], cfg["count_gid"])
                        else:
                            c_url = build_sheet_name_url(cfg["sheet_id"], cfg["count_sheet"])
                        try:
                            tab_c = load_team_counts(c_url, cfg["disciplines"])
                            if tab_c:
                                team_counts = tab_c
                        except Exception:
                            pass

                    # Auto-backup on Refresh All or if no backup exists yet
                    if do_backup_all or not list_backups(t_name):
                        if team_df is not None and not team_df.empty:
                            save_backup(t_name, team_df, team_counts)

                    team_calc_df, t_count_col = prepare_calc_df(team_df, cfg["mode"], cfg["disciplines"])
                    render_project_gantt_chart(team_calc_df, cfg["disciplines"], cfg["mode"], t_count_col, hide_comp)

                    # Collect completed projects for this team
                    name_col = find_name_col(team_calc_df)
                    for _, r in team_calc_df.iterrows():
                        e_date = r.get("End Date")
                        if pd.notnull(e_date):
                            if isinstance(e_date, str):
                                e_date = pd.to_datetime(e_date, errors="coerce").date()
                            elif isinstance(e_date, pd.Timestamp):
                                e_date = e_date.date()

                            if e_date and e_date < today:
                                p_label = make_project_label(r, name_col)
                                all_completed_projects.append({
                                    "Project Name": p_label,
                                    "End Date": e_date,
                                    "Department": t_name,
                                })

                except Exception as e:
                    st.error(f"Could not load data for {t_name}: {e}")
        st.markdown("---")

    if do_backup_all:
        st.success("✅ Refreshed all sheets and automatically archived backup snapshots for each team.")

    # ------------------------------------------------------------------
    # Completed Projects Section (English Interface & Date Range Filters)
    # ------------------------------------------------------------------
    st.subheader("🏁 Completed Projects Register")

    if not all_completed_projects:
        st.info("No completed projects recorded across any team.")
    else:
        comp_df = pd.DataFrame(all_completed_projects)

        min_date = comp_df["End Date"].min()
        max_date = comp_df["End Date"].max()

        f_col1, f_col2, f_col3 = st.columns([1.6, 1, 1])
        with f_col1:
            selected_teams = st.multiselect(
                "👥 Filter by Department / Team:",
                options=valid_teams,
                default=valid_teams,
                key="completed_team_filter"
            )
        with f_col2:
            start_date_filter = st.date_input(
                "📅 End Date (From):",
                value=min_date,
                key="completed_start_date"
            )
        with f_col3:
            end_date_filter = st.date_input(
                "📅 End Date (To):",
                value=max_date,
                key="completed_end_date"
            )

        if start_date_filter > end_date_filter:
            st.warning("⚠️ Start Date must be before or equal to End Date.")
            filtered_comp = pd.DataFrame(columns=["Project Name", "End Date", "Department"])
        else:
            mask = (
                (comp_df["Department"].isin(selected_teams)) &
                (comp_df["End Date"] >= start_date_filter) &
                (comp_df["End Date"] <= end_date_filter)
            )
            filtered_comp = comp_df[mask].sort_values("End Date", ascending=False).reset_index(drop=True)

        # Summary metrics
        metric_cols = st.columns(len(selected_teams) + 1)
        metric_cols[0].metric("📊 Total Completed", len(filtered_comp))
        for idx, t in enumerate(selected_teams):
            t_count = len(filtered_comp[filtered_comp["Department"] == t])
            metric_cols[idx + 1].metric(f"{t}", t_count)

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

        # Tabs for unified view and per-team breakdown
        tab_labels = [f"📋 All Departments ({len(filtered_comp)})"] + [
            f"👥 {t} ({len(filtered_comp[filtered_comp['Department'] == t])})"
            for t in selected_teams
        ]
        comp_tabs = st.tabs(tab_labels)

        with comp_tabs[0]:
            if filtered_comp.empty:
                st.info("No completed projects match the selected filter criteria.")
            else:
                st.dataframe(
                    filtered_comp[["Project Name", "End Date", "Department"]],
                    use_container_width=True,
                    hide_index=True
                )

        for idx, t in enumerate(selected_teams):
            with comp_tabs[idx + 1]:
                t_sub = filtered_comp[filtered_comp["Department"] == t][["Project Name", "End Date"]]
                if t_sub.empty:
                    st.info(f"No completed projects for {t} within the selected date range.")
                else:
                    st.dataframe(t_sub, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------
# Team selection
# ----------------------------------------------------------------------
selected_team = st.radio(
    "👥 Select View / Team:", [MAIN_OPTION] + list(TEAMS.keys()) + [GANTT_OPTION], horizontal=True
)

if selected_team == MAIN_OPTION:
    render_main_overview()
    st.stop()

if selected_team == GANTT_OPTION:
    render_wbs_gantt()
    st.stop()

team_cfg = TEAMS[selected_team]
team_mode = team_cfg["mode"]
disciplines = team_cfg["disciplines"]
SHEET_ID = team_cfg["sheet_id"]
CSV_URL = build_csv_url(SHEET_ID, team_cfg["gid"])

# ----------------------------------------------------------------------
# 2e. Data Source Selection & Automatic Backup Controls
# ----------------------------------------------------------------------
st.markdown("---")

# Check if a refresh was triggered
do_refresh_backup = st.session_state.pop(f"refresh_backup_{selected_team}", False)

# Fetch Live Data
live_projects = None
live_eng_counts = {}
try:
    live_projects, live_eng_counts = load_from_gsheet(CSV_URL, disciplines)
    if team_cfg.get("count_sheet") or team_cfg.get("count_gid") is not None:
        if team_cfg.get("count_gid") is not None:
            c_url = build_csv_url(SHEET_ID, team_cfg["count_gid"])
        else:
            c_url = build_sheet_name_url(SHEET_ID, team_cfg["count_sheet"])
        try:
            tab_c = load_team_counts(c_url, disciplines)
            if tab_c:
                live_eng_counts = tab_c
        except Exception:
            pass

    # Save backup automatically upon refresh, or on initial run if no backups exist yet
    if (do_refresh_backup or not list_backups(selected_team)) and live_projects is not None and not live_projects.empty:
        new_ts = save_backup(selected_team, live_projects, live_eng_counts)
        if do_refresh_backup:
            st.toast(f"✅ Auto-backup archived on refresh: {format_backup_label(new_ts)}")

except Exception as e:
    st.error(f"Could not read the {selected_team} Google Sheet ({e}). Using empty template.")
    live_projects = get_empty_template(team_mode, disciplines)

# List available backups after ensuring initial/refresh backup is saved
available_backups = list_backups(selected_team)

c_mode, c_hist, c_actions = st.columns([1.8, 1.8, 2.8])
with c_mode:
    data_source = st.radio(
        "📂 Data Source:",
        ["🟢 Live Google Sheet", "🕰️ Historical Backup"],
        horizontal=True,
        help="Choose whether to load current live data from Google Sheet or load a previous snapshot."
    )

selected_backup_date = None
with c_hist:
    if data_source == "🕰️ Historical Backup":
        if available_backups:
            selected_backup_date = st.selectbox(
                "📅 Select Backup Snapshot:",
                available_backups,
                format_func=format_backup_label,
                index=0
            )
        else:
            st.warning("No previous backups found for this team yet.")

with c_actions:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    c_btn1, c_btn2, c_btn3 = st.columns([1, 1, 1.4])
    with c_btn1:
        refresh_clicked = st.button("🔄 Refresh Sheet", use_container_width=True)
    with c_btn2:
        save_backup_now = st.button("💾 Save Backup", use_container_width=True, help="Immediately save current data as a backup snapshot.")
    with c_btn3:
        st.link_button("🔗 Open Google Sheet", f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit", use_container_width=True)

if refresh_clicked:
    load_from_gsheet.clear()
    load_team_counts.clear()
    for d in disciplines:
        st.session_state.pop(f"eng_{selected_team}_{d}", None)
    st.session_state[f"refresh_backup_{selected_team}"] = True
    st.rerun()

if save_backup_now and live_projects is not None:
    saved_ts = save_backup(selected_team, live_projects, live_eng_counts)
    st.success(f"✅ Saved backup snapshot: {format_backup_label(saved_ts)}")
    st.rerun()

# Determine active dataset based on user selection
counts_source = "defaults"
if data_source == "🕰️ Historical Backup" and selected_backup_date:
    df_projects, sheet_eng_counts = load_backup(selected_team, selected_backup_date)
    if df_projects is None or df_projects.empty:
        st.warning("⚠️ Could not load backup data. Reverting to live data.")
        df_projects = live_projects if live_projects is not None else get_empty_template(team_mode, disciplines)
        sheet_eng_counts = live_eng_counts
        counts_source = "Live Google Sheet"
    else:
        counts_source = f"Backup ({format_backup_label(selected_backup_date)})"
        st.info(f"🕰️ **Viewing Historical Snapshot from {format_backup_label(selected_backup_date)}**. All calculations and timelines below reflect this snapshot.")
else:
    df_projects = live_projects if live_projects is not None else get_empty_template(team_mode, disciplines)
    sheet_eng_counts = live_eng_counts
    counts_source = "Live Google Sheet"
    st.success(f"🟢 **{selected_team}**: Viewing Live Data from Google Sheet (Auto-backup enabled on refresh).")

# ----------------------------------------------------------------------
# 2f. Differences & Change Comparison
# ----------------------------------------------------------------------
with st.expander("🔍 Compare Changes with a Previous Backup"):
    cmp_backups = list_backups(selected_team)
    if not cmp_backups:
        st.info("No saved backup files available to compare.")
    elif live_projects is None:
        st.warning("Live data not available to compare.")
    else:
        cmp_date = st.selectbox(
            "Select historical backup to compare against current live data:",
            cmp_backups,
            format_func=format_backup_label,
            key="cmp_date"
        )
        hist_df, hist_counts = load_backup(selected_team, cmp_date)
        if hist_df is not None:
            added, removed, modified = compare_datasets(live_projects, hist_df, disciplines)

            m_c1, m_c2, m_c3 = st.columns(3)
            m_c1.metric("🆕 New Projects Added", len(added))
            m_c2.metric("❌ Removed / Completed", len(removed))
            m_c3.metric("🔄 Modified Projects", len(modified))

            if added:
                st.markdown("**🆕 Projects added in current data:**")
                st.write(", ".join(added))

            if removed:
                st.markdown("**❌ Projects present in backup but missing in current data:**")
                st.write(", ".join(removed))

            if modified:
                st.markdown("**🔄 Detailed Project Differences (Start, End, or Allocated Hours):**")
                st.dataframe(pd.DataFrame(modified), use_container_width=True, hide_index=True)

            if not added and not removed and not modified:
                st.success("✅ Identical: No differences detected between current data and this backup.")

# ----------------------------------------------------------------------
# 3. Sidebar - Capacity Settings
# ----------------------------------------------------------------------
st.sidebar.header("⚙️ Team Capacity Settings")
st.sidebar.caption(f"Team: **{selected_team}**")
st.sidebar.caption(f"Engineers count source: {counts_source}")
hours_per_day = st.sidebar.number_input(
    "Working Hours per Day (per engineer)",
    min_value=1.0, max_value=12.0, value=float(HOURS_PER_DAY), step=0.5,
    help="Daily capacity = Engineers × Hours per Day × Efficiency Factor.",
)
st.sidebar.markdown("Set the number of available engineers:")

default_engineers = [
    sheet_eng_counts.get(disc, fallback)
    for disc, fallback in zip(disciplines, team_cfg["engineers"])
]

engineers = {}
capacities = {}
efficiency = st.sidebar.slider("Efficiency Factor (%)", 50, 100, 80) / 100.0

for disc, default in zip(disciplines, default_engineers):
    engineers[disc] = st.sidebar.number_input(
        f"{disc} Engineers", value=int(default), min_value=0, key=f"eng_{selected_team}_{data_source}_{selected_backup_date}_{disc}"
    )
    capacities[disc] = engineers[disc] * hours_per_day * efficiency

total_team_engineers = sum(engineers.values())
st.sidebar.markdown("---")
st.sidebar.metric("👥 Total Team Engineers", total_team_engineers)

# ----------------------------------------------------------------------
# 4. Project table
# ----------------------------------------------------------------------
st.subheader("📋 Project Register & Hours Allocation")
st.caption("Changes made in this table are temporary (for what-if analysis). To preserve changes, update Google Sheets or save a backup.")

edited_df = st.data_editor(
    df_projects,
    key=f"editor_{selected_team}_{data_source}_{selected_backup_date}",
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)

# ----------------------------------------------------------------------
# 4a. Prepare hours column in background
# ----------------------------------------------------------------------
calc_df, count_col = prepare_calc_df(edited_df, team_mode, disciplines, hours_per_day)

# ----------------------------------------------------------------------
# 4b. Project Timeline (Gantt Chart & Exact-Fit A3 Vector PDF Option)
# ----------------------------------------------------------------------
st.markdown("---")
st.subheader("🗓️ Project Timeline (Gantt Chart)")

col_g1, col_g2 = st.columns([2.5, 1.5])
with col_g1:
    hide_completed = st.checkbox("Filter completed", value=False, key=f"hide_comp_{selected_team}")

team_a3_html = generate_team_a3_vector_gantt_html(calc_df, selected_team, disciplines)
team_pdf_bytes = export_a3_pdf(team_a3_html)

with col_g2:
    if team_pdf_bytes:
        st.download_button(
            "📥 Download Team A3 Vector PDF",
            data=team_pdf_bytes,
            file_name=f"{_get_safe_team_name(selected_team)}_Timeline_A3_{datetime.date.today().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            use_container_width=True,
            help="Download high-resolution A3 Landscape Vector PDF for this team"
        )
    else:
        st.download_button(
            "📄 Download Team A3 HTML",
            data=team_a3_html,
            file_name=f"{_get_safe_team_name(selected_team)}_Timeline_A3_{datetime.date.today().strftime('%Y%m%d')}.html",
            mime="text/html",
            use_container_width=True,
            help="Open in browser and choose Print -> Save as PDF (A3 Landscape)"
        )

render_project_gantt_chart(calc_df, disciplines, team_mode, count_col, hide_completed)

# ----------------------------------------------------------------------
# 5. Calculation Engine (daily, Sunday - Thursday)
# ----------------------------------------------------------------------
st.markdown("---")
st.subheader("🔥 Daily Bottleneck Analysis & Executive Dashboard")

col1, col2 = st.columns(2)
with col1:
    start_timeline = st.date_input("Timeline Start Date:", value=datetime.date.today())
with col2:
    num_weeks = st.slider("Number of Weeks to Analyze:", 1, 12, 4)

num_days = num_weeks * 5
days = [d.date() for d in pd.bdate_range(start=start_timeline, periods=num_days, freq="C", weekmask=PD_WEEKMASK)]
day_labels = [d.strftime("%a %d-%b") for d in days]

demand = {disc: [0.0] * num_days for disc in disciplines}

for idx, row in calc_df.iterrows():
    if pd.isnull(row.get("Start Date")) or pd.isnull(row.get("End Date")):
        continue

    s_date = row["Start Date"]
    e_date = row["End Date"]
    if isinstance(s_date, str):
        s_date = pd.to_datetime(s_date, errors="coerce").date()
    if isinstance(e_date, str):
        e_date = pd.to_datetime(e_date, errors="coerce").date()

    if not s_date or not e_date:
        continue

    workdays_total = np.busday_count(s_date, e_date + datetime.timedelta(days=1), weekmask=NP_WEEKMASK)
    if workdays_total <= 0:
        if s_date == e_date:
            workdays_total = 1
        else:
            continue

    for disc in disciplines:
        col_name = f"{disc} (Hrs)"
        if col_name not in row or pd.isnull(row.get(col_name)):
            continue

        try:
            total_hrs = float(row[col_name])
        except (ValueError, TypeError):
            continue

        daily_rate = total_hrs / workdays_total

        for i, day in enumerate(days):
            if s_date <= day <= e_date:
                demand[disc][i] += daily_rate

# ----------------------------------------------------------------------
# 6. Display Charts and Tables
# ----------------------------------------------------------------------
tabs = st.tabs(disciplines)


def highlight_bottlenecks(val):
    if isinstance(val, (int, float)) and val < 0:
        return "background-color: #ffcccc; color: #900000; font-weight: bold"
    return ""


for idx, disc in enumerate(disciplines):
    with tabs[idx]:
        team_title = disc if disc.endswith("Team") else f"{disc} Team"
        st.markdown(f"### {team_title} Analysis (Daily)")

        results_df = pd.DataFrame({
            "Metric": ["Demand (Hrs)", "Capacity (Hrs)", "Variance (Shortage/Surplus)"],
        })

        var_list, dem_list, cap_list = [], [], []

        for i, d_label in enumerate(day_labels):
            dem = round(demand[disc][i], 1)
            cap = capacities[disc]
            var = round(cap - dem, 1)

            results_df[d_label] = [dem, cap, var]
            var_list.append(var)
            dem_list.append(dem)
            cap_list.append(cap)

        short_days = [(day_labels[i], v) for i, v in enumerate(var_list) if v < 0]
        if short_days:
            worst = min(short_days, key=lambda x: x[1])
            st.warning(f"⚠️ {len(short_days)} bottleneck day(s) out of {num_days}. Worst: **{worst[0]}** ({worst[1]:.2f} hrs).")
        else:
            st.success("✅ No bottlenecks in the selected period.")

        st.dataframe(
            results_df.style
                .map(highlight_bottlenecks, subset=day_labels)
                .format("{:.2f}", subset=day_labels),
            use_container_width=True,
        )

        chart_data = pd.DataFrame({
            "Day": day_labels,
            "Variance (Shortage/Surplus)": var_list,
            "Demand": dem_list,
            "Capacity": cap_list,
        })
        chart_data["Color"] = np.where(chart_data["Variance (Shortage/Surplus)"] >= 0, "#2ca02c", "#d62728")

        st.markdown("#### 📉 Daily Variance Chart (Dips below 0 indicate bottlenecks)")
        variance_chart = alt.Chart(chart_data).mark_bar().encode(
            x=alt.X("Day:N", sort=day_labels, title="Day", axis=alt.Axis(labelAngle=-90)),
            y=alt.Y("Variance (Shortage/Surplus):Q", title="Variance (Shortage/Surplus)"),
            color=alt.Color("Color:N", scale=None),
            tooltip=["Day", "Variance (Shortage/Surplus)", "Demand", "Capacity"],
        )
        st.altair_chart(variance_chart, use_container_width=True)

        st.markdown("#### 📈 Daily Demand vs Capacity Trend")
        trend_df = chart_data.melt(
            id_vars="Day", value_vars=["Demand", "Capacity"],
            var_name="Metric", value_name="Hours",
        )
        trend_chart = alt.Chart(trend_df).mark_line(point=True).encode(
            x=alt.X("Day:N", sort=day_labels, title="Day", axis=alt.Axis(labelAngle=-90)),
            y=alt.Y("Hours:Q"),
            color=alt.Color("Metric:N"),
            tooltip=["Day", "Metric", "Hours"],
        )
        st.altair_chart(trend_chart, use_container_width=True)
