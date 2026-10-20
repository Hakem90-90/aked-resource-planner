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
    "QC Team": {
        "sheet_id": "1g0carFHs1RSN4MWtVFdt8kWfTnEmCFrMiicEznft8Bc",
        "gid": None,
        "mode": "hours",
        "disciplines": ["Arch", "Structural", "MEP", "Electrical"],
        "engineers": [2, 1, 1, 2],  # Fallback defaults (Total = 6)
    },
}

# ----- Gantt Chart option (WBS file) -----
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
# 1b. Backup Management System (Daily Snapshots & Differences)
# ----------------------------------------------------------------------
def _get_safe_team_name(team_name):
    return "".join(c for c in team_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")


def save_daily_backup(team_name, df, counts=None, date_str=None):
    """Saves a daily backup CSV (and optional JSON counts)."""
    if date_str is None:
        date_str = datetime.date.today().isoformat()
    safe_team = _get_safe_team_name(team_name)
    csv_path = os.path.join(BACKUP_DIR, f"{safe_team}_{date_str}.csv")
    df.to_csv(csv_path, index=False)
    if counts is not None:
        json_path = os.path.join(BACKUP_DIR, f"{safe_team}_{date_str}_counts.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(counts, f, ensure_ascii=False, indent=2)
    return csv_path


def list_backups(team_name):
    """Lists available backup dates in descending order."""
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
    """Loads dataframe and counts from a specified backup date."""
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

        if pd.notnull(s_old) and pd.notnull(s_new) and s_old != s_new:
            diffs.append(f"Start: {s_old} ➔ {s_new}")
        elif pd.isnull(s_old) != pd.isnull(s_new):
            diffs.append(f"Start: {s_old} ➔ {s_new}")

        if pd.notnull(e_old) and pd.notnull(e_new) and e_old != e_new:
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
# 2b. WBS Gantt Chart page
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
        return max(int(((pd.Timestamp(e).normalize() - pd.Timestamp(s).normalize()).days + 1) * dw), 4)

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

    # Backup Controls for WBS
    wbs_backups = list_backups("WBS_Gantt")
    col_mode, col_date = st.columns([2, 2])
    with col_mode:
        data_source = st.radio(
            "WBS Data Source:",
            ["🟢 Live Data (Google Sheet)", "🕰️ Historical Backup"],
            horizontal=True,
            key="wbs_data_source"
        )
    with col_date:
        selected_b_date = None
        if data_source == "🕰️ Historical Backup":
            if wbs_backups:
                selected_b_date = st.selectbox("Select Snapshot Date:", wbs_backups, key="wbs_b_date")
            else:
                st.info("No WBS backups found yet.")

    col_a, col_b, col_c = st.columns([1.2, 1.2, 2.6])
    with col_a:
        if st.button("🔄 Refresh Live Sheet", use_container_width=True):
            load_wbs.clear()
            st.rerun()
    with col_b:
        save_wbs_btn = st.button("💾 Save Backup Now", use_container_width=True)
    with col_c:
        st.link_button("🔗 Open Google Sheet", f"https://docs.google.com/spreadsheets/d/{WBS_SHEET_ID}/edit")

    # Load Data
    live_df = None
    try:
        live_df = load_wbs(wbs_url)
        # Auto-backup daily if in live mode
        save_daily_backup("WBS_Gantt", live_df)
    except Exception as e:
        if data_source == "🟢 Live Data (Google Sheet)":
            st.error(f"Could not read the WBS Google Sheet ({e}).")
            return

    if save_wbs_btn and live_df is not None:
        save_daily_backup("WBS_Gantt", live_df)
        st.success("✅ Current WBS snapshot saved successfully to backups!")

    if data_source == "🕰️ Historical Backup" and selected_b_date:
        df, _ = load_backup("WBS_Gantt", selected_b_date)
        if df is None:
            st.error("Could not load selected backup file.")
            return
        st.info(f"Viewing historical WBS snapshot from: **{selected_b_date}**")
    else:
        df = live_df

    if df is None:
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
    df["Task"] = (code + " · " + task).str.strip(" ·")
    df["Stage"] = df[stage_col].astype(str) if stage_col else "-"
    df["Disc"] = df[disc_col].astype(str) if disc_col else "-"
    df["Resp"] = df[resp_col].astype(str) if resp_col else "-"

    df = df.sort_values(["Start", "End"]).reset_index(drop=True)

    # ---- Summary metrics ----
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tasks", len(df))
    m2.metric("First start", f"{df['Start Date'].min():%d-%b-%Y}")
    m3.metric("Last end", f"{df['End Date'].max():%d-%b-%Y}")
    m4.metric(
        "Working days (Sun-Thu)",
        int(np.busday_count(df["Start Date"].min().date(),
                            df["End Date"].max().date() + datetime.timedelta(days=1),
                            weekmask=NP_WEEKMASK)),
    )

    # ---- MS Project style Gantt ----
    df["Code"] = code
    html_doc, comp_h = build_wbs_html(df, zoom, today)
    components.html(html_doc, height=comp_h, scrolling=False)


# ----------------------------------------------------------------------
# Team selection
# ----------------------------------------------------------------------
selected_team = st.radio(
    "👥 Select Team:", list(TEAMS.keys()) + [GANTT_OPTION], horizontal=True
)

if selected_team == GANTT_OPTION:
    render_wbs_gantt()
    st.stop()

team_cfg = TEAMS[selected_team]
team_mode = team_cfg["mode"]
disciplines = team_cfg["disciplines"]
SHEET_ID = team_cfg["sheet_id"]
CSV_URL = build_csv_url(SHEET_ID, team_cfg["gid"])

# ----------------------------------------------------------------------
# 2c. Data Source Selection & Daily Backup Controls
# ----------------------------------------------------------------------
st.markdown("---")
available_backups = list_backups(selected_team)

c_mode, c_hist, c_actions = st.columns([1.8, 1.8, 2.8])
with c_mode:
    data_source = st.radio(
        "📂 Data Source:",
        ["🟢 Live Google Sheet", "🕰️ Historical Backup"],
        horizontal=True,
        help="Choose whether to load current live data from Google Sheet or load a previous day's snapshot."
    )

selected_backup_date = None
with c_hist:
    if data_source == "🕰️ Historical Backup":
        if available_backups:
            selected_backup_date = st.selectbox(
                "📅 Select Backup Snapshot Date:",
                available_backups,
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
    st.rerun()

# Fetch Live Data
live_projects = None
live_eng_counts = {}
try:
    live_projects, live_eng_counts = load_from_gsheet(CSV_URL, disciplines)
    # Also fetch team counts tab if configured
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

    # Automatically keep a daily backup on every live fetch
    save_daily_backup(selected_team, live_projects, live_eng_counts)
except Exception as e:
    if data_source == "🟢 Live Google Sheet":
        st.error(f"Could not read the {selected_team} Google Sheet ({e}). Using empty template.")
        live_projects = get_empty_template(team_mode, disciplines)

if save_backup_now and live_projects is not None:
    save_daily_backup(selected_team, live_projects, live_eng_counts)
    st.success("✅ Current state successfully archived as today's backup snapshot!")

# Determine active dataset based on user selection
counts_source = "defaults"
if data_source == "🕰️ Historical Backup" and selected_backup_date:
    df_projects, sheet_eng_counts = load_backup(selected_team, selected_backup_date)
    counts_source = f"Backup ({selected_backup_date})"
    st.info(f"🕰️ **Viewing Historical Snapshot from {selected_backup_date}**. All calculations and timelines below reflect this snapshot.")
else:
    df_projects = live_projects if live_projects is not None else get_empty_template(team_mode, disciplines)
    sheet_eng_counts = live_eng_counts
    counts_source = "Live Google Sheet"
    st.success(f"🟢 **{selected_team}**: Viewing Live Data from Google Sheet (Daily backup automatically archived).")

# ----------------------------------------------------------------------
# 2d. Differences & Change Comparison (مقارنة الفروقات)
# ----------------------------------------------------------------------
with st.expander("🔍 Compare Changes with a Previous Backup (مقارنة الفروقات)"):
    if not available_backups:
        st.info("No saved backup files available to compare.")
    elif live_projects is None:
        st.warning("Live data not available to compare.")
    else:
        cmp_date = st.selectbox("Select historical backup to compare against current live data:", available_backups, key="cmp_date")
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
        f"{disc} Engineers", value=int(default), min_value=0, key=f"eng_{selected_team}_{disc}"
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
calc_df = edited_df.copy()


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


count_col = find_count_col(calc_df)

if team_mode == "team_count":
    hrs_col_name = f"{disciplines[0]} (Hrs)"
    sheet_hrs_col = find_calc_hrs_col(calc_df)

    if sheet_hrs_col is not None:
        calc_df[hrs_col_name] = pd.to_numeric(calc_df[sheet_hrs_col], errors="coerce").fillna(0)
    elif count_col is not None:
        calc_df[count_col] = pd.to_numeric(calc_df[count_col], errors="coerce").fillna(0)
        work_days = [
            0 if (pd.isnull(s_d) or pd.isnull(e_d))
            else max(0, int(np.busday_count(s_d, e_d + datetime.timedelta(days=1), weekmask=NP_WEEKMASK)))
            for s_d, e_d in zip(calc_df["Start Date"], calc_df["End Date"])
        ]
        calc_df[hrs_col_name] = calc_df[count_col] * work_days * hours_per_day

# ----------------------------------------------------------------------
# 4b. Project Timeline (Gantt Chart)
# ----------------------------------------------------------------------
st.markdown("---")
st.subheader("🗓️ Project Timeline (Gantt Chart)")

hide_completed = st.checkbox("Filter completed", value=True)


def find_name_col(df):
    skip = {"No.", "Start Date", "End Date"} | set(DATA_COLS)
    for c in df.columns:
        low = str(c).lower()
        if c not in skip and any(k in low for k in ("name", "project", "contract")):
            return c
    for c in df.columns:
        if c not in skip and df[c].dtype == object:
            return c
    return None


NAME_COL = find_name_col(edited_df)


def make_project_label(r):
    name = r.get(NAME_COL) if NAME_COL is not None else None
    name = str(name).strip() if pd.notnull(name) and str(name).strip() != "" else "Unnamed"
    no = r.get("No.")
    if pd.notnull(no) and str(no).strip() != "":
        try:
            no = int(float(no))
        except (ValueError, TypeError):
            pass
        return f"{no}. {name}"
    return name


gantt_df = calc_df.copy()
gantt_df["Start"] = pd.to_datetime(gantt_df["Start Date"], errors="coerce")
gantt_df["End"] = pd.to_datetime(gantt_df["End Date"], errors="coerce")
gantt_df = gantt_df.dropna(subset=["Start", "End"])
gantt_df = gantt_df[gantt_df["End"] >= gantt_df["Start"]]

today = pd.Timestamp.today().normalize()
if hide_completed:
    gantt_df = gantt_df[gantt_df["End"] >= today]

if gantt_df.empty:
    st.info("No ongoing or upcoming projects with valid dates to display.")
else:
    hrs_cols = [f"{d} (Hrs)" for d in disciplines if f"{d} (Hrs)" in gantt_df.columns]
    gantt_df["Project"] = gantt_df.apply(make_project_label, axis=1)
    gantt_df["EndPlus"] = gantt_df["End"] + pd.Timedelta(days=1)
    gantt_df["TotalHrs"] = gantt_df[hrs_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    gantt_df["WorkDays"] = [
        int(np.busday_count(s.date(), e.date() + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
        for s, e in zip(gantt_df["Start"], gantt_df["End"])
    ]
    gantt_df = gantt_df.sort_values(["Start", "End"])
    gantt_df["DateRange"] = [
        f"{s:%d-%b-%Y}  →  {e:%d-%b-%Y}" for s, e in zip(gantt_df["Start"], gantt_df["End"])
    ]
    project_order = gantt_df["Project"].tolist()

    x_min = gantt_df["Start"].min() - pd.Timedelta(days=2)
    span_days = (gantt_df["EndPlus"].max() - gantt_df["Start"].min()).days
    x_max = gantt_df["EndPlus"].max() + pd.Timedelta(days=max(14, int(span_days * 0.25)))
    x_scale = alt.Scale(domain=[x_min.isoformat(), x_max.isoformat()])

    extra_tooltips = []
    if team_mode == "team_count" and count_col is not None and count_col in gantt_df.columns:
        gantt_df["TeamCount"] = pd.to_numeric(gantt_df[count_col], errors="coerce")
        extra_tooltips.append(alt.Tooltip("TeamCount:Q", title="Team count"))

    bars = alt.Chart(gantt_df).mark_bar(cornerRadius=3).encode(
        y=alt.Y("Project:N", sort=project_order, title=None, axis=alt.Axis(labelLimit=300)),
        x=alt.X("Start:T", scale=x_scale, title="Date", axis=alt.Axis(format="%d-%b", labelAngle=-45)),
        x2="EndPlus:T",
        color=alt.Color("Project:N", legend=None),
        tooltip=[
            alt.Tooltip("Project:N", title="Project"),
            alt.Tooltip("Start:T", title="Start", format="%a %d-%b-%Y"),
            alt.Tooltip("End:T", title="End", format="%a %d-%b-%Y"),
            alt.Tooltip("WorkDays:Q", title="Working days (Sun-Thu)"),
            alt.Tooltip("TotalHrs:Q", title="Total hours", format=",.0f"),
            *extra_tooltips,
        ],
    )

    date_labels = alt.Chart(gantt_df).mark_text(
        align="left", baseline="middle", dx=6, fontSize=11
    ).encode(
        y=alt.Y("Project:N", sort=project_order),
        x=alt.X("EndPlus:T", scale=x_scale),
        text="DateRange:N",
    )

    layers = [bars, date_labels]

    if gantt_df["Start"].min() <= today <= gantt_df["EndPlus"].max():
        today_rule = alt.Chart(pd.DataFrame({"Today": [today]})).mark_rule(
            color="red", strokeDash=[5, 4], strokeWidth=2
        ).encode(x=alt.X("Today:T", scale=x_scale))
        layers.append(today_rule)

    gantt_chart = alt.layer(*layers).properties(height=max(150, 34 * len(gantt_df) + 60))
    st.altair_chart(gantt_chart, use_container_width=True)

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

    workdays_total = np.busday_count(s_date, e_date + datetime.timedelta(days=1), weekmask=NP_WEEKMASK)
    if workdays_total <= 0:
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
