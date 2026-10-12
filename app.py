import streamlit as st
import pandas as pd
import numpy as np
import datetime
import io
import altair as alt

# 1. Page Configuration
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 Dynamic Engineering Resource Planner - AKED")

st.info("💡 **Workflow Tip:** Upload your existing project CSV file to view the analysis. You can edit the data directly in the table below and then download the updated version to your computer for your next session.")

# 2. File Upload Functionality
uploaded_file = st.file_uploader("📂 Upload your Project Data (CSV format)", type=["csv"])

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
    engineers[disc] = st.sidebar.number_input(f"{disc} Engineers", value=default, min_value=0)
    capacities[disc] = engineers[disc] * 40 * efficiency

# 4. Data Editor (Editable Table)
st.subheader("📋 Project Register & Hours Allocation (Editable)")
st.markdown("You can edit the project details, add new rows, or delete existing ones directly in the table below.")

edited_df = st.data_editor(
    df_projects,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True
)

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

csv_data = convert_df_to_csv(edited_df)

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
week_labels_str = [w.strftime("%d-%b") for w in weeks] 

# Initialize demand dictionary for all disciplines
demand = {disc: [0.0] * num_weeks for disc in disciplines}

# High Precision Calculation Engine (Actual Working Days) based on EDITED data
for idx, row in edited_df.iterrows():
    if pd.isnull(row.get('Start Date')) or pd.isnull(row.get('End Date')):
        continue
        
    s_date = row
