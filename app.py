# app.py
# PESONet & InstaPay Volume and Value Dashboard
# Data source: Bangko Sentral ng Pilipinas (BSP) — fetched live on load

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────
# PAGE CONFIG  (must be first Streamlit call)
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="PESONet & InstaPay Monitor",
    page_icon="₱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# DATA SOURCES  (BSP live URLs)
# ─────────────────────────────────────────────
SOURCES: Dict[str, str] = {
    "PESONet": "https://www.bsp.gov.ph/PaymentAndSettlement/PESONet_vv.xlsx",
    "InstaPay": "https://www.bsp.gov.ph/PaymentAndSettlement/Instapay_vv.xlsx",
}

SOURCE_LABEL: Dict[str, str] = {
    "PESONet": "Philippine Clearing House Corporation (PCHC) via BSP",
    "InstaPay": "BancNet via BSP",
}

SERIES_COLOR: Dict[str, str] = {
    "PESONet": "#16a34a",   # green-600
    "InstaPay": "#dc2626",  # red-600
}

LINE_COLOR  = "#1e3a5f"   # dark navy for Value line (both series)

# Local fallback cache directory (gitignored)
CACHE_DIR = Path(__file__).parent / ".cache"

# ─────────────────────────────────────────────
# CSS INJECTION
# Scoped carefully so sidebar dark theme does NOT
# bleed into main-content widget colours.
# ─────────────────────────────────────────────
def _inject_css() -> None:
    st.markdown(
        """
        <style>
        /* ════════════════════════════════════════
           MAIN CANVAS — always light
           ════════════════════════════════════════ */
        [data-testid="stAppViewContainer"] > .main {
            background-color: #f8fafc;
        }
        /* Force all main-content text to dark so it
           reads on the light canvas regardless of the
           user's OS dark-mode setting */
        [data-testid="stAppViewContainer"] > .main,
        [data-testid="stAppViewContainer"] > .main p,
        [data-testid="stAppViewContainer"] > .main span,
        [data-testid="stAppViewContainer"] > .main h1,
        [data-testid="stAppViewContainer"] > .main h2,
        [data-testid="stAppViewContainer"] > .main h3,
        [data-testid="stAppViewContainer"] > .main h4,
        [data-testid="stAppViewContainer"] > .main label {
            color: #1e293b;
        }

        /* ════════════════════════════════════════
           SIDEBAR — dark navy, scoped tightly
           ════════════════════════════════════════ */
        [data-testid="stSidebar"] > div:first-child {
            background: linear-gradient(180deg, #0f2044 0%, #1a3560 100%);
        }
        /* Only colour direct text nodes inside the sidebar;
           do NOT use a bare * selector — that would nuke
           Streamlit's internal widget colour tokens */
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] div.stMarkdown,
        [data-testid="stSidebar"] div.stRadio > label,
        [data-testid="stSidebar"] .stSelectbox label,
        [data-testid="stSidebar"] .stSlider label {
            color: #dce8f5 !important;
        }
        [data-testid="stSidebar"] hr {
            border-color: #2e4d7b !important;
        }
        /* Slider track */
        [data-testid="stSidebar"] [data-testid="stSlider"] div[data-baseweb="slider"] div {
            background: #3b6abf;
        }

        /* ════════════════════════════════════════
           METRIC CARDS
           ════════════════════════════════════════ */
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 14px 18px 10px;
            box-shadow: 0 1px 3px rgba(0,0,0,.07);
        }
        /* Label row — muted grey */
        [data-testid="stMetricLabel"] > div {
            color: #64748b !important;
            font-size: .78rem !important;
        }
        /* Value row — prominent dark */
        [data-testid="stMetricValue"] > div {
            color: #0f172a !important;
            font-size: 1.5rem !important;
            font-weight: 700 !important;
        }
        /* Delta row colours preserved (green/red) */
        [data-testid="stMetricDelta"] svg { display: none; }

        /* ════════════════════════════════════════
           TABS
           ════════════════════════════════════════ */
        [data-testid="stTabs"] [role="tab"] {
            font-weight: 600;
            font-size: .88rem;
            color: #475569;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            color: #0f172a !important;
            border-bottom-color: #3b6abf !important;
        }

        /* ════════════════════════════════════════
           DOWNLOAD BUTTONS
           ════════════════════════════════════════ */
        [data-testid="stDownloadButton"] > button {
            background: #f1f5f9 !important;
            border: 1px solid #cbd5e1 !important;
            color: #334155 !important;
            border-radius: 6px;
            font-size: .82rem;
        }

        /* ════════════════════════════════════════
           DIVIDER
           ════════════════════════════════════════ */
        hr { margin: .5rem 0 !important; border-color: #e2e8f0 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# CACHE HELPERS  (issue 2 — offline fallback)
# On every successful fetch the raw bytes are
# written to .cache/<name>.parquet + a JSON
# sidecar with the fetch timestamp.
# If BSP is unreachable the parquet is loaded
# and a warning banner is shown.
# ─────────────────────────────────────────────
def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.parquet"

def _meta_path(name: str) -> Path:
    return CACHE_DIR / f"{name}_meta.json"

def _save_cache(name: str, df: pd.DataFrame) -> None:
    """Persist df + fetch timestamp to .cache/."""
    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(_cache_path(name), index=False)
    _meta_path(name).write_text(
        json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat()})
    )

def _load_cache(name: str) -> Optional[Tuple[pd.DataFrame, str]]:
    """Return (df, fetched_at_str) from disk, or None if no cache exists."""
    cp = _cache_path(name)
    mp = _meta_path(name)
    if not cp.exists():
        return None
    df = pd.read_parquet(cp)
    fetched_at = "unknown time"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text())
            fetched_at = meta.get("fetched_at", fetched_at)
        except Exception:
            pass
    return df, fetched_at


def _parse_bsp_bytes(name: str, raw_bytes: bytes) -> Optional[pd.DataFrame]:
    """
    Parse the in-memory BSP XLSX bytes into a clean DataFrame.
    BSP file layout:
        Row 0  → title string
        Row 1  → blank
        Row 2  → headers: Period | Volume | Value
        Row 3+ → monthly data
    Scans for the header row dynamically.
    """
    raw = io.BytesIO(raw_bytes)

    # Step 1 — find the header row
    try:
        df_scan = pd.read_excel(
            raw, sheet_name=0, header=None,
            engine="openpyxl", nrows=15,
        )
    except Exception as exc:
        st.error(f"Could not open {name} workbook: {exc}")
        return None

    header_row = None
    for i, row in df_scan.iterrows():
        if any(
            str(cell).strip().lower() == "period"
            for cell in row.values
            if pd.notna(cell)
        ):
            header_row = int(i)
            break

    if header_row is None:
        st.error(
            f"{name}: could not locate a 'Period' header row in the first 15 rows. "
            f"First row seen: {list(df_scan.iloc[0])}"
        )
        return None

    # Step 2 — re-read with the correct header
    raw.seek(0)
    try:
        df = pd.read_excel(
            raw, sheet_name=0,
            header=header_row,
            engine="openpyxl",
        )
    except Exception as exc:
        st.error(f"Could not parse {name} data: {exc}")
        return None

    # Step 3 — normalise columns
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed:")]
    df = df.dropna(how="all")

    # Step 4 — keep recognised columns only
    keep = [
        c for c in
        ["Period", "Volume", "Value",
         "%Change in Vol", "%Change in Val", "Last12MTH", "Quarter"]
        if c in df.columns
    ]
    if "Period" not in keep:
        st.error(f"{name}: 'Period' column not found after parse. Got: {list(df.columns)}")
        return None
    df = df[keep].copy()

    # Step 5 — parse & validate dates
    df["Period"] = pd.to_datetime(df["Period"], errors="coerce")
    df = df.dropna(subset=["Period"])
    df = df[df["Period"].dt.year >= 2000]   # drop any junk pre-2000 dates

    # Step 6 — coerce numerics
    for col in ["Volume", "Value", "%Change in Vol", "%Change in Val", "Last12MTH"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Step 7 — derive helper columns
    df["Year"]      = df["Period"].dt.year
    df["Month"]     = df["Period"].dt.month
    df["MonthName"] = df["Period"].dt.strftime("%b")
    df["YearMonth"] = df["Period"].dt.to_period("M").dt.to_timestamp()
    df["YearQ"]     = (
        df["Period"].dt.to_period("Q")
        .astype(str)
        .str.replace("Q", "-Q", regex=False)
    )

    return df.sort_values("Period").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_all_series() -> Dict[str, pd.DataFrame]:
    """
    For each series:
      1. Try to fetch from BSP URL.
         - On success: parse + save to .cache/ as Parquet.
      2. On any network/HTTP failure:
         - Load last-good Parquet from .cache/.
         - Attach a '_stale' flag so the UI can show a warning.
    Returns a dict keyed by series name.
    Each value is a clean DataFrame; stale ones have a '_stale_since'
    attribute stored in st.session_state for the warning banner.
    """
    out: Dict[str, pd.DataFrame] = {}

    for name, url in SOURCES.items():
        fetched_ok = False
        raw_bytes: Optional[bytes] = None

        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            raw_bytes = resp.content
            fetched_ok = True
        except Exception:
            pass   # handled below

        if fetched_ok and raw_bytes:
            df = _parse_bsp_bytes(name, raw_bytes)
            if df is not None:
                _save_cache(name, df)   # persist for future offline use
                out[name] = df
                st.session_state.pop(f"_stale_{name}", None)
                continue

        # ── Fallback: load from local cache ──────────────────────────
        cached = _load_cache(name)
        if cached is not None:
            df, fetched_at = cached
            out[name] = df
            st.session_state[f"_stale_{name}"] = fetched_at
        else:
            st.error(
                f"**{name}**: BSP data unavailable and no local cache found. "
                f"Please check your internet connection and reload."
            )

    return out


# ─────────────────────────────────────────────
# PURE HELPERS  (unchanged logic, kept as-is)
# ─────────────────────────────────────────────
def _humanize(x: float | int | None, is_money: bool = False) -> str:
    if x is None or pd.isna(x):
        return "—"
    absx = abs(x)
    sign = "-" if x < 0 else ""
    if absx >= 1_000_000_000_000:
        text = f"{sign}{absx/1_000_000_000_000:,.1f}T"
    elif absx >= 1_000_000_000:
        text = f"{sign}{absx/1_000_000_000:,.1f}B"
    elif absx >= 1_000_000:
        text = f"{sign}{absx/1_000_000:,.1f}M"
    else:
        text = f"{sign}{absx:,.1f}"
    return f"₱{text}" if is_money else text


def _agg_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("YearQ", as_index=False).agg({"Volume": "sum", "Value": "sum"})
    yq = g["YearQ"].str.extract(r"((\d{4})\-Q([1-4]))")
    g["Year"] = yq[1].astype(int)
    g["Qtr"]  = yq[2].astype(int)
    return g.sort_values(["Year", "Qtr"])


def _agg_annual(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("Year", as_index=False)
        .agg({"Volume": "sum", "Value": "sum"})
        .sort_values("Year")
    )


def _ytm(df: pd.DataFrame, end_ts: pd.Timestamp) -> Tuple[float, float]:
    d = df[(df["Year"] == end_ts.year) & (df["Month"] <= end_ts.month)]
    return d["Volume"].sum(), d["Value"].sum()


def _safe_pct(new: float, base: float) -> float | None:
    if base is None or base == 0 or pd.isna(base):
        return None
    return (new - base) / base


def _fmt_delta(val: float | None, suffix: str = "") -> str:
    if val is None:
        return ""
    return f"{val*100:+.1f}%{(' ' + suffix) if suffix else ''}"


def _format_table(df_in: pd.DataFrame, period_fmt: bool = False) -> pd.DataFrame:
    t = df_in.copy()
    if period_fmt and "Period" in t.columns:
        t["Period"] = t["Period"].dt.strftime("%b %Y")
    t["Volume_display"] = t["Volume"].map(
        lambda x: "—" if pd.isna(x) else f"{x:,.0f}"
    )
    t["Value_display"] = t["Value"].map(
        lambda x: "—" if pd.isna(x) else f"₱{x:,.1f}"
    )
    cols: List[str] = []
    if "Period"  in t.columns: cols.append("Period")
    if "Quarter" in t.columns: cols.append("Quarter")
    if "Year"    in t.columns: cols.append("Year")
    cols += ["Volume_display", "Value_display"]
    return t[cols]


# ─────────────────────────────────────────────
# CHART  (AMENDMENT 4 — dynamic axis scaling)
# Old version used hardcoded ranges per series.
# New version computes a clean ceiling from actual data.
# ─────────────────────────────────────────────
def _nice_ceil(val: float, steps: int = 6) -> Tuple[float, float]:
    """Return (max_range, step_size) giving ~steps intervals above val."""
    if val <= 0:
        return 1.0, 1.0 / steps
    magnitude = 10 ** int(np.floor(np.log10(val)))
    candidates = [1, 2, 2.5, 5, 10]
    for c in candidates:
        step = c * magnitude
        ceil_val = np.ceil(val / step) * step
        if ceil_val / step <= steps + 1:
            return float(ceil_val), float(step)
    return float(np.ceil(val / magnitude) * magnitude), float(magnitude)


def _build_ticks(max_val: float, step: float) -> Tuple[List[float], List[str]]:
    vals = list(np.arange(0, max_val + step * 0.5, step))
    billion, million = 1_000_000_000, 1_000_000

    def _label(v: float) -> str:
        if v == 0:
            return "0"
        if max_val >= billion:
            return f"{v/billion:g}B"
        return f"{v/million:g}M"

    return vals, [_label(v) for v in vals]


def _bar_line_chart(df: pd.DataFrame, series: str) -> go.Figure:
    bar_color  = SERIES_COLOR[series]
    line_color = LINE_COLOR

    # ── Dynamic axis ranges (AMENDMENT 4)
    v_max, v_step = _nice_ceil(df["Volume"].max(), steps=5)
    b_max, b_step = _nice_ceil(df["Value"].max(),  steps=5)
    v_vals, v_text = _build_ticks(v_max, v_step)
    b_vals, b_text = _build_ticks(b_max, b_step)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=df["Period"], y=df["Volume"],
            name="Volume",
            marker_color=bar_color,
            marker_line_width=0,
            opacity=0.55,
            hovertemplate="%{x|%b %Y}  Volume: <b>%{y:,}</b><extra></extra>",
        ),
        secondary_y=True,
    )

    fig.add_trace(
        go.Scatter(
            x=df["Period"], y=df["Value"],
            mode="lines+markers",
            name="Value (₱)",
            line=dict(color=line_color, width=2.5),
            marker=dict(size=4, color=line_color),
            hovertemplate="%{x|%b %Y}  Value: <b>₱%{y:,.1f}</b><extra></extra>",
        ),
        secondary_y=False,
    )

    # Keep Scatter on top layer
    bars  = [t for t in fig.data if t.type == "bar"]
    lines = [t for t in fig.data if t.type == "scatter"]
    fig.data = tuple(bars + lines)

    fig.update_yaxes(
        title_text="Value (₱)",
        secondary_y=False,
        range=[0, b_max],
        tickvals=b_vals, ticktext=b_text,
        ticks="outside", showgrid=True,
        gridcolor="#f0f4f8",
    )
    fig.update_yaxes(
        title_text="Volume",
        secondary_y=True,
        range=[0, v_max],
        tickvals=v_vals, ticktext=v_text,
        ticks="outside", showgrid=False,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_layout(
        hovermode="x unified",
        barmode="overlay",
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01,
            xanchor="right", x=1, bgcolor="rgba(0,0,0,0)",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )
    return fig


# ─────────────────────────────────────────────
# DATE RANGE SIDEBAR  (logic unchanged; label polish only)
# ─────────────────────────────────────────────
def _date_range_controls(
    df_for_series: pd.DataFrame, key_prefix: str = ""
) -> pd.DataFrame:
    st.sidebar.markdown("### Date Range")

    min_m = df_for_series["Period"].min().to_period("M").to_timestamp()
    max_m = df_for_series["Period"].max().to_period("M").to_timestamp()

    slider_key  = f"{key_prefix}_date_range_slider"
    pending_key = f"{key_prefix}_date_range_pending"
    default_span = (min_m.to_pydatetime(), max_m.to_pydatetime())

    if pending_key in st.session_state:
        try:
            ps, pe = st.session_state[pending_key]
            ps = max(pd.Timestamp(ps).to_period("M").to_timestamp(), min_m)
            pe = min(pd.Timestamp(pe).to_period("M").to_timestamp(), max_m)
            if ps <= pe:
                st.session_state[slider_key] = (ps.to_pydatetime(), pe.to_pydatetime())
        finally:
            del st.session_state[pending_key]

    start_dt, end_dt = st.sidebar.slider(
        "Start  ·  End month",
        min_value=min_m.to_pydatetime(),
        max_value=max_m.to_pydatetime(),
        value=st.session_state.get(slider_key, default_span),
        format="YYYY-MM",
        key=slider_key,
    )

    st.sidebar.markdown("**Or pick exact months:**")

    months      = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]
    month_to_num = {m: i + 1 for i, m in enumerate(months)}
    years        = list(range(int(min_m.year), int(max_m.year) + 1))

    cur_s = pd.Timestamp(start_dt).to_period("M").to_timestamp()
    cur_e = pd.Timestamp(end_dt).to_period("M").to_timestamp()

    c1, c2 = st.sidebar.columns(2)
    with c1:
        start_year = st.selectbox(
            "From year", years,
            index=years.index(int(cur_s.year)),
            key=f"{key_prefix}_sy",
        )
    with c2:
        start_month = st.selectbox(
            "From month", months,
            index=int(cur_s.month) - 1,
            key=f"{key_prefix}_sm",
        )

    c3, c4 = st.sidebar.columns(2)
    with c3:
        end_year = st.selectbox(
            "To year", years,
            index=years.index(int(cur_e.year)),
            key=f"{key_prefix}_ey",
        )
    with c4:
        end_month = st.selectbox(
            "To month", months,
            index=int(cur_e.month) - 1,
            key=f"{key_prefix}_em",
        )

    if st.sidebar.button("Apply", key=f"{key_prefix}_apply", use_container_width=True):
        bp = max(pd.Timestamp(int(start_year), month_to_num[start_month], 1), min_m)
        ep = min(pd.Timestamp(int(end_year),   month_to_num[end_month],   1), max_m)
        if bp > ep:
            st.sidebar.error("Start must be ≤ End.")
        else:
            st.session_state[pending_key] = (bp.to_pydatetime(), ep.to_pydatetime())
            st.rerun()

    beg = pd.Timestamp(start_dt).to_period("M").to_timestamp()
    end = pd.Timestamp(end_dt).to_period("M").to_timestamp()

    if beg > end:
        st.sidebar.error("Start must be ≤ End.")
        return df_for_series.iloc[0:0]

    return df_for_series[
        (df_for_series["Period"] >= beg) & (df_for_series["Period"] <= end)
    ]


# ═════════════════════════════════════════════
# MAIN APP
# ═════════════════════════════════════════════
_inject_css()

# ── Load data (AMENDMENT 9 — spinner feedback)
with st.spinner("Fetching latest data from BSP…"):
    data = _load_all_series()

if not data:
    st.error("No data could be loaded. Check your internet connection and reload the page.")
    st.stop()

AVAILABLE_SERIES = [s for s in SOURCES if s in data]   # preserve declared order

# Show a single stale-data banner covering all affected series
_stale_series = [
    (name, st.session_state[f"_stale_{name}"])
    for name in AVAILABLE_SERIES
    if f"_stale_{name}" in st.session_state
]
if _stale_series:
    stale_lines = "  \n".join(
        f"- **{n}**: last successfully fetched at {ts} UTC"
        for n, ts in _stale_series
    )
    st.warning(
        f"⚠️ **BSP data source currently unreachable.** "
        f"Showing the most recent locally cached data:\n\n{stale_lines}\n\n"
        f"Data will refresh automatically once the BSP website is back online.",
        icon=None,
    )

# ─────────────────────────────────────────────
# SIDEBAR  (AMENDMENT 6 — branding + data badge)
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
        <div style="text-align:center; padding: 6px 0 14px 0;">
            <span style="font-size:2rem;">₱</span><br>
            <span style="font-size:1.05rem; font-weight:700;
                         letter-spacing:.04em;">PH Payments Monitor</span><br>
            <span style="font-size:.72rem; opacity:.7;">
                PESONet &amp; InstaPay Analytics
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    series = st.radio(
        "Payment stream",
        options=AVAILABLE_SERIES,
        index=0,
        key="series_choice",
    )

    st.divider()
    # Data freshness badge
    st.markdown(
        f"""
        <div style="font-size:.72rem; opacity:.75; line-height:1.6;">
            <b>Source</b><br>{SOURCE_LABEL[series]}<br><br>
            <b>Data URL</b><br>
            <a href="{SOURCES[series]}" target="_blank"
               style="color:#93c5fd; word-break:break-all;">
               bsp.gov.ph ↗
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

df0 = data[series].copy()
if df0.empty:
    st.warning(f"No rows found for {series}.")
    st.stop()

# ─────────────────────────────────────────────
# DATE FILTER
# ─────────────────────────────────────────────
df = _date_range_controls(df0, key_prefix=series)
if df.empty:
    st.info("No data for the chosen period.")
    st.stop()

# ─────────────────────────────────────────────
# PAGE HEADER  (AMENDMENT 6 — dynamic, clean)
# ─────────────────────────────────────────────
accent = SERIES_COLOR[series]
sel_start = df["Period"].min().strftime("%b %Y")
sel_end   = df["Period"].max().strftime("%b %Y")
range_label = sel_start if sel_start == sel_end else f"{sel_start} – {sel_end}"

st.markdown(
    f"""
    <div style="border-left: 5px solid {accent};
                padding: 6px 0 6px 16px; margin-bottom: 4px;">
        <h1 style="margin:0; font-size:1.8rem; font-weight:800; color:#0f172a;">
            {series} Volume &amp; Value
        </h1>
        <p style="margin:2px 0 0 0; font-size:.85rem; color:#64748b;">
            {SOURCE_LABEL[series]} &nbsp;|&nbsp; Showing: <b>{range_label}</b>
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)
st.divider()

# ─────────────────────────────────────────────
# KPI METRICS  (AMENDMENT 7 — 3-col layout, cleaner labels)
# ─────────────────────────────────────────────
sel_vol = df["Volume"].sum()
sel_val = df["Value"].sum()

latest_period  = df0["Period"].max()
ytm_vol, ytm_val   = _ytm(df0, latest_period)
prev_ref           = latest_period.replace(year=latest_period.year - 1)
ytm_prev_vol, ytm_prev_val = _ytm(df0, prev_ref)
ytm_vol_yoy = _safe_pct(ytm_vol, ytm_prev_vol)
ytm_val_yoy = _safe_pct(ytm_val, ytm_prev_val)

q_agg = _agg_quarterly(df0)
a_agg = _agg_annual(df0)

q_vol = q_val = q_vol_qoq = q_val_qoq = None
if not q_agg.empty:
    lq = q_agg.iloc[-1]
    q_vol, q_val = lq["Volume"], lq["Value"]
    if len(q_agg) >= 2:
        pq = q_agg.iloc[-2]
        q_vol_qoq = _safe_pct(q_vol, pq["Volume"])
        q_val_qoq = _safe_pct(q_val, pq["Value"])

a_vol = a_val = a_vol_yoy = a_val_yoy = None
if not a_agg.empty:
    la = a_agg.iloc[-1]
    a_vol, a_val = la["Volume"], la["Value"]
    if len(a_agg) >= 2:
        pa = a_agg.iloc[-2]
        a_vol_yoy = _safe_pct(a_vol, pa["Volume"])
        a_val_yoy = _safe_pct(a_val, pa["Value"])

# Row 1 — Selected range summary (2 wide cols)
st.markdown("#### Selected Period")
r1c1, r1c2 = st.columns(2)
r1c1.metric(
    f"Total Volume  ({range_label})",
    _humanize(sel_vol),
    help="Sum of transactions in the filtered month range.",
)
r1c2.metric(
    f"Total Value  ({range_label})",
    _humanize(sel_val, is_money=True),
    help="Sum of transaction value (₱) in the filtered month range.",
)

st.markdown("#### Year-to-Month  " + f"<span style='font-size:.8rem;color:#64748b;'>({latest_period.strftime('%b %Y')})</span>", unsafe_allow_html=True)
r2c1, r2c2, r2c3 = st.columns(3)
r2c1.metric(
    "YTM Volume",
    _humanize(ytm_vol),
    _fmt_delta(ytm_vol_yoy, "YoY"),
    help=f"Jan–{latest_period.strftime('%b %Y')} vs same period last year.",
)
r2c2.metric(
    "YTM Value",
    _humanize(ytm_val, is_money=True),
    _fmt_delta(ytm_val_yoy, "YoY"),
)
r2c3.metric(
    "YTM vs Prior Year (Vol)",
    _humanize(ytm_prev_vol),
    help=f"Jan–{prev_ref.strftime('%b %Y')} baseline.",
)

st.markdown("#### Latest Quarter & Year")
r3c1, r3c2, r3c3, r3c4 = st.columns(4)
r3c1.metric(
    f"Q Volume  ({q_agg.iloc[-1]['YearQ'] if not q_agg.empty else '—'})",
    _humanize(q_vol),
    _fmt_delta(q_vol_qoq, "QoQ"),
)
r3c2.metric(
    f"Q Value  ({q_agg.iloc[-1]['YearQ'] if not q_agg.empty else '—'})",
    _humanize(q_val, is_money=True),
    _fmt_delta(q_val_qoq, "QoQ"),
)
r3c3.metric(
    f"Annual Volume  ({int(a_agg.iloc[-1]['Year']) if not a_agg.empty else '—'})",
    _humanize(a_vol),
    _fmt_delta(a_vol_yoy, "YoY"),
)
r3c4.metric(
    f"Annual Value  ({int(a_agg.iloc[-1]['Year']) if not a_agg.empty else '—'})",
    _humanize(a_val, is_money=True),
    _fmt_delta(a_val_yoy, "YoY"),
)

with st.expander("Metric definitions"):
    st.markdown(
        """
        | Term | Definition |
        |---|---|
        | **Selected Period** | Sum of the exact month range chosen in the sidebar filter |
        | **YTM (Year-to-Month)** | January through the latest data month of the current year |
        | **YoY** | Year-on-year change vs the identical calendar span one year prior |
        | **QoQ** | Quarter-on-quarter change vs the immediately preceding quarter |
        | **Annual** | Full-calendar-year aggregate for the latest available year |
        """
    )

st.divider()

# ─────────────────────────────────────────────
# CHART  (AMENDMENT 8 — title via st.markdown)
# ─────────────────────────────────────────────
st.markdown(
    f"#### Monthly Trend — {series}"
    f"<span style='font-size:.8rem; color:#64748b; margin-left:10px;'>"
    f"Bar = Volume (right axis) · Line = Value ₱ (left axis)</span>",
    unsafe_allow_html=True,
)

fig = _bar_line_chart(df, series)
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.divider()

# ─────────────────────────────────────────────
# DATA TABLES
# ─────────────────────────────────────────────
tab_monthly, tab_quarterly, tab_annual, tab_ytm = st.tabs(
    ["Monthly (filtered)", "Quarterly", "Annual", "YTM & YTD"]
)

_COL_CFG = {
    "Period":  st.column_config.TextColumn(),
    "Quarter": st.column_config.TextColumn(),
    "Year":    st.column_config.TextColumn(),
    "Volume":  st.column_config.TextColumn(help="Transactions (comma-separated)"),
    "Value":   st.column_config.TextColumn(help="₱ value, 1 decimal"),
}

# ── Monthly ──────────────────────────────────
with tab_monthly:
    show_cols = [c for c in ["Period", "Volume", "Value"] if c in df.columns]
    t_disp = _format_table(
        df[show_cols].sort_values("Period", ascending=False),
        period_fmt=True,
    ).rename(columns={"Volume_display": "Volume", "Value_display": "Value"})

    st.dataframe(
        t_disp, use_container_width=True, hide_index=True,
        column_config=_COL_CFG, height=420,
    )

    t_csv = df[show_cols].sort_values("Period", ascending=False).copy()
    t_csv["Period"] = t_csv["Period"].dt.strftime("%b %Y")
    st.download_button(
        "Download CSV", data=t_csv.to_csv(index=False).encode(),
        file_name=f"{series}_monthly.csv", mime="text/csv",
    )

# ── Quarterly ────────────────────────────────
with tab_quarterly:
    tq = _agg_quarterly(df0)
    tq_disp = (
        tq[["YearQ", "Volume", "Value"]]
        .rename(columns={"YearQ": "Quarter"})
        .iloc[::-1]
    )
    t_disp = _format_table(tq_disp).rename(
        columns={"Volume_display": "Volume", "Value_display": "Value"}
    )
    st.dataframe(
        t_disp, use_container_width=True, hide_index=True,
        column_config=_COL_CFG, height=420,
    )
    st.download_button(
        "Download CSV", data=tq_disp.to_csv(index=False).encode(),
        file_name=f"{series}_quarterly.csv", mime="text/csv",
    )

# ── Annual ───────────────────────────────────
with tab_annual:
    ta = _agg_annual(df0).iloc[::-1].copy()
    ta["Year"] = ta["Year"].astype("Int64").astype(str)
    t_disp = _format_table(ta).rename(
        columns={"Volume_display": "Volume", "Value_display": "Value"}
    )
    st.dataframe(
        t_disp, use_container_width=True, hide_index=True,
        column_config=_COL_CFG, height=420,
    )
    st.download_button(
        "Download CSV", data=ta.to_csv(index=False).encode(),
        file_name=f"{series}_annual.csv", mime="text/csv",
    )

# ── YTM & YTD ────────────────────────────────
with tab_ytm:
    ytm_rows = pd.DataFrame([
        {"Metric": "YTM Volume",
         f"Current ({latest_period.strftime('%b %Y')})": _humanize(ytm_vol),
         f"Prior Year ({prev_ref.strftime('%b %Y')})": _humanize(ytm_prev_vol),
         "YoY Change": _fmt_delta(ytm_vol_yoy)},
        {"Metric": "YTM Value",
         f"Current ({latest_period.strftime('%b %Y')})": _humanize(ytm_val, is_money=True),
         f"Prior Year ({prev_ref.strftime('%b %Y')})": _humanize(ytm_prev_val, is_money=True),
         "YoY Change": _fmt_delta(ytm_val_yoy)},
    ])
    st.dataframe(ytm_rows, use_container_width=True, hide_index=True, height=140)

# ─────────────────────────────────────────────
# FOOTER  (AMENDMENT 10 — source attribution)
# ─────────────────────────────────────────────
st.divider()
st.markdown(
    f"""
    <div style="font-size:.75rem; color:#94a3b8; text-align:center; padding:8px 0 16px;">
        Data sourced from the
        <a href="https://www.bsp.gov.ph" target="_blank"
           style="color:#60a5fa;">Bangko Sentral ng Pilipinas (BSP)</a>
        &nbsp;·&nbsp;
        <a href="{SOURCES['PESONet']}" target="_blank" style="color:#60a5fa;">PESONet XLSX</a>
        &nbsp;·&nbsp;
        <a href="{SOURCES['InstaPay']}" target="_blank" style="color:#60a5fa;">InstaPay XLSX</a>
        &nbsp;·&nbsp; Refreshed hourly
    </div>
    """,
    unsafe_allow_html=True,
)