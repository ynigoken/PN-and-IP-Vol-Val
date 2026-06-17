# PESONet & InstaPay Volume and Value Monitor

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ynigoken/PN-and-IP-Vol-Val)

---

## About this project

The **Bangko Sentral ng Pilipinas (BSP)** publishes monthly transaction data for the Philippines' two main retail electronic fund transfer systems — **PESONet** (batch) and **InstaPay** (real-time) — as downloadable Excel files on their website. The data is publicly available, consistently structured, and updated regularly, which made it a great candidate for a live dashboard experiment.

The goal of this project was to explore whether Streamlit could serve as a lightweight but polished interface for referencing a live government data source directly — no database, no ETL pipeline, no manual file uploads. Just a URL, a Python script, and a deploy button.

The result is a single-file app that:
- Fetches the latest BSP XLSX files on load from `bsp.gov.ph`
- Parses them dynamically (the header row is detected automatically, not assumed)
- Computes KPIs across different time horizons — selected range, YTM, quarterly, annual
- Falls back to a local cache if BSP is temporarily unreachable, with a visible warning
- Deploys in one click to Streamlit Community Cloud or runs instantly in GitHub Codespaces

---

## Live data sources

The app reads directly from these BSP-published files — no local copies, no manual refresh:

| Series | Clearing operator | BSP source file |
|--------|------------------|-----------------|
| **PESONet** | Philippine Clearing House Corporation (PCHC) | [PESONet_vv.xlsx](https://www.bsp.gov.ph/PaymentAndSettlement/PESONet_vv.xlsx) |
| **InstaPay** | BancNet | [Instapay_vv.xlsx](https://www.bsp.gov.ph/PaymentAndSettlement/Instapay_vv.xlsx) |

Data is cached for one hour per session. If BSP is unreachable, the app falls back to the last successfully fetched copy stored locally and shows a warning banner with the cache timestamp.

---

## Dashboard features

- **Payment stream toggle** — switch between PESONet and InstaPay in the sidebar
- **Interactive date filter** — drag a month-range slider or use the year/month dropdowns
- **KPI cards** — selected period totals, Year-to-Month (YTM) with YoY change, latest quarter QoQ, latest annual YoY
- **Dual-axis trend chart** — Volume as bars (right axis) overlaid with Value ₱ as a line (left axis); scales dynamically to the filtered data
- **Data tables** — four tabs: Monthly (filtered), Quarterly, Annual, YTM & YTD — all with CSV download
- **Offline fallback** — last-good data cached locally; shown with a stale-data banner if BSP is down

---

## Run locally

```bash
# Clone
git clone https://github.com/ynigoken/PN-and-IP-Vol-Val.git
cd PN-and-IP-Vol-Val

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501).

---

## Run in GitHub Codespaces

Click the **Open in GitHub Codespaces** badge at the top of this page.

The devcontainer will install dependencies and launch the app automatically on port 8501, opening a live preview inside VS Code — no local setup needed.

---

## Deploy to Streamlit Community Cloud

1. Fork this repo to your GitHub account
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
3. Point it to this repo, branch `main`, file `app.py`
4. Click **Deploy** — no secrets or environment variables required

---

## Project structure

```
PN-and-IP-Vol-Val/
├── app.py                   # Streamlit app (single file)
├── requirements.txt         # Python dependencies
├── .devcontainer/
│   └── devcontainer.json    # GitHub Codespaces config
├── .gitignore
└── README.md
```

A `.cache/` folder is created at runtime to store offline fallback data. It is gitignored and never committed.

---

## Dependencies

```
streamlit
pandas
openpyxl
plotly
requests
numpy
```

---

*Data © Bangko Sentral ng Pilipinas. This project is an independent exploration and is not affiliated with BSP.*
