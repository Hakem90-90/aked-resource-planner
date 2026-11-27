import datetime
import re
from urllib.parse import quote

import streamlit as st
import pandas as pd
import numpy as np
import altair as alt


# ----------------------------------------------------------------------
# 1. Page Configuration & Setup
# ----------------------------------------------------------------------
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 Dynamic Engineering Resource Planner - ACKD")

# Maximum number of project rows read from each Google Sheet
MAX_ROWS = 50

# Single source of truth for Tech / Actual Team headcount (Hakem's "Team count" tab)
HAKEM_HEADCOUNT_SOURCE = {
    "sheet_id": "1DGuOh10TsEbaGAukCVIvf7zhnzzTtb0sT5lghdOREZo",
    "gid": 188228010,
}

# ----- Teams: each team can read from multiple PM Google Sheets -----
TEAMS = {
    "Tech Team": {
        "sources": [
            {"pm": "Hatem", "sheet_id": "1uhTGZRXIpEo17xAafGAlvZQiozpfQpGuEdONTDqC07M", "gid": None},
            {"pm": "M.Jamal", "sheet_id": "1Gi3OT0ckWjGLbGj1D6gLRjzJP3-3M7ufnSuW5XaTtiM", "gid": None},
            {"pm": "ALI", "sheet_id": "1X_mO4jK3DWSnz-HBYX5bTL6w7VwpzGJqPSax8sJ6FtQ", "gid": None},
            {"pm": "Hakem", "sheet_id": "1DGuOh10TsEbaGAukCVIvf7zhnzzTtb0sT5lghdOREZo", "gid": None},
            {"pm": "Saed", "sheet_id": "1L7WGgEQlfVHnuBgJ9pcFN147-2iKOS4eAoZDXabMQw4", "gid": None},
        ],
        "mode": "hours",
        "count_source": HAKEM_HEADCOUNT_SOURCE,
        "disciplines": ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical", "QS"],
        "engineers": [13, 16, 5, 5, 11, 2],  # Fallback defaults matching Hakem's sheet
    },
    "Design Team": {
        "sources": [
            {"pm": "Hatem", "sheet_id": "1OLu-8F-rLzWQDBwBXY6hy7UdinAAmT9HudFjR4hwg-s", "gid": None},
            {"pm": "M.Jamal", "sheet_id": "1EZhne868HwGFMhGctKMIpTS9q9Bu9uOxLK8HFAVcDJI", "gid": None},
            {"pm": "ALI", "sheet_id": "1T-uTqRrj434npG_O2t_6H00ZdmB4RYHD-GqCma0mBFU", "gid": None},
            {"pm": "Hakem", "sheet_id": "12kQT3spDilCM3cqapJhfeoxX7u7fuRqsLuqY5PGJDHM", "gid": None},
            {"pm": "Saed", "sheet_id": "1JydBR9p0Ne-4d-8Ekx8XLGJ7veVygyRBjSZLaFXlrww", "gid": None},
        ],
        "mode": "team_count",
        "disciplines": ["Arch Design Team"],
        "engineers": [21],
    },
    "BIM Team": {
        "sources": [
            {"pm": "All", "sheet_id": "1g9lFbLem738PcQ3FOWGjXZJopwWnf2g5-ncS6dUwNn8", "gid": None},
        ],
        "mode": "team_count",
        "disciplines": ["BIM Team"],
        "engineers": [3],
    },
    "QC Team": {
        "sources": [
            {"pm": "All", "sheet_id": "1g0carFHs1RSN4MWtVFdt8kWfTnEmCFrMiicEznft8Bc", "gid": None},
        ],
        "mode": "hours",
        "disciplines": ["Arch", "Structural", "MEP", "Electrical"],
        "engineers": [2, 1, 1, 2],
    },
}

# ----- Actual Team Tracking Sheets (by Discipline) -----
ACTUAL_TEAM_OPTION = "Actual Team"
ACTUAL_TEAM_SOURCES = {
    "Electrical": {
        "label_ar": "فريق الكهرباء",
        "sheet_id": "1wuUdghyxxDJqNk-oTC26X3CHpWRX6TiuMctDc4j87YM",
        "gid": 0,
        "fallback_engineers": 11,
    },
    "HVAC": {
        "label_ar": "فريق الـ HVAC",
        "sheet_id": "1pvQ4vIiax5UiJPrysV4ADtuiiqDITf89pQKwx1n94TU",
        "gid": 0,
        "fallback_engineers": 5,
    },
    "Plumbing": {
        "label_ar": "فريق Plumbing",
        "sheet_id": "1RzMbLSaSXm4CiIQxk65bPlLqdEvQ-zduSZWfX6CLErk",
        "gid": 0,
        "fallback_engineers": 5,
    },
    "Arch Tech": {
        "label_ar": "فريق المعماري تيكنيكال",
        "sheet_id": "1DsPBL8RqaK5MG1TJfAFIa-sTs925YGEJbHu-JjukDGw",
        "gid": 0,
        "fallback_engineers": 13,
    },
    "Structural": {
        "label_ar": "فريق الإنشائي",
        "sheet_id": "183zQfKqhcRJAkulTMx47JoNHempE9gshuMseQGVVgLM",
        "gid": 0,
        "fallback_engineers": 16,
    },
}

MAIN_OPTION = "Main"


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
# 2. Load data from Google Sheet(s)
# ----------------------------------------------------------------------
def get_empty_template(mode="hours", disciplines=None):
    today = datetime.date.today()
    if mode == "team_count":
        return pd.DataFrame({
            "Project Manager": ["Default"],
            "No.": [1],
            "Project Name": ["Example Project"],
            "Start Date": [today],
            "End Date": [today + datetime.timedelta(days=30)],
            "Team Count": [2],
            "Calculated Hours": [160.0],
        })
    data = {
        "Project Manager": ["Default"],
        "No.": [1],
        "Project Name": ["Example Project"],
        "Start Date": [today],
        "End Date": [today + datetime.timedelta(days=30)],
    }
    for d in (disciplines or ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical", "QS"]):
        data[f"{d} (Hrs)"] = [40.0]
    return pd.DataFrame(data)


def parse_dates(series, dayfirst=False):
    """Parse mixed date formats safely (e.g. 2026-10-18, 11/1/2026, or 15/11/2026)."""
    try:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=dayfirst)
    except (TypeError, ValueError):
        parsed = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)
    return parsed.dt.date


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
        if ("qs" in raw_low or "quantity" in raw_low) and "qs" in d_low:
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
def load_from_gsheet(url, disciplines, max_rows=MAX_ROWS):
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
                if pd.notnull(val) and str(val).strip().lower() == "discipline":
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
    df = df.head(max_rows).copy()

    # Drop completely empty project rows (where Project Name is missing)
    name_c = find_name_col(df)
    if name_c and name_c in df.columns:
        df = df[df[name_c].notna() & (df[name_c].astype(str).str.strip() != "")].reset_index(drop=True)

    if "Start Date" in df.columns:
        df["Start Date"] = parse_dates(df["Start Date"])
    if "End Date" in df.columns:
        df["End Date"] = parse_dates(df["End Date"])

    for c in df.columns:
        if c in DATA_COLS or "(hrs)" in c.lower() or "hours" in c.lower() or "count" in c.lower():
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df, eng_counts


def load_team_merged_data(team_cfg, max_rows=MAX_ROWS):
    """Load and merge all PM Google Sheets configured for a team."""
    disciplines = team_cfg["disciplines"]
    sources = team_cfg.get("sources", [])

    dfs = []
    merged_eng_counts = {}
    errors = []

    # If a dedicated headcount source (e.g. Hakem's Team count tab) is configured, read from it exclusively
    dedicated_count_src = team_cfg.get("count_source")
    if dedicated_count_src:
        c_url = build_csv_url(dedicated_count_src["sheet_id"], dedicated_count_src.get("gid"))
        try:
            tab_c = load_team_counts(c_url, disciplines)
            if tab_c:
                merged_eng_counts.update(tab_c)
        except Exception as e:
            errors.append(f"Headcount tab: {e}")

    for src in sources:
        pm_name = src.get("pm", "Unknown")
        s_id = src["sheet_id"]
        gid = src.get("gid")
        csv_url = build_csv_url(s_id, gid)

        try:
            df_part, counts_part = load_from_gsheet(csv_url, disciplines, max_rows)

            # Tag each row with its Project Manager if multiple PMs exist
            if len(sources) > 1:
                df_part.insert(0, "Project Manager", pm_name)

            dfs.append(df_part)

            if not dedicated_count_src:
                if counts_part and not merged_eng_counts:
                    merged_eng_counts.update(counts_part)

                if not merged_eng_counts and (team_cfg.get("count_sheet") or team_cfg.get("count_gid") is not None):
                    if team_cfg.get("count_gid") is not None:
                        c_url = build_csv_url(s_id, team_cfg["count_gid"])
                    else:
                        c_url = build_sheet_name_url(s_id, team_cfg["count_sheet"])
                    try:
                        tab_c = load_team_counts(c_url, disciplines)
                        if tab_c:
                            merged_eng_counts.update(tab_c)
                    except Exception:
                        pass
        except Exception as e:
            errors.append(f"{pm_name}: {e}")

    if dfs:
        combined_df = pd.concat(dfs, ignore_index=True, sort=False)
        # Reorder standard columns nicely
        front_cols = [c for c in ["Project Manager", "No.", "Project Name", "Start Date", "End Date"] if c in combined_df.columns]
        other_cols = [c for c in combined_df.columns if c not in front_cols]
        combined_df = combined_df[front_cols + other_cols]
    else:
        combined_df = get_empty_template(team_cfg["mode"], disciplines)

    return combined_df, merged_eng_counts, errors


# ----------------------------------------------------------------------
# 2b. Actual Team Data Loading & Resource Analysis Helpers
# ----------------------------------------------------------------------
def split_engineer_names(raw_val):
    """Split a cell containing engineer names separated by '-', '/', ',', or '،'."""
    if pd.isnull(raw_val):
        return []
    text = str(raw_val).strip()
    if not text or re.fullmatch(r"[-–—_\s]+", text):
        return []
    parts = re.split(r"\s*[-–—/,،&+]+\s*", text)
    cleaned = []
    for p in parts:
        name = re.sub(r"\s+", " ", p).strip()
        if name and len(name) > 1:
            cleaned.append(name)
    return cleaned


def _parse_actual_date_cell(val):
    """Parse DD/MM/YYYY dates safely; return None for blank or '-----'."""
    if pd.isnull(val):
        return None
    txt = str(val).strip()
    if not txt or re.fullmatch(r"[-–—_\s]+", txt):
        return None
    ts = pd.to_datetime(txt, errors="coerce", dayfirst=True)
    if pd.isnull(ts):
        return None
    return ts.date()


@st.cache_data(ttl=60, show_spinner="Loading Actual Team tracking sheet...")
def load_actual_team_sheet(url, discipline_name):
    """Read an Arabic Actual Team resource sheet (skipping merged title rows automatically)."""
    raw = pd.read_csv(url, header=None, dtype=str)
    if raw.empty:
        return pd.DataFrame(columns=[
            "Discipline", "Unit Head", "Engineers", "Project", "Task",
            "Engineers Count", "Start Date", "End Date", "Is Ongoing", "Engineer List"
        ])

    # Detect header row dynamically (look for المشروع / المهندس / عدد المهندسين)
    header_idx = None
    for idx, row in raw.iterrows():
        row_joined = " ".join(str(x).strip().lower() for x in row if pd.notnull(x))
        if any(k in row_joined for k in ("المشروع", "المهندس", "عدد المهندسين", "تاريخ البدء", "project", "engineer")):
            header_idx = idx
            break

    if header_idx is None:
        header_idx = 0

    headers = [str(x).strip() if pd.notnull(x) else "" for x in raw.iloc[header_idx]]
    body = raw.iloc[header_idx + 1:].copy().reset_index(drop=True)

    # Map column indices flexibly
    col_map = {
        "unit_head": None,
        "engineers": None,
        "project": None,
        "task": None,
        "count": None,
        "start": None,
        "end": None,
    }
    for i, h in enumerate(headers):
        h_low = h.lower()
        if "unit" in h_low or "head" in h_low or "رئيس" in h_low:
            col_map["unit_head"] = i
        elif "عدد" in h_low or "count" in h_low:
            col_map["count"] = i
        elif "مهندس" in h_low or "engineer" in h_low:
            col_map["engineers"] = i
        elif "مشروع" in h_low or "project" in h_low:
            col_map["project"] = i
        elif "مهم" in h_low or "task" in h_low:
            col_map["task"] = i
        elif "بدء" in h_low or "بداي" in h_low or "start" in h_low:
            col_map["start"] = i
        elif "نهاي" in h_low or "انته" in h_low or "end" in h_low:
            col_map["end"] = i

    records = []
    for _, r in body.iterrows():
        def _get(key):
            c_idx = col_map[key]
            if c_idx is None or c_idx >= len(r):
                return ""
            v = r.iloc[c_idx]
            return "" if pd.isnull(v) else str(v).strip()

        unit_head = _get("unit_head")
        eng_str = _get("engineers")
        project = _get("project")
        task = _get("task")
        cnt_raw = _get("count")
        start_raw = _get("start")
        end_raw = _get("end")

        # Skip completely empty rows
        if not any([eng_str, project, task, start_raw, end_raw]):
            continue

        eng_list = split_engineer_names(eng_str)

        try:
            eng_count = int(float(cnt_raw)) if cnt_raw != "" else len(eng_list)
        except (ValueError, TypeError):
            eng_count = len(eng_list)

        s_date = _parse_actual_date_cell(start_raw)
        e_date = _parse_actual_date_cell(end_raw)
        # Ongoing if Start Date exists but End Date is blank or '-----'
        is_ongoing = (s_date is not None) and (e_date is None)

        records.append({
            "Discipline": discipline_name,
            "Unit Head": unit_head if unit_head else "-",
            "Engineers": eng_str if eng_str else "-",
            "Project": project if project else "-",
            "Task": task if task else "-",
            "Engineers Count": max(0, eng_count),
            "Start Date": s_date,
            "End Date": e_date,
            "Is Ongoing": is_ongoing,
            "Engineer List": eng_list,
        })

    return pd.DataFrame(records)


def get_program_discipline_counts():
    """Fetch live engineer counts exclusively from Hakem's Tech Team 'Team count' tab."""
    disciplines = list(ACTUAL_TEAM_SOURCES.keys())
    counts = {}

    c_url = build_csv_url(HAKEM_HEADCOUNT_SOURCE["sheet_id"], HAKEM_HEADCOUNT_SOURCE["gid"])
    try:
        tab_c = load_team_counts(c_url, disciplines)
        if tab_c:
            counts.update(tab_c)
    except Exception:
        pass

    # Fill any missing discipline with fallback
    for d, cfg in ACTUAL_TEAM_SOURCES.items():
        if d not in counts:
            counts[d] = cfg["fallback_engineers"]
    return counts


def classify_actual_task(row, ref_date, soon_days):
    """Classify task status relative to ref_date."""
    s_date = row["Start Date"]
    e_date = row["End Date"]
    is_ongoing = row["Is Ongoing"]

    if s_date is None and e_date is None:
        return "⚪ No Dates", None

    if is_ongoing:
        if s_date <= ref_date:
            return "♾️ Ongoing (No End Date)", None
        return "🔵 Upcoming", None

    if s_date is not None and s_date > ref_date:
        return "🔵 Upcoming", (e_date - ref_date).days if e_date else None

    if e_date is not None and e_date < ref_date:
        return "⚪ Completed", (e_date - ref_date).days

    # Active on ref_date
    days_left = (e_date - ref_date).days if e_date is not None else None
    if days_left is not None and 0 <= days_left <= soon_days:
        return "⏳ Ending Soon", days_left
    return "🟢 Active", days_left


def is_task_active_on_date(row, check_date):
    s_date = row["Start Date"]
    e_date = row["End Date"]
    if s_date is None:
        return False
    if row["Is Ongoing"]:
        return s_date <= check_date
    if e_date is None:
        return False
    return s_date <= check_date <= e_date


def render_actual_team_view():
    st.markdown("---")
    st.subheader("👷 Actual Team — Live Resource Allocation & Availability Tracker")

    # Refresh & Direct Links to all 5 sheets
    disc_list = list(ACTUAL_TEAM_SOURCES.keys())
    btn_cols = st.columns([1.2] + [1] * len(disc_list))
    with btn_cols[0]:
        refresh_actual = st.button("🔄 Refresh All 5 Sheets", use_container_width=True, key="refresh_actual_btn")

    for idx, disc in enumerate(disc_list):
        cfg = ACTUAL_TEAM_SOURCES[disc]
        with btn_cols[idx + 1]:
            st.link_button(
                f"🔗 {disc}",
                f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/edit?gid={cfg['gid']}#gid={cfg['gid']}",
                use_container_width=True,
            )

    if refresh_actual:
        load_actual_team_sheet.clear()
        load_team_counts.clear()
        for d in disc_list:
            st.session_state.pop(f"actual_total_eng_{d}", None)
        st.rerun()

    # Load all 5 sheets
    all_dfs = []
    load_errors = []
    for disc, cfg in ACTUAL_TEAM_SOURCES.items():
        url = build_csv_url(cfg["sheet_id"], cfg["gid"])
        try:
            df_d = load_actual_team_sheet(url, disc)
            all_dfs.append(df_d)
        except Exception as e:
            load_errors.append(f"{disc}: {e}")

    if load_errors:
        st.warning(f"⚠️ Could not load some sheets: {'; '.join(load_errors)}")

    if all_dfs:
        actual_df = pd.concat(all_dfs, ignore_index=True)
    else:
        st.error("No Actual Team sheets could be loaded.")
        return

    # Sidebar: Program Engineers Count (pulled exclusively from Hakem's Tech Team 'Team count' tab)
    program_defaults = get_program_discipline_counts()
    st.sidebar.header("⚙️ Actual Team Headcount")
    st.sidebar.caption("Source: Hakem — Tech Team (Team count tab)")
    st.sidebar.link_button(
        "🔗 Open Hakem Headcount Tab",
        f"https://docs.google.com/spreadsheets/d/{HAKEM_HEADCOUNT_SOURCE['sheet_id']}/edit?gid={HAKEM_HEADCOUNT_SOURCE['gid']}#gid={HAKEM_HEADCOUNT_SOURCE['gid']}",
        use_container_width=True,
    )

    total_engineers_map = {}
    for disc in disc_list:
        total_engineers_map[disc] = st.sidebar.number_input(
            f"{disc} Total Engineers",
            min_value=0,
            value=int(program_defaults.get(disc, ACTUAL_TEAM_SOURCES[disc]["fallback_engineers"])),
            key=f"actual_total_eng_{disc}",
        )
    st.sidebar.markdown("---")
    st.sidebar.metric("👥 Total Engineers (All 5 Disciplines)", sum(total_engineers_map.values()))

    # Top Filter Controls
    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.5, 1.5])
    with c1:
        ref_date = st.date_input("📅 Reference Date (Check Availability):", value=datetime.date.today(), key="actual_ref_date")
    with c2:
        soon_days = st.slider("⏳ 'Free Soon' Window (Days):", min_value=1, max_value=30, value=7, key="actual_soon_days")
    with c3:
        selected_discs = st.multiselect(
            "🏗️ Disciplines:",
            options=disc_list,
            default=disc_list,
            key="actual_disc_filter",
        )
    with c4:
        calc_basis = st.radio(
            "🧮 Busy Count Basis:",
            options=["By 'عدد المهندسين' Column", "By Unique Engineer Names"],
            horizontal=True,
            key="actual_calc_basis",
            help="Use 'عدد المهندسين' for total task load, or 'Unique Engineer Names' when one engineer works on multiple projects simultaneously.",
        )

    if not selected_discs:
        st.info("Please select at least one discipline.")
        return

    work_df = actual_df[actual_df["Discipline"].isin(selected_discs)].copy()

    # Classify each task relative to ref_date
    statuses = []
    days_left_list = []
    active_flags = []
    for _, r in work_df.iterrows():
        status_lbl, d_left = classify_actual_task(r, ref_date, soon_days)
        statuses.append(status_lbl)
        days_left_list.append(d_left)
        active_flags.append(is_task_active_on_date(r, ref_date))

    work_df["Status"] = statuses
    work_df["Days Left"] = days_left_list
    work_df["Is Active"] = active_flags

    # ------------------------------------------------------------------
    # Section 1: Summary by Discipline (Working vs. Free Engineers)
    # ------------------------------------------------------------------
    summary_rows = []
    for disc in selected_discs:
        d_sub = work_df[work_df["Discipline"] == disc]
        active_sub = d_sub[d_sub["Is Active"]]
        soon_sub = d_sub[d_sub["Status"] == "⏳ Ending Soon"]

        total_in_prog = total_engineers_map[disc]
        assigned_sum = int(active_sub["Engineers Count"].sum()) if not active_sub.empty else 0

        unique_active_names = sorted({
            name for names in active_sub["Engineer List"] for name in names
        })
        unique_active_count = len(unique_active_names)

        working_used = assigned_sum if calc_basis == "By 'عدد المهندسين' Column" else unique_active_count
        free_count = total_in_prog - working_used

        soon_eng_sum = int(soon_sub["Engineers Count"].sum()) if not soon_sub.empty else 0

        if free_count > 0:
            status_badge = f"🟢 {free_count} Free"
        elif free_count == 0:
            status_badge = "🟡 Fully Utilized"
        else:
            status_badge = f"🔴 Overloaded ({free_count})"

        summary_rows.append({
            "Discipline": disc,
            "Total in Program": total_in_prog,
            "Active Tasks": len(active_sub),
            "Working (عدد المهندسين)": assigned_sum,
            "Unique Names Active": unique_active_count,
            "Free / Available": free_count,
            f"Ending in ≤{soon_days}d (Tasks)": len(soon_sub),
            f"Freeing Up Soon (Eng)": soon_eng_sum,
            "Status": status_badge,
        })

    summary_df = pd.DataFrame(summary_rows)

    total_prog_all = int(summary_df["Total in Program"].sum())
    total_working_all = int(
        summary_df["Working (عدد المهندسين)"].sum()
        if calc_basis == "By 'عدد المهندسين' Column"
        else summary_df["Unique Names Active"].sum()
    )
    total_free_all = total_prog_all - total_working_all
    total_soon_tasks = int(summary_df[f"Ending in ≤{soon_days}d (Tasks)"].sum())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("👥 Total Engineers (Program)", total_prog_all)
    k2.metric("🛠️ Working on Projects", total_working_all)
    k3.metric("🟢 Free / Available Now", total_free_all)
    k4.metric(f"⏳ Tasks Ending Within {soon_days} Days", total_soon_tasks)

    st.markdown("### 📊 Availability Summary by Discipline")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    # Bar chart: Working vs Available per discipline
    chart_rows = []
    for _, r in summary_df.iterrows():
        working_val = r["Working (عدد المهندسين)"] if calc_basis == "By 'عدد المهندسين' Column" else r["Unique Names Active"]
        free_val = max(0, r["Free / Available"])
        overload_val = max(0, -r["Free / Available"])
        chart_rows.append({"Discipline": r["Discipline"], "Category": "Working (Assigned)", "Engineers": min(working_val, r["Total in Program"])})
        if free_val > 0:
            chart_rows.append({"Discipline": r["Discipline"], "Category": "Free / Available", "Engineers": free_val})
        if overload_val > 0:
            chart_rows.append({"Discipline": r["Discipline"], "Category": "Overloaded (Multi-Task)", "Engineers": overload_val})

    avail_chart_df = pd.DataFrame(chart_rows)
    if not avail_chart_df.empty:
        color_scale = alt.Scale(
            domain=["Working (Assigned)", "Free / Available", "Overloaded (Multi-Task)"],
            range=["#1f77b4", "#2ca02c", "#d62728"],
        )
        bar_chart = alt.Chart(avail_chart_df).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("Discipline:N", title="Discipline", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Engineers:Q", title="Number of Engineers"),
            color=alt.Color("Category:N", scale=color_scale, legend=alt.Legend(title="Status")),
            tooltip=["Discipline", "Category", "Engineers"],
        ).properties(height=300)
        st.altair_chart(bar_chart, use_container_width=True)

    # ------------------------------------------------------------------
    # Section 2: Who Is Free Now & Who Will Be Free Soon
    # ------------------------------------------------------------------
    st.markdown("---")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown(f"### ⏳ Freeing Up Soon (Ending Within {soon_days} Days)")
        soon_df = work_df[work_df["Status"] == "⏳ Ending Soon"].sort_values("End Date")
        if soon_df.empty:
            st.info(f"No active tasks ending within {soon_days} days of {ref_date}.")
        else:
            st.dataframe(
                soon_df[["Discipline", "Engineers", "Project", "Task", "Engineers Count", "End Date", "Days Left"]],
                use_container_width=True,
                hide_index=True,
            )

    with col_right:
        st.markdown("### 🟢 Engineers Currently Without Active Tasks")
        st.caption("Engineers listed in the sheets whose tasks ended before the reference date (or haven't started yet).")

        free_eng_records = []
        for disc in selected_discs:
            d_sub = work_df[work_df["Discipline"] == disc]
            all_known_names = sorted({n for lst in d_sub["Engineer List"] for n in lst})
            active_names = {n for lst in d_sub[d_sub["Is Active"]]["Engineer List"] for n in lst}

            upcoming_sub = d_sub[d_sub["Status"] == "🔵 Upcoming"]
            completed_sub = d_sub[d_sub["Status"] == "⚪ Completed"]

            for name in all_known_names:
                if name not in active_names:
                    # Check if they have an upcoming task
                    if not upcoming_sub.empty:
                        next_mask = upcoming_sub["Engineer List"].apply(lambda lst: name in lst).astype(bool)
                        next_tasks = upcoming_sub[next_mask].sort_values("Start Date")
                    else:
                        next_tasks = pd.DataFrame()

                    if not next_tasks.empty:
                        nxt = next_tasks.iloc[0]
                        next_info = f"Booked: {nxt['Project']} (starts {nxt['Start Date']})"
                    else:
                        next_info = "No upcoming task scheduled"

                    # Last completed task
                    if not completed_sub.empty:
                        prev_mask = completed_sub["Engineer List"].apply(lambda lst: name in lst).astype(bool)
                        prev_tasks = completed_sub[prev_mask].sort_values("End Date", ascending=False)
                    else:
                        prev_tasks = pd.DataFrame()

                    last_proj = prev_tasks.iloc[0]["Project"] if not prev_tasks.empty else "-"

                    free_eng_records.append({
                        "Discipline": disc,
                        "Engineer": name,
                        "Last Project": last_proj,
                        "Upcoming Status": next_info,
                    })

        if free_eng_records:
            st.dataframe(pd.DataFrame(free_eng_records), use_container_width=True, hide_index=True)
        else:
            st.info("All named engineers in the selected sheets currently have active tasks (check numeric 'Free / Available' above for unlisted team members).")

    # Upcoming tasks notice
    upcoming_all = work_df[work_df["Status"] == "🔵 Upcoming"].sort_values("Start Date")
    if not upcoming_all.empty:
        with st.expander(f"🔵 Upcoming Scheduled Tasks ({len(upcoming_all)})"):
            st.dataframe(
                upcoming_all[["Discipline", "Engineers", "Project", "Task", "Engineers Count", "Start Date", "End Date"]],
                use_container_width=True,
                hide_index=True,
            )

    # ------------------------------------------------------------------
    # Section 3: Daily Availability Forecast (Sun - Thu)
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 📈 Daily Free Engineers Forecast (Sunday - Thursday)")

    forecast_weeks = st.slider("Forecast Horizon (Weeks):", 1, 8, 3, key="actual_forecast_weeks")
    f_days = [
        d.date()
        for d in pd.bdate_range(start=ref_date, periods=forecast_weeks * 5, freq="C", weekmask=PD_WEEKMASK)
    ]
    f_labels = [d.strftime("%a %d-%b") for d in f_days]

    forecast_table_rows = []
    forecast_chart_rows = []

    for disc in selected_discs:
        d_sub = work_df[work_df["Discipline"] == disc]
        tot_eng = total_engineers_map[disc]
        row_dict = {"Discipline": disc, "Total": tot_eng}

        for d_obj, d_lbl in zip(f_days, f_labels):
            active_on_d = d_sub[d_sub.apply(lambda r: is_task_active_on_date(r, d_obj), axis=1)]
            if calc_basis == "By 'عدد المهندسين' Column":
                busy_cnt = int(active_on_d["Engineers Count"].sum()) if not active_on_d.empty else 0
            else:
                busy_cnt = len({n for lst in active_on_d["Engineer List"] for n in lst})
            free_cnt = tot_eng - busy_cnt
            row_dict[d_lbl] = free_cnt
            forecast_chart_rows.append({
                "Day": d_lbl,
                "Discipline": disc,
                "Free Engineers": free_cnt,
                "Busy Engineers": busy_cnt,
            })

        forecast_table_rows.append(row_dict)

    forecast_df = pd.DataFrame(forecast_table_rows)

    def _style_free_cells(val):
        if isinstance(val, (int, float)):
            if val < 0:
                return "background-color: #ffcccc; color: #900000; font-weight: bold"
            if val > 0:
                return "background-color: #e6f4ea; color: #137333; font-weight: bold"
        return ""

    st.caption("Positive (green) = available engineers | Negative (red) = overloaded / multi-tasking")
    st.dataframe(
        forecast_df.style.map(_style_free_cells, subset=f_labels),
        use_container_width=True,
        hide_index=True,
    )

    f_chart_df = pd.DataFrame(forecast_chart_rows)
    if not f_chart_df.empty:
        line_chart = alt.Chart(f_chart_df).mark_line(point=True).encode(
            x=alt.X("Day:N", sort=f_labels, title="Working Day", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("Free Engineers:Q", title="Free / Available Engineers"),
            color=alt.Color("Discipline:N"),
            tooltip=["Day", "Discipline", "Busy Engineers", "Free Engineers"],
        ).properties(height=300)
        zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="red", strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart(line_chart + zero_rule, use_container_width=True)

    # ------------------------------------------------------------------
    # Section 4: Detailed Tasks & Gantt per Discipline
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 📋 Detailed Task Register & Timeline by Discipline")

    tab_names = ["All Disciplines"] + selected_discs
    disc_tabs = st.tabs(tab_names)

    for idx, t_name in enumerate(tab_names):
        with disc_tabs[idx]:
            sub = work_df if t_name == "All Disciplines" else work_df[work_df["Discipline"] == t_name]
            if sub.empty:
                st.info(f"No tasks recorded for {t_name}.")
                continue

            display_cols = ["Discipline", "Status", "Unit Head", "Engineers", "Project", "Task", "Engineers Count", "Start Date", "End Date", "Days Left"]
            st.dataframe(sub[display_cols], use_container_width=True, hide_index=True)

            # Mini Gantt for tasks with valid dates
            g_df = sub[sub["Start Date"].notna()].copy()
            if not g_df.empty:
                g_df["Start"] = pd.to_datetime(g_df["Start Date"])
                # For ongoing tasks with no End Date, visualize up to ref_date + 14 days
                fallback_end = pd.Timestamp(ref_date + datetime.timedelta(days=14))
                g_df["End"] = g_df["End Date"].apply(
                    lambda d: pd.Timestamp(d) if pd.notnull(d) else fallback_end
                )
                g_df["EndPlus"] = g_df["End"] + pd.Timedelta(days=1)
                g_df["Label"] = g_df.apply(
                    lambda r: f"[{r['Discipline']}] {r['Project']} ({r['Engineers']})"
                    if t_name == "All Disciplines"
                    else f"{r['Project']} ({r['Engineers']})",
                    axis=1,
                )
                if g_df["Label"].duplicated().any():
                    seen = {}
                    uniq = []
                    for lbl in g_df["Label"]:
                        c = seen.get(lbl, 0) + 1
                        seen[lbl] = c
                        uniq.append(f"{lbl} #{c}" if c > 1 else lbl)
                    g_df["Label"] = uniq

                g_df = g_df.sort_values(["Start", "End"])
                g_order = g_df["Label"].tolist()

                bars = alt.Chart(g_df).mark_bar(cornerRadius=3).encode(
                    y=alt.Y("Label:N", sort=g_order, title=None, axis=alt.Axis(labelLimit=320)),
                    x=alt.X("Start:T", title="Timeline", axis=alt.Axis(format="%d-%b", labelAngle=-45)),
                    x2="EndPlus:T",
                    color=alt.Color("Status:N"),
                    tooltip=[
                        alt.Tooltip("Discipline:N"),
                        alt.Tooltip("Project:N"),
                        alt.Tooltip("Engineers:N"),
                        alt.Tooltip("Task:N"),
                        alt.Tooltip("Engineers Count:Q"),
                        alt.Tooltip("Start:T", format="%d-%b-%Y"),
                        alt.Tooltip("End:T", format="%d-%b-%Y"),
                        alt.Tooltip("Status:N"),
                    ],
                )
                ref_rule = alt.Chart(pd.DataFrame({"Ref": [pd.Timestamp(ref_date)]})).mark_rule(
                    color="red", strokeDash=[5, 4], strokeWidth=2
                ).encode(x="Ref:T")

                st.altair_chart(
                    (bars + ref_rule).properties(height=max(160, 32 * len(g_df) + 50)),
                    use_container_width=True,
                )


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
    skip = {"Project Manager", "No.", "Start Date", "End Date"} | set(DATA_COLS)
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
    pm = r.get("Project Manager")
    pm_prefix = f"[{pm}] " if pd.notnull(pm) and str(pm).strip() not in ("", "All", "Default") else ""

    no = r.get("No.")
    if pd.notnull(no) and str(no).strip() != "":
        try:
            no = int(float(no))
        except (ValueError, TypeError):
            pass
        return f"{pm_prefix}{no}. {name}"
    return f"{pm_prefix}{name}"


def prepare_calc_df(df, team_mode, disciplines, hours_per_day=HOURS_PER_DAY):
    calc_df = df.copy()
    count_col = find_count_col(calc_df)

    calc_df["Start Date"] = parse_dates(calc_df["Start Date"])
    calc_df["End Date"] = parse_dates(calc_df["End Date"])
    calc_df["End Date"] = calc_df["End Date"].fillna(calc_df["Start Date"])
    calc_df["Start Date"] = calc_df["Start Date"].fillna(calc_df["End Date"])

    if team_mode == "team_count":
        hrs_col_name = f"{disciplines[0]} (Hrs)"
        sheet_hrs_col = find_calc_hrs_col(calc_df)

        calc_from_count = False
        if sheet_hrs_col is not None and sheet_hrs_col in calc_df.columns:
            calc_df[hrs_col_name] = pd.to_numeric(calc_df[sheet_hrs_col], errors="coerce")
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


def render_project_gantt_chart(calc_df, disciplines, team_mode, count_col, hide_completed=True):
    name_col = find_name_col(calc_df)
    gantt_df = calc_df.copy()
    gantt_df["Start"] = pd.to_datetime(gantt_df["Start Date"], errors="coerce")
    gantt_df["End"] = pd.to_datetime(gantt_df["End Date"], errors="coerce")

    gantt_df["End"] = gantt_df["End"].fillna(gantt_df["Start"])
    gantt_df["Start"] = gantt_df["Start"].fillna(gantt_df["End"])

    total_rows = len(gantt_df)
    gantt_df = gantt_df.dropna(subset=["Start", "End"])
    invalid_dates = total_rows - len(gantt_df)
    gantt_df = gantt_df[gantt_df["End"] >= gantt_df["Start"]]
    reversed_dates = total_rows - invalid_dates - len(gantt_df)

    today = pd.Timestamp.today().normalize()
    hidden_completed = 0
    if hide_completed:
        before = len(gantt_df)
        gantt_df = gantt_df[gantt_df["End"] >= today]
        hidden_completed = before - len(gantt_df)

    notes = []
    if invalid_dates:
        notes.append(f"{invalid_dates} row(s) with unreadable dates")
    if reversed_dates:
        notes.append(f"{reversed_dates} row(s) where End Date is before Start Date")
    if hidden_completed:
        notes.append(f"{hidden_completed} completed row(s) hidden by the filter")
    st.caption(
        f"Rows read: {total_rows} | Rows shown in chart: {len(gantt_df)}"
        + (f" | Not shown: {'; '.join(notes)}" if notes else "")
    )

    if gantt_df.empty:
        st.info("No ongoing or upcoming projects with valid dates to display.")
        return

    hrs_cols = [f"{d} (Hrs)" for d in disciplines if f"{d} (Hrs)" in gantt_df.columns]
    gantt_df["Project"] = gantt_df.apply(lambda r: make_project_label(r, name_col), axis=1)

    if gantt_df["Project"].duplicated().any():
        seen = {}
        unique_labels = []
        for p in gantt_df["Project"]:
            count = seen.get(p, 0) + 1
            seen[p] = count
            unique_labels.append(f"{p} ({count})" if count > 1 else p)
        gantt_df["Project"] = unique_labels

    gantt_df["EndPlus"] = gantt_df["End"] + pd.Timedelta(days=1)
    gantt_df["TotalHrs"] = (
        gantt_df[hrs_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1) if hrs_cols else 0.0
    )

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
    if "Project Manager" in gantt_df.columns:
        extra_tooltips.append(alt.Tooltip("Project Manager:N", title="Project Manager"))
    if team_mode == "team_count" and count_col is not None and count_col in gantt_df.columns:
        gantt_df["TeamCount"] = pd.to_numeric(gantt_df[count_col], errors="coerce")
        extra_tooltips.append(alt.Tooltip("TeamCount:Q", title="Team count"))

    tooltip_items = [
        alt.Tooltip("Project:N", title="Project"),
        *extra_tooltips,
        alt.Tooltip("Start:T", title="Start", format="%a %d-%b-%Y"),
        alt.Tooltip("End:T", title="End", format="%a %d-%b-%Y"),
        alt.Tooltip("WorkDays:Q", title="Working days (Sun-Thu)"),
        alt.Tooltip("TotalHrs:Q", title="Total hours", format=",.0f"),
    ]

    color_field = "Project Manager:N" if ("Project Manager" in gantt_df.columns and gantt_df["Project Manager"].nunique() > 1) else "Project:N"
    show_legend = alt.Legend(title="Project Manager") if color_field == "Project Manager:N" else None

    bars = alt.Chart(gantt_df).mark_bar(cornerRadius=3).encode(
        y=alt.Y("Project:N", sort=project_order, title=None, axis=alt.Axis(labelLimit=280)),
        x=alt.X("Start:T", scale=x_scale, title="Date", axis=alt.Axis(format="%d-%b", labelAngle=-45)),
        x2="EndPlus:T",
        color=alt.Color(color_field, legend=show_legend),
        tooltip=tooltip_items,
    )

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

    col_f1, col_f2, col_f3 = st.columns([1.5, 2, 1.5])
    with col_f1:
        hide_comp = st.checkbox("Filter completed", value=False, key="main_hide_comp")
    with col_f2:
        all_pms = sorted({
            src["pm"]
            for cfg in TEAMS.values()
            for src in cfg.get("sources", [])
            if src["pm"] != "All"
        })
        selected_pms = st.multiselect(
            "👔 Filter by Project Manager:",
            options=all_pms,
            default=all_pms,
            key="main_pm_filter",
        )
    with col_f3:
        if st.button("🔄 Refresh All Sheets", use_container_width=True):
            load_from_gsheet.clear()
            load_team_counts.clear()
            st.rerun()

    team_order = ["BIM Team", "Tech Team", "Design Team", "QC Team"]
    valid_teams = [t for t in team_order if t in TEAMS]

    all_completed_projects = []
    today = datetime.date.today()

    for i in range(0, len(valid_teams), 2):
        pair = valid_teams[i:i + 2]
        cols = st.columns(2)
        for col_idx, t_name in enumerate(pair):
            with cols[col_idx]:
                cfg = TEAMS[t_name]
                st.markdown(f"### 👥 {t_name}")
                try:
                    team_df, team_counts, errs = load_team_merged_data(cfg, MAX_ROWS)
                    if errs:
                        st.warning(f"Partial load warnings: {'; '.join(errs)}")

                    if "Project Manager" in team_df.columns and selected_pms:
                        team_df = team_df[team_df["Project Manager"].isin(selected_pms + ["All", "Default"])]

                    team_calc_df, t_count_col = prepare_calc_df(team_df, cfg["mode"], cfg["disciplines"])
                    render_project_gantt_chart(team_calc_df, cfg["disciplines"], cfg["mode"], t_count_col, hide_comp)

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
                                    "Project Manager": r.get("Project Manager", "-"),
                                    "Project Name": p_label,
                                    "End Date": e_date,
                                    "Department": t_name,
                                })

                except Exception as e:
                    st.error(f"Could not load data for {t_name}: {e}")
        st.markdown("---")

    # ------------------------------------------------------------------
    # Completed Projects Section
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
            start_date_filter = st.date_input("📅 End Date (From):", value=min_date, key="completed_start_date")
        with f_col3:
            end_date_filter = st.date_input("📅 End Date (To):", value=max_date, key="completed_end_date")

        if start_date_filter > end_date_filter:
            st.warning("⚠️ Start Date must be before or equal to End Date.")
            filtered_comp = pd.DataFrame(columns=["Project Manager", "Project Name", "End Date", "Department"])
        else:
            mask = (
                (comp_df["Department"].isin(selected_teams)) &
                (comp_df["End Date"] >= start_date_filter) &
                (comp_df["End Date"] <= end_date_filter)
            )
            filtered_comp = comp_df[mask].sort_values("End Date", ascending=False).reset_index(drop=True)

        metric_cols = st.columns(len(selected_teams) + 1)
        metric_cols[0].metric("📊 Total Completed", len(filtered_comp))
        for idx, t in enumerate(selected_teams):
            t_count = len(filtered_comp[filtered_comp["Department"] == t])
            metric_cols[idx + 1].metric(f"{t}", t_count)

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

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
                    filtered_comp[["Project Manager", "Project Name", "End Date", "Department"]],
                    use_container_width=True,
                    hide_index=True
                )

        for idx, t in enumerate(selected_teams):
            with comp_tabs[idx + 1]:
                t_sub = filtered_comp[filtered_comp["Department"] == t][["Project Manager", "Project Name", "End Date"]]
                if t_sub.empty:
                    st.info(f"No completed projects for {t} within the selected date range.")
                else:
                    st.dataframe(t_sub, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------
# Team selection
# ----------------------------------------------------------------------
selected_team = st.radio(
    "👥 Select View / Team:",
    [MAIN_OPTION] + list(TEAMS.keys()) + [ACTUAL_TEAM_OPTION],
    horizontal=True,
)

if selected_team == MAIN_OPTION:
    render_main_overview()
    st.stop()

if selected_team == ACTUAL_TEAM_OPTION:
    render_actual_team_view()
    st.stop()

team_cfg = TEAMS[selected_team]
team_mode = team_cfg["mode"]
disciplines = team_cfg["disciplines"]
sources = team_cfg["sources"]

# ----------------------------------------------------------------------
# 2e. Live Data Loading (Merged across PMs)
# ----------------------------------------------------------------------
st.markdown("---")

live_projects, live_eng_counts, load_errors = load_team_merged_data(team_cfg, MAX_ROWS)

if load_errors:
    st.warning(f"⚠️ Could not read some sheets for {selected_team}: {'; '.join(load_errors)}")

# Refresh & Direct Sheet Links
btn_cols = st.columns([1.2] + [1] * len(sources))
with btn_cols[0]:
    refresh_clicked = st.button("🔄 Refresh Sheets", use_container_width=True)

for idx, src in enumerate(sources):
    with btn_cols[idx + 1]:
        btn_label = f"🔗 {src['pm']}" if len(sources) > 1 else "🔗 Open Google Sheet"
        st.link_button(
            btn_label,
            f"https://docs.google.com/spreadsheets/d/{src['sheet_id']}/edit",
            use_container_width=True,
        )

if refresh_clicked:
    load_from_gsheet.clear()
    load_team_counts.clear()
    for d in disciplines:
        st.session_state.pop(f"eng_{selected_team}_{d}", None)
    st.rerun()

df_projects = live_projects
sheet_eng_counts = live_eng_counts
counts_source = "Hakem's Tech Team (Team count tab)" if team_cfg.get("count_source") else "Live Google Sheet"

# Optional PM filter inside the team view
if "Project Manager" in df_projects.columns and df_projects["Project Manager"].nunique() > 1:
    pm_options = sorted(df_projects["Project Manager"].dropna().unique().tolist())
    chosen_pms = st.multiselect(
        "👔 Filter by Project Manager:",
        options=pm_options,
        default=pm_options,
        key=f"pm_filter_{selected_team}",
    )
    df_projects = df_projects[df_projects["Project Manager"].isin(chosen_pms)].reset_index(drop=True)

st.success(
    f"🟢 **{selected_team}**: Merged Live Data from {len(sources)} sheet(s) "
    f"— {len(df_projects)} project rows loaded."
)

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
st.caption("Changes made in this table are temporary (for what-if analysis). To preserve changes, update Google Sheets.")

edited_df = st.data_editor(
    df_projects,
    key=f"editor_{selected_team}",
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)

# ----------------------------------------------------------------------
# 4a. Prepare hours column in background
# ----------------------------------------------------------------------
calc_df, count_col = prepare_calc_df(edited_df, team_mode, disciplines, hours_per_day)

bad_rows = calc_df[calc_df["Start Date"].isna() | calc_df["End Date"].isna()]
if not bad_rows.empty:
    st.warning(f"⚠️ {len(bad_rows)} row(s) have invalid dates and will not appear in the charts:")
    st.dataframe(bad_rows, use_container_width=True)

# ----------------------------------------------------------------------
# 4b. Project Timeline (Gantt Chart)
# ----------------------------------------------------------------------
st.markdown("---")
st.subheader("🗓️ Project Timeline (Gantt Chart)")

hide_completed = st.checkbox("Filter completed", value=False, key=f"hide_comp_{selected_team}")
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
