# General_Parameters.py
# Provides global operating assumptions and region-specific cost parameters
from __future__ import annotations
import os
import pandas as pd
from path import COST_REGION_XLSX, PRICE_INDEX_DIR

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
    value = _safe_float(row.get(region, 0.0))
    if sheet_name == SHEET_OPEX:
        value *= float(opex_index_info(row)["index_factor"])
    return value


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
    """Cost parameters per region, indexed to OPEX_PRICE_TARGET_DATE where a series is set."""
    region = str(region).strip()
    if region not in REGION_OPEX.columns:
        raise KeyError(
            f"Region column '{region}' not found in sheet '{SHEET_OPEX}' of {REGION_FILE}"
        )
    out = {}
    for _, row in REGION_OPEX.iterrows():
        item = str(row.get("item", "") or "").strip()
        if not item:
            continue
        factor = float(opex_index_info(row)["index_factor"])
        out[item] = _safe_float(row.get(region, 0.0)) * factor
    return out


def get_region_gwp(region: str) -> dict:
    """GWP/emission parameters per region; keys match Excel item names exactly."""
    return _region_values_by_item(REGION_GWP, region, SHEET_GWP)


def get_region_opex_meta() -> dict[str, dict]:
    """Metadata per Excel item from the cost sheet, including the index factor."""
    out = {}
    for _, row in REGION_OPEX.iterrows():
        item = str(row.get("item", "") or "").strip()
        if not item:
            continue
        meta = _meta_for_row(row)
        meta.update(opex_index_info(row))
        out[item] = meta
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
# OPEX / REVENUE PRICE INDICES (FRED workbooks in Input/Price Index)
# Base: annual average of the reference-period year.
# Target: OPEX_PRICE_TARGET_DATE.
# Machine CAPEX stays on INDICES / machine.price_index_factor.
# ============================================================

OPEX_PRICE_TARGET_DATE = "2026-04-01"

_PRICE_INDEX_SKIP = {
    "not escalated (2026 price)",
    "not applicable (location factor)",
}

_SERIES_CACHE: dict[tuple[str, int, str], tuple[pd.Series, int]] = {}


def _row_col(row: pd.Series, name: str):
    lut = {_norm(str(c)): c for c in row.index}
    col = lut.get(_norm(name))
    if col is None:
        return None
    return row.get(col)


def _clean_index_id(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none"}:
        return ""
    return text


def _parse_reference_year(value) -> int | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return int(value.year)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if pd.isna(value):
            return None
        return int(value)
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none"}:
        return None
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return int(float(text))


def _price_index_paths() -> dict[str, str]:
    if not os.path.isdir(PRICE_INDEX_DIR):
        return {}
    out: dict[str, str] = {}
    for name in os.listdir(PRICE_INDEX_DIR):
        if name.startswith("~$") or not name.lower().endswith(".xlsx"):
            continue
        series_id = os.path.splitext(name)[0]
        out[series_id] = os.path.join(PRICE_INDEX_DIR, name)
    return out


def _infer_periods_per_year(series: pd.Series) -> int:
    if len(series) < 3:
        raise ValueError("Price index series is too short to infer its frequency.")
    gaps = series.index.to_series().diff().dt.days.dropna()
    median_gap = float(gaps.median())
    if median_gap >= 60:
        return 4
    return 12


def load_price_index_series(path: str, series_id: str) -> tuple[pd.Series, int]:
    """Load a FRED workbook. Returns the series and 12 (monthly) or 4 (quarterly)."""
    path = os.path.abspath(path)
    mtime = int(os.path.getmtime(path))
    key = (path, mtime, series_id)
    cached = _SERIES_CACHE.get(key)
    if cached is not None:
        return cached

    xl = pd.ExcelFile(path)
    data_sheets = [s for s in xl.sheet_names if str(s).strip().casefold() != "readme"]
    if not data_sheets:
        raise ValueError(f"Price index file '{path}' has no data sheet.")
    sheet = data_sheets[0]
    df = pd.read_excel(path, sheet_name=sheet)
    df.columns = df.columns.astype(str).str.strip()
    if "observation_date" not in df.columns:
        raise ValueError(f"Price index file '{path}' is missing column 'observation_date'.")
    if series_id not in df.columns:
        raise ValueError(f"Price index file '{path}' is missing value column '{series_id}'.")

    dates = pd.to_datetime(df["observation_date"], errors="coerce").dt.normalize()
    values = pd.to_numeric(df[series_id], errors="coerce")
    series = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(dates), dtype="float64")
    series = series[series.index.notna()]
    series = series[series.notna()].sort_index()
    series = series[~series.index.duplicated(keep="last")]

    sheet_name = str(sheet).casefold()
    if "quarter" in sheet_name:
        periods = 4
    elif "month" in sheet_name:
        periods = 12
    else:
        periods = _infer_periods_per_year(series)

    loaded = (series, periods)
    _SERIES_CACHE[key] = loaded
    return loaded


def annual_average_index_factor(
    series: pd.Series,
    reference_year: int,
    *,
    periods_per_year: int,
    target_date: str = OPEX_PRICE_TARGET_DATE,
    item: str = "",
    series_id: str = "",
) -> float:
    """Index(target date) / mean of every observation in the reference year."""
    year = int(reference_year)
    year_obs = series[series.index.year == year]
    label = f"item '{item}'" if item else f"series '{series_id}'"
    if periods_per_year == 12:
        months = {int(m) for m in year_obs.index.month}
        complete = len(year_obs) == 12 and months == set(range(1, 13))
        expected = "12 monthly observations covering January–December"
    elif periods_per_year == 4:
        complete = len(year_obs) == 4
        expected = "4 quarterly observations"
    else:
        raise ValueError(f"Unsupported price-index frequency ({periods_per_year}) for {label}.")
    if not complete:
        raise ValueError(
            f"Price index '{series_id}' for {label}, reference year {year}, "
            f"has {len(year_obs)} observations; expected {expected}."
        )
    base = float(year_obs.mean())
    if base == 0.0:
        raise ValueError(f"Price index '{series_id}' average for {year} is zero ({label}).")
    target = pd.Timestamp(target_date).normalize()
    if target not in series.index:
        raise KeyError(
            f"Price index '{series_id}' has no observation on {target.date().isoformat()} ({label})."
        )
    return float(series.loc[target]) / base


def _blank_index_info(series_id: str = "", reference_year: int | None = None) -> dict:
    return {
        "price_index": series_id,
        "reference_year": "" if reference_year is None else int(reference_year),
        "reference_basis": "",
        "target_date": "",
        "index_factor": 1.0,
    }


def opex_index_info(row: pd.Series) -> dict:
    """Index metadata for one Cost-Parameter row. Factor is 1 when no series applies."""
    item = str(row.get("item", "") or "").strip()
    series_id = _clean_index_id(_row_col(row, "Price index"))
    reference_year = _parse_reference_year(_row_col(row, "Reference period"))
    if not series_id or series_id.casefold() in _PRICE_INDEX_SKIP:
        return _blank_index_info(series_id, reference_year)

    path = _price_index_paths().get(series_id)
    if path is None:
        raise FileNotFoundError(
            f"Price index '{series_id}' for item '{item}' has no workbook in '{PRICE_INDEX_DIR}'."
        )
    if reference_year is None:
        raise ValueError(
            f"Item '{item}' uses price index '{series_id}' but has no reference year."
        )
    series, periods = load_price_index_series(path, series_id)
    factor = annual_average_index_factor(
        series,
        reference_year,
        periods_per_year=periods,
        item=item,
        series_id=series_id,
    )
    return {
        "price_index": series_id,
        "reference_year": int(reference_year),
        "reference_basis": "annual average",
        "target_date": OPEX_PRICE_TARGET_DATE,
        "index_factor": float(factor),
    }


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

