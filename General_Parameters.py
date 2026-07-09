# General_Parameters.py
# Provides global operating assumptions and region-specific cost parameters
from __future__ import annotations
import os
import pandas as pd
from path import COST_REGION_XLSX

REGION_FILE = COST_REGION_XLSX
# ============================================================
# Plant operating schedule assumptions
# ============================================================

WORKING_HOURS_PER_YEAR: float = 350 * 8 * 3   # 8400 h/y
OPERATING_DAYS_PER_YEAR: float = 350.0

def get_working_hours_per_year() -> float:
    return float(WORKING_HOURS_PER_YEAR)

def get_operating_days_per_year() -> float:
    return float(OPERATING_DAYS_PER_YEAR)

# ============================================================
# REGION TABLES (Excel-driven)
# ============================================================

REGION_FILE = COST_REGION_XLSX
SHEET_OPEX = "Cost Parameter"
SHEET_GWP = "GWP Parameter"

META_COLS = [
    "role",
    "economic type",
    "environmental type",
    "category",
    "unit",
]

def _norm(s: str) -> str:
    return str(s).strip().lower()


def _safe_float(v) -> float:
    if isinstance(v, (int, float)) and pd.notna(v):
        return float(v)

    s = str(v or "").strip()
    if not s:
        return 0.0

    s = s.replace(" ", "")
    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # Use the last separator as decimal separator.
        if s.rfind(",") > s.rfind("."):
            # e.g. 1.234,56 -> 1234.56
            s = s.replace(".", "").replace(",", ".")
        else:
            # e.g. 1,234.56 -> 1234.56
            s = s.replace(",", "")
    elif has_comma and not has_dot:
        # e.g. 0,16 -> 0.16
        s = s.replace(",", ".")

    x = pd.to_numeric(pd.Series([s]), errors="coerce").iloc[0]
    return float(x) if pd.notna(x) else 0.0


def _load_table(sheet_name: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(REGION_FILE, sheet_name=sheet_name)
    except Exception as e:
        raise RuntimeError(
            f"Could not load '{REGION_FILE}'. "
            f"Make sure the file exists and contains sheet '{sheet_name}'."
        ) from e

    df.columns = df.columns.astype(str).str.strip()
    col_lut = {_norm(c): c for c in df.columns}
    item_col = col_lut.get("item") or col_lut.get("material")
    if not item_col:
        raise KeyError(
            f"Missing column 'item' (or legacy 'material') in sheet '{sheet_name}' of {REGION_FILE}"
        )
    if item_col != "item":
        df = df.rename(columns={item_col: "item"})

    df["item"] = df["item"].astype(str).str.strip()
    df["__item_norm"] = df["item"].map(_norm)
    return df


REGION_OPEX = _load_table(SHEET_OPEX)
REGION_GWP = _load_table(SHEET_GWP)


def set_region_file(xlsx_path: str) -> None:
    """Switch the cost/GWP workbook used for subsequent scenario calculations."""
    global REGION_FILE, REGION_OPEX, REGION_GWP
    path = os.path.abspath(str(xlsx_path))
    if path == os.path.abspath(str(REGION_FILE)):
        return
    old_file = REGION_FILE
    old_opex = REGION_OPEX
    old_gwp = REGION_GWP
    try:
        REGION_FILE = path
        REGION_OPEX = _load_table(SHEET_OPEX)
        REGION_GWP = _load_table(SHEET_GWP)
    except Exception:
        REGION_FILE = old_file
        REGION_OPEX = old_opex
        REGION_GWP = old_gwp
        raise


def _row_for_item(df: pd.DataFrame, item: str, sheet_name: str) -> pd.Series:
    key = _norm(item)
    r = df.loc[df["__item_norm"] == key]
    if r.empty:
        raise ValueError(f"Item '{item}' not found in sheet '{sheet_name}'.")
    return r.iloc[0]


def _value_for_region(df: pd.DataFrame, region: str, item: str, sheet_name: str) -> float:
    region = str(region).strip()
    if region not in df.columns:
        raise KeyError(
            f"Region column '{region}' not found in sheet '{sheet_name}' of {REGION_FILE}"
        )
    row = _row_for_item(df, item, sheet_name)
    return _safe_float(row.get(region, 0.0))


def _meta_for_row(row: pd.Series) -> dict:
    meta = {}
    for c in META_COLS:
        if c in row.index:
            meta[c] = str(row.get(c, "") or "").strip()
    meta["item"] = str(row.get("item", "") or "").strip()
    return meta


def _region_values_by_item(df: pd.DataFrame, region: str, sheet_name: str) -> dict:
    region = str(region).strip()
    if region not in df.columns:
        raise KeyError(
            f"Region column '{region}' not found in sheet '{sheet_name}' of {REGION_FILE}"
        )
    out = {}
    for _, r in df.iterrows():
        item = str(r.get("item", "") or "").strip()
        if not item:
            continue
        out[item] = _safe_float(r.get(region, 0.0))
    return out


def get_region_opex(region: str) -> dict:
    """Cost parameters per region; keys match Excel item names exactly."""
    return _region_values_by_item(REGION_OPEX, region, SHEET_OPEX)


def get_region_gwp(region: str) -> dict:
    """GWP/emission parameters per region; keys match Excel item names exactly."""
    return _region_values_by_item(REGION_GWP, region, SHEET_GWP)


def get_region_opex_meta() -> dict[str, dict]:
    """Metadata per Excel item from cost sheet (role/type/category/unit/item)."""
    out = {}
    for _, row in REGION_OPEX.iterrows():
        item = str(row.get("item", "") or "").strip()
        if not item:
            continue
        out[item] = _meta_for_row(row)
    return out


def get_region_gwp_meta() -> dict[str, dict]:
    """Metadata per Excel item from GWP sheet (role/type/category/unit/item)."""
    out = {}
    for _, row in REGION_GWP.iterrows():
        item = str(row.get("item", "") or "").strip()
        if not item:
            continue
        out[item] = _meta_for_row(row)
    return out


# ============================================================
# APPLY REGION → ctx
# ============================================================

def apply_region(ctx: dict, region: str) -> dict:
    opex = get_region_opex(region)
    gwp = get_region_gwp(region)

    ctx["region"] = str(region).strip()
    ctx["region_file"] = REGION_FILE
    ctx["currency"] = "USD"  # optional; otherwise unused

    # Excel is single source of truth: keys in prices match the item column exactly.
    ctx["prices"] = dict(opex)

    ctx["building_cost_m2_base"] = float(opex.get("Building costs", 0.0) or 0.0)
    ctx["building_factor"] = float(opex.get("building_factor", 0.0) or 0.0)
    ctx["capex_factor"] = float(opex.get("capex_factor", 0.0) or 0.0)

    # Emission/GWP factors analogous to price logic
    ctx["gwp_factors"] = dict(gwp)

    # Additional metadata from Excel (role, type, category, unit)
    ctx["price_meta"] = get_region_opex_meta()
    ctx["gwp_meta"] = get_region_gwp_meta()

    return ctx

# ============================================================
# PRICE INDICES (for machine.py)
# ============================================================

INDICES = {
    "CEPCI": {
        "2012-01": 584.6,
        "2013-01": 567.3,
        "2014-01": 576.1,
        "2015-01": 556.8,
        "2016-01": 541.7,
        "2017-01": 567.5,
        "2018-01": 603.1,
        "2019-01": 607.5,
        "2020-01": 596.2,
        "2021-01": 708.8,
        "2022-01": 816.0,
        "2023-01": 797.9,
        "2024-06": 798.8,
    },
    "IPPI": {
        "2024-06": 117.1,
        "2024-07": 117.1,
        "2024-08": 117.3,
        "2024-09": 117.1,
        "2024-10": 117.3,
        "2024-11": 117.4,
        "2024-12": 117.5,
        "2025-01": 118.2,
        "2025-02": 118.3,
        "2025-03": 118.2,
        "2025-04": 118.2,
        "2025-05": 118.2,
        "2025-06": 118.2,
        "2025-07": 118.2,
        "2025-06": 119.6,
        "2025-09": 119.6,
        "2025-10": 119.5,
        "2025-11": 119.6,
        "2025-12": 119.5,
        "2026-01": 120.5,
        "2026-02": 120.9,
        "2026-03": 121.0,
        "2026-04": 121.5,
    },
}

