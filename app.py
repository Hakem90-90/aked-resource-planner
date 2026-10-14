import streamlit as st
import pandas as pd
import numpy as np
import datetime
import altair as alt

# ----------------------------------------------------------------------
# 1. Page Configuration
# ----------------------------------------------------------------------
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 Dynamic Engineering Resource Planner - ACKD")

# ----- Teams: each team has its own Google Sheet and default number of engineers -----
# mode "hours"      : the sheet has one hours column per discipline, e.g. "Arch Tech (Hrs)"
# mode "team_count" : the sheet has a "Team Count" column; hours are calculated automatically as
#                     Team Count x Working Days (Sun-Thu) x Working Hours per Day
# engineers: default number of engineers per discipline (same order as "disciplines")
# gid: None = first tab, or put the tab's gid number (the value after gid= in the sheet URL)
TEAMS = {
    "Tech Team": {
        "sheet_id": "1RUqihUZreld3OY9M2cuPWtpxtuCS9p-2ut0FCFFwFvQ",
        "gid": None,
        "mode": "hours",
        "disciplines": ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"],
        "engineers": [16, 10, 5, 5, 12],  # Fallback defaults if not found in sheet
    },
    "Design Team": {
        "sheet_id": "15AR4hB_q1JZ1SIwegy2ieusDkPQAMSXFG5uG7Y2zaFg",
        "gid": None,
        "mode": "team_count",
        "disciplines": ["Arch Design Team"],
        "engineers": [10],
    },
}


def build_csv_url(sheet_id, gid=None):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid is not None:
        url += f"&gid={gid}"
    return url


DATA_COLS = ["Arch Tech (Hrs)", "Structural (Hrs)", "Plumbing (Hrs)", "HVAC (Hrs)", "Electrical (Hrs)"]

# Working week: Sunday to Thursday (Friday & Saturday are the weekend)
# numpy weekmask order is Mon Tue Wed Thu Fri Sat Sun
NP_WEEKMASK = "1111001"
PD_WEEKMASK = "Sun Mon Tue Wed Thu"
HOURS_PER_DAY = 8


# ----------------------------------------------------------------------
# 2. Load data from Google Sheet (read-only, refreshed every 60 seconds)
# ----------------------------------------------------------------------
def get_empty_template(mode="hours"):
    today = datetime.date.today()
    if mode == "team_count":
        return pd.DataFrame({
            "No.": [1],
            "Project Name": ["Example Project"],
            "Start Date": [today],
            "End Date": [today + datetime.timedelta(days=30)],
            "Team Count": [2],
        })
    return pd.DataFrame({
        "No.": [1],
        "Project / Contract Name": ["Example Project"],
        "Start Date": [today],
        "End Date": [today + datetime.timedelta(days=30)],
        "Arch Tech (Hrs)": [100.0],
        "Structural (Hrs)": [80.0],
        "Plumbing (Hrs)": [40.0],
        "HVAC (Hrs)": [40.0],
        "Electrical (Hrs)": [60.0],
    })


def match_discipline_name(raw_name, disciplines):
    """يربط اسم التخصص في جدول الإكسيل باسم التخصص المعتمد في الكود"""
    raw_low = str(raw_name).strip().lower()
    for d in disciplines:
        d_low = d.lower()
        if d_low in raw_low or raw_low in d_low:
            return d
        if "arch" in raw_low and "arch" in d_low:
            return d
        if "struct" in raw_low and "struct" in d_low:
            return d
        if "plumb" in raw_low and "plumb" in d_low:
            return d
        if "hvac" in raw_low and "hvac" in d_low:
            return d
        if "elec" in raw_low and "elec" in d_low:
            return d
    return None


@st.cache_data(ttl=60, show_spinner="Loading data from Google Sheet...")
def load_from_gsheet(url, disciplines):
    raw_df = pd.read_csv(url)
    raw_df.columns = raw_df.columns.astype(str).str.strip()
    raw_df = raw_df.loc[:, ~raw_df.columns.str.startswith("Unnamed")]

    eng_counts = {}

    # الحالة 1: جدول المهندسين موجود كأعمدة جانبية (مثلاً Discipline / Team و No. of Engineers في الصف الأول)
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
            # إذا لم يتعرف على اسم عمود الأعداد، يأخذ العمود المجاور لعمود التخصص مباشرة
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

        # حذف أعمدة جدول المهندسين من جدول المشاريع حتى لا تظهر في جدول المشاريع
        cols_to_drop = [c for c in [disc_col_name, eng_col_name] if c is not None and c in raw_df.columns]
        df = raw_df.drop(columns=cols_to_drop).copy()

    else:
        # الحالة 2 (احتياطية): إذا كان جدول المهندسين موجوداً في أسفل الشيت تحت المشاريع
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
        if c in DATA_COLS or "count" in c.lower():
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df, eng_counts


selected_team = st.radio("👥 Select Team:", list(TEAMS.keys()), horizontal=True)
team_cfg = TEAMS[selected_team]
team_mode = team_cfg["mode"]
disciplines = team_cfg["disciplines"]
SHEET_ID = team_cfg["sheet_id"]
CSV_URL = build_csv_url(SHEET_ID, team_cfg["gid"])

col_a, col_b = st.columns([1, 3])
with col_a:
    if st.button("🔄 Refresh from Google Sheet", use_container_width=True):
        load_from_gsheet.clear()
        for d in disciplines:
            st.session_state.pop(f"eng_{selected_team}_{d}", None)
        st.rerun()
with col_b:
    st.link_button("🔗 Open Google Sheet", f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")

try:
    df_projects, sheet_eng_counts = load_from_gsheet(CSV_URL, disciplines)
    st.success(f"✅ {selected_team}: data loaded from Google Sheet.")
except Exception as e:
    df_projects = get_empty_template(team_mode)
    sheet_eng_counts = {}
    st.error(
        f"Could not read the {selected_team} Google Sheet ({e}). Make sure sharing is set to "
        "'Anyone with the link: Viewer'. Showing template data instead."
    )

# ----------------------------------------------------------------------
# 3. Sidebar - Capacity Settings
# ----------------------------------------------------------------------
st.sidebar.header("⚙️ Team Capacity Settings")
st.sidebar.caption(f"Team: **{selected_team}**")
hours_per_day = st.sidebar.number_input(
    "Working Hours per Day (per engineer)",
    min_value=1.0, max_value=12.0, value=float(HOURS_PER_DAY), step=0.5,
    help="Daily capacity = Engineers × Hours per Day × Efficiency Factor. "
         "For teams that use Team Count, hours are also calculated as Team Count × Working Days × Hours per Day.",
)
st.sidebar.markdown("Set the number of available engineers:")

# استخدام أعداد المهندسين القادمة من الشيت (أو القيم الافتراضية في حال عدم وجودها)
default_engineers = [
    sheet_eng_counts.get(disc, fallback)
    for disc, fallback in zip(disciplines, team_cfg["engineers"])
]

engineers = {}
capacities = {}  # daily capacity (hours per working day)
efficiency = st.sidebar.slider("Efficiency Factor (%)", 50, 100, 80) / 100.0

for disc, default in zip(disciplines, default_engineers):
    engineers[disc] = st.sidebar.number_input(
        f"{disc} Engineers", value=int(default), min_value=0, key=f"eng_{selected_team}_{disc}"
    )
    capacities[disc] = engineers[disc] * hours_per_day * efficiency

# ----------------------------------------------------------------------
# 4. Project table (temporary edits only - not saved back to the sheet)
# ----------------------------------------------------------------------
st.subheader("📋 Project Register & Hours Allocation")
st.caption("Data comes from the Google Sheet. Changes made here are temporary (for what-if analysis) and are not saved. Edit the Google Sheet itself to update the data permanently.")

edited_df = st.data_editor(
    df_projects,
    key=f"editor_{selected_team}",
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)

# ----------------------------------------------------------------------
# 4a. Calculated hours (only for teams that use "Team Count")
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


if team_mode == "team_count":
    count_col = find_count_col(calc_df)
    if count_col is None:
        st.error(
            "Could not find a 'Team Count' column in the sheet. "
            f"Columns found: {list(calc_df.columns)}"
        )
        st.stop()

    hrs_col_name = f"{disciplines[0]} (Hrs)"
    calc_df[count_col] = pd.to_numeric(calc_df[count_col], errors="coerce")

    work_days = []
    for s_d, e_d in zip(calc_df["Start Date"], calc_df["End Date"]):
        if pd.isnull(s_d) or pd.isnull(e_d):
            work_days.append(0)
        else:
            work_days.append(max(0, int(np.busday_count(s_d, e_d + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))))
    calc_df["Working Days (Sun-Thu)"] = work_days
    calc_df[hrs_col_name] = (calc_df[count_col].fillna(0) * calc_df["Working Days (Sun-Thu)"] * hours_per_day)

    st.markdown(f"##### 🧮 Calculated Hours: {count_col} × Working Days (Sun-Thu) × {hours_per_day:g} hrs/day")
    st.dataframe(calc_df, use_container_width=True, hide_index=True)
    st.caption(f"Total calculated hours for all projects: **{calc_df[hrs_col_name].sum():,.1f}**")

# ----------------------------------------------------------------------
# 4b. Project Timeline (Gantt Chart) - updates automatically from the table
# ----------------------------------------------------------------------
st.markdown("---")
st.subheader("🗓️ Project Timeline (Gantt Chart)")

def find_name_col(df):
    """Find the project-name column even if the header text differs slightly."""
    skip = {"No.", "Start Date", "End Date"} | set(DATA_COLS)
    for c in df.columns:
        low = str(c).lower()
        if c not in skip and any(k in low for k in ("name", "project", "contract")):
            return c
    for c in df.columns:  # fallback: first text column
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

if gantt_df.empty:
    st.info("No projects with valid start and end dates to display.")
else:
    hrs_cols = [f"{d} (Hrs)" for d in disciplines if f"{d} (Hrs)" in gantt_df.columns]
    gantt_df["Project"] = gantt_df.apply(make_project_label, axis=1)
    gantt_df["EndPlus"] = gantt_df["End"] + pd.Timedelta(days=1)  # include the end day in the bar
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

    # Pad the right side of the axis so the date labels next to the last bars are not cut off
    x_min = gantt_df["Start"].min() - pd.Timedelta(days=2)
    span_days = (gantt_df["EndPlus"].max() - gantt_df["Start"].min()).days
    x_max = gantt_df["EndPlus"].max() + pd.Timedelta(days=max(14, int(span_days * 0.25)))
    x_scale = alt.Scale(domain=[x_min.isoformat(), x_max.isoformat()])

    extra_tooltips = []
    if team_mode == "team_count":
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

    # Start - End dates written right next to each bar
    date_labels = alt.Chart(gantt_df).mark_text(
        align="left", baseline="middle", dx=6, fontSize=11
    ).encode(
        y=alt.Y("Project:N", sort=project_order),
        x=alt.X("EndPlus:T", scale=x_scale),
        text="DateRange:N",
    )

    layers = [bars, date_labels]

    # Red dashed line for today (only if it falls inside the projects' date range)
    today = pd.Timestamp.today().normalize()
    if gantt_df["Start"].min() <= today <= gantt_df["EndPlus"].max():
        today_rule = alt.Chart(pd.DataFrame({"Today": [today]})).mark_rule(
            color="red", strokeDash=[5, 4], strokeWidth=2
        ).encode(x=alt.X("Today:T", scale=x_scale))
        layers.append(today_rule)

    gantt_chart = alt.layer(*layers).properties(height=max(150, 34 * len(gantt_df) + 60))
    st.altair_chart(gantt_chart, use_container_width=True)
    st.caption("Projects are sorted by start date. The red dashed line marks today. Hover over a bar for details.")

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

    # Total working days of the project (Sun-Thu only)
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

        # Bottleneck summary
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
