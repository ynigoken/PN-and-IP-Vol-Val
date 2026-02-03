# app.py
# PESONet & InstaPay Dashboard
# Streamlit app to visualize monthly, quarterly, annual, YTM, and YTD metrics
# for Volume and Value using "PN and IP Database.xlsx".

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
st.caption("v1 • built for PN & IP Database")

DATA_FILE = "PN and IP Database.xlsx"  # keep the file in the repo root


# =========================
# Helpers
# =========================
@st.cache_data
def _load_excel(file_path: str) -> Dict[str, pd.DataFrame]:
    """
    Loads both sheets (PESONet, InstaPay) and returns a dict of cleaned DataFrames.
    Expected columns: Period, Volume, Value, %Change in Vol, %Change in Val, Last12MTH, Quarter
    """
    p = Path(file_path)
    if not p.exists():
        # common Streamlit Cloud pattern: relative to app file location
        p = Path(__file__).parent / file_path

    xls = pd.ExcelFile(p, engine="openpyxl")
    out = {}

    for sheet in xls.sheet_names:
        df = pd.read_excel(p, sheet_name=sheet, engine="openpyxl")
        # Standardize column names
        df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]

        # Only keep expected columns if present
        keep = [c for c in ["Period", "Volume", "Value", "%Change in Vol", "%Change in Val", "Last12MTH", "Quarter"] if c in df.columns]
        df = df[keep].copy()

        # Parse dates
        if "Period" in df.columns:
            df["Period"] = pd.to_datetime(df["Period"], errors="coerce")

        # Coerce numerics
        for c in ["Volume", "Value", "%Change in Vol", "%Change in Val", "Last12MTH"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # Clean Quarter text (extract YYYY-Q#)
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
            # Make YearQ consistent with 'YYYY-Q#' style
            df["YearQ"] = df["YearQ"].str.replace("Q", "-Q", regex=False)

        out[sheet] = df.sort_values("Period")

    return out


def _format_num(x: float | int, is_money: bool = False) -> str:
    if pd.isna(x):
        return "—"
    if is_money:
        # Philippine peso style with thousands separator; no currency symbol in chart labels to keep clean
        return f"₱{x:,.0f}"
    return f"{x:,.0f}"


def _agg_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["YearQ"], as_index=False).agg({"Volume": "sum", "Value": "sum"})
    # Also keep Year and quarter number for sorting and display
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
    """
    YTD: Jan..end_date (same as YTM at month granularity; kept separate for clarity).
    """
    return _ytm(df, end_ts)


def _safe_pct(new: float, base: float) -> float | None:
    if base is None or base == 0 or pd.isna(base):
        return None
    return (new - base) / base


def _month_range_slider(df: pd.DataFrame, key_prefix: str = "") -> Tuple[pd.Timestamp, pd.Timestamp]:
    min_d = df["Period"].min()
    max_d = df["Period"].max()
    st.sidebar.caption("**Select month range**")
    start, end = st.sidebar.slider(
        "Period",
        min_value=min_d.to_pydatetime(),
        max_value=max_d.to_pydatetime(),
        value=(min_d.to_pydatetime(), max_d.to_pydatetime()),
        format="YYYY-MM",
        key=f"{key_prefix}_range",
    )
    return pd.to_datetime(start), pd.to_datetime(end)


def _months_of_year_multiselect() -> set[int]:
    st.sidebar.caption("**Optionally filter by months of the year**")
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    chosen = st.sidebar.multiselect(
        "Months (optional)",
        options=months,
        default=months,
    )
    m2num = {m:i+1 for i,m in enumerate(months)}
    return {m2num[m] for m in chosen}


def _dual_axis_chart(df: pd.DataFrame, title: str = "") -> go.Figure:
    """
    Left axis: Volume; Right axis: Value
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=df["Period"], y=df["Volume"], mode="lines+markers",
            name="Volume", line=dict(color="#1f77b4"), hovertemplate="%{x|%Y-%m} • Volume: %{y:,}<extra></extra>"
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df["Period"], y=df["Value"], mode="lines+markers",
            name="Value (₱)", line=dict(color="#ff7f0e"), hovertemplate="%{x|%Y-%m} • Value: ₱%{y:,.0f}<extra></extra>"
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
# Sidebar controls
# =========================
st.sidebar.header("Controls")

series = st.sidebar.radio("Payment stream", options=AVAILABLE_SERIES, index=0)
df0 = data[series].copy()

if df0.empty:
    st.warning("The selected series has no rows.")
    st.stop()

# Month range slider and Month-of-year multiselect
start_ts, end_ts = _month_range_slider(df0, key_prefix=series)
allowed_months = _months_of_year_multiselect()

# Apply filters
df = df0[(df0["Period"] >= start_ts) & (df0["Period"] <= end_ts)]
df = df[df["Month"].isin(allowed_months)]

if df.empty:
    st.info("No data for the chosen filters.")
    st.stop()

st.divider()


# =========================
# KPIs
# =========================
latest_period = df["Period"].max()

# Selected window totals
sel_vol = df["Volume"].sum()
sel_val = df["Value"].sum()

# YTM (current year to selected month)
ytm_vol, ytm_val = _ytm(df0, latest_period)

# YTM (previous year to the same month) for YoY
prev_ref = latest_period.replace(year=latest_period.year - 1)
ytm_prev_vol, ytm_prev_val = _ytm(df0, prev_ref)

ytm_vol_yoy = _safe_pct(ytm_vol, ytm_prev_vol)
ytm_val_yoy = _safe_pct(ytm_val, ytm_prev_val)

# YTD (same as YTM at monthly granularity; separated for explicit display)
ytd_vol, ytd_val = _ytd(df0, latest_period)

# Latest quarter and annual context (based on full dataset, not only filtered range)
q_agg = _agg_quarterly(df0)
a_agg = _agg_annual(df0)

if not q_agg.empty:
    last_q = q_agg.iloc[-1]
    q_vol, q_val = last_q["Volume"], last_q["Value"]
    if len(q_agg) >= 2:
        prev_q = q_agg.iloc[-2]
        q_vol_qoq = _safe_pct(q_vol, prev_q["Volume"])
        q_val_qoq = _safe_pct(q_val, prev_q["Value"])
    else:
        q_vol_qoq = q_val_qoq = None
else:
    q_vol = q_val = q_vol_qoq = q_val_qoq = None

if not a_agg.empty:
    last_a = a_agg.iloc[-1]
    a_vol, a_val = last_a["Volume"], last_a["Value"]
    if len(a_agg) >= 2:
        prev_a = a_agg.iloc[-2]
        a_vol_yoy = _safe_pct(a_vol, prev_a["Volume"])
        a_val_yoy = _safe_pct(a_val, prev_a["Value"])
    else:
        a_vol_yoy = a_val_yoy = None
else:
    a_vol = a_val = a_vol_yoy = a_val_yoy = None

# KPI layout
k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Selected Window Volume ({series})", _format_num(sel_vol), help="Sum of Volume within the selected month range.")
k2.metric(f"Selected Window Value ({series})", _format_num(sel_val, is_money=True), help="Sum of Value within the selected month range.")
k3.metric(f"YTM {latest_period.strftime('%Y-%m')} Volume", _format_num(ytm_vol), f"{'' if ytm_vol_yoy is None else f'{ytm_vol_yoy*100:,.1f}% YoY'}", help="Jan..selected month of current year vs same months last year.")
k4.metric(f"YTM {latest_period.strftime('%Y-%m')} Value", _format_num(ytm_val, is_money=True), f"{'' if ytm_val_yoy is None else f'{ytm_val_yoy*100:,.1f}% YoY'}", help="Jan..selected month of current year vs same months last year.")

k5, k6, k7, k8 = st.columns(4)
k5.metric("Latest Quarter Volume", _format_num(q_vol), f"{'' if q_vol_qoq is None else f'{q_vol_qoq*100:,.1f}% QoQ'}")
k6.metric("Latest Quarter Value", _format_num(q_val, is_money=True), f"{'' if q_val_qoq is None else f'{q_val_qoq*100:,.1f}% QoQ'}")
k7.metric("Latest Year Volume", _format_num(a_vol), f"{'' if a_vol_yoy is None else f'{a_vol_yoy*100:,.1f}% YoY'}")
k8.metric("Latest Year Value", _format_num(a_val, is_money=True), f"{'' if a_val_yoy is None else f'{a_val_yoy*100:,.1f}% YoY'}")

with st.expander("Definitions"):
    st.markdown(
        """
- **Quarterly**: Sum of monthly Volume/Value per calendar quarter  
- **Annual**: Sum of monthly Volume/Value per calendar year  
- **YTM (Year-to-Month)**: From **January** to the **selected month** of the **current year**, with YoY vs the same Jan–month range last year  
- **YTD (Year-to-Date)**: Same range as YTM at monthly granularity (shown here explicitly)
        """
    )

st.divider()


# =========================
# Chart
# =========================
st.subheader(f"Monthly Trend — {series}")
fig = _dual_axis_chart(df, title=f"{series} Volume & Value")
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# =========================
# Aggregations
# =========================
tab_monthly, tab_quarterly, tab_annual, tab_ytm_ytd = st.tabs(["Monthly (filtered)", "Quarterly", "Annual", "YTM & YTD"])

with tab_monthly:
    show_cols = ["Period", "Volume", "Value"]
    t = df[show_cols].copy()
    t["Period"] = t["Period"].dt.strftime("%Y-%m")
    st.dataframe(
        t,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Volume": st.column_config.NumberColumn(format="%,d"),
            "Value": st.column_config.NumberColumn(format="₱%,.0f"),
        },
        height=420,
    )

    csv = t.to_csv(index=False).encode("utf-8")
    st.download_button("Download monthly (CSV)", data=csv, file_name=f"{series}_monthly_filtered.csv", mime="text/csv")

with tab_quarterly:
    tq = _agg_quarterly(df0)
    tq_disp = tq[["YearQ", "Volume", "Value"]].rename(columns={"YearQ": "Quarter"})
    st.dataframe(
        tq_disp,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Volume": st.column_config.NumberColumn(format="%,d"),
            "Value": st.column_config.NumberColumn(format="₱%,.0f"),
        },
        height=420,
    )
    csv = tq_disp.to_csv(index=False).encode("utf-8")
    st.download_button("Download quarterly (CSV)", data=csv, file_name=f"{series}_quarterly.csv", mime="text/csv")

with tab_annual:
    ta = _agg_annual(df0)
    st.dataframe(
        ta,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Volume": st.column_config.NumberColumn(format="%,d"),
            "Value": st.column_config.NumberColumn(format="₱%,.0f"),
        },
        height=420,
    )
    csv = ta.to_csv(index=False).encode("utf-8")
    st.download_button("Download annual (CSV)", data=csv, file_name=f"{series}_annual.csv", mime="text/csv")

with tab_ytm_ytd:
    ytm_table = pd.DataFrame(
        {
            "Metric": ["YTM Volume", "YTM Value", "YTM YoY", "YTD Volume", "YTD Value"],
            "Current": [
                ytm_vol,
                ytm_val,
                None if ytm_vol_yoy is None else ytm_vol_yoy,
                ytd_vol,
                ytd_val,
            ],
            "Previous (YoY base)": [
                ytm_prev_vol,
                ytm_prev_val,
                None,
                ytm_prev_vol,  # shown for context
                ytm_prev_val,
            ],
        }
    )
    # Pretty formatting
    ytm_table["Current (fmt)"] = [
        _format_num(ytm_vol),
        _format_num(ytm_val, is_money=True),
        "—" if ytm_vol_yoy is None else f"{ytm_vol_yoy*100:,.1f}%",
        _format_num(ytd_vol),
        _format_num(ytd_val, is_money=True),
    ]
    ytm_table["Previous (fmt)"] = [
        _format_num(ytm_prev_vol),
        _format_num(ytm_prev_val, is_money=True),
        "—",
        _format_num(ytm_prev_vol),
        _format_num(ytm_prev_val, is_money=True),
    ]
    st.dataframe(
        ytm_table[["Metric", "Current (fmt)", "Previous (fmt)"]],
        use_container_width=True,
        hide_index=True,
        height=320,
    )

st.caption("Tip: Use the sidebar to switch between PESONet and InstaPay, set a month range, and optionally pick specific months of the year (e.g., only Mar, Jun, Sep, Dec).")

