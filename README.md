# PESONet & InstaPay Volume and Value Monitor

A Streamlit dashboard that tracks the monthly transaction **volume** and **value** of the Philippines' two major retail electronic payment systems — **PESONet** and **InstaPay** — using live data published by the **Bangko Sentral ng Pilipinas (BSP)**.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ynigoken/PN-and-IP-Vol-Val)

---

## Features

- **Live BSP data** — fetched directly from official BSP XLSX files on every load (cached hourly, no local file needed)
- **Interactive date filter** — month-range slider + year/month dropdowns
- **KPI metrics** — Selected period totals, YTM (Year-to-Month) with YoY delta, latest quarter QoQ, latest annual YoY
- **Dual-axis chart** — Volume (bar, right axis) overlaid with Value ₱ (line, left axis); dynamic scaling
- **Data tables** — Monthly, Quarterly, Annual, and YTM tabs with CSV download
- **Responsive layout** — wide mode, styled metric cards, dark sidebar

---

## Data Sources

| Series | Source | URL |
|--------|--------|-----|
| PESONet | Philippine Clearing House Corporation (PCHC) via BSP | [PESONet_vv.xlsx](https://www.bsp.gov.ph/PaymentAndSettlement/PESONet_vv.xlsx) |
| InstaPay | BancNet via BSP | [Instapay_vv.xlsx](https://www.bsp.gov.ph/PaymentAndSettlement/Instapay_vv.xlsx) |

Data is refreshed automatically every hour via `@st.cache_data(ttl=3600)`.

---

## Run Locally

```bash
# 1. Clone the repo
git clone https://github.com/ynigoken/PN-and-IP-Vol-Val.git
cd PN-and-IP-Vol-Val

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Run in GitHub Codespaces

Click the badge above or go to **Code → Codespaces → Create codespace on main**.

The devcontainer will automatically:
1. Install all Python dependencies from `requirements.txt`
2. Launch the Streamlit app on port `8501`
3. Open a live preview inside VS Code

---

## Deploy to Streamlit Community Cloud

1. Fork or push this repo to your GitHub account
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
3. Set **Main file path** to `app.py`
4. Click **Deploy** — no secrets or environment variables required

---

## Project Structure

```
PN-and-IP-Vol-Val/
├── app.py                  # Main Streamlit application
├── requirements.txt        # Python dependencies
├── .devcontainer/
│   └── devcontainer.json   # GitHub Codespaces configuration
├── .gitignore
└── README.md
```

---

## Requirements

```
streamlit
pandas
openpyxl
plotly
requests
numpy
```

---

## License

This project is for informational and analytical purposes. Data © Bangko Sentral ng Pilipinas.
