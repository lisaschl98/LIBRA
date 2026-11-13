from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable

import pandas as pd

from step_utils import resolve_output_item_key
from stoichiometry import FEPO4_C_PRODUCT_RULES, MOLAR_MASS, NMC_PRECURSOR_RULES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_M_H2O = float(MOLAR_MASS["H2O"])
_M_SO4 = float(MOLAR_MASS.get("SO4", 96.06))
_M_NISO4_6H2O = float(MOLAR_MASS["Ni"]) + _M_SO4 + 6.0 * _M_H2O
_M_COSO4_7H2O = float(MOLAR_MASS["CoSO4"]) + 7.0 * _M_H2O
_M_MNSO4_H2O = float(MOLAR_MASS["MnSO4"]) + _M_H2O
_M_FEC2O4_2H2O = float(MOLAR_MASS["FeC2O4_2H2O"])
_M_LIH2PO4 = float(MOLAR_MASS["LiH2PO4"])
_M_FEPO4 = float(MOLAR_MASS["FePO4"])
_FEPO4_C_SOLID_FRAC = 1.0 - float(FEPO4_C_PRODUCT_RULES["carbon_wt_frac_default"])
_M_FE_OH3 = float(MOLAR_MASS["Fe(OH)3"])
_M_AL_OH3 = 78.0
_M_OH = 17.007

_METAL_TARGETS = ("Li", "Ni", "Co", "Mn", "Fe", "Cu", "Al")

# Recovery > this % is invalid (NaN) and triggers the "Exceeds input" note.
_RECOVERY_PCT_CEILING = 100.1
# Structural cap / "recovered capped" note only when recovered mass exceeds input by > this fraction.
_STRUCTURAL_CAP_MIN_EXCESS_FRAC = 0.001

_WASTE_TOKENS: tuple[str, ...] = (
    "wastewater",
    "waste",
    "off-gas",
    "off gas",
    "loss",
    "residue",
    "mother liquor",
    "slurry",
    "slag",
    "flyash",
    "fly ash",
)

_NON_SALEABLE_PRODUCT_TOKENS: tuple[str, ...] = (
    "wastewater",
    "sodium sulfate",
    "calcium sulfate",
    "sand",
)

@dataclass
class LibraRecoveryResult:
    product_output_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    recovery_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    element_recovery: Dict[str, float | None] = field(default_factory=dict)
    overall_metal_recovery: float | None = None
    saleable_product_yield: float | None = None
    saleable_product_mass_kg_h: float = 0.0
    feed_mass_kg_h: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def _norm_name(name: str) -> str:
    return str(resolve_output_item_key(name) or "").strip()


def _norm_lower(name: str) -> str:
    return _norm_name(name).lower()


def _is_waste_name(name: str) -> bool:
    return any(tok in _norm_lower(name) for tok in _WASTE_TOKENS)


def _is_non_saleable_product(name: str) -> bool:
    nl = _norm_lower(name)
    if _is_waste_name(nl):
        return True
    return any(tok in nl for tok in _NON_SALEABLE_PRODUCT_TOKENS)


def _recovery_pct(recovered: float, inp: float) -> float | None:
    if inp <= 0.0:
        return None
    pct = 100.0 * recovered / inp
    if pct < 0.0 or pct > _RECOVERY_PCT_CEILING:
        return None
    return pct


def _saleable_yield_pct(recovered: float, inp: float) -> float | None:
    """Saleable product yield: no upper cap (mass sum may exceed feed); negatives invalid."""
    if inp <= 0.0:
        return None
    pct = 100.0 * recovered / inp
    if pct < 0.0:
        return None
    return pct


def _annual_feed_kg(ctx: dict | None) -> float:
    ctx = ctx or {}
    return _safe_float(ctx.get("feed_mass_kg_per_year"), 0.0)


def _feed_mass_kg_h(ctx: dict | None, steps_df: pd.DataFrame | None) -> float:
    ctx = ctx or {}
    if _safe_float(ctx.get("feed_kg_per_h"), 0.0) > 0.0:
        return _safe_float(ctx.get("feed_kg_per_h"), 0.0)
    mass_y = _annual_feed_kg(ctx)
    hours = _safe_float(ctx.get("hours_per_year"), 0.0)
    if hours > 0.0 and mass_y > 0.0:
        return mass_y / hours
    if steps_df is not None and not steps_df.empty and "In kg/h" in steps_df.columns:
        return _safe_float(steps_df.iloc[0].get("In kg/h"), 0.0)
    return 0.0


def _iter_feed_comp_kg_h(ctx: dict | None) -> Iterable[tuple[str, float]]:
    from recovery_config import iter_unified_feed_comp_kg_h

    return iter_unified_feed_comp_kg_h(ctx)


def _feed_pool_mass_kg_h(
    ctx: dict | None,
    recovery_route: str,
    target: str,
    steps_df: pd.DataFrame | None = None,
) -> float:
    from recovery_config import recovery_input_mass_kg_h

    return recovery_input_mass_kg_h(ctx, recovery_route, target, steps_df)


def _battery_feed_pool_mass_kg_h(ctx: dict | None, recovery_route: str, target: str) -> float:
    from recovery_config import battery_feed_input_mass_kg_h

    return battery_feed_input_mass_kg_h(ctx, recovery_route, target)


def _pyro_iron_hydroxide_iron_pool_fe_kg_h(
    product_mass_kg_h: float,
    ctx: dict | None,
    recovery_route: str,
    steps_df: pd.DataFrame | None,
    *,
    iron_budget_h: float | None = None,
) -> tuple[float, float | None]:
    """
  Pyro only: Fe in iron hydroxide credited to Iron = Iron-pool share of total Fe.

  Steel-origin share is excluded from recovery (steel stays on Steel scrap only).
  Other routes use full hydroxide → Iron via product_contributions.
    """
    from recovery_config import STEEL_FE_MASS_FRAC

    fe_frac = float(MOLAR_MASS["Fe"]) / _M_FE_OH3
    fe_total_h = max(0.0, float(product_mass_kg_h) * fe_frac)
    iron_basis_h = _feed_pool_mass_kg_h(ctx, recovery_route, "Iron", steps_df)
    steel_basis_h = _battery_feed_pool_mass_kg_h(ctx, recovery_route, "Steel") * float(STEEL_FE_MASS_FRAC)
    denom = iron_basis_h + steel_basis_h
    if denom > 1e-12:
        fe_iron_h = fe_total_h * (iron_basis_h / denom)
    else:
        fe_iron_h = fe_total_h

    if iron_budget_h is not None:
        fe_iron_h = min(fe_iron_h, max(0.0, iron_budget_h))
        iron_budget_h = max(0.0, iron_budget_h - fe_iron_h)

    return fe_iron_h, iron_budget_h


def _nmc_precursor_fractions(nmc_code: str) -> tuple[float, float, float]:
    ratios = NMC_PRECURSOR_RULES.get(str(nmc_code), NMC_PRECURSOR_RULES["111"])
    x, y, z = float(ratios["ni"]), float(ratios["co"]), float(ratios["mn"])
    total = x + y + z
    if total <= 0.0:
        return 0.0, 0.0, 0.0
    x, y, z = x / total, y / total, z / total
    m_prec = x * float(MOLAR_MASS["Ni"]) + y * float(MOLAR_MASS["Co"]) + z * float(MOLAR_MASS["Mn"]) + 2.0 * _M_OH
    if m_prec <= 0.0:
        return 0.0, 0.0, 0.0
    return (
        x * float(MOLAR_MASS["Ni"]) / m_prec,
        y * float(MOLAR_MASS["Co"]) / m_prec,
        z * float(MOLAR_MASS["Mn"]) / m_prec,
    )


def _nmc_code_from_product(name: str, default_code: str) -> str:
    m = re.search(r"NMC\s*(\d{3})\s*Precursor", _norm_name(name), flags=re.IGNORECASE)
    return str(m.group(1)) if m else str(default_code or "811")


def _is_nmc_precursor_product(product: str) -> bool:
    nl = _norm_lower(product)
    return "precursor" in nl and "nmc" in nl


_NMC_FEED_METAL_COLS = {
    "Ni": "Ni from battery feed (kg/h)",
    "Co": "Co from battery feed (kg/h)",
    "Mn": "Mn from battery feed (kg/h)",
}

_NMC_SULFATE_MAKEUP_COLS = {
    "Ni": "NiSO4 makeup (kg/h)",
    "Co": "CoSO4 makeup (kg/h)",
    "Mn": "MnSO4 makeup (kg/h)",
}

_NMC_SULFATE_MOLAR_MASS = {
    "Ni": float(MOLAR_MASS["NiSO4"]),
    "Co": float(MOLAR_MASS["CoSO4"]),
    "Mn": float(MOLAR_MASS["MnSO4"]),
}

_NMC_PRECIP_STEP_RE = re.compile(r" – NMC Precipitation$", re.IGNORECASE)


def _nmc_precipitation_step_mask(steps_df: pd.DataFrame) -> pd.Series:
    """Only Hydro NMC / Hydro Mix – NMC Precipitation (not Li/Fe+Al precipitation)."""
    return steps_df["Step"].astype(str).str.contains(_NMC_PRECIP_STEP_RE, na=False)


def _metal_from_sulfate_makeup_kg_h(row: pd.Series, metal: str) -> float:
    col = _NMC_SULFATE_MAKEUP_COLS.get(metal)
    if not col or col not in row.index:
        return 0.0
    m_salt = _safe_float(row.get(col), 0.0)
    if m_salt <= 0.0:
        return 0.0
    mm_salt = _NMC_SULFATE_MOLAR_MASS.get(metal, 0.0)
    mm_metal = float(MOLAR_MASS.get(metal, 0.0))
    if mm_salt <= 0.0 or mm_metal <= 0.0:
        return 0.0
    return m_salt * mm_metal / mm_salt


def _nmc_precursor_battery_shares(steps_df: pd.DataFrame | None) -> dict[str, float]:
    """
    Battery share of each metal inside the precipitated hydroxide.

    ``Ni from battery feed`` is the total metal put into the solid, including sulfate
    makeup. Filtration and washing scale that solid afterwards, so the share stays
    valid on the dried product.
    """
    if steps_df is None or steps_df.empty or "Step" not in steps_df.columns:
        return {}
    sub = steps_df.loc[_nmc_precipitation_step_mask(steps_df)]
    if sub.empty:
        return {}
    out: dict[str, float] = {}
    for metal, col in _NMC_FEED_METAL_COLS.items():
        if col not in sub.columns:
            continue
        used = 0.0
        battery = 0.0
        for _, row in sub.iterrows():
            m_used = _safe_float(row.get(col), 0.0)
            m_mk = _metal_from_sulfate_makeup_kg_h(row, metal)
            used += m_used
            battery += max(0.0, m_used - m_mk)
        if used > 0.0:
            out[metal] = battery / used
        else:
            out[metal] = 0.0
    return out


def _nmc_precursor_feed_contrib_kg_per_kg(
    product: str,
    steps_df: pd.DataFrame | None,
    product_mass_kg_h: float,
) -> dict[str, float]:
    """
    Battery Ni/Co/Mn per kg of dried precursor.

    The product mass already includes precipitation yield, filtration and washing.
    Stoichiometry gives the metal in that mass; the precipitation share removes makeup.
    """
    if not _is_nmc_precursor_product(product) or product_mass_kg_h <= 0.0:
        return {}
    shares = _nmc_precursor_battery_shares(steps_df)
    if not shares:
        return {}
    ni_f, co_f, mn_f = _nmc_precursor_fractions(_nmc_code_from_product(product, "811"))
    fracs = {"Ni": ni_f, "Co": co_f, "Mn": mn_f}
    out: dict[str, float] = {}
    for metal, frac in fracs.items():
        if metal not in shares or frac <= 0.0:
            continue
        out[metal] = float(frac) * float(shares[metal])
    return out


def product_contributions_kg_per_kg(
    product: str,
    ctx: dict | None,
    *,
    steps_df: pd.DataFrame | None = None,
    product_mass_kg_h: float = 0.0,
    rule: Any | None = None,
) -> Dict[str, float]:
    """Target element mass [kg/kg product] for a saleable product on this route."""
    if rule is not None and rule.nmc_precursor_feed_only:
        feed = _nmc_precursor_feed_contrib_kg_per_kg(product, steps_df, product_mass_kg_h)
        if feed:
            return feed
    return _product_recovery_contributions_kg_per_kg_product(product, ctx)


def _product_recovery_contributions_kg_per_kg_product(
    product: str, ctx: dict | None
) -> Dict[str, float]:
    """
    Explicit product → recovery-target mapping [kg target per kg product].
    Returns empty dict if product is not mapped or excluded.
    """
    nl = _norm_lower(product)
    ctx = ctx or {}
    nmc_default = str(ctx.get("nmc_code", "811") or "811")
    out: Dict[str, float] = {}

    if "lithium carbonate" in nl or nl == "li2co3":
        out["Li"] = 2.0 * float(MOLAR_MASS["Li"]) / float(MOLAR_MASS["Li2CO3"])
    elif "lithium dihydrogen" in nl or "lih2po4" in nl.replace(" ", ""):
        out["Li"] = float(MOLAR_MASS["Li"]) / _M_LIH2PO4
        out["P"] = float(MOLAR_MASS["P"]) / _M_LIH2PO4
    elif "fepo4-c" in nl.replace(" ", "") or ("carbon coated" in nl and "phosphate" in nl):
        out["Fe"] = _FEPO4_C_SOLID_FRAC * float(MOLAR_MASS["Fe"]) / _M_FEPO4
        out["P"] = _FEPO4_C_SOLID_FRAC * float(MOLAR_MASS["P"]) / _M_FEPO4
    elif _is_nmc_precursor_product(product):
        # Full stoich fractions only when feed-metal split is unavailable (see build_recovery_table).
        ni_f, co_f, mn_f = _nmc_precursor_fractions(_nmc_code_from_product(product, nmc_default))
        if ni_f > 0.0:
            out["Ni"] = ni_f
        if co_f > 0.0:
            out["Co"] = co_f
        if mn_f > 0.0:
            out["Mn"] = mn_f
    elif "nickel sulfate" in nl or "niso4" in nl.replace(" ", ""):
        out["Ni"] = float(MOLAR_MASS["Ni"]) / _M_NISO4_6H2O
    elif "cobalt sulfate" in nl or "coso4" in nl.replace(" ", ""):
        out["Co"] = float(MOLAR_MASS["Co"]) / _M_COSO4_7H2O
    elif "manganese sulfate" in nl or "mnso4" in nl.replace(" ", ""):
        out["Mn"] = float(MOLAR_MASS["Mn"]) / _M_MNSO4_H2O
    elif "iron oxalate" in nl or "ferrous oxalate" in nl or "fec2o4" in nl.replace(" ", ""):
        out["Fe"] = float(MOLAR_MASS["Fe"]) / _M_FEC2O4_2H2O
    elif "fepo4" in nl.replace(" ", "") or "iron phosphate" in nl:
        out["Fe"] = float(MOLAR_MASS["Fe"]) / _M_FEPO4
        out["P"] = float(MOLAR_MASS["P"]) / _M_FEPO4
    elif nl == "graphite":
        out["Graphite"] = 1.0
    elif "copper scrap" in nl or nl == "copper":
        out["Cu"] = 1.0
    elif "aluminium hydroxide" in nl or "aluminum hydroxide" in nl:
        out["Al"] = float(MOLAR_MASS["Al"]) / _M_AL_OH3
    elif "aluminium scrap" in nl or "aluminum scrap" in nl:
        out["Al"] = 1.0
    elif "iron hydroxide" in nl:
        out["Iron"] = float(MOLAR_MASS["Fe"]) / _M_FE_OH3
    elif "iron scrap" in nl:
        out["Iron"] = 1.0
    elif "steel scrap" in nl or nl == "steel":
        out["Steel"] = 1.0
    elif "electronic scrap" in nl or nl == "electronics":
        out["Electronics"] = 1.0

    return {k: v for k, v in out.items() if v > 0.0}


def _product_output_lines_df(econ: dict | None) -> pd.DataFrame:
    """Raw revenue output lines with category == product."""
    if not isinstance(econ, dict):
        return pd.DataFrame()
    revenue_raw = econ.get("revenue_raw", {})
    if not isinstance(revenue_raw, dict):
        return pd.DataFrame()
    lines = revenue_raw.get("output_lines", []) or []
    if not lines:
        return pd.DataFrame()

    df = pd.DataFrame(lines)
    if df.empty:
        return df

    df["qty_kg_y"] = pd.to_numeric(df.get("qty_kg_y", 0.0), errors="coerce").fillna(0.0)
    df["amount_per_y"] = pd.to_numeric(df.get("amount_per_y", 0.0), errors="coerce").fillna(0.0)
    df["economic_type"] = df.get("economic_type", "").astype(str).str.strip().str.lower()
    df["category"] = df.get("category", "").astype(str).str.strip().str.lower()
    df["item"] = df["item"].astype(str).map(_norm_name)
    df = df[df["category"] == "product"].copy()
    df = df[df["qty_kg_y"] > 0.0].copy()
    if df.empty:
        return df
    if "step_name" not in df.columns:
        df["step_name"] = ""
    else:
        df["step_name"] = df["step_name"].astype(str).str.strip()
    dedup_keys = ["step_name", "item"]
    sum_cols = [c for c in ("qty_kg_y", "amount_per_y") if c in df.columns]
    first_cols = [c for c in df.columns if c not in dedup_keys + sum_cols]
    agg: dict[str, str] = {c: "first" for c in first_cols}
    for c in sum_cols:
        agg[c] = "sum"
    df = df.groupby(dedup_keys, as_index=False).agg(agg)
    return df


def build_product_output_table(
    econ: dict | None,
    ctx: dict | None,
    steps_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Table 1: saleable products aggregated by product name within the scenario
    (e.g. Copper scrap from Pack Dismantle + Cu Filtration → one row).
    """
    annual_feed = _annual_feed_kg(ctx)
    df = _product_output_lines_df(econ)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Product",
                "Total mass (kg/y)",
                "Output (kg/kg feed)",
                "Revenue ($/y)",
                "Revenue share (%)",
                "Contributing steps",
                "Recovery kind",
                "Feed keys (recovery input)",
            ]
        )

    mass_grp = df.groupby("item", as_index=False)["qty_kg_y"].sum().rename(
        columns={"item": "Product", "qty_kg_y": "Total mass (kg/y)"}
    )
    if "step_name" in df.columns:
        steps_grp = (
            df.groupby("item")["step_name"]
            .apply(lambda s: "; ".join(sorted({str(x).strip() for x in s if str(x).strip()})))
            .reset_index()
            .rename(columns={"item": "Product", "step_name": "Contributing steps"})
        )
        mass_grp = mass_grp.merge(steps_grp, on="Product", how="left")
    else:
        mass_grp["Contributing steps"] = ""
    rev_rows = df[df["economic_type"] == "revenue"].copy()
    if not rev_rows.empty:
        rev_grp = (
            rev_rows.groupby("item", as_index=False)["amount_per_y"]
            .sum()
            .rename(columns={"item": "Product", "amount_per_y": "Revenue ($/y)"})
        )
        out = mass_grp.merge(rev_grp, on="Product", how="left")
    else:
        out = mass_grp.copy()
        out["Revenue ($/y)"] = 0.0

    out["Revenue ($/y)"] = pd.to_numeric(out["Revenue ($/y)"], errors="coerce").fillna(0.0)
    out["Output (kg/kg feed)"] = out["Total mass (kg/y)"].apply(
        lambda m: (float(m) / annual_feed) if annual_feed > 0.0 else 0.0
    )
    pos_rev = float(out.loc[out["Revenue ($/y)"] > 0.0, "Revenue ($/y)"].sum())
    out["Revenue share (%)"] = out["Revenue ($/y)"].apply(
        lambda v: (100.0 * float(v) / pos_rev) if pos_rev > 0.0 else 0.0
    )

    from recovery_config import (
        feed_pool_keys,
        find_product_rule,
        get_product_rules,
        resolve_recovery_route,
    )

    rec_route = resolve_recovery_route(ctx)
    rules = get_product_rules(rec_route)
    kinds: list[str] = []
    feed_cols: list[str] = []
    for product in out["Product"].astype(str):
        rule = find_product_rule(product, rules)
        if rule is None:
            kinds.append("—")
            feed_cols.append("—")
            continue
        kinds.append(rule.category)
        contrib = product_contributions_kg_per_kg(product, ctx, rule=rule)
        pool_keys: list[str] = []
        for tgt in contrib:
            pool_keys.extend(feed_pool_keys(rec_route, tgt))
        feed_cols.append(", ".join(dict.fromkeys(pool_keys)))
    out["Recovery kind"] = kinds
    out["Feed keys (recovery input)"] = feed_cols

    out = out.sort_values("Total mass (kg/y)", ascending=False).reset_index(drop=True)
    return out


def _saleable_product_mass_kg_h_from_table(
    product_output_df: pd.DataFrame,
    hours_y: float,
    ctx: dict | None = None,
) -> float:
    """Sum each route-mapped saleable product once (product_output_df is pre-aggregated by name)."""
    if product_output_df.empty or hours_y <= 0.0:
        return 0.0
    rules = None
    if ctx is not None:
        from recovery_config import find_product_rule, get_product_rules, resolve_recovery_route

        rules = get_product_rules(resolve_recovery_route(ctx))
    total_y = 0.0
    for _, row in product_output_df.iterrows():
        product = str(row.get("Product", ""))
        if _is_non_saleable_product(product):
            continue
        if rules is not None and find_product_rule(product, rules) is None:
            continue
        total_y += _safe_float(row.get("Total mass (kg/y)"), 0.0)
    return total_y / hours_y


def build_recovery_table(
    product_output_df: pd.DataFrame,
    ctx: dict | None,
    hours_y: float,
    route: str | None = None,
    steps_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Recovery by target: fixed feed pools (recovery_config) + route-allowed products.
    """
    from recovery_config import (
        ROUTES_IRON_HYDROXIDE_SPLIT_BY_ORIGIN,
        active_targets_for_route,
        find_product_rule,
        get_product_rules,
        process_addition_input_mass_kg_h,
        recovery_table_targets,
        resolve_recovery_route,
        component_targets,
        target_category,
    )

    ctx = ctx or {}
    recovery_route = resolve_recovery_route(ctx) if route is None else str(route).strip().lower()
    if recovery_route not in ("pyro", "lfp", "nmc", "mix"):
        recovery_route = resolve_recovery_route(ctx)

    rules = get_product_rules(recovery_route)
    valid_targets = frozenset(active_targets_for_route(recovery_route)) | frozenset(component_targets())
    detail_targets = [t for t in recovery_table_targets(recovery_route) if t != "active"]

    recovered_kg_h: Dict[str, float] = {}
    products_by_target: Dict[str, list[str]] = {}
    nmc_feed_only_targets: set[str] = set()
    iron_pool_budget_h: float | None = None
    if recovery_route in ROUTES_IRON_HYDROXIDE_SPLIT_BY_ORIGIN:
        iron_pool_budget_h = _feed_pool_mass_kg_h(ctx, recovery_route, "Iron", steps_df)
        if not product_output_df.empty and hours_y > 0.0:
            for _, row in product_output_df.iterrows():
                if "iron scrap" in _norm_lower(str(row.get("Product", ""))):
                    iron_pool_budget_h -= _safe_float(row.get("Total mass (kg/y)"), 0.0) / hours_y
            iron_pool_budget_h = max(0.0, float(iron_pool_budget_h))

    if not product_output_df.empty and hours_y > 0.0 and rules:
        for _, row in product_output_df.iterrows():
            product = str(row.get("Product", ""))
            if _is_non_saleable_product(product):
                continue
            m_kg_h = _safe_float(row.get("Total mass (kg/y)"), 0.0) / hours_y
            if m_kg_h <= 0.0:
                continue

            rule = find_product_rule(product, rules)
            if rule is None:
                continue

            if (
                recovery_route in ROUTES_IRON_HYDROXIDE_SPLIT_BY_ORIGIN
                and "iron hydroxide" in _norm_lower(product)
            ):
                iron_add_h, iron_pool_budget_h = _pyro_iron_hydroxide_iron_pool_fe_kg_h(
                    m_kg_h,
                    ctx,
                    recovery_route,
                    steps_df,
                    iron_budget_h=iron_pool_budget_h,
                )
                if iron_add_h > 1e-12:
                    recovered_kg_h["Iron"] = recovered_kg_h.get("Iron", 0.0) + iron_add_h
                    products_by_target.setdefault("Iron", []).append(product)
                continue

            contrib = product_contributions_kg_per_kg(
                product, ctx, steps_df=steps_df, product_mass_kg_h=m_kg_h, rule=rule
            )
            if rule.nmc_precursor_feed_only and contrib:
                nmc_feed_only_targets.update(contrib.keys())

            for target, frac in contrib.items():
                if target not in valid_targets:
                    continue
                add_h = m_kg_h * float(frac)
                recovered_kg_h[target] = recovered_kg_h.get(target, 0.0) + add_h
                if add_h > 1e-12:
                    products_by_target.setdefault(target, []).append(product)

    rows: list[dict[str, Any]] = []
    for target in detail_targets:
        rec_h_raw = float(recovered_kg_h.get(target, 0.0))
        rec_h = rec_h_raw
        inp_h = _feed_pool_mass_kg_h(ctx, recovery_route, target, steps_df)
        component_capped = False
        if target in nmc_feed_only_targets and inp_h > 0.0:
            rec_h = min(rec_h, inp_h)
        if (
            target in component_targets()
            and inp_h > 0.0
            and (rec_h_raw - inp_h) / inp_h >= _STRUCTURAL_CAP_MIN_EXCESS_FRAC
        ):
            rec_h = inp_h
            component_capped = True
        rec_y = rec_h * hours_y
        inp_y = inp_h * hours_y
        pct = _recovery_pct(rec_y, inp_y)
        prods = sorted(set(products_by_target.get(target, [])))
        cat = target_category(target) or "—"
        notes = f"{cat} | route {recovery_route}"
        if process_addition_input_mass_kg_h(steps_df, recovery_route, target) > 1e-9:
            notes = f"{notes}; incl. process addition"
        if inp_y <= 0.0 and rec_y > 0.0:
            notes = "No feed input in pool"
        elif inp_y > 0.0 and (100.0 * rec_y / inp_y) > _RECOVERY_PCT_CEILING:
            notes = f"Exceeds input ({100.0 * rec_y / inp_y:.1f}%)"
        elif not prods:
            notes = "No mapped products on route"
        if target in nmc_feed_only_targets:
            notes = "NMC precursor excl. sulfate makeup"
        elif (
            target == "Iron"
            and recovery_route in ROUTES_IRON_HYDROXIDE_SPLIT_BY_ORIGIN
            and prods
            and any("iron hydroxide" in _norm_lower(p) for p in prods)
        ):
            notes = f"{notes}; iron hydroxide Fe → Iron pool share only (excl. steel origin)"
        elif component_capped:
            notes = f"{notes}; recovered capped to UNIFIED feed"
        elif target in component_targets() and inp_y > 0.0 and rec_y < inp_y * 0.995 and prods:
            notes = f"{notes}; recovered < feed (partial recovery)"
        rows.append(
            {
                "Category": cat,
                "Target": target,
                "Input mass (kg/y)": inp_y,
                "Recovered mass (kg/y)": rec_y,
                "Recovery (%)": _recovery_pct_value(pct),
                "Products counted": "; ".join(prods) if prods else "—",
                "Notes": notes,
            }
        )

    active_row = _active_material_rollup_row(rows, recovery_route)
    if active_row:
        rows.insert(0, active_row)
    return pd.DataFrame(rows)


def _recovery_pct_value(pct: float | None) -> float:
    """NaN for missing/invalid recovery (keeps Excel export numeric column stable)."""
    if pct is None:
        return math.nan
    return float(pct)


def _active_material_rollup_row(rows: list[dict[str, Any]], recovery_route: str) -> dict[str, Any] | None:
    from recovery_config import active_rollup_targets

    if not rows:
        return None
    rollup = set(active_rollup_targets(recovery_route))
    sub = [r for r in rows if str(r.get("Target", "")) in rollup]
    if not sub:
        return None
    inp_y = sum(_safe_float(r.get("Input mass (kg/y)"), 0.0) for r in sub)
    rec_y = sum(_safe_float(r.get("Recovered mass (kg/y)"), 0.0) for r in sub)
    pct = _recovery_pct(rec_y, inp_y)
    prods: list[str] = []
    for r in sub:
        cell = str(r.get("Products counted", ""))
        if cell != "—":
            prods.extend(p.strip() for p in cell.split(";") if p.strip())
    return {
        "Category": "active",
        "Target": "active",
        "Input mass (kg/y)": inp_y,
        "Recovered mass (kg/y)": rec_y,
        "Recovery (%)": _recovery_pct_value(pct),
        "Products counted": "; ".join(sorted(set(prods))) if prods else "—",
        "Notes": f"Rollup: {', '.join(sorted(rollup))}",
    }


def _overall_metal_recovery(recovery_df: pd.DataFrame) -> float | None:
    metals_in = 0.0
    metals_rec = 0.0
    for m in _METAL_TARGETS:
        sub = recovery_df[recovery_df["Target"].astype(str) == m]
        if sub.empty:
            continue
        inp_y = _safe_float(sub.iloc[0]["Input mass (kg/y)"], 0.0)
        if inp_y <= 0.0:
            continue
        metals_in += inp_y
        metals_rec += _safe_float(sub.iloc[0]["Recovered mass (kg/y)"], 0.0)
    return _recovery_pct(metals_rec, metals_in)


def compute_libra_recovery(
    ctx: dict | None,
    steps_df: pd.DataFrame | None,
    econ: dict | None = None,
) -> LibraRecoveryResult:
    ctx = ctx or {}
    hours_y = _safe_float(ctx.get("hours_per_year"), 8760.0)
    if hours_y <= 0.0:
        hours_y = 8760.0

    feed_kg_h = _feed_mass_kg_h(ctx, steps_df)
    product_output_df = build_product_output_table(econ, ctx, steps_df)
    recovery_df = build_recovery_table(product_output_df, ctx, hours_y, steps_df=steps_df)

    saleable_kg_h = _saleable_product_mass_kg_h_from_table(product_output_df, hours_y, ctx=ctx)
    saleable_yield = _saleable_yield_pct(saleable_kg_h * hours_y, _annual_feed_kg(ctx))
    overall_metal = _overall_metal_recovery(recovery_df)

    from recovery_config import recovery_table_targets, resolve_recovery_route

    rec_route = resolve_recovery_route(ctx)
    element_recovery: Dict[str, float | None] = {}
    for target in recovery_table_targets(rec_route):
        sub = recovery_df[recovery_df["Target"].astype(str) == target]
        if sub.empty:
            element_recovery[target] = None
            continue
        raw_pct = sub.iloc[0]["Recovery (%)"]
        element_recovery[target] = None if pd.isna(raw_pct) else float(raw_pct)

    return LibraRecoveryResult(
        product_output_df=product_output_df,
        recovery_df=recovery_df,
        element_recovery=element_recovery,
        overall_metal_recovery=overall_metal,
        saleable_product_yield=saleable_yield,
        saleable_product_mass_kg_h=saleable_kg_h,
        feed_mass_kg_h=feed_kg_h,
    )


