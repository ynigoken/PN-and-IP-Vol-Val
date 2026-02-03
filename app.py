# app.py
# PESONet & InstaPay Dashboard
# Streamlit app to visualize monthly, quarterly, annual, YTM/YTD metrics
# Updates:
# - Title: "PESONet and InstaPay Volume and Value"
# - Gray caption: "PESONet Source: Philippine Clearing House Corporation · InstaPay Source: BancNet"
# - Humanized units: M, B, T (uppercase T) with ₱ for Value
# - PESONet: Volume (green BAR, RIGHT axis 0→10M, ticks 2M); Value (dark blue LINE, LEFT axis 0→1.4T, ticks 200B)
# - InstaPay: Volume (red BAR, RIGHT axis 0→800M, ticks 200M);  Value (dark blue LINE, LEFT axis 0→1.4T, ticks 200B)
# - Line is guaranteed ON TOP of bars (add order + explicit trace reordering). Bars are solid (no opacity).
# - Tables: Volume as comma-int; Value as ₱ comma + 1 decimal; Period as Jan-YYYY

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Tuple, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# =========================
# App config
# =========================
st.set_page_config(page_title="PESONet and InstaPay Volume and Value", layout="wide")
st.title("PESONet and InstaPay Volume and Value")
st.caption("PESONet Source: Philippine Clearing House Corporation · InstaPay Source: BancNet")

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
        p = Path(__file__).parent / file_path

    xls = pd.ExcelFile(p, engine="openpyxl")
    out = {}

    for sheet in xls.sheet_names:
        df = pd.read_excel(p, sheet_name=sheet, engine="openpyxl")

        # Standardize column names
        df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]

        # Keep expected columns if present
        keep = [c for c in ["Period", "Volume", "Value", "%Change in Vol", "%Change in Val", "Last12MTH", "Quarter"] if c in df.columns]
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
            df["YearQ"] = df["Period"].dt.to_period("Q").astype(str)  # '2024Q1'
            df["YearQ"] = df["YearQ"].str.replace("Q", "-Q", regex=False)  # '2024-Q1'

        out[sheet] = df.sort_values("Period")

    return out


def _humanize(x: float | int, is_money: bool = False) -> str:
    """
    Formats a number with one decimal and suffix:
      - < 1,000,000: 12,345.7
      - >= 1M: 1.1M
      - >= 1B: 1.1B
      - >= 1T: 1.1T (uppercase T for trillion)
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
        text = f"{sign}{num:,.1f}T"
    elif absx >= billion:
        num = absx / billion
        text = f"{sign}{num:,.1f}B"
    elif absx >= million:
        num = absx / million
        text = f"{sign}{num:,.1f}M"
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
    """YTM (Year-to-Month): Jan..end_month of end_ts within end_ts.year."""
    m_end = end_ts.month
    y_end = end_ts.year
    d = df[(df["Year"] == y_end) & (df["Month"] <= m_end)]
    return d["Volume"].sum(), d["Value"].sum()


def _ytd(df: pd.DataFrame, end_ts: pd.Timestamp) -> Tuple[float, float]:
    return _ytm(df, end_ts)


def _safe_pct(new: float, base: float) -> float | None:
    if base is None or base == 0 or pd.isna(base):
        return None
    return (new - base) / base


def _format_table(df_in: pd.DataFrame, period_fmt: bool = False) -> pd.DataFrame:
    """Return a copy with formatted display columns for Period (optional), Volume, Value."""
    t = df_in.copy()
    if period_fmt and "Period" in t.columns:
        t["Period"] = t["Period"].dt.strftime("%b-%Y")
    t["Volume_display"] = t["Volume"].map(lambda x: "—" if pd.isna(x) else f"{x:,.0f}")
    t["Value_display"]  = t["Value"].map(lambda x: "—" if pd.isna(x) else f"₱{x:,.1f}")
    cols: List[str] = []
    if "Period" in t.columns: cols.append("Period")
    if "Quarter" in t.columns: cols.append("Quarter")
    cols += ["Volume_display", "Value_display"]
    return t[cols]


# === Axis helpers ===
def _ticks_custom(start: float, stop: float, step: float, unit_label: str) -> tuple[list[float], list[str]]:
    """
    Generic helper to produce tick values and 'pretty' labels.
    For unit_label == "M": labels are v/1e6 + "M"
    For unit_label == "B": labels are v/1e9 + "B"
    """
    vals = list(np.arange(start, stop + 0.5 * step, step))
    if unit_label == "M":
        labels = ["0"] + [f"{int(v/1e6)}M" for v in vals[1:]]
    else:
        labels = ["0"] + [f"{int(v/1e9)}B" for v in vals[1:]]
    return vals, labels

def _ticks_volume_pesonet() -> tuple[list[float], list[str]]:
    # PESONet Volume: 0..10M, step 2M
    return _ticks_custom(0, 10e6, 2e6, "M")

def _ticks_volume_default() -> tuple[list[float], list[str]]:
    # Default Volume (InstaPay): 0..800M, step 200M
    return _ticks_custom(0, 800e6, 200e6, "M")

def _ticks_value_default() -> tuple[list[float], list[str]]:
    # Value for all: 0..1.4T, step 200B (labels in B)
    return _ticks_custom(0, 1.4e12, 200e9, "B")


def _bar_line_chart(df: pd.DataFrame, series: str, title: str = "") -> go.Figure:
    """
    Volume = BAR on RIGHT axis; Value = LINE on LEFT axis.
    PESONet: Volume ticks 0..10M step 2M (labels 2M, 4M, ...).
    InstaPay: Volume ticks 0..800M step 200M.
    Value (all): 0..1.4T step 200B (labels 200B, 400B, ...).
    Colors: PESONet -> bar green, InstaPay -> bar red; line dark blue for both.
    NOTE: Add BAR first (behind), then LINE (on top), then explicitly re-order traces to ensure the line sits on top.
    """
    # Colors
    dark_blue = "#003366"
    green     = "#2ca02c"
    red       = "#d62728"

    if series.lower() == "pesonet":
        bar_color, line_color = green, dark_blue
        v_vals, v_text = _ticks_volume_pesonet()
        v_range = [0, 10e6]
    else:
        bar_color, line_color = red, dark_blue
        v_vals, v_text = _ticks_volume_default()
        v_range = [0, 800e6]

    # Value ticks (common)
    b_vals, b_text = _ticks_value_default()
    b_range = [0, 1.4e12]

    fig = make_subplots(specs=[[{"secondary_y": True}]]) 

    
    # 1) VOLUME (BAR) on RIGHT  --- add FIRST (behind)
    bar_trace = go.Bar(
        x=df["Period"],
        y=df["Volume"],
        name="Volume",
        marker_color=bar_color,
        marker_line_color=bar_color,  # solid color
        marker_line_width=0.0,
        hovertemplate="%{x|%Y-%m} • Volume: %{y:,}<extra></extra>",
    )
    fig.add_trace(bar_trace,secondary_y=True) #secondary_y=True

     # 2) VALUE (LINE) on LEFT   --- add SECOND (on top)
    line_trace = go.Scatter(
        x=df["Period"],
        y=df["Value"],
        mode="lines+markers",
        name="Value (₱)",
        line=dict(color=line_color, width=3),
        marker=dict(size=5, color=line_color),
        hovertemplate="%{x|%Y-%m} • Value: ₱%{y:,.1f}<extra></extra>",
        cliponaxis=False,
    )
    fig.add_trace(line_trace, secondary_y=True) #secondary_y=False

    # --- Hard guarantee the line is on top: move all scatter traces to the end of the trace list
    if any(t.type == "scatter" for t in fig.data):
        bars = [t for t in fig.data if t.type != "scatter"]
        lines = [t for t in fig.data if t.type == "scatter"]
        fig.data = tuple(lines + bars)

    # Left (Value) axis
    fig.update_yaxes(
        title_text="Value (₱)", secondary_y=False,
        range=b_range, tickvals=b_vals, ticktext=b_text,
        ticks="outside", rangemode="tozero",
    )
    # Right (Volume) axis
    fig.update_yaxes(
        title_text="Volume (count)", secondary_y=True,
        range=v_range, tickvals=v_vals, ticktext=v_text,
        ticks="outside", rangemode="tozero",
    )

    fig.update_layout(
        title=title,
        hovermode="x unified",
        barmode="overlay",
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
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
# Sidebar - choose series first & filters
# =========================
series = st.sidebar.radio("Payment stream", options=AVAILABLE_SERIES, index=0, key="series_choice")
df0 = data[series].copy()
if df0.empty:
    st.warning("The selected series has no rows.")
    st.stop()

def _filter_controls(df_for_series: pd.DataFrame, key_prefix: str = "") -> pd.DataFrame:
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
        d = df_for_series[(df_for_series["Period"] >= pd.to_datetime(start)) & (df_for_series["Period"] <= pd.to_datetime(end))]
        d = d[d["Month"].isin(allowed_month_nums)]
        return d
    else:
        years = sorted(df_for_series["Year"].dropna().unique().tolist())
        sel_years = st.sidebar.multiselect("Year(s)", options=years, default=years[-1:], key=f"{key_prefix}_years")
        sel_months = st.sidebar.multiselect("Month(s)", options=months, default=months, key=f"{key_prefix}_months")
        allowed_month_nums = {m2num[m] for m in sel_months}
        d = df_for_series[df_for_series["Year"].isin(sel_years)]
        d = d[d["Month"].isin(allowed_month_nums)]
        return d

df = _filter_controls(df0, key_prefix=series)
if df.empty:
    st.info("No data for the chosen filters.")
    st.stop()

st.divider()


# =========================
# KPIs — FIRST: Selected filter totals
# =========================
sel_vol = df["Volume"].sum()
sel_val = df["Value"].sum()
k0a, k0b = st.columns(2)
k0a.metric(f"{series} • Volume (Selected Filter)", _humanize(sel_vol), help="Sum of Volume for the exact months/years you selected.")
k0b.metric(f"{series} • Value (Selected Filter)", _humanize(sel_val, is_money=True), help="Sum of Value (₱) for the exact months/years you selected.")
st.divider()


# =========================
# Additional KPIs (context)
# =========================
latest_period = df["Period"].max()
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
    a_vol = a_val = a_val_yoy = a_val_yoy = None

k1, k2, k3, k4 = st.columns(4)
k1.metric(f"YTM {latest_period.strftime('%Y-%m')} Volume", _humanize(ytm_vol),
          f"{'' if ytm_vol_yoy is None else f'{ytm_vol_yoy*100:,.1f}% YoY'}",
          help="Jan..selected month of current year vs same months last year.")
k2.metric(f"YTM {latest_period.strftime('%Y-%m')} Value", _humanize(ytm_val, is_money=True),
          f"{'' if ytm_val_yoy is None else f'{ytm_val_yoy*100:,.1f}% YoY'}")
k3.metric("Latest Quarter Volume", _humanize(q_vol), f"{'' if q_vol_qoq is None else f'{q_vol_qoq*100:,.1f}% QoQ'}")
k4.metric("Latest Quarter Value", _humanize(q_val, is_money=True), f"{'' if q_val_qoq is None else f'{q_val_qoq*100:,.1f}% QoQ'}")

k5, k6 = st.columns(2)
k5.metric("Latest Year Volume", _humanize(a_vol), f"{'' if a_vol_yoy is None else f'{a_vol_yoy*100:,.1f}% YoY'}")
k6.metric("Latest Year Value", _humanize(a_val, is_money=True), f"{'' if a_val_yoy is None else f'{a_val_yoy*100:,.1f}% YoY'}")

with st.expander("Definitions"):
    st.markdown(
        """
- **Selected Filter totals (top)**: Sum of the exact months & years you picked  
- **Quarterly**: Sum per calendar quarter  
- **Annual**: Sum per calendar year  
- **YTM (Year-to-Month)**: January to the selected month of the current year; YoY vs the same Jan–month range last year  
- **YTD (Year-to-Date)**: Same span as YTM at monthly granularity
        """
    )

st.divider()


# =========================
# Chart (series-colored; Volume BAR RIGHT, Value LINE LEFT; line on top)
# =========================
st.subheader(f"Monthly Trend — {series}")
fig = _bar_line_chart(df, series, title=f"{series} • Value (line, left) over Volume (bar, right)")
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# =========================
# Aggregations (Tables)
# =========================
tab_monthly, tab_quarterly, tab_annual, tab_ytm_ytd = st.tabs(["Monthly (filtered)", "Quarterly", "Annual", "YTM & YTD"])

# ---- Monthly (filtered)
with tab_monthly:
    show_cols = ["Period", "Volume", "Value"]
    t_raw = df[show_cols].copy()             # raw for CSV
    t_disp = _format_table(df[show_cols], period_fmt=True)
    st.dataframe(
        t_disp.rename(columns={"Volume_display": "Volume", "Value_display": "Value"}),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Period": st.column_config.TextColumn(),
            "Volume": st.column_config.TextColumn(help="Integers with comma separators"),
            "Value": st.column_config.TextColumn(help="₱, commas, one decimal"),
        },
        height=420,
    )
    # CSV export (Period formatted, numbers raw for analysis)
    t_csv = t_raw.copy()
    t_csv["Period"] = t_csv["Period"].dt.strftime("%b-%Y")
    csv = t_csv.to_csv(index=False).encode("utf-8")
    st.download_button("Download monthly (CSV)", data=csv, file_name=f"{series}_monthly_filtered.csv", mime="text/csv")

# ---- Quarterly (full series context)
with tab_quarterly:
    tq = _agg_quarterly(df0)
    tq_disp = tq[["YearQ", "Volume", "Value"]].rename(columns={"YearQ": "Quarter"})
    t_disp = _format_table(tq_disp, period_fmt=False)
    st.dataframe(
        t_disp.rename(columns={"Volume_display": "Volume", "Value_display": "Value"}),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quarter": st.column_config.TextColumn(),
            "Volume": st.column_config.TextColumn(help="Integers with comma separators"),
            "Value": st.column_config.TextColumn(help="₱, commas, one decimal"),
        },
        height=420,
    )
    csv = tq_disp.to_csv(index=False).encode("utf-8")
    st.download_button("Download quarterly (CSV)", data=csv, file_name=f"{series}_quarterly.csv", mime="text/csv")

# ---- Annual (full series context)
with tab_annual:
    ta = _agg_annual(df0)
    t_disp = _format_table(ta, period_fmt=False)
    st.dataframe(
        t_disp.rename(columns={"Volume_display": "Volume", "Value_display": "Value"}),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Volume": st.column_config.TextColumn(help="Integers with comma separators"),
            "Value": st.column_config.TextColumn(help="₱, commas, one decimal"),
        },
        height=420,
    )
    csv = ta.to_csv(index=False).encode("utf-8")
    st.download_button("Download annual (CSV)", data=csv, file_name=f"{series}_annual.csv", mime="text/csv")

# ---- YTM & YTD summary table (kept humanized for readability)
with tab_ytm_ytd:
    ytm_table = pd.DataFrame(
        {
            "Metric": ["YTM Volume", "YTM Value", "YTM YoY", "YTD Volume", "YTD Value"],
            "Current": [ytm_vol, ytm_val, None if ytm_vol_yoy is None else ytm_vol_yoy, ytd_vol, ytd_val],
            "Previous (YoY base)": [ytm_prev_vol, ytm_prev_val, None, ytm_prev_vol, ytm_prev_val],
        }
    )
    ytm_table["Current (fmt)"] = [
        _humanize(ytm_vol),
        _humanize(ytm_val, is_money=True),
        "—" if ytm_vol_yoy is None else f"{ytm_vol_yoy*100:,.1f}%",
        _humanize(ytd_vol),
        _humanize(ytd_val, is_money=True),
    ]
    ytm_table["Previous (fmt)"] = [
        _humanize(ytm_prev_vol),
        _humanize(ytm_prev_val, is_money=True),
        "—",
        _humanize(ytm_prev_vol),
        _humanize(ytm_prev_val, is_money=True),
    ]
    st.dataframe(
        ytm_table[["Metric", "Current (fmt)", "Previous (fmt)"]],
        use_container_width=True,
        hide_index=True,
        height=320,
    )
