import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

# =========================
# App config
# =========================
st.set_page_config(page_title="ASEAN Regulatory Dashboard", layout="wide")
st.title("ASEAN Regulatory Dashboard")

DATA_FILE = "CBregs.xlsx"  


# =========================
# Helpers
# =========================
ASEAN_FLAG = {
    "Brunei": "🇧🇳",
    "Cambodia": "🇰🇭",
    "Indonesia": "🇮🇩",
    "Lao PDR": "🇱🇦",
    "Laos": "🇱🇦",
    "Malaysia": "🇲🇾",
    "Myanmar": "🇲🇲",
    "Philippines": "🇵🇭",
    "Singapore": "🇸🇬",
    "Thailand": "🇹🇭",
    "Viet Nam": "🇻🇳",
    "Vietnam": "🇻🇳",
    "Timor-Leste": "🇹🇱",
}

META_COL_CANDIDATES = {
    "country": ["Country"],
    "regulator": ["Regulator"],
    "year": ["Year", "Year approved/implemented", "Year Approved/Implemented", "Year approved / implemented"],
    "source": ["Official Source", "Official source", "Official Source links", "Official source links", "Source", "URL", "Link"],
    "title": [
        "Regulation / Legal Instrument",
        "Regulation / Legal instrument",
        "Primary Legal / Regulatory Framework",
        "Primary Legal/Regulatory Framework",
        "Regulations on fraud risk management",
        "Regulations on consumer protection (payments)",
        "Regulation",
        "Legal Instrument",
    ],
}

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    return df

def extract_year(value) -> Optional[int]:
    if pd.isna(value):
        return None
    s = str(value).strip()
    m = re.search(r"(19\d{2}|20\d{2})", s)
    return int(m.group(1)) if m else None

def pick_first_existing_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def infer_title_col(df: pd.DataFrame) -> Optional[str]:
    # 1) Try known title candidates
    c = pick_first_existing_col(df, META_COL_CANDIDATES["title"])
    if c:
        return c

    # 2) Fallback: pick first non-meta-ish column with text values
    known_meta = set(META_COL_CANDIDATES["country"] + META_COL_CANDIDATES["regulator"] +
                     META_COL_CANDIDATES["year"] + META_COL_CANDIDATES["source"] + ["Regulation ID"])
    for col in df.columns:
        if col in known_meta:
            continue
        # Heuristic: choose first column that looks like a name/title field (string-ish)
        if df[col].astype(str).str.len().mean() > 5:
            return col
    return None

def safe_linkify(url: str) -> str:
    url = str(url).strip()
    if not url or url.lower() in {"nan", "none"}:
        return ""
    # Keep as markdown link; display a compact label
    return f"[Source]({url})"

@st.cache_data
def load_cbregs(file_path: str) -> pd.DataFrame:
    p = Path(file_path)
    if not p.exists():
        # common Streamlit Cloud pattern: relative to app file
        p = Path(__file__).parent / file_path

    xls = pd.ExcelFile(p, engine="openpyxl")
    frames = []

    for sheet in xls.sheet_names:
        df = pd.read_excel(p, sheet_name=sheet, engine="openpyxl")
        df = normalize_columns(df).dropna(how="all").dropna(axis=1, how="all")

        country_col = pick_first_existing_col(df, META_COL_CANDIDATES["country"])
        regulator_col = pick_first_existing_col(df, META_COL_CANDIDATES["regulator"])
        year_col = pick_first_existing_col(df, META_COL_CANDIDATES["year"])
        source_col = pick_first_existing_col(df, META_COL_CANDIDATES["source"])
        title_col = infer_title_col(df)

        # Build standardized view while retaining originals for the country modal
        out = df.copy()
        out["Category"] = sheet

        out["Country_std"] = out[country_col] if country_col else pd.NA
        out["Regulator_std"] = out[regulator_col] if regulator_col else pd.NA
        out["Year_raw"] = out[year_col] if year_col else pd.NA
        out["Year"] = out["Year_raw"].apply(extract_year).astype("Int64")

        if title_col:
            out["Regulation_Title"] = out[title_col].astype(str)
        else:
            out["Regulation_Title"] = pd.NA

        if source_col:
            out["Source_URL"] = out[source_col].astype(str)
        else:
            out["Source_URL"] = pd.NA

        frames.append(out)

    all_df = pd.concat(frames, ignore_index=True)

    # Clean
    all_df["Country_std"] = all_df["Country_std"].astype(str).str.strip()
    all_df["Regulator_std"] = all_df["Regulator_std"].astype(str).str.strip()
    all_df["Regulation_Title"] = all_df["Regulation_Title"].astype(str).str.strip()

    # Treat "nan" strings produced by astype(str)
    for c in ["Country_std", "Regulator_std", "Regulation_Title", "Source_URL"]:
        all_df.loc[all_df[c].str.lower().isin(["nan", "none"]), c] = pd.NA

    return all_df


def latest_regs_by_country(df: pd.DataFrame, country: str, n: int = 10) -> pd.DataFrame:
    d = df[df["Country_std"] == country].copy()
    d = d.dropna(subset=["Regulation_Title"])
    # Year might be NA; put those last
    d["Year_sort"] = d["Year"].fillna(-1).astype(int)
    d = d.sort_values(["Year_sort", "Regulation_Title"], ascending=[False, True])
    return d.head(n)[["Year", "Regulation_Title", "Category", "Regulator_std", "Source_URL"]]


def build_hover_list(df_country_latest: pd.DataFrame) -> str:
    if df_country_latest.empty:
        return "No regulations found."
    lines = []
    for _, r in df_country_latest.iterrows():
        y = r["Year"]
        y_txt = str(int(y)) if pd.notna(y) else "—"
        title = str(r["Regulation_Title"])
        lines.append(f"{y_txt} — {title}")
    # Plotly hover supports <br>
    return "<br>".join(lines)


# =========================
# Load data
# =========================
df_all = load_cbregs(DATA_FILE)

if df_all.empty:
    st.error("CBregs.xlsx loaded but produced no rows.")
    st.stop()

# =========================
# Sidebar filters (ORDER: Category -> Year -> Country -> Regulator)
# =========================
st.sidebar.header("Filters")

categories = ["All"] + sorted(df_all["Category"].dropna().unique().tolist())
sel_category = st.sidebar.selectbox("Category (worksheet)", options=categories, index=0)

df_f = df_all.copy()
if sel_category != "All":
    df_f = df_f[df_f["Category"] == sel_category]

# Year slider
years = df_f["Year"].dropna().astype(int)
if len(years) > 0:
    y_min, y_max = int(years.min()), int(years.max())
    sel_year = st.sidebar.slider("Year", min_value=y_min, max_value=y_max, value=(y_min, y_max))
    df_f = df_f[df_f["Year"].notna()]
    df_f = df_f[(df_f["Year"] >= sel_year[0]) & (df_f["Year"] <= sel_year[1])]
else:
    st.sidebar.caption("No parseable years found in the current category filter.")

countries = sorted(df_f["Country_std"].dropna().unique().tolist())
sel_countries = st.sidebar.multiselect("Country", options=countries, default=countries)
if sel_countries:
    df_f = df_f[df_f["Country_std"].isin(sel_countries)]

regulators = sorted(df_f["Regulator_std"].dropna().unique().tolist())
sel_regulators = st.sidebar.multiselect("Regulator", options=regulators, default=regulators)
if sel_regulators:
    df_f = df_f[df_f["Regulator_std"].isin(sel_regulators)]

# Basic KPI
k1, k2, k3 = st.columns(3)
k1.metric("Regulations (rows)", f"{len(df_f):,}")
k2.metric("Countries", f"{df_f['Country_std'].nunique():,}")
k3.metric("Regulators", f"{df_f['Regulator_std'].nunique():,}")

st.divider()

# =========================
# Tabs (Map default)
# =========================
tab_map, tab_table = st.tabs(["Map", "Table"])

# =========================
# MAP TAB
# =========================
with tab_map:
    st.subheader("Map")

    # Country counts + hover preview
    by_country = (
        df_f.groupby("Country_std", dropna=False)
        .size()
        .reset_index(name="Regulation_Count")
        .rename(columns={"Country_std": "Country"})
    )

    # Build hover text = latest 10 regs per country
    hover_texts = []
    for c in by_country["Country"].tolist():
        latest10 = latest_regs_by_country(df_f, c, n=10)
        hover_texts.append(build_hover_list(latest10))
    by_country["Latest_10"] = hover_texts

    # Choropleth
    fig = px.choropleth(
        by_country,
        locations="Country",
        locationmode="country names",
        color="Regulation_Count",
        hover_name="Country",
        hover_data={"Regulation_Count": True, "Latest_10": True, "Country": False},
    )

    fig.update_geos(
    scope="asia",
    showcountries=True,
    showcoastlines=True,
    fitbounds="locations",
    )

    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=520)
    st.plotly_chart(fig, use_container_width=True)

    st.caption("Hover a country to preview its 10 most recent regulations (based on the current filters).")

    # Country selector to open modal (map click is harder without extra packages)
    map_country = st.selectbox("Open a country details popup", options=["(Select)"] + sorted(by_country["Country"].tolist()))
    if map_country != "(Select)":
        st.session_state["selected_country"] = map_country


# =========================
# TABLE TAB
# =========================
with tab_table:
    st.subheader("Table")

    # Build per-country summary table:
    # columns: Flag, Country (with Regulator), counts per each worksheet name
    all_sheet_names = sorted(df_all["Category"].dropna().unique().tolist())

    regs_by_country = (
        df_f.groupby("Country_std")["Regulator_std"]
        .apply(lambda x: ", ".join(sorted(set([v for v in x.dropna().tolist()]))))
        .reset_index()
        .rename(columns={"Country_std": "Country", "Regulator_std": "Regulator(s)"})
    )

    counts = (
        df_f.groupby(["Country_std", "Category"])
        .size()
        .reset_index(name="Count")
        .pivot(index="Country_std", columns="Category", values="Count")
        .fillna(0)
        .astype(int)
        .reset_index()
        .rename(columns={"Country_std": "Country"})
    )

    t = regs_by_country.merge(counts, on="Country", how="outer").fillna({"Regulator(s)": ""})
    for s in all_sheet_names:
        if s not in t.columns:
            t[s] = 0

    t.insert(0, "Flag", t["Country"].map(lambda x: ASEAN_FLAG.get(str(x), "🏳️")))
    t = t[["Flag", "Country", "Regulator(s)"] + all_sheet_names].sort_values("Country")

    # Use dataframe selection; show preview + open modal
    st.caption("Select a row to preview and open a country popup.")
    event = st.dataframe(
        t,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=520,
    )

    if event and event.selection and event.selection.get("rows"):
        idx = event.selection["rows"][0]
        selected_country = t.iloc[idx]["Country"]
        st.session_state["selected_country"] = selected_country

        # Preview
        st.markdown(f"### Preview: {selected_country}")
        latest10 = latest_regs_by_country(df_f, selected_country, n=10)
        if latest10.empty:
            st.info("No regulations found for this country under the current filters.")
        else:
            preview_lines = []
            for _, r in latest10.iterrows():
                y = r["Year"]
                y_txt = str(int(y)) if pd.notna(y) else "—"
                preview_lines.append(f"- **{y_txt}** — {r['Regulation_Title']}")
            st.markdown("\n".join(preview_lines))


# =========================
# Country popup (modal)
# =========================
@st.dialog("Country regulations")
def country_dialog(country: str):
    st.markdown(f"## {ASEAN_FLAG.get(country, '🏳️')} {country}")

    d = df_f[df_f["Country_std"] == country].copy()
    if d.empty:
        st.info("No regulations found for this country under the current filters.")
        return

    # Quick header info
    regs = sorted(set([x for x in d["Regulator_std"].dropna().tolist()]))
    st.markdown("**Regulator(s):** " + (", ".join(regs) if regs else "—"))
    st.markdown(f"**Total regulations (rows):** {len(d):,}")

    # Show grouped by category
for cat in sorted(d["Category"].dropna().unique().tolist()):
    st.markdown(f"### {cat}")

    dc = d[d["Category"] == cat].copy()
    dc["Year_sort"] = dc["Year"].fillna(-1).astype(int)
    dc = dc.sort_values(["Year_sort", "Regulation_Title"], ascending=[False, True])

    # Columns we don't want to show as "extra details"
    internal_cols = {
        "Category", "Country_std", "Regulator_std", "Year_raw", "Year", "Year_sort",
        "Regulation_Title", "Source_URL"
    }

    # Everything else from the sheet row will be shown as details
    detail_cols = [c for c in dc.columns if c not in internal_cols]

    for i, row in dc.reset_index(drop=True).iterrows():
        y = row["Year"]
        y_txt = str(int(y)) if pd.notna(y) else "—"
        title = row["Regulation_Title"] if pd.notna(row["Regulation_Title"]) else "—"
        regulator = row["Regulator_std"] if pd.notna(row["Regulator_std"]) else "—"
        src_md = safe_linkify(row["Source_URL"])

        header = f"{y_txt} — {title}"

        with st.expander(header, expanded=False):
            st.markdown(f"**Regulator:** {regulator}")
            if src_md:
                st.markdown(f"**Link:** {src_md}")

            if detail_cols:
                # Show remaining columns as a key-value table
                details = (
                    row[detail_cols]
                    .dropna()
                    .astype(str)
                    .to_frame(name="Value")
                )
                details.index.name = "Field"
                st.dataframe(details, use_container_width=True, hide_index=False)
            else:
                st.caption("No additional fields found for this row.")


    st.caption("Links shown as 'Source' are taken directly from the 'Official Source' column in CBregs.xlsx.")


# Fire dialog if a country is chosen
if "selected_country" in st.session_state and st.session_state["selected_country"]:
    country_dialog(st.session_state["selected_country"])
    # optional: clear after showing (keeps UX from reopening on every rerun)
    st.session_state["selected_country"] = None
