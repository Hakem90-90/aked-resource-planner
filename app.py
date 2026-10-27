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
        "mode": "team_count
