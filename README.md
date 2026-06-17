# PESONet & InstaPay Volume & Value Monitor

A Streamlit dashboard that pulls live BSP data to visualize the monthly volume and value of Philippine retail electronic payments.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ynigoken/PN-and-IP-Vol-Val)

---

## About this project

This is a joint development exploration by **[@ynigoken](https://github.com/ynigoken)** and **[@kevynndelgado](https://github.com/kevynndelgado)**.

We wanted to see how far a single Python file and Streamlit could go as a live, self-updating dashboard — one that reads directly from a government website, with no database, no ETL, and no manual file uploads.

The **Bangko Sentral ng Pilipinas (BSP)** publishes monthly transaction data for the Philippines' two retail electronic fund transfer systems — **PESONet** (batch, operated by PCHC) and **InstaPay** (real-time, operated by BancNet) — as downloadable Excel files. The data is publicly available, consistently structured, and updated regularly, making it a great fit for this kind of experiment.

### What we explored

- **Live URL ingestion** — Can we skip the "download file → clean it → upload it" loop and just point at the source?
- **Resilient parsing** — BSP files have title rows, blank rows, and occasionally bad date entries. Can we detect the header row dynamically instead of hardcoding `header=2`?
- **Offline fallback** — Government sites go down. Can the app cache the last-good data locally and gracefully degrade with a visible warning?
- **One-click deploy** — GitHub Codespaces for dev, Streamlit Community Cloud for public sharing — both from the same repo, zero config.

The result is `app.py` — a ~1,000-line single-file app that does all of the above.

---

## Live data sources

The app fetches directly from BSP on every load (cached for 1 hour):

| Series | Operator | BSP source file |
|--------|----------|-----------------|
| **PESONet** | Philippine Clearing House Corporation (PCHC) | [PESONet_vv.xlsx](https://www.bsp.gov.ph/PaymentAndSettlement/PESONet_vv.xlsx) |
| **InstaPay** | BancNet | [Instapay_vv.xlsx](https://www.bsp.gov.ph/PaymentAndSettlement/Instapay_vv.xlsx) |

If BSP is unreachable, the app loads from a local `.cache/` directory and shows a stale-data banner with the last fetch timestamp.

---

## Dashboard features

- **Payment stream toggle** — PESONet (green theme) or InstaPay (red theme)
- **Interactive date filter** — month-range slider + year/month dropdown pickers
- **KPI cards** — selected-period totals, Year-to-Month (YTM) with YoY change, latest quarter QoQ, latest annual YoY
- **Dual-axis trend chart** — Volume bars (right axis) overlaid with Value ₱ line (left axis); axes scale dynamically
- **Data tables** — Monthly, Quarterly, Annual, and YTM & YTD tabs with CSV download
- **Offline fallback** — transparent stale-data warning when BSP is temporarily down

---

## Run locally

```bash
git clone https://github.com/ynigoken/PN-and-IP-Vol-Val.git
cd PN-and-IP-Vol-Val

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501).

---

## Run in GitHub Codespaces

Click the **Open in GitHub Codespaces** badge at the top, or go to **Code → Codespaces → Create codespace on main**.

The devcontainer will install dependencies and launch the app automatically — a live preview opens inside VS Code on port 8501.

---

## Deploy to Streamlit Community Cloud

1. Fork this repo
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
3. Point to this repo, branch `main`, file `app.py`
4. Click **Deploy** — no secrets or env vars needed

---

## Project structure

```
PN-and-IP-Vol-Val/
├── app.py                   # Streamlit app (single file)
├── requirements.txt         # Python dependencies
├── .streamlit/
│   └── config.toml          # Locks light theme + colours
├── .devcontainer/
│   └── devcontainer.json    # GitHub Codespaces config
├── .gitignore
└── README.md
```

A `.cache/` folder is created at runtime to store offline fallback data. It is gitignored and never committed.

---

## Dependencies

| Package | Purpose |
|---------|--------|
| `streamlit` | Web app framework |
| `pandas` | Data manipulation |
| `openpyxl` | XLSX parsing |
| `plotly` | Interactive charts |
| `requests` | HTTP fetching from BSP |
| `numpy` | Axis tick calculations |

---

## Authors

- **[@ynigoken](https://github.com/ynigoken)**
- **[@kevynndelgado](https://github.com/kevynndelgado)**

---

*Data © Bangko Sentral ng Pilipinas. This is an independent exploration project and is not affiliated with BSP.*
