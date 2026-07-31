# LIBRA — Lithium-Ion Battery Recycling Assessment

**Version:** 1.0 · **DOI:** [10.5281/zenodo.21276866](https://doi.org/10.5281/zenodo.21276866)

**LIBRA** is a process-based techno-economic and environmental assessment model for lithium-ion battery (LIB) recycling. It combines mass and energy balances, equipment sizing, CAPEX/OPEX estimation, revenue accounting, and life-cycle greenhouse-gas indicators in a single framework.

The main user interface is a **Streamlit dashboard** (`app_streamlit.py`). The underlying simulation engine is implemented in Python and can also be run programmatically via `main.py`.

Developed by **Lisa Schlott** at the **Institute of Business Chemistry, University of Münster**.

**Development and AI assistance:** During the preparation of this work, the authors used [Cursor](https://cursor.com/) for assistance in developing parts of the Python code used in the model. After using this tool, the authors carefully reviewed, validated, and edited all outputs as needed, and take full responsibility for the content of the publication.

**Live demo:** [https://lib-recycling-assessment.streamlit.app/](https://lib-recycling-assessment.streamlit.app/)

---

## What LIBRA models

LIBRA supports comparative assessment of LIB recycling routes, including:

- **Discharge, dismantling, and feed preparation**
- **Mechanical pretreatment** (shredding, drying, classification, magnetic separation, etc.)
- **Pyrometallurgical processing** (smelting, gas scrubbing, granulation)
- **Hydrometallurgical refining** for:
  - NMC black mass
  - LFP black mass
  - Mixed NMC + LFP feeds
  - Pyro intermediate products (alloy and slag routes)
- **Infrastructure layouts** (integrated site or hub-and-spoke)
- **Economics** (CAPEX, OPEX, overhead, product revenue)
- **Environmental performance** (regional GWP factors)

---

## Requirements

- **Python 3.12** (see `.python-version`)
- Excel input files in the `Input/` folder (included in this repository)

---

## Installation

```bash
git clone https://github.com/lisaschl98/LIBRA.git
cd LIBRA

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
Typical installation time: approximately 5–10 minutes on a standard desktop computer with a stable internet connection.
```

### Optional: PDF export (Playwright)

PDF generation in the dashboard uses Playwright. After installing Python dependencies:

```bash
playwright install chromium
```

On Linux deployment hosts (e.g. Streamlit Cloud), system libraries listed in `packages.txt` are required.

---

## Quick start

### Live dashboard

Try LIBRA in your browser (no local installation required):

**[https://lib-recycling-assessment.streamlit.app/](https://lib-recycling-assessment.streamlit.app/)**

### Run the dashboard locally

```bash
streamlit run app_streamlit.py
```

Open the local URL shown in the terminal (typically `http://localhost:8501`).

### Run scenarios from Python

```python
from main import SCENARIOS, run_scenario

scen = next(s for s in SCENARIOS if s["name"] == "Mech_10tpy_MIX_unlimited_Co_basis")
steps_df, extras, ctx = run_scenario(scen)

print(steps_df[["Step", "Out kg/h"]].head())
print(extras["Overhead"]["summary"])
```

Example scenarios are defined at the bottom of `main.py` (`SCENARIOS`).

---

## Input data

All default model parameters are read from Excel workbooks in `Input/`:

| File | Purpose |
|------|---------|
| `Pack_Module_Cell_technologies.xlsx` | Cell, module, and pack compositions; feedstock definitions |
| `Cost_GWP_Region_Values.xlsx` | Regional cost items, price indices, machine CAPEX data, GWP factors |
| `Recycling_Efficiencies_Configuration.xlsx` | Step-wise partition, yield, and stream routing (EFF configuration) |

If any of these files are missing, the model raises a clear error on startup (`path.assert_input_files()`).

---

## Repository structure

```
app_streamlit.py          # Streamlit dashboard (main entry point for users)
main.py                   # Scenario orchestration and process route execution
machine.py                # Equipment sizing, CAPEX scaling, and energy helpers
stoichiometry.py          # Chemistry and reagent demand calculations
thermal_energy.py         # Thermal energy models (drying, digestion, roasting, etc.)
infrastructure.py         # Transport, site layout, and infrastructure costing
Save.py                   # Excel export and reporting tables
Input/                    # Default Excel parameter files
S01_... / S02_... / ...   # Individual process step modules
Economics/                # OPEX, overhead, revenue, and profit aggregation
Environmental/            # GWP burden and credit calculations
dashboard_support/        # PDF export, analytics, and UI helpers
tests/                    # Pytest test suite
```

Process steps follow a consistent pattern: each module exposes a `run_*` function returning output streams, a reporting row, and optional extras.

---

## Tests

```bash
python -m pytest tests/ -q
```

The test suite covers recovery scopes, infrastructure logic, thermal-energy helpers, stoichiometry labels, and end-to-end scenario execution.

---

## Deployment (Streamlit Cloud)

**Public instance:** [https://lib-recycling-assessment.streamlit.app/](https://lib-recycling-assessment.streamlit.app/)

This repository is configured for Streamlit Cloud deployment:

- `requirements.txt` — Python dependencies
- `packages.txt` — Linux system libraries for Playwright
- `.python-version` — Python 3.12
- `.streamlit/config.toml` — theme settings

Optional analytics (GoatCounter) can be enabled via `.streamlit/secrets.toml`. A commented template is included; do not commit real API tokens.

---

## Reproducibility notes for publications

When referring to LIBRA results in a paper:

1. State the **LIBRA version** (git commit hash or release tag).
2. Document the **scenario settings** used in the dashboard or `SCENARIOS` dict:
   - route (`mech` / `pyro`)
   - feed composition (cell IDs and shares)
   - annual feed mass (`mass_feed_kg_y`)
   - region and infrastructure mode
   - hydro recovery scope (NMC / LFP / MIX / pyro-hydro)
3. Note the **input workbook versions** in `Input/` if parameters were modified.
4. Export results via the dashboard **Export Center** for archival tables and PDF summaries.

---

## Citation

If you use LIBRA in academic work, please cite the **concept DOI** (covers all versions):

- **DOI:** [10.5281/zenodo.21276866](https://doi.org/10.5281/zenodo.21276866)
- **Version 1.0:** [10.5281/zenodo.21276867](https://doi.org/10.5281/zenodo.21276867)
- **Zenodo record:** [zenodo.org/records/21276867](https://zenodo.org/records/21276867)

```bibtex
@software{libra2026,
  author    = {Schlott, Lisa},
  title     = {LIBRA: Lithium-Ion Battery Recycling Assessment},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.21276866},
  url       = {https://github.com/lisaschl98/LIBRA},
  version   = {1.0}
}
```



---

## Funding

Development of LIBRA was supported by the **ProRec** project (2023–2026), funded by the **German Federal Ministry of Education and Research (BMBF)** under grant number **03XP0537A**.

---

## License

This project is licensed under the [Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/) (CC BY 4.0).

You may redistribute and reuse this work if the creators are appropriately credited. See [`LICENSE`](LICENSE) for details.

---

## Contact

**Lisa Schlott**  
Institute of Business Chemistry  
University of Münster  

For questions about the model or data, please open a GitHub issue in this repository.
