import os
import glob
import datetime
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

    if gantt_df["Project"].duplicated().any():
        seen = {}
        unique_labels = []
        for p in gantt_df["Project"]:
            count = seen.get(p, 0) + 1
            seen[p] = count
            unique_labels.append(f"{p} ({count})" if count > 1 else p)
        gantt_df["Project"] = unique_labels

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

    bars = alt.Chart(gantt_df).mark_bar(cornerRadius=3).encode(
        y=alt.Y("Project:N", sort=project_order, title=None, axis=alt.Axis(labelLimit=250)),
        x=alt.X("Start:T", scale=x_scale, title="Date", axis=alt.Axis(format="%d-%b", labelAngle=-45)),
        x2="EndPlus:T",
        color=alt.Color("Project:N", legend=None),
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

    col_f1, col_f2 = st.columns([2, 2])
    with col_f1:
        hide_comp = st.checkbox("Filter completed", value=False, key="main_hide_comp")
    with col_f2:
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
                    csv_url = build_csv_url(cfg["sheet_id"], cfg["gid"])
                    team_df, team_counts = load_from_gsheet(csv_url, cfg["disciplines"])

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
                                    "Project Name": p_label,
                                    "End Date": e_date,
                                    "Department": t_name,
                                })

                except Exception as e:
                    st.error(f"Could not load data for {t_name}: {e}")
        st.markdown("---")

    # Completed Projects Section
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
    "👥 Select View / Team:", [MAIN_OPTION] + list(TEAMS.keys()), horizontal=True
)

if selected_team == MAIN_OPTION:
    render_main_overview()
    st.stop()

team_cfg = TEAMS[selected_team]
team_mode = team_cfg["mode"]
disciplines = team_cfg["disciplines"]
SHEET_ID = team_cfg["sheet_id"]
CSV_URL = build_csv_url(SHEET_ID, team_cfg["gid"])

# ----------------------------------------------------------------------
# Data Loading & Controls
# ----------------------------------------------------------------------
st.markdown("---")

live_projects = None
live_eng_counts = {}
try:
    live_projects, live_eng_counts = load_from_gsheet(CSV_URL, disciplines)
    if team_cfg.get("count_sheet") or team_cfg.get("count_gid") is not None:
        if team_cfg.get("count_gid") is not None:
            c_url = build_csv_url
