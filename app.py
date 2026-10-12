import streamlit as st
import pandas as pd
import numpy as np
import datetime
import io

# 1. Page Configuration
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 Dynamic Engineering Resource Planner - AKED")

st.info("💡 **Workflow Tip:** Upload your existing project CSV file to view the analysis. You can edit the data directly in the table below and then download the updated version to your computer for your next session.")

# 2. File Upload Functionality
uploaded_file = st.file_uploader("📂 Upload your Project Data (CSV format)", type=["csv"])

# Function to provide an empty template if no file is uploaded
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
        "Electrical (Hrs)": [60.0]
    })

# Load data from uploaded file or use template
if uploaded_file is not None:
    try:
        df_projects = pd.read_csv(uploaded_file)
        # Clean and parse dates
        df_projects['Start Date'] = pd.to_datetime(df_projects['Start Date'], errors='coerce').dt.date
        df_projects['End Date'] = pd.to_datetime(df_projects['End Date'], errors='coerce').dt.date
        st.success("✅ File uploaded successfully!")
    except Exception as e:
        st.error(f"Error reading file: {e}")
        df_projects = get_empty_template()
else:
    df_projects = get_empty_template()
    st.warning("⚠️ No file uploaded. Displaying template data. Please upload a CSV file or start editing below.")

# 3. Sidebar - Capacity Settings
st.sidebar.header("⚙️ Team Capacity Settings")
st.sidebar.markdown("Set the number of available engineers:")

disciplines = ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"]
default_engineers = [16, 10, 5, 5, 12]
engineers = {}
capacities = {}
efficiency = st.sidebar.slider("Efficiency Factor (%)", 50, 100, 80) / 100.0

for disc, default in zip(disciplines, default_engineers):
    col_name = f"{disc} (Hrs)" if disc != "Arch Tech" else "Arch Tech (Hrs)"
    engineers[disc] = st.sidebar.number_input(f"{disc} Engineers", value=default, min_value=0)
    capacities[disc] = engineers[disc] * 40 * efficiency

# 4. Data Editor (Editable Table)
st.subheader("📋 Project Register & Hours Allocation (Editable)")
st.markdown("You can edit the project details, add new rows, or delete existing ones directly in the table below.")

# Interactive table
edited_df = st.data_editor(
    df_projects,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True
)

# Function to convert df to csv for downloading
@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

csv_data = convert_df_to_csv(edited_df)

# Download button for the updated data
st.download_button(
    label="⬇️ Download Updated Project Data (CSV)",
    data=csv_data,
    file_name="Updated_Engineering_Resource_Data.csv",
    mime="text/csv",
    help="Click here to download your updated project list. You can upload this file next time you open the app."
)

# 5. Calculation Engine
st.markdown("---")
st.subheader("🔥 Bottleneck Analysis & Executive Dashboard")

col1, col2 = st.columns(2)
with col1:
    start_timeline = st.date_input("Timeline Start Date:", datetime.date(2026, 9, 20))
with col2:
    num_weeks = st.slider("Number of Weeks to Analyze:", 5, 20, 10)

weeks = [start_timeline + datetime.timedelta(days=7*i) for i in range(num_weeks)]
week_labels = [w.strftime("%d-%b") for w in weeks]

# Initialize demand dictionary for all disciplines
demand = {disc: [0.0] * num_weeks for disc in disciplines}

# High Precision Calculation Engine (Actual Working Days) based on EDITED data
for idx, row in edited_df.iterrows():
    if pd.isnull(row.get('Start Date')) or pd.isnull(row.get('End Date')):
        continue
        
    s_date = row['Start Date']
    e_date = row['End Date']
    
    # Calculate Total Working Days (Excluding Fri/Sat)
    workdays_total = np.busday_count(s_date, e_date + datetime.timedelta(days=1), weekmask='1111100')
    if workdays_total <= 0: continue

    for disc in disciplines:
        col_name = f"{disc} (Hrs)" if disc != "Arch Tech" else "Arch Tech (Hrs)"
        if col_name not in row or pd.isnull(row.get(col_name)):
            continue
            
        try:
            total_hrs = float(row[col_name])
        except ValueError:
            continue
            
        daily_rate = total_hrs / workdays_total
        
        for i, w_start in enumerate(weeks):
            w_end = w_start + datetime.timedelta(days=6)
            overlap_start = max(s_date, w_start)
            overlap_end = min(e_date, w_end)
            
            if overlap_start <= overlap_end:
                overlap_days = np.busday_count(overlap_start, overlap_end + datetime.timedelta(days=1), weekmask='1111100')
                demand[disc][i] += (daily_rate * overlap_days)

# 6. Display Charts and Tables (Tabs for each discipline)
tabs = st.tabs(disciplines)

def highlight_bottlenecks(val):
    if isinstance(val, (int, float)) and val < 0:
        return 'background-color: #ffcccc; color: #900000; font-weight: bold'
    return ''

for idx, disc in enumerate(disciplines):
    with tabs[idx]:
        st.markdown(f"### {disc} Team Analysis")
        
        results_df = pd.DataFrame({
            "Metric": ["Demand (Hrs)", "Capacity (Hrs)", "Variance (Shortage/Surplus)"],
        })
        
        var_list = []
        dem_list = []
        cap_list = []
        
        for i, w_label in enumerate(week_labels):
            dem = round(demand[disc][i], 1)
            cap = capacities[disc]
            var = round(cap - dem, 1)
            
            results_df[w_label] = [dem, cap, var]
            var_list.append(var)
            dem_list.append(dem)
            cap_list.append(cap)
            
        # Display Heatmap Table
        st.dataframe(results_df.style.map(highlight_bottlenecks, subset=week_labels), use_container_width=True)
        
        # Prepare Chart Data
        chart_data = pd.DataFrame({
            "Week": week_labels,
            "Variance (Shortage/Surplus)": var_list,
            "Demand": dem_list,
            "Capacity": cap_list
        })
        
        # --- التعديل هنا: إضافة عمود لتحديد اللون بناءً على القيمة ---
        chart_data["Color"] = np.where(chart_data["Variance (Shortage/Surplus)"] >= 0, "#2ca02c", "#d62728")
        
        # Display Interactive Charts
        st.markdown("#### 📉 Weekly Variance Chart (Dips below 0 indicate bottlenecks)")
        # استخدام المتغيرات x و y و color للتحكم الدقيق بالرسم
        st.bar_chart(chart_data, x="Week", y="Variance (Shortage/Surplus)", color="Color") 
        
        st.markdown("#### 📈 Demand vs Capacity Trend")
        # استرجاع Week كـ Index لتعمل رسمة الخطوط بشكل صحيح كما في نسختك
        st.line_chart(chart_data.set_index("Week")[["Demand", "Capacity"]])
