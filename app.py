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
            col = next((c for
