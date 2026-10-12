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

SHEET_ID = "1RUqihUZreld3OY9M2cuPWtpxtuCS9p-2ut0FCFFwFvQ"
SHEET_GID = None  # None = first tab. Or put the tab's gid number, e.g. 123456789
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
if SHEET_GID is not None:
    CSV_URL += f"&gid={SHEET_GID}"

DATA_COLS = ["Arch Tech (Hrs)", "Structural (Hrs)", "Plumbing (Hrs)", "HVAC (Hrs)", "Electrical (Hrs)"]

# Working week: Sunday to Thursday (Friday & Saturday are the weekend)
# numpy weekmask order is Mon Tue Wed Thu Fri Sat Sun
NP_WEEKMASK = "1111001"
PD_WEEKMASK = "Sun Mon Tue Wed Thu"
HOURS_PER_DAY = 8


# ----------------------------------------------------------------------
# 2. Load data from Google Sheet (read-only, refreshed every 60 seconds)
# ----------------------------------------------------------------------
def get_empty_template():
    return pd.DataFrame({
        "No.": [1],
        "Project / Contract Name": ["Example Project"],
        "Start Date": [datetime.date(2026, 9, 20)],
        "End Date": [datetime.date(2026, 10, 20)],
        "Arch Tech (Hrs)": [100.0],
        "Structural (Hrs)": [80.0],
        "Plumbing (Hrs)": [40.0],
        "HVAC (Hrs)": [40.0],
        "Electrical (Hrs)": [60.0],
    })


@st.cache_data(ttl=60, show_spinner="Loading data from Google Sheet...")
def load_from_gsheet(url):
    df = pd.read_csv(url)
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce").dt.date
    df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce").dt.date
    for c in DATA_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


col_a, col_b = st.columns([1, 3])
with col_a:
    if st.button("🔄 Refresh from Google Sheet", use_container_width=True):
        load_from_gsheet.clear()
        st.rerun()
with col_b:
    st.link_button("🔗 Open Google Sheet", f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")

try:
    df_projects = load_from_gsheet(CSV_URL)
    st.success("✅ Data loaded from Google Sheet.")
except Exception as e:
    df_projects = get_empty_template()
    st.error(
        f"Could not read the Google Sheet ({e}). Make sure sharing is set to "
        "'Anyone with the link: Viewer'. Showing template data instead."
    )

# ----------------------------------------------------------------------
# 3. Sidebar - Capacity Settings
# ----------------------------------------------------------------------
st.sidebar.header("⚙️ Team Capacity Settings")
st.sidebar.markdown("Set the number of available engineers:")

disciplines = ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"]
default_engineers = [16, 10, 5, 5, 12]
engineers = {}
capacities = {}  # daily capacity (hours per working day)
efficiency = st.sidebar.slider("Efficiency Factor (%)", 50, 100, 80) / 100.0

for disc, default in zip(disciplines, default_engineers):
    engineers[disc] = st.sidebar.number_input(f"{disc} Engineers", value=default, min_value=0)
    capacities[disc] = engineers[disc] * HOURS_PER_DAY * efficiency

# ----------------------------------------------------------------------
# 4. Project table (temporary edits only - not saved back to the sheet)
# ----------------------------------------------------------------------
st.subheader("📋 Project Register & Hours Allocation")
st.caption("Data comes from the Google Sheet. Changes made here are temporary (for what-if analysis) and are not saved. Edit the Google Sheet itself to update the data permanently.")

edited_df = st.data_editor(
    df_projects,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)

# ----------------------------------------------------------------------
# 5. Calculation Engine (daily, Sunday - Thursday)
# ----------------------------------------------------------------------
st.markdown("---")
st.subheader("🔥 Daily Bottleneck Analysis & Executive Dashboard")

col1, col2 = st.columns(2)
with col1:
    start_timeline = st.date_input("Timeline Start Date:", datetime.date(2026, 9, 20))
with col2:
    num_weeks = st.slider("Number of Weeks to Analyze:", 1, 12, 4)

num_days = num_weeks * 5
days = [d.date() for d in pd.bdate_range(start=start_timeline, periods=num_days, freq="C", weekmask=PD_WEEKMASK)]
day_labels = [d.strftime("%a %d-%b") for d in days]

demand = {disc: [0.0] * num_days for disc in disciplines}

for idx, row in edited_df.iterrows():
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
        st.markdown(f"### {disc} Team Analysis (Daily)")

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
