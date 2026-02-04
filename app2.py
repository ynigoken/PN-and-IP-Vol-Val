# app.py
# Streamlit app to visualize monthly, quarterly, annual, YTM/YTD metrics


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
# Keep neutral page config; dynamic visible title/caption will change per stream below.
st.set_page_config(page_title="PESONet and InstaPay Volume and Value", layout="wide")

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

        # Keep ascending in memory for charts and time-based calcs
        out[sheet] = df.sort_values("Period")

    return out


def _humanize(x: float | int, is_money: bool = False) -> str:
    """
    Format with one decimal & suffix; ₱ when money.
    """
    if x is None or pd.isna(x):
        return "—"
    absx = abs(x)
    sign = "-" if x < 0 else ""
    trillion = 1_000_000_000_000
    billion  = 1_000_000_000
    million  = 1_000_000
    if absx >= trillion:
        text = f"{sign}{absx/trillion:,.1f}T"
    elif absx >= billion:
        text = f"{sign}{absx/billion:,.1f}B"
    elif absx >= million:
        text = f"{sign}{absx/million:,.1f}M"
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
    """
    Return a copy with formatted display columns for Period (optional), Volume, Value.
    Keeps Year/Quarter when present.
    """
    t = df_in.copy()
    if period_fmt and "Period" in t.columns:
        t["Period"] = t["Period"].dt.strftime("%b-%Y")
    t["Volume_display"] = t["Volume"].map(lambda x: "—" if pd.isna(x) else f"{x:,.0f}")
    t["Value_display"]  = t["Value"].map(lambda x: "—" if pd.isna(x) else f"₱{x:,.1f}")
    cols: List[str] = []
    if "Period" in t.columns: cols.append("Period")
    if "Quarter" in t.columns: cols.append("Quarter")
    if "Year" in t.columns: cols.append("Year")
    cols += ["Volume_display", "Value_display"]
    return t[cols]


# === Axis helpers ===
def _ticks_custom(start: float, stop: float, step: float, unit_label: str) -> tuple[list[float], list[str]]:
    vals = list(np.arange(start, stop + 0.5 * step, step))
    if unit_label == "M":
        labels = ["0"] + [f"{int(v/1e6)}M" for v in vals[1:]]
    else:
        labels = ["0"] + [f"{int(v/1e9)}B" for v in vals[1:]]
    return vals, labels

def _ticks_volume_pesonet() -> tuple[list[float], list[str]]:
    return _ticks_custom(0, 10e6, 2e6, "M")

def _ticks_volume_default() -> tuple[list[float], list[str]]:
    return _ticks_custom(0, 800e6, 200e6, "M")

def _ticks_value_default() -> tuple[list[float], list[str]]:
    return _ticks_custom(0, 1.4e12, 200e9, "B")


def _bar_line_chart(df: pd.DataFrame, series: str, title: str = "") -> go.Figure:
    """
    Volume = BAR on RIGHT; Value = LINE on LEFT. Line on top.
    """
    dark_blue = "#003366"; green = "#2ca02c"; red = "#d62728"
    if series.lower() == "pesonet":
        bar_color, line_color = green, dark_blue
        v_vals, v_text = _ticks_volume_pesonet(); v_range = [0, 10e6]
    else:
        bar_color, line_color = red, dark_blue
        v_vals, v_text = _ticks_volume_default(); v_range = [0, 800e6]
    b_vals, b_text = _ticks_value_default(); b_range = [0, 1.4e12]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=df["Period"], y=df["Volume"], name="Volume",
        marker_color=bar_color, marker_line_color=bar_color, marker_line_width=0.0,
        hovertemplate="%{x|%Y-%m} • Volume: %{y:,}<extra></extra>",
    ), secondary_y=True)
    fig.add_trace(go.Scatter(
        x=df["Period"], y=df["Value"], mode="lines+markers", name="Value (₱)",
        line=dict(color=dark_blue, width=3), marker=dict(size=5, color=dark_blue),
        hovertemplate="%{x|%Y-%m} • Value: ₱%{y:,.1f}<extra></extra>",
    ), secondary_y=False)

    fig.update_traces(selector=dict(type="bar"), opacity=0.55)
    if any(t.type == "scatter" for t in fig.data):
        bars = [t for t in fig.data if t.type != "scatter"]
        lines = [t for t in fig.data if t.type == "scatter"]
        fig.data = tuple(bars + lines)

    fig.update_yaxes(title_text="Value (₱)", secondary_y=False, range=b_range, tickvals=b_vals, ticktext=b_text, ticks="outside", rangemode="tozero")
    fig.update_yaxes(title_text="Volume (count)", secondary_y=True, range=v_range, tickvals=v_vals, ticktext=v_text, ticks="outside", rangemode="tozero")
    fig.update_layout(title=title, hovermode="x unified", barmode="overlay",
                      margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
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
# Sidebar - choose series
# =========================
series = st.sidebar.radio("Payment stream", options=AVAILABLE_SERIES, index=0, key="series_choice")

# ---- Dynamic title & source per series (visible header)
TITLE_BY_SERIES = {
    "PESONet": "PESONet Volume and Value",
    "InstaPay": "InstaPay Volume and Value",
}
SOURCE_BY_SERIES = {
    "PESONet": "Source: Philippine Clearing House Corporation",
    "InstaPay": "Source: BancNet",
}
title_text = TITLE_BY_SERIES.get(series, "Volume and Value")
source_text = SOURCE_BY_SERIES.get(series, "Source")

st.title(title_text)
st.caption(source_text)

# (Optional) also update browser tab title
st.markdown(f"""
    <script>document.title = "{title_text}";</script>
""", unsafe_allow_html=True)

df0 = data[series].copy()
if df0.empty:
    st.warning("The selected series has no rows.")
    st.stop()


# =========================
# Date Range controls (Slider FIRST, then dropdowns)
# =========================
def _date_range_controls(df_for_series: pd.DataFrame, key_prefix: str = "") -> pd.DataFrame:
    """
    Single 'Date Range' filter with:
      - Month slider (rendered FIRST)
      - Dropdowns (Start Year | Start Month; End Year | End Month) + 'Apply dropdown period' button
    Uses a PENDING value in session state + st.rerun() to safely apply dropdowns to the slider
    without mutating the slider's value after it's created.
    """
    st.sidebar.header("Date Range")

    # Normalize bounds to the first day of month
    min_m = df_for_series["Period"].min().to_period("M").to_timestamp()
    max_m = df_for_series["Period"].max().to_period("M").to_timestamp()

    slider_key = f"{key_prefix}_date_range_slider"
    pending_key = f"{key_prefix}_date_range_pending"
    default_span = (min_m.to_pydatetime(), max_m.to_pydatetime())

    # --- PRE-APPLY any pending value BEFORE the slider is created
    if pending_key in st.session_state:
        try:
            pend_start, pend_end = st.session_state[pending_key]
            pend_start = pd.Timestamp(pend_start).to_period("M").to_timestamp()
            pend_end   = pd.Timestamp(pend_end).to_period("M").to_timestamp()
            # clamp & validate
            pend_start = max(pend_start, min_m)
            pend_end   = min(pend_end, max_m)
            if pend_start <= pend_end:
                st.session_state[slider_key] = (pend_start.to_pydatetime(), pend_end.to_pydatetime())
        finally:
            # always clear the pending directive
            del st.session_state[pending_key]

    # --- SLIDER FIRST (uses existing session value or default)
    start_dt, end_dt = st.sidebar.slider(
        "Select Start and End Month",
        min_value=min_m.to_pydatetime(),
        max_value=max_m.to_pydatetime(),
        value=st.session_state.get(slider_key, default_span),
        format="YYYY-MM",
        key=slider_key,
    )

    # --- DROPDOWNS BELOW THE SLIDER
    st.sidebar.markdown("**Or set via dropdowns:**")

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    month_to_num = {m: i + 1 for i, m in enumerate(months)}
    years = list(range(int(min_m.year), int(max_m.year) + 1))

    # Use current slider selection to preselect dropdowns
    cur_start = pd.Timestamp(start_dt).to_period("M").to_timestamp()
    cur_end   = pd.Timestamp(end_dt).to_period("M").to_timestamp()

    # Row 1: Start Year | Start Month
    row1_col1, row1_col2 = st.sidebar.columns(2)
    with row1_col1:
        start_year = st.selectbox(
            "Start Year",
            options=years,
            index=years.index(int(cur_start.year)),
            key=f"{key_prefix}_start_year",
        )
    with row1_col2:
        start_month = st.selectbox(
            "Start Month",
            options=months,
            index=int(cur_start.month) - 1,
            key=f"{key_prefix}_start_month",
        )

    # Row 2: End Year | End Month
    row2_col1, row2_col2 = st.sidebar.columns(2)
    with row2_col1:
        end_year = st.selectbox(
            "End Year",
            options=years,
            index=years.index(int(cur_end.year)),
            key=f"{key_prefix}_end_year",
        )
    with row2_col2:
        end_month = st.selectbox(
            "End Month",
            options=months,
            index=int(cur_end.month) - 1,
            key=f"{key_prefix}_end_month",
        )

    # Apply dropdowns -> store PENDING (not the slider value) and rerun
    if st.sidebar.button("Apply dropdown period", key=f"{key_prefix}_apply_dropdown"):
        beg_period = pd.Timestamp(int(start_year), month_to_num[start_month], 1)
        end_period = pd.Timestamp(int(end_year), month_to_num[end_month], 1)
        # clamp
        beg_period = max(beg_period, min_m)
        end_period = min(end_period, max_m)

        if beg_period > end_period:
            st.sidebar.error("Begin Period must be earlier than or equal to End Period.")
        else:
            st.session_state[pending_key] = (beg_period.to_pydatetime(), end_period.to_pydatetime())
            st.rerun()

    # Inclusive filter normalized to month starts
    beg = pd.Timestamp(start_dt).to_period("M").to_timestamp()
    end = pd.Timestamp(end_dt).to_period("M").to_timestamp()

    if beg > end:
        st.sidebar.error("Begin Period must be earlier than or equal to End Period.")
        return df_for_series.iloc[0:0]

    return df_for_series[(df_for_series["Period"] >= beg) & (df_for_series["Period"] <= end)]


df = _date_range_controls(df0, key_prefix=series)
if df.empty:
    st.info("No data for the chosen period.")
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
    # Typo fix: include a_vol_yoy here as well
    a_vol = a_val = a_vol_yoy = a_val_yoy = None

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

# ---- Monthly (filtered): show latest first
with tab_monthly:
    show_cols = ["Period", "Volume", "Value"]

    t_disp = _format_table(
        df[show_cols].sort_values("Period", ascending=False),
        period_fmt=True
    )

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

    # CSV export (latest first)
    t_csv = df[show_cols].sort_values("Period", ascending=False).copy()
    t_csv["Period"] = t_csv["Period"].dt.strftime("%b-%Y")
    csv = t_csv.to_csv(index=False).encode("utf-8")
    st.download_button("Download monthly (CSV)", data=csv, file_name=f"{series}_monthly_filtered.csv", mime="text/csv")

# ---- Quarterly (full series context): show latest first
with tab_quarterly:
    tq = _agg_quarterly(df0)
    tq_disp = tq[["YearQ", "Volume", "Value"]].rename(columns={"YearQ": "Quarter"})

    t_disp = _format_table(tq_disp.iloc[::-1], period_fmt=False)

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

    csv = tq_disp.iloc[::-1].to_csv(index=False).encode("utf-8")
    st.download_button("Download quarterly (CSV)", data=csv, file_name=f"{series}_quarterly.csv", mime="text/csv")

# ---- Annual (full series context): include Year column, left-aligned, latest first
with tab_annual:
    ta = _agg_annual(df0)
    ta_latest_first = ta.iloc[::-1].copy()

    # Convert Year to string to ensure left alignment via TextColumn
    ta_latest_first_display = ta_latest_first.copy()
    ta_latest_first_display["Year"] = ta_latest_first_display["Year"].astype("Int64").astype(str)

    t_disp = _format_table(ta_latest_first_display, period_fmt=False)

    st.dataframe(
        t_disp.rename(columns={"Volume_display": "Volume", "Value_display": "Value"}),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Year": st.column_config.TextColumn(),  # left-aligned
            "Volume": st.column_config.TextColumn(help="Integers with comma separators"),
            "Value": st.column_config.TextColumn(help="₱, commas, one decimal"),
        },
        height=420,
    )

    # CSV latest first (keep Year numeric in CSV for analysis)
    csv = ta_latest_first.to_csv(index=False).encode("utf-8")
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
