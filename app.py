
# app.py
# PESONet & InstaPay Dashboard
# Streamlit app to visualize monthly, quarterly, annual, YTM/YTD metrics
# with: (a) month/year pickers, (b) selected-filter totals first,
# (c) humanized numbers (one decimal, Million/Billion/Trillion, ₱ retained),
# (d) tables with comma separators and Period as Jan-YYYY.

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# =========================
# App config
# =========================
st.set_page_config(page_title="PESONet & InstaPay Dashboard", layout="wide")
st.title("PESONet & InstaPay Dashboard")
st.caption("v1.3 • month/year pickers • humanized KPIs • formatted tables")

DATA_FILE = "PN and IP Database.xlsx"  # keep the file in the repo root


# =========================
# Helpers
# =========================
@st.cache_data
def _load_excel(file_path: str) -> Dict[str, pd.DataFrame]:
    """
    Loads both sheets (e.g., PESONet, InstaPay) and returns a dict of cleaned DataFrames.
    Expected columns: Period, Volume, Value, %Change in Vol, %Change in Val, Last12MTH, Quarter
    """
    p = Path(file_path)
    if not p.exists():
        # Streamlit Cloud pattern: relative to app file
        p = Path(__file__).parent / file_path

    xls = pd.ExcelFile(p, engine="openpyxl")
    out = {}

    for sheet in xls.sheet_names:
        df = pd.read_excel(p, sheet_name=sheet, engine="openpyxl")

        # Standardize column names
        df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]

        # Keep expected columns if present
        keep = [
            c for c in [
                "Period", "Volume", "Value",
                "%Change in Vol", "%Change in Val",
                "Last12MTH", "Quarter"
            ] if c in df.columns
        ]
        df = df[keep].copy()

        # Parse dates
        if "Period" in df.columns:
            df["Period"] = pd.to_datetime(df["Period"], errors="coerce")

        # Coerce numerics
        for c in ["Volume", "Value", "%Change in Vol", "%Change in Val", "Last12MTH"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # Clean Quarter text to 'YYYY-Q#'
        if "Quarter" in df.columns:
            df["Quarter"] = (
                df["Quarter"]
                .astype(str)
                .str.extract(r"((?:19|20)\d{2}\-Q[1-4])", expand=False)
            )

        # Derive convenience fields
        if "Period" in df.columns:
            df["Year"] = df["Period"].dt.year
            df["Month"] = df["Period"].dt.month
            df["MonthName"] = df["Period"].dt.strftime("%b")
            df["YearMonth"] = df["Period"].dt.to_period("M").dt.to_timestamp()
            df["YearQ"] = df["Period"].dt.to_period("Q").astype(str)  # e.g., '2024Q1'
            df["YearQ"] = df["YearQ"].str.replace("Q", "-Q", regex=False)  # '2024-Q1'

        out[sheet] = df.sort_values("Period")

    return out


def _humanize(x: float | int, is_money: bool = False) -> str:
    """
    Formats a number with at least one decimal and suffix:
      - < 1,000,000: 12,345.7
      - >= 1M: 1.1 Million
      - >= 1B: 1.1 Billion
      - >= 1T: 1.1 Trillion
    Always keeps '₱' for money.
    """
    if x is None or pd.isna(x):
        return "—"

    absx = abs(x)
    sign = "-" if x < 0 else ""
    trillion = 1_000_000_000_000
    billion  = 1_000_000_000
    million  = 1_000_000

    if absx >= trillion:
        num = absx / trillion
        text = f"{sign}{num:,.1f} Trillion"
    elif absx >= billion:
        num = absx / billion
        text = f"{sign}{num:,.1f} Billion"
    elif absx >= million:
        num = absx / million
        text = f"{sign}{num:,.1f} Million"
    else:
        text = f"{sign}{absx:,.1f}"

    return f"₱{text}" if is_money else text


def _agg_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["YearQ"], as_index=False).agg({"Volume": "sum", "Value": "sum"})
    yq = g["YearQ"].str.extract(r"((\d{4})\-Q([1-4]))")
    g["Year"] = yq[1].astype(int)
    g["Qtr"] = yq[2].astype(int)
    return g.sort_values(["Year", "Qtr"])


def _agg_annual(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["Year"], as_index=False).agg({"Volume": "sum", "Value": "sum"})
    return g.sort_values("Year")


def _ytm(df: pd.DataFrame, end_ts: pd.Timestamp) -> Tuple[float, float]:
    """
    YTM (Year-to-Month): Jan..end_month of end_ts within end_ts.year.
    Returns (vol_sum, val_sum).
    """
    m_end = end_ts.month
    y_end = end_ts.year
    d = df[(df["Year"] == y_end) & (df["Month"] <= m_end)]
    return d["Volume"].sum(), d["Value"].sum()


def _ytd(df: pd.DataFrame, end_ts: pd.Timestamp) -> Tuple[float, float]:
    # Same range as YTM at monthly granularity (kept separate for clarity)
    return _ytm(df, end_ts)


def _safe_pct(new: float, base: float) -> float | None:
    if base is None or base == 0 or pd.isna(base):
        return None
    return (new - base) / base


def _filter_controls(df_for_series: pd.DataFrame, key_prefix: str = "") -> pd.DataFrame:
    """
    Returns a filtered DataFrame based on sidebar controls.
      Mode A: Range (min..max month) + optional months-of-year
      Mode B: Pick months & years (explicit)
    """
    st.sidebar.header("Controls")

    min_d = df_for_series["Period"].min()
    max_d = df_for_series["Period"].max()

    mode = st.sidebar.radio(
        "Filter mode",
        options=["Range", "Pick months & years"],
        index=0,
        key=f"{key_prefix}_mode",
        help="Choose a continuous date range or explicitly pick year(s) and month(s).",
    )

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    m2num = {m:i+1 for i,m in enumerate(months)}

    if mode == "Range":
        st.sidebar.caption("**Select month range**")
        start, end = st.sidebar.slider(
            "Period",
            min_value=min_d.to_pydatetime(),
            max_value=max_d.to_pydatetime(),
            value=(min_d.to_pydatetime(), max_d.to_pydatetime()),
            format="YYYY-MM",
            key=f"{key_prefix}_range",
        )
        allowed_months = st.sidebar.multiselect(
            "Months (optional)",
            options=months,
            default=months,
            key=f"{key_prefix}_months_optional",
        )
        allowed_month_nums = {m2num[m] for m in allowed_months}

        d = df_for_series[
            (df_for_series["Period"] >= pd.to_datetime(start)) &
            (df_for_series["Period"] <= pd.to_datetime(end))
        ]
        d = d[d["Month"].isin(allowed_month_nums)]
        return d

    else:
        years = sorted(df_for_series["Year"].dropna().unique().tolist())
        sel_years = st.sidebar.multiselect(
            "Year(s)",
            options=years,
            default=years[-1:],  # latest year by default
            key=f"{key_prefix}_years",
        )
        sel_months = st.sidebar.multiselect(
            "Month(s)",
            options=months,
            default=months,  # all months by default
            key=f"{key_prefix}_months",
            help="Pick specific month(s) to include. Use with Year(s) above.",
        )
        allowed_month_nums = {m2num[m] for m in sel_months}

        d = df_for_series[df_for_series["Year"].isin(sel_years)]
        d = d[d["Month"].isin(allowed_month_nums)]
        return d


def _dual_axis_chart(df: pd.DataFrame, title: str = "") -> go.Figure:
    """
    Left axis: Volume; Right axis: Value
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=df["Period"], y=df["Volume"], mode="lines+markers",
            name="Volume", line=dict(color="#1f77b4"),
            hovertemplate="%{x|%Y-%m} • Volume: %{y:,.1f}<extra></extra>"
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df["Period"], y=df["Value"], mode="lines+markers",
            name="Value (₱)", line=dict(color="#ff7f0e"),
            hovertemplate="%{x|%Y-%m} • Value: ₱%{y:,.1f}<extra></extra>"
        ),
        secondary_y=True,
    )
    fig.update_layout(
        title=title,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Volume (count)", secondary_y=False, rangemode="tozero")
    fig.update_yaxes(title_text="Value (₱)", secondary_y=True, rangemode="tozero")
    return fig


# =========================
# Load data
# =========================
data = _load_excel(DATA_FILE)

if not data:
    st.error("Could not load any data from the Excel file.")
    st.stop()

AVAILABLE_SERIES = list(data.keys())  # e.g., ["PESONet", "InstaPay"]


# =========================
# Sidebar - choose series first
# =========================
series = st.sidebar.radio("Payment stream", options=AVAILABLE_SERIES, index=0, key="series_choice")
df0 = data[series].copy()

if df0.empty:
    st.warning("The selected series has no rows.")
    st.stop()

# Apply filter controls
df = _filter_controls(df0, key_prefix=series)

if df.empty:
    st.info("No data for the chosen filters.")
    st.stop()

st.divider()


# =========================
# KPIs — FIRST: Selected filter totals (as requested)
# =========================
sel_vol = df["Volume"].sum()
sel_val = df["Value"].sum()

k0a, k0b = st.columns(2)
k0a.metric(f"{series} • Volume (Selected Filter)", _humanize(sel_vol),
           help="Sum of Volume for the exact months/years you selected.")
k0b.metric(f"{series} • Value (Selected Filter)", _humanize(sel_val, is_money=True),
           help="Sum of Value (₱) for the exact months/years you selected.")

st.divider()


# =========================
# Additional KPIs (context)
# =========================
latest_period = df["Period"].max()

# YTM & YTD use the full series reference
ytm_vol, ytm_val = _ytm(df0, latest_period)
prev_ref = latest_period.replace(year=latest_period.year - 1)
ytm_prev_vol, ytm_prev_val = _ytm(df0, prev_ref)

ytm_vol_yoy = _safe_pct(ytm_vol, ytm_prev_vol)
ytm_val_yoy = _safe_pct(ytm_val, ytm_prev_val)

ytd_vol, ytd_val = _ytd(df0, latest_period)

q_agg = _agg_quarterly(df0)
a_agg = _agg_annual(df0)

if not q_agg.empty:
    last_q = q_agg.iloc[-1]
    q_vol, q_val = last_q["Volume"], last_q["Value"]
    if len(q_agg) >= 2:
        prev_q = q_agg.iloc[-2]
        q_vol_qoq = _safe_pct(q_vol, prev_q["Volume"])
        q_val_qoq = _safe_pct(q_val, prev_q["Value"])
