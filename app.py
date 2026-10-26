import os
import glob
import json
import datetime
from urllib.parse import quote
import html as _html
import io

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
    """Generates A3 PDF bytes from HTML if weasyprint is installed and working."""
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
# 2b. WBS Gantt Chart: Interactive View & MS Project A3 Vector PDF Builder
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


def build_a3_single_page_html(df, schedule_title="PROJECT SCHEDULE & WORK BREAKDOWN STRUCTURE (WBS)"):
    """
    Builds an authentic Microsoft Project-style A3 Landscape vector HTML/PDF schedule
    calibrated strictly to fit onto 1 single A3 page (420mm x 297mm) with zero overflow.
    Features:
      - Classic MS Project Entry Sheet Columns: ID, Indicator/Mode Icon, WBS, Task Name (with
        Project Summary & Stage Summary rollup hierarchy), Duration, Start, Finish, Department, Resource Names
      - Adaptive 3-Tier MS Project Timescale Header (Month/Quarter, Week, Day-of-Week)
      - Full-height vertical gridlines (Months, Weeks, Fri-Sat Non-Working Weekend shading, Red Today Status Line)
      - Authentic MS Project Summary Rollup Bars (dark charcoal bracket bars with downward triangular end-caps)
      - Beveled vector Task Bars with elapsed progress fill, Milestone diamonds (◆), and Finish-to-Start (FS) link connectors
      - Professional Engineering Schedule Footer & Graphical Legend Title Block
    """
    esc = lambda v: _html.escape(str(v), quote=True)
    today = pd.Timestamp.today().normalize()

    if df is None or df.empty:
        return "<html><body><h3>No tasks to display</h3></body></html>"

    wdf = df.copy()
    wdf["Start Date"] = pd.to_datetime(wdf["Start Date"], errors="coerce")
    wdf["End Date"] = pd.to_datetime(wdf["End Date"], errors="coerce")
    wdf = wdf.dropna(subset=["Start Date", "End Date"]).reset_index(drop=True)
    if wdf.empty:
        return "<html><body><h3>No valid task dates to display</h3></body></html>"

    # Plot coordinates (use snapped Start/End if available, otherwise Start Date / End Date)
    if "Start" not in wdf.columns:
        wdf["Start"] = wdf["Start Date"]
    else:
        wdf["Start"] = pd.to_datetime(wdf["Start"], errors="coerce").fillna(wdf["Start Date"])

    if "End" not in wdf.columns:
        wdf["End"] = wdf["End Date"]
    else:
        wdf["End"] = pd.to_datetime(wdf["End"], errors="coerce").fillna(wdf["End Date"])

    # Clean task name so WBS Code is not duplicated inside the Task Name column
    raw_tasks = []
    for _, r in wdf.iterrows():
        c_str = str(r.get("Code", "")).strip()
        t_str = str(r.get("Task", "")).strip()
        if c_str and t_str.startswith(c_str):
            cleaned = t_str[len(c_str):].lstrip(" ·-:")
            raw_tasks.append(cleaned if cleaned else t_str)
        else:
            raw_tasks.append(t_str if t_str else "Task")
    wdf["_CleanTask"] = raw_tasks

    if "WorkDays" not in wdf.columns:
        wds = []
        for s, e in zip(wdf["Start Date"], wdf["End Date"]):
            wd = int(np.busday_count(s.date(), e.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
            if s.date() == e.date() and wd == 0:
                wd = 1
            wds.append(max(1, wd))
        wdf["WorkDays"] = wds

    if "Stage" not in wdf.columns:
        wdf["Stage"] = "Project Schedule"
    if "Disc" not in wdf.columns:
        wdf["Disc"] = "-"
    if "Resp" not in wdf.columns:
        wdf["Resp"] = ""
    if "Code" not in wdf.columns:
        wdf["Code"] = [str(i + 1) for i in range(len(wdf))]

    # Timeline bounds aligned to Sunday (start of KSA workweek)
    min_start = wdf["Start"].min().normalize()
    max_end = wdf["End"].max().normalize()
    origin = min_start - pd.Timedelta(days=(min_start.dayofweek + 1) % 7)
    span_raw = max(7, int((max_end - origin).days) + 1)
    right_pad_days = max(7, int(span_raw * 0.08))
    last = max_end + pd.Timedelta(days=right_pad_days)
    # Align `last` to Saturday (end of week) so week blocks are exact 7-day multiples
    rem = (5 - last.dayofweek) % 7
    last = last + pd.Timedelta(days=rem)
    total_days = max(7, int((last - origin).days) + 1)
    all_days = pd.date_range(origin, last, freq="D")

    def get_pos(dt):
        d = (pd.Timestamp(dt).normalize() - origin).days
        return round((d / total_days) * 100, 4)

    def get_width(s, e):
        d = (pd.Timestamp(e).normalize() - pd.Timestamp(s).normalize()).days + 1
        return max(round((d / total_days) * 100, 4), 0.35)

    # Group by Stage in chronological order (MS Project Summary Tasks)
    stage_order = wdf.groupby("Stage")["Start"].min().sort_values().index.tolist()
    include_project_summary = len(stage_order) > 1
    n_summary_rows = len(stage_order) + (1 if include_project_summary else 0)
    n_total_rows = len(wdf) + n_summary_rows

    # Strict 1-Page A3 Landscape Vertical Budget
    # Printable height on A3 Landscape (297mm - 10mm margin = 287mm)
    # Header Banner (38px) + 3-Tier Timescale Header (42px) + Legend Footer (28px) = 108px
    avail_h = 910
    row_h = max(10, min(22, int(avail_h / max(1, n_total_rows))))
    bar_h = max(5, min(13, int(row_h * 0.58)))
    sum_bar_h = max(4, min(6, int(row_h * 0.28)))
    font_sz = max(6.8, min(10.0, round(row_h * 0.48, 1)))
    sub_font_sz = max(6.0, round(font_sz - 0.8, 1))

    # MS Project Stage Palette (Classic MS Project blues, emeralds, ambers, purples, teals)
    ms_palette = [
        ("#2b6cb0", "#1e4e8c", "#63b3ed"),  # MS Project Classic Steel Blue
        ("#2f855a", "#22543d", "#68d391"),  # Emerald Green
        ("#c05621", "#7b341e", "#f6ad55"),  # Warm Ochre / Orange
        ("#6b46c1", "#44337a", "#b794f4"),  # Royal Purple
        ("#0987a0", "#065666", "#4fd1c5"),  # Cyan / Teal
        ("#b83280", "#702459", "#f687b3"),  # Magenta / Plum
        ("#2c5282", "#1a365d", "#90cdf4"),  # Deep Navy Blue
        ("#975a16", "#5f370e", "#fbd38d"),  # Goldenrod
        ("#285e61", "#1d4044", "#81e6d9"),  # Deep Slate Teal
        ("#742a2a", "#4a1c1c", "#feb2b2"),  # Crimson Brick
    ]
    stage_colors = {s: ms_palette[i % len(ms_palette)] for i, s in enumerate(stage_order)}

    # Build Timescale Header Tiers:
    # Tier 1: Months
    month_blocks = []
    i = 0
    while i < total_days:
        j = i
        while j < total_days and all_days[j].month == all_days[i].month and all_days[j].year == all_days[i].year:
            j += 1
        span = j - i
        pct = round((span / total_days) * 100, 4)
        lbl = all_days[i].strftime("%B %Y") if pct >= 8.0 else all_days[i].strftime("%b '%y")
        month_blocks.append((lbl, pct, round((i / total_days) * 100, 4)))
        i = j

    # Tier 2: Weeks (starting Sunday)
    week_blocks = []
    i = 0
    while i < total_days:
        span = min(7, total_days - i)
        pct = round((span / total_days) * 100, 4)
        left_p = round((i / total_days) * 100, 4)
        if pct >= 2.4:
            lbl = all_days[i].strftime("%d %b")
        elif pct >= 1.2:
            lbl = all_days[i].strftime("%d/%m")
        else:
            lbl = all_days[i].strftime("%d")
        week_blocks.append((lbl, pct, left_p))
        i += 7

    # Tier 3: Daily Cells (when total_days <= 140) or Sub-Week Ticks (when total_days > 140)
    day_letters = ["M", "T", "W", "T", "F", "S", "S"]
    if total_days <= 140:
        day_w_pct = round(100.0 / total_days, 4)
        day_cells = []
        for d in all_days:
            is_wknd = d.dayofweek in (4, 5)  # Friday=4, Saturday=5
            dl = day_letters[d.dayofweek] if total_days <= 98 else ""
            wk_cls = " t-day-wknd" if is_wknd else ""
            day_cells.append(f'<div class="t-day-cell{wk_cls}" style="width:{day_w_pct}%">{dl}</div>')
        day_tier_html = f'<div class="hdr-row hdr-tier-days">{"".join(day_cells)}</div>'
    else:
        # Render week day-number sub-band so 3-tier MS Project look is preserved at all scales
        sub_cells = [
            f'<div class="hdr-cell hdr-subweek" style="width:{pct}%;">W{idx+1}</div>'
            for idx, (_, pct, _) in enumerate(week_blocks)
        ]
        day_tier_html = f'<div class="hdr-row hdr-tier-days">{"".join(sub_cells)}</div>'

    # Background vertical gridlines (Weeks, Months, Weekend shading, and Today line)
    grid_overlays = []
    if total_days <= 180:
        for idx_d, d in enumerate(all_days):
            if d.dayofweek == 4:  # Friday start of 2-day weekend
                w_span = min(2, total_days - idx_d)
                l_pct = round((idx_d / total_days) * 100, 4)
                w_pct = round((w_span / total_days) * 100, 4)
                grid_overlays.append(
                    f'<div class="bg-wknd" style="left:{l_pct}%;width:{w_pct}%"></div>'
                )

    for _, _, left_p in week_blocks:
        if left_p > 0:
            grid_overlays.append(f'<div class="bg-week-line" style="left:{left_p}%"></div>')

    for _, _, left_p in month_blocks:
        if left_p > 0:
            grid_overlays.append(f'<div class="bg-month-line" style="left:{left_p}%"></div>')

    today_line_html = ""
    today_hdr_badge = ""
    if origin <= today <= last:
        t_pct = get_pos(today)
        today_line_html = f'<div class="bg-today-line" style="left:{t_pct}%"></div>'
        today_hdr_badge = f'<div class="today-flag" style="left:{t_pct}%">TODAY</div>'

    grid_bg_html = "".join(grid_overlays) + today_line_html

    # Helper SVG icons for MS Project Task Mode / Indicator column
    svg_mode_summary = (
        '<svg width="11" height="11" viewBox="0 0 12 12" style="display:block;margin:auto;">'
        '<path d="M1 3h10v3H9l-1.5 2v-2h-3v2L3 6H1V3z" fill="#0f172a"/>'
        '</svg>'
    )
    svg_mode_task = (
        '<svg width="11" height="11" viewBox="0 0 12 12" style="display:block;margin:auto;">'
        '<rect x="1" y="3.5" width="10" height="5" rx="1" fill="#2b6cb0" stroke="#1e4e8c" stroke-width="0.8"/>'
        '<path d="M3 2l-1.5 1.5L3 5M9 2l1.5 1.5L9 5" stroke="#475569" stroke-width="0.9" fill="none"/>'
        '</svg>'
    )
    svg_mode_done = (
        '<svg width="11" height="11" viewBox="0 0 12 12" style="display:block;margin:auto;">'
        '<circle cx="6" cy="6" r="4.8" fill="#16a34a"/>'
        '<path d="M3.6 6.2l1.6 1.6 3.2-3.4" stroke="#ffffff" stroke-width="1.4" fill="none" stroke-linecap="round"/>'
        '</svg>'
    )
    svg_mode_milestone = (
        '<svg width="10" height="10" viewBox="0 0 12 12" style="display:block;margin:auto;">'
        '<polygon points="6,1 11,6 6,11 1,6" fill="#0f172a"/>'
        '</svg>'
    )

    fmt_date = lambda dt: pd.Timestamp(dt).strftime("%a %d-%b-%y")
    fmt_short = lambda dt: pd.Timestamp(dt).strftime("%d-%b")

    # Build Rows (Project Summary + Stage Summaries + Subtasks)
    rows_html = []
    row_id = 0

    all_s_min = wdf["Start Date"].min()
    all_e_max = wdf["End Date"].max()
    all_wd_total = max(
        1,
        int(np.busday_count(all_s_min.date(), all_e_max.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
    )

    if include_project_summary:
        row_id += 1
        p_left = get_pos(wdf["Start"].min())
        p_width = get_width(wdf["Start"].min(), wdf["End"].max())
        p_lbl_pos = (
            f"left:calc({round(p_left + p_width, 2)}% + 6px);"
            if (p_left + p_width) < 84
            else f"right:calc({round(100 - p_left, 2)}% + 6px);"
        )
        rows_html.append(f"""
        <div class="g-row g-row-proj-sum">
            <div class="c-col c-id">{row_id}</div>
            <div class="c-col c-mode">{svg_mode_summary}</div>
            <div class="c-col c-code">0</div>
            <div class="c-col c-name"><span class="tw-arrow">&#9662;</span> <strong>PROJECT MASTER SCHEDULE SUMMARY</strong></div>
            <div class="c-col c-days">{all_wd_total} days</div>
            <div class="c-col c-date">{fmt_date(all_s_min)}</div>
            <div class="c-col c-date">{fmt_date(all_e_max)}</div>
            <div class="c-col c-disc">All Depts</div>
            <div class="c-col c-resp">ACKD</div>
            <div class="c-timeline-cell">
                <div class="ms-sum-bar ms-proj-bar" style="left:{p_left}%; width:{p_width}%;">
                    <span class="ms-sum-cap-l"></span>
                    <span class="ms-sum-cap-r"></span>
                </div>
                <span class="ms-sum-label" style="{p_lbl_pos}">Master Schedule ({all_wd_total}d)</span>
            </div>
        </div>
        """)

    for s_idx, stage in enumerate(stage_order, start=1):
        g = wdf[wdf["Stage"] == stage].sort_values(["Start", "End"])
        base_col, border_col, hi_col = stage_colors[stage]
        s_all = g["Start Date"].min()
        e_all = g["End Date"].max()
        ps_all = g["Start"].min()
        pe_all = g["End"].max()
        wd_all = int(np.busday_count(s_all.date(), e_all.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
        if s_all.date() == e_all.date() and wd_all == 0:
            wd_all = 1

        first_code = str(g.iloc[0].get("Code", "")).strip()
        if "." in first_code:
            stage_wbs = first_code.split(".")[0] + ".0"
        else:
            stage_wbs = f"{s_idx}.0"

        s_left = get_pos(ps_all)
        s_width = get_width(ps_all, pe_all)
        row_id += 1

        sum_lbl_pos = (
            f"left:calc({round(s_left + s_width, 2)}% + 6px);"
            if (s_left + s_width) < 84
            else f"right:calc({round(100 - s_left, 2)}% + 6px);"
        )
        rows_html.append(f"""
        <div class="g-row g-row-stage">
            <div class="c-col c-id">{row_id}</div>
            <div class="c-col c-mode">{svg_mode_summary}</div>
            <div class="c-col c-code">{esc(stage_wbs)}</div>
            <div class="c-col c-name" title="{esc(stage)}">
                <span class="tw-arrow">&#9662;</span>
                <span class="stage-dot" style="background:{base_col};border-color:{border_col}"></span>
                <strong>{esc(stage)}</strong>
            </div>
            <div class="c-col c-days">{wd_all} days</div>
            <div class="c-col c-date">{fmt_date(s_all)}</div>
            <div class="c-col c-date">{fmt_date(e_all)}</div>
            <div class="c-col c-disc"></div>
            <div class="c-col c-resp"></div>
            <div class="c-timeline-cell">
                <div class="ms-sum-bar" style="left:{s_left}%; width:{s_width}%;">
                    <span class="ms-sum-cap-l"></span>
                    <span class="ms-sum-cap-r"></span>
                </div>
                <span class="ms-sum-label" style="{sum_lbl_pos}">{esc(stage)} ({wd_all}d)</span>
            </div>
        </div>
        """)

        prev_right_pct = None
        g_list = list(g.iterrows())
        for idx_in_stage, (_, r) in enumerate(g_list):
            row_id += 1
            left_pct = get_pos(r["Start"])
            w_pct = get_width(r["Start"], r["End"])
            s_dt = r["Start Date"]
            e_dt = r["End Date"]
            is_milestone = (s_dt.date() == e_dt.date()) and int(r["WorkDays"]) <= 1
            is_completed = e_dt < today
            code_str = str(r.get("Code", ""))
            task_str = str(r.get("_CleanTask", "Task"))
            disc_str = str(r.get("Disc", "-"))
            days_val = int(r.get("WorkDays", 1))
            days_str = f"{days_val} day" if days_val == 1 else f"{days_val} days"
            resp_str = str(r.get("Resp", "")).strip()
            if resp_str in ("-", "nan", "None"):
                resp_str = ""

            # Compute elapsed progress percentage relative to Today (MS Project inner progress bar)
            if is_completed:
                prog_pct = 100.0
            elif s_dt <= today <= e_dt:
                total_cal = max(1, (e_dt - s_dt).days + 1)
                done_cal = max(0, (today - s_dt).days + 1)
                prog_pct = min(100.0, round((done_cal / total_cal) * 100.0, 1))
            else:
                prog_pct = 0.0

            prog_html = (
                f'<div class="g-bar-prog" style="width:{prog_pct}%;"></div>'
                if prog_pct > 0
                else ""
            )

            # Subtle MS Project Finish-to-Start dependency link line from predecessor in same stage
            dep_link_html = ""
            if prev_right_pct is not None and left_pct >= prev_right_pct - 0.5:
                conn_w = max(0.3, round(left_pct - prev_right_pct, 3))
                dep_link_html = (
                    f'<div class="ms-fs-link" style="left:{prev_right_pct}%;width:{conn_w}%;"></div>'
                    f'<div class="ms-fs-arrow" style="left:{left_pct}%;">&#9656;</div>'
                )
            prev_right_pct = round(left_pct + w_pct, 3)

            # Position label cleanly to right of bar (or left if bar is near right margin)
            bar_right_edge = left_pct + w_pct
            if resp_str:
                bar_txt = f"{esc(resp_str)}"
            else:
                bar_txt = f"{fmt_short(s_dt)} - {fmt_short(e_dt)}"

            if bar_right_edge <= 84.5:
                lbl_style = f"left:calc({round(bar_right_edge, 3)}% + 5px);"
            else:
                lbl_style = f"right:calc({round(100.0 - left_pct, 3)}% + 5px); text-align:right;"

            is_last_sub = (idx_in_stage == len(g_list) - 1)
            branch_char = "└─" if is_last_sub else "├─"

            if is_milestone:
                bar_visual = f"""
                {dep_link_html}
                <div class="ms-milestone" style="left:{left_pct}%;" title="{esc(task_str)}">◆</div>
                <span class="g-bar-label" style="{lbl_style}"><strong>{fmt_short(s_dt)}</strong> {bar_txt}</span>
                """
                mode_icon = svg_mode_milestone
            else:
                bar_visual = f"""
                {dep_link_html}
                <div class="g-bar" style="left:{left_pct}%; width:{w_pct}%; background:linear-gradient(180deg, {hi_col} 0%, {base_col} 40%, {border_col} 100%); border:1px solid {border_col};">
                    <div class="g-bar-shine"></div>
                    {prog_html}
                </div>
                <span class="g-bar-label" style="{lbl_style}">{bar_txt}</span>
                """
                mode_icon = svg_mode_done if is_completed else svg_mode_task

            rows_html.append(f"""
            <div class="g-row g-row-task">
                <div class="c-col c-id">{row_id}</div>
                <div class="c-col c-mode">{mode_icon}</div>
                <div class="c-col c-code">{esc(code_str)}</div>
                <div class="c-col c-name c-name-sub" title="{esc(task_str)}">
                    <span class="tree-branch">{branch_char}</span>{esc(task_str)}
                </div>
                <div class="c-col c-days">{days_str}</div>
                <div class="c-col c-date">{fmt_date(s_dt)}</div>
                <div class="c-col c-date">{fmt_date(e_dt)}</div>
                <div class="c-col c-disc" title="{esc(disc_str)}">{esc(disc_str)}</div>
                <div class="c-col c-resp" title="{esc(resp_str)}">{esc(resp_str)}</div>
                <div class="c-timeline-cell">
                    {bar_visual}
                </div>
            </div>
            """)

    m_hdr_html = "".join([f'<div class="hdr-cell hdr-month" style="width:{pct}%;">{lbl}</div>' for lbl, pct, _ in month_blocks])
    w_hdr_html = "".join([f'<div class="hdr-cell hdr-week" style="width:{pct}%;">{lbl}</div>' for lbl, pct, _ in week_blocks])

    # Stage legend pills for the footer
    stage_legend_items = "".join([
        f'<span class="leg-item"><span class="leg-swatch" style="background:{stage_colors[s][0]};border:1px solid {stage_colors[s][1]}"></span>{esc(s)}</span>'
        for s in stage_order[:8]
    ])

    hdr_total_h = 42
    tier_h = 14

    html = f"""<!DOCTYPE html>
&lt;html&gt;
&lt;head&gt;
&lt;meta charset=&quot;utf-8&quot;&gt;
&lt;title&gt;MS Project WBS Gantt Schedule - A3 Landscape&lt;/title&gt;
&lt;style&gt;
    @page {{
        size: 420mm 297mm;
        margin: 5mm 7mm;
    }}
    *, *:before, *:after {{
        box-sizing: border-box;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }}
    html, body {{
        font-family: &quot;Segoe UI&quot;, -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
        color: #0f172a;
        background: #ffffff;
        margin: 0;
        padding: 0;
        width: 100%;
        height: 286mm;
        max-height: 286mm;
        overflow: hidden;
        page-break-after: avoid;
        page-break-inside: avoid;
        font-size: {font_sz}px;
    }}
    .no-print {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #0f2b48;
        color: #ffffff;
        padding: 8px 16px;
        border-radius: 4px;
        margin-bottom: 6px;
    }}
    /* MS Project Top Title Banner */
    .msp-title-banner {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: linear-gradient(90deg, #0f2b48 0%, #1e3a5f 60%, #1e40af 100%);
        color: #ffffff;
        padding: 5px 12px;
        border: 1px solid #0f172a;
        border-bottom: 2px solid #fbbf24;
        height: 38px;
        margin-bottom: 3px;
    }}
    .msp-title-left {{
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    .msp-logo-badge {{
        background: #fbbf24;
        color: #0f172a;
        font-weight: 800;
        font-size: 10.5px;
        padding: 3px 7px;
        border-radius: 2px;
        letter-spacing: 0.5px;
    }}
    .msp-main-title {{
        font-size: 13.5px;
        font-weight: 700;
        letter-spacing: 0.3px;
        line-height: 1.15;
    }}
    .msp-sub-title {{
        font-size: 8.5px;
        color: #cbd5e1;
    }}
    .msp-kpi-strip {{
        display: flex;
        gap: 12px;
        align-items: center;
        font-size: 8.5px;
    }}
    .msp-kpi-item {{
        background: rgba(255,255,255,0.1);
        border: 1px solid rgba(255,255,255,0.22);
        padding: 2px 8px;
        border-radius: 3px;
    }}
    .msp-kpi-item strong {{
        color: #fde68a;
        font-size: 9.5px;
    }}

    /* Main MS Project Split Grid Container */
    .g-container {{
        width: 100%;
        border: 1.5px solid #475569;
        background: #ffffff;
        position: relative;
        page-break-inside: avoid;
    }}

    /* Table + Timeline Header */
    .g-header {{
        display: flex;
        background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
        border-bottom: 1.5px solid #475569;
        font-weight: 700;
        color: #1e293b;
        height: {hdr_total_h}px;
        font-size: {sub_font_sz}px;
    }}
    .c-col {{
        padding: 0 4px;
        border-right: 1px solid #cbd5e1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: none;
        display: flex;
        align-items: center;
        height: 100%;
    }}
    .g-header .c-col {{
        border-right: 1px solid #94a3b8;
        justify-content: center;
        text-transform: uppercase;
        letter-spacing: 0.2px;
    }}
    .g-header .c-name {{
        justify-content: flex-start;
        padding-left: 6px;
    }}
    /* MS Project Sheet Column Widths (Total = 655px) */
    .c-id   {{ width: 24px; justify-content: center; background: #f1f5f9; color: #475569; font-weight: 600; font-size: {sub_font_sz}px; }}
    .c-mode {{ width: 20px; justify-content: center; padding: 0; background: #f8fafc; }}
    .c-code {{ width: 42px; justify-content: flex-start; color: #334155; font-family: "Consolas", "Courier New", monospace; font-size: {sub_font_sz}px; }}
    .c-name {{ width: 225px; color: #0f172a; }}
    .c-days {{ width: 48px; justify-content: flex-end; font-variant-numeric: tabular-nums; color: #1e293b; }}
    .c-date {{ width: 74px; justify-content: center; font-variant-numeric: tabular-nums; color: #334155; font-size: {sub_font_sz}px; }}
    .c-disc {{ width: 72px; color: #334155; }}
    .c-resp {{ width: 76px; color: #334155; border-right: 2px solid #475569 !important; }}

    /* Right Timeline Header */
    .c-timeline-hdr {{
        flex: 1;
        display: flex;
        flex-direction: column;
        position: relative;
        overflow: hidden;
    }}
    .hdr-row {{
        display: flex;
        width: 100%;
        border-bottom: 1px solid #94a3b8;
        height: {tier_h}px;
        align-items: center;
    }}
    .hdr-row:last-child {{ border-bottom: none; }}
    .hdr-cell {{
        text-align: center;
        border-right: 1px solid #94a3b8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        height: 100%;
        line-height: {tier_h}px;
        font-size: {sub_font_sz}px;
    }}
    .hdr-month {{
        background: #dde5ef;
        font-weight: 700;
        color: #0f2b48;
    }}
    .hdr-week {{
        background: #eef2f7;
        font-weight: 600;
        color: #334155;
        border-right: 1px solid #cbd5e1;
    }}
    .hdr-subweek {{
        background: #f8fafc;
        font-size: {max(5.2, sub_font_sz - 1.0)}px;
        color: #64748b;
        border-right: 1px solid #e2e8f0;
    }}
    .hdr-tier-days {{
        background: #f8fafc;
    }}
    .t-day-cell {{
        flex: none;
        height: 100%;
        line-height: {tier_h}px;
        text-align: center;
        font-size: {max(5.2, sub_font_sz - 1.2)}px;
        color: #64748b;
        border-right: 1px solid #e2e8f0;
    }}
    .t-day-wknd {{
        background: #cbd5e1;
        color: #475569;
        font-weight: 700;
    }}
    .today-flag {{
        position: absolute;
        top: 0;
        transform: translateX(-50%);
        background: #dc2626;
        color: #fff;
        font-size: 6.5px;
        font-weight: 800;
        padding: 0 3px;
        line-height: 10px;
        border-radius: 0 0 2px 2px;
        z-index: 10;
    }}

    /* Body Wrapper with Full-Height Gridlines */
    .g-body-wrap {{
        position: relative;
        width: 100%;
    }}
    .g-timeline-bg-layer {{
        position: absolute;
        top: 0;
        bottom: 0;
        left: 655px; /* exact sum of left columns: 24+20+42+225+48+74+74+72+76 = 655px */
        right: 0;
        pointer-events: none;
        z-index: 1;
        overflow: hidden;
    }}
    .bg-wknd {{
        position: absolute;
        top: 0;
        bottom: 0;
        background: rgba(148, 163, 184, 0.16);
        border-left: 1px solid rgba(148, 163, 184, 0.22);
        border-right: 1px solid rgba(148, 163, 184, 0.22);
    }}
    .bg-week-line {{
        position: absolute;
        top: 0;
        bottom: 0;
        width: 0;
        border-left: 1px dashed #d5dde7;
    }}
    .bg-month-line {{
        position: absolute;
        top: 0;
        bottom: 0;
        width: 0;
        border-left: 1px solid #94a3b8;
    }}
    .bg-today-line {{
        position: absolute;
        top: 0;
        bottom: 0;
        width: 0;
        border-left: 1.8px dashed #dc2626;
        z-index: 8;
    }}

    /* Rows */
    .g-row {{
        display: flex;
        border-bottom: 1px solid #e2e8f0;
        height: {row_h}px;
        align-items: center;
        position: relative;
        z-index: 2;
        page-break-inside: avoid;
    }}
    .g-row-task:nth-child(even) {{
        background: rgba(248, 250, 252, 0.65);
    }}
    .g-row-proj-sum {{
        background: #cbd5e1 !important;
        border-top: 1.5px solid #334155;
        border-bottom: 1.5px solid #334155;
        font-weight: 700;
        color: #0f172a;
    }}
    .g-row-proj-sum .c-col {{
        font-weight: 700;
    }}
    .g-row-stage {{
        background: #e2e8f0 !important;
        border-top: 1px solid #94a3b8;
        border-bottom: 1px solid #94a3b8;
        font-weight: 700;
        color: #0f172a;
    }}
    .g-row-stage .c-col {{
        font-weight: 700;
        color: #0f172a;
    }}
    .tw-arrow {{
        display: inline-block;
        font-size: 9px;
        margin-right: 3px;
        color: #1e293b;
    }}
    .stage-dot {{
        display: inline-block;
        width: 7px;
        height: 7px;
        border-radius: 1px;
        border: 1px solid #1e293b;
        margin-right: 4px;
        flex: none;
    }}
    .c-name-sub {{
        padding-left: 12px;
    }}
    .tree-branch {{
        color: #94a3b8;
        font-family: monospace;
        margin-right: 3px;
        font-size: {sub_font_sz}px;
    }}

    /* Timeline Cell & MS Project Bars */
    .c-timeline-cell {{
        flex: 1;
        height: 100%;
        position: relative;
    }}
    .g-bar {{
        position: absolute;
        top: {max(1, (row_h - bar_h) // 2)}px;
        height: {bar_h}px;
        border-radius: 1.5px;
        z-index: 4;
        box-shadow: 0 1px 1px rgba(15, 23, 42, 0.18);
        overflow: hidden;
    }}
    .g-bar-shine {{
        width: 100%;
        height: 35%;
        background: rgba(255, 255, 255, 0.28);
    }}
    .g-bar-prog {{
        position: absolute;
        left: 0;
        top: 35%;
        height: 32%;
        background: rgba(15, 23, 42, 0.45);
        border-right: 1px solid rgba(255, 255, 255, 0.7);
    }}
    .g-bar-label {{
        position: absolute;
        top: 0;
        line-height: {row_h}px;
        font-size: {sub_font_sz}px;
        color: #1e293b;
        font-weight: 600;
        white-space: nowrap;
        z-index: 5;
    }}

    /* Finish-to-Start Dependency Connectors */
    .ms-fs-link {{
        position: absolute;
        top: 0;
        height: 55%;
        border-left: 1px solid #64748b;
        border-bottom: 1px solid #64748b;
        z-index: 3;
        pointer-events: none;
    }}
    .ms-fs-arrow {{
        position: absolute;
        top: 50%;
        transform: translate(-85%, -52%);
        font-size: 7px;
        color: #475569;
        z-index: 5;
        pointer-events: none;
    }}

    /* MS Project Summary Bar with Downward Fangs/Brackets */
    .ms-sum-bar {{
        position: absolute;
        top: {max(2, (row_h - sum_bar_h) // 2 - 1)}px;
        height: {sum_bar_h}px;
        background: #1e293b;
        z-index: 5;
    }}
    .ms-proj-bar {{
        background: #0f172a;
        height: {sum_bar_h + 1}px;
    }}
    .ms-sum-cap-l, .ms-sum-cap-r {{
        position: absolute;
        top: {sum_bar_h - 1}px;
        width: 0;
        height: 0;
        border-top: {max(4, sum_bar_h)}px solid #1e293b;
        border-left: 3.5px solid transparent;
        border-right: 3.5px solid transparent;
    }}
    .ms-sum-cap-l {{ left: -0.5px; }}
    .ms-sum-cap-r {{ right: -0.5px; }}
    .ms-sum-label {{
        position: absolute;
        top: 0;
        line-height: {row_h}px;
        font-size: {sub_font_sz}px;
        font-weight: 700;
        color: #0f172a;
        white-space: nowrap;
        z-index: 5;
    }}

    /* Milestone Diamond */
    .ms-milestone {{
        position: absolute;
        top: 0;
        transform: translateX(-50%);
        line-height: {row_h}px;
        font-size: {max(8.0, font_sz + 1.5)}px;
        color: #0f172a;
        z-index: 6;
    }}

    /* MS Project Footer Title Block & Legend */
    .msp-footer {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border: 1px solid #475569;
        border-top: none;
        background: #f8fafc;
        padding: 3px 10px;
        height: 28px;
        font-size: 8px;
        color: #334155;
    }}
    .leg-group {{
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: nowrap;
        overflow: hidden;
    }}
    .leg-item {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        white-space: nowrap;
        font-weight: 600;
    }}
    .leg-swatch {{
        display: inline-block;
        width: 12px;
        height: 7px;
        border-radius: 1px;
    }}
    .leg-sum-demo {{
        display: inline-block;
        width: 14px;
        height: 4px;
        background: #1e293b;
        position: relative;
        margin-bottom: 2px;
    }}
    .leg-sum-demo:before, .leg-sum-demo:after {{
        content: "";
        position: absolute;
        top: 3px;
        border-top: 4px solid #1e293b;
        border-left: 2.5px solid transparent;
        border-right: 2.5px solid transparent;
    }}
    .leg-sum-demo:before {{ left: 0; }}
    .leg-sum-demo:after {{ right: 0; }}
    .leg-today-demo {{
        display: inline-block;
        width: 10px;
        height: 0;
        border-top: 2px dashed #dc2626;
    }}
    .leg-wknd-demo {{
        display: inline-block;
        width: 10px;
        height: 8px;
        background: #cbd5e1;
        border: 1px solid #94a3b8;
    }}
    @media print {{
        .no-print {{ display: none !important; }}
    }}
&lt;/style&gt;
&lt;/head&gt;
&lt;body&gt;
    &lt;div class=&quot;no-print&quot;&gt;
        &lt;div style=&quot;font-weight:700; font-size:13px;&quot;&gt;
            📊 Microsoft Project View — A3 Landscape Master Schedule (1-Page Vector Fit)
        &lt;/div&gt;
        &lt;button onclick=&quot;window.print()&quot; style=&quot;background:#fbbf24; color:#0f172a; border:none; padding:6px 18px; border-radius:3px; font-weight:700; cursor:pointer; font-size:12px;&quot;&gt;
            🖨️ Print / Save as A3 PDF
        &lt;/button&gt;
    &lt;/div&gt;

    <!-- MS Project Header Title Block -->
    <div class="msp-title-banner">
        <div class="msp-title-left">
            <div class="msp-logo-badge">MS PROJECT VIEW</div>
            <div>
                <div class="msp-main-title">{esc(schedule_title)}</div>
                <div class="msp-sub-title">Dynamic Engineering Resource Planner — ACKD &nbsp;|&nbsp; Work Calendar: Sunday–Thursday (8 Hrs/Day) &nbsp;|&nbsp; A3 Landscape Vector Print</div>
            </div>
        </div>
        <div class="msp-kpi-strip">
            <div class="msp-kpi-item">Stages: <strong>{len(stage_order)}</strong></div>
            <div class="msp-kpi-item">Activities: <strong>{len(wdf)}</strong></div>
            <div class="msp-kpi-item">Start: <strong>{all_s_min.strftime('%d-%b-%Y')}</strong></div>
            <div class="msp-kpi-item">Finish: <strong>{all_e_max.strftime('%d-%b-%Y')}</strong></div>
            <div class="msp-kpi-item">Net Duration: <strong>{all_wd_total} Work Days</strong></div>
            <div class="msp-kpi-item">Status Date: <strong>{today.strftime('%d-%b-%Y')}</strong></div>
        </div>
    </div>

    <!-- Main Split Sheet + Gantt Chart Container -->
    <div class="g-container">
        <div class="g-header">
            <div class="c-col c-id">ID</div>
            <div class="c-col c-mode">&#9432;</div>
            <div class="c-col c-code">WBS</div>
            <div class="c-col c-name">Task Name</div>
            <div class="c-col c-days">Duration</div>
            <div class="c-col c-date">Start</div>
            <div class="c-col c-date">Finish</div>
            <div class="c-col c-disc">Department</div>
            <div class="c-col c-resp">Resource</div>
            <div class="c-timeline-hdr">
                {today_hdr_badge}
                <div class="hdr-row">{m_hdr_html}</div>
                <div class="hdr-row">{w_hdr_html}</div>
                {day_tier_html}
            </div>
        </div>
        <div class="g-body-wrap">
            <div class="g-timeline-bg-layer">
                {grid_bg_html}
            </div>
            {"".join(rows_html)}
        </div>
    </div>

    <!-- MS Project Legend & Engineering Footer Block -->
    <div class="msp-footer">
        <div class="leg-group">
            <span style="font-weight:800; color:#0f2b48;">LEGEND:</span>
            <span class="leg-item"><span class="leg-sum-demo"></span> Summary Rollup</span>
            <span class="leg-item"><span class="leg-swatch" style="background:linear-gradient(180deg,#63b3ed,#2b6cb0);border:1px solid #1e4e8c"></span> Activity Bar</span>
            <span class="leg-item"><span>◆</span> Milestone</span>
            <span class="leg-item"><span class="leg-today-demo"></span> Today Line</span>
            <span class="leg-item"><span class="leg-wknd-demo"></span> Weekend (Fri–Sat)</span>
            <span style="color:#94a3b8;">|</span>
            {stage_legend_items}
        </div>
        <div style="white-space:nowrap; font-weight:700; color:#0f2b48;">
            ACKD Engineering Planner &nbsp;|&nbsp; Scale: 1-Page A3 (420×297mm) &nbsp;|&nbsp; Page 1 of 1
        </div>
    </div>
&lt;/body&gt;
&lt;/html&gt;
&quot;&quot;&quot;
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

    # ---- Action Toolbar: Guaranteed MS Project A3 PDF Print / Download Button ----
    col_a, col_b, col_c = st.columns([1.5, 2.8, 2.0])
    with col_a:
        if st.button("🔄 Refresh Live Sheet", use_container_width=True):
            load_wbs.clear()
            st.rerun()

    # Pre-generate exact-fit MS Project A3 Single-Page Vector HTML & PDF
    a3_html = build_a3_single_page_html(df)
    pdf_bytes = export_a3_pdf(a3_html) if HAS_WEASYPRINT else None

    with col_b:
        if pdf_bytes:
            st.download_button(
                "📥 Download MS Project A3 PDF (1-Page Fit)",
                data=pdf_bytes,
                file_name=f"MS_Project_WBS_Gantt_A3_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                help="Download exact-fit MS Project style A3 Landscape Vector PDF fitted strictly onto 1 single page"
            )
        else:
            # Client-side 1-click A3 print dialog (works 100% reliably on all platforms)
            escaped_html = json.dumps(a3_html)
            components.html(f"""
                <button onclick="printA3Doc()" style="
                    width: 100%;
                    height: 38px;
                    background: linear-gradient(90deg, #0f2b48 0%, #1e40af 100%);
                    color: white;
                    border: 1px solid #0f172a;
                    border-bottom: 2px solid #fbbf24;
                    border-radius: 4px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 13px;
                    font-weight: 700;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 6px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.18);
                ">
                    🖨️ Print / Save MS Project A3 PDF (1-Page Fit)
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

    # Interactive Web View Gantt
    html_doc, comp_h = build_wbs_html(df, zoom, today)
    components.html(html_doc, height=comp_h, scrolling=False)


# ----------------------------------------------------------------------
# 2c. Helper Functions for Team Gantt Charts
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


def render_project_gantt_chart(calc_df, disciplines, team_mode, count_col, hide_completed=True, team_label=None, show_a3_export=False):
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

    # Optional MS Project A3 PDF Export button for Team Project Timelines
    if show_a3_export:
        export_df = pd.DataFrame({
            "Code": [str(r.get("No.", i + 1)) if pd.notnull(r.get("No.")) and str(r.get("No.")).strip() != "" else str(i + 1) for i, (_, r) in enumerate(gantt_df.iterrows())],
            "Task": [str(r.get(name_col, r["Project"])) if name_col else str(r["Project"]) for _, r in gantt_df.iterrows()],
            "Stage": [team_label or "Active Projects"] * len(gantt_df),
            "Start Date": gantt_df["Start"].values,
            "End Date": gantt_df["End"].values,
            "Start": gantt_df["Start"].values,
            "End": gantt_df["End"].values,
            "WorkDays": gantt_df["WorkDays"].values,
            "Disc": [team_label or ", ".join(disciplines)] * len(gantt_df),
            "Resp": [f"{r['TotalHrs']:,.0f} Hrs" if r["TotalHrs"] > 0 else "" for _, r in gantt_df.iterrows()],
        })
        title_str = f"{team_label.upper()} — PROJECT SCHEDULE & GANTT TIMELINE" if team_label else "PROJECT SCHEDULE & GANTT TIMELINE"
        team_a3_html = build_a3_single_page_html(export_df, schedule_title=title_str)
        team_pdf_bytes = export_a3_pdf(team_a3_html) if HAS_WEASYPRINT else None
        if team_pdf_bytes:
            st.download_button(
                "📥 Download MS Project A3 PDF (1-Page Fit)",
                data=team_pdf_bytes,
                file_name=f"MS_Project_{_get_safe_team_name(team_label or 'Team')}_Gantt_A3_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                key=f"dl_a3_{team_label}",
            )
        else:
            escaped_team_html = json.dumps(team_a3_html)
            components.html(f"""
                <button onclick="printTeamA3Doc()" style="
                    padding: 6px 16px;
                    height: 34px;
                    background: linear-gradient(90deg, #0f2b48 0%, #1e40af 100%);
                    color: white;
                    border: 1px solid #0f172a;
                    border-bottom: 2px solid #fbbf24;
                    border-radius: 4px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 12.5px;
                    font-weight: 700;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                ">
                    🖨️ Print / Save MS Project A3 PDF (1-Page Fit)
                </button>
                <script>
                function printTeamA3Doc() {{
                    var docContent = {escaped_team_html};
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
            """, height=42)

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
    st.markdown("&lt;div style=&#39;height: 28px;&#39;&gt;&lt;/div&gt;", unsafe_allow_html=True)
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
# 4b. Project Timeline (Gantt Chart)
# ----------------------------------------------------------------------
st.markdown("---")
st.subheader("🗓️ Project Timeline (Gantt Chart)")

hide_completed = st.checkbox("Filter completed", value=False, key=f"hide_comp_{selected_team}")
render_project_gantt_chart(
    calc_df, disciplines, team_mode, count_col, hide_completed,
    team_label=selected_team, show_a3_export=True
)

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
