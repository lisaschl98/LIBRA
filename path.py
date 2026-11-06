# path.py
from __future__ import annotations
import os

# Base: directory containing path.py (= project root)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_input_dir() -> str:
    """
    Locate the Excel input folder (case-insensitive on Linux/Streamlit Cloud).
    Repo standard name is ``Input``; ``input`` also works.
    """
    for name in ("Input", "input", "INPUT"):
        candidate = os.path.join(BASE_DIR, name)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(BASE_DIR, "Input")


INPUT_DIR = _resolve_input_dir()


def _resolve_price_index_dir() -> str:
    """FRED price-index workbooks live in ``Input/Price Index``."""
    direct = os.path.join(INPUT_DIR, "Price Index")
    if os.path.isdir(direct):
        return direct
    if os.path.isdir(INPUT_DIR):
        for name in os.listdir(INPUT_DIR):
            if name.casefold() == "price index" and os.path.isdir(os.path.join(INPUT_DIR, name)):
                return os.path.join(INPUT_DIR, name)
    return direct


# Input workbook paths
COST_REGION_XLSX = os.path.join(INPUT_DIR, "Cost_GWP_Region_Values.xlsx")
PRICE_INDEX_DIR = _resolve_price_index_dir()
CELL_TECH_XLSX = os.path.join(INPUT_DIR, "Pack_Module_Cell_technologies.xlsx")
EFF_XLSX = os.path.join(INPUT_DIR, "Recycling_Efficiencies_Configuration.xlsx")


def assert_input_files() -> None:
    """Raise a clear error if required Excel inputs are missing (e.g. not pushed to Git)."""
    missing = [p for p in (COST_REGION_XLSX, CELL_TECH_XLSX, EFF_XLSX) if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(
            "Required Excel file(s) missing. Commit the Input/ folder to Git:\n"
            + "\n".join(f"  - {p}" for p in missing)
        )
