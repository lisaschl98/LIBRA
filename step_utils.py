# step_utils.py
from __future__ import annotations

import pandas as pd
import General_Parameters as gp
import machine as ms

from Massflow import MassFlow


# -------------------------- basics --------------------------

def hours_per_year(ctx: dict) -> float:
    return float(ctx.get("hours_per_year") or gp.get_working_hours_per_year())


def denom_mixed_feed_kg_y(ctx: dict) -> float:
    """
    Normalization basis for ALL $/kg: Mixed feed mass.
    UNIFIED sets this as ctx["feed_mass_kg_per_year"].
    """
    return float(ctx.get("feed_mass_kg_per_year") or 0.0)


PACK_DISMANTLE_STEP = "Pack Dismantle"


def feed_has_pack_from_feed_list(feed: list | None) -> bool:
    """True when the UNIFIED feed list includes pack-level input with positive share."""
    if not feed:
        return False
    for item in feed:
        if not isinstance(item, dict):
            continue
        if str(item.get("level", "")).strip().lower() != "pack":
            continue
        if float(item.get("share") or 0.0) > 1e-12:
            return True
    return False


def feed_has_pack_level(ctx: dict | None) -> bool:
    """True when the active scenario feed includes pack-level battery input."""
    if not ctx:
        return False
    if bool(ctx.get("feed_has_pack")):
        return True
    if float(ctx.get("pack_mass_kg_per_year") or 0.0) > 1e-12:
        return True
    for row in (ctx.get("feed_details") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("level", "")).strip().lower() != "pack":
            continue
        if float(row.get("share") or 0.0) > 1e-12:
            return True
    return False


def is_pack_dismantle_step(step: str) -> bool:
    return str(step or "").strip().casefold() == PACK_DISMANTLE_STEP.casefold()


# Step reporting columns (kg/h) → Excel price/GWP item keys (ctx["prices"], ctx["gwp_factors"]).
# Keep in sync with Save.py ``materials_added_cols``; exclude circulating solvent inventory
# (e.g. DMF/D2EHPA/Kerosene circulating) — only makeup/added columns belong here.
REAGENT_COLUMNS_BY_PRICE_ITEM: dict[str, list[str]] = {
    "Limestone": ["Limestone added (kg/h)"],
    "Sand": ["Sand added (kg/h)"],
    "Oxygen": ["Oxygen added (kg/h)"],
    "Sulfuric acid (95%)": [
        "H2SO4 95% added (kg/h)",
        "H2SO4 95% added for stripping (kg/h)",
    ],
    "Water": [
        "H2O added (kg/h)",
        "H2O added 2 (kg/h)",
        "Water added (kg/h)",
        "H2O added NMC (kg/h)",
        "Water for oxalic solution (kg/h)",
        "Wash water added (kg/h)",
        "Water added for washing (kg/h)",
        "NaOH solution water added (kg/h)",
    ],
    "Iron powder": ["Fe added (kg/h)"],
    "Hydrogen peroxide": ["H2O2 added (kg/h)"],
    "Sodium hydroxide (50%)": [
        "NaOH added (kg/h)",
        "NaOH 50% (kg/h)",
        "NaOH 50% added for NMC precipitation (kg/h)",
        "NaOH 50% for sulfate neutralization (kg/h)",
        "NaOH 50% for extraction pH (kg/h)",
    ],
    "Ammonia (25%)": ["NH3 solution (kg/h)", "NH3 solution makeup (kg/h)"],
    "Nickel sulfate": ["NiSO4 makeup (kg/h)"],
    "Cobalt sulfate": ["CoSO4 makeup (kg/h)"],
    "Manganese sulfate": ["MnSO4 makeup (kg/h)"],
    "Sodium carbonate": ["Na2CO3 added (kg/h)"],
    "Oxalic acid": ["Oxalic acid pure added (kg/h)"],
    "Ethanol": ["Ethanol added (kg/h)"],
    "CH-90 Na resin": ["CH-90 Na makeup (kg/h)"],
    "PVP": ["PVP added (kg/h)"],
    "DMF": ["DMF make-up (kg/h)"],
    "D2EHPA": ["D2EHPA added (kg/h)"],
    "Cyanex 272": ["Cyanex 272 added (kg/h)"],
    "Cyanex 301GN": ["Cyanex 301GN added (kg/h)"],
    "Nitrogen": ["Nitrogen for shredding (kg/h)"],
}

# If the primary column is set, secondary columns are omitted from chem_use (massflow reports the primary only).
REAGENT_SUPPRESS_IF_PRIMARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Oxalic acid pure added (kg/h)",
        ("Oxalic acid solution added (kg/h)",),
    ),
)

# Massflow display labels (_standardize_display_name) → Excel price/GWP keys for cross-checks.
# Step / massflow output labels → Excel price/GWP item keys (outputs_kg_h, revenue, credits).
OUTPUT_ITEM_ALIASES: dict[str, str] = {
    "Lithium Carbonate anhydrous": "Lithium carbonate",
    "Lithium Carbonate Anhydrous": "Lithium carbonate",
    "Wastewater treated": "Wastewater",
    "Wastewater Treated": "Wastewater",
    "Copper": "Copper scrap",
    "Iron Oxalate": "Ferrous oxalate",
    "CaSO4": "Calcium sulfate",
    "CoSO4*7H2O": "Cobalt sulfate",
    "NiSO4*6H2O": "Nickel sulfate",
    "MnSO4·H2O": "Manganese sulfate",
    "MnSO4*H2O": "Manganese sulfate",
}

# Massflow separated display label → Excel output item key (for cross-checks).
MASSFLOW_SEPARATED_TO_OUTPUT_ITEM: dict[str, str] = {
    "Pack Aluminium": "Aluminium scrap",
    "Pack Copper": "Copper scrap",
    "Pack Iron": "Iron scrap",
    "Pack Steel": "Steel scrap",
    "Pack Electronics": "Electronic scrap",
    "Pack Other/Waste": "Waste",
    "Steel From Cell Packaging": "Steel scrap",
    "Steel From Modules": "Steel scrap",
    "Aluminium From Cell Packaging": "Aluminium scrap",
    "Aluminium From Modules": "Aluminium scrap",
    "Aluminium Foil": "Aluminium scrap",
    "Copper From Modules": "Copper scrap",
    "Copper Foil": "Copper scrap",
    "Copper": "Copper scrap",
    "Electronics From Modules": "Electronic scrap",
    "Plastic From Modules": "Plastics",
    "Plastic (Separator + Pouch Foil)": "Plastics",
    "Graphite": "Graphite",
    "Lithium Carbonate Anhydrous": "Lithium carbonate",
    "Carbon coated Iron Phosphate (FePO4-C)": "Carbon coated Iron Phosphate (FePO4-C)",
    "Sodium Sulfate": "Sodium sulfate",
    "Wastewater Treated": "Wastewater",
    "NMC 622 Precursor": "NMC 622 Precursor",
    "NMC Precursor": "NMC 622 Precursor",
    "Mix NMC cake": "NMC 622 Precursor",
    "Iron Oxalate": "Ferrous oxalate",
    "Lithium dihydrogenphosphate": "Lithium dihydrogenphosphate",
    "Lithium Dihydrogen Phosphate": "Lithium dihydrogenphosphate",
    "Sand": "Sand",
    "CaSO4": "Calcium sulfate",
    "Iron hydroxide": "Iron hydroxide",
    "Aluminium hydroxide": "Aluminium hydroxide",
    "Cobalt Sulfate (CoSO4·7 H2O)": "Cobalt sulfate",
    "Nickel Sulfate (NiSO4·6 H2O)": "Nickel sulfate",
    "Manganese Sulfate (MnSO4·H2O)": "Manganese sulfate",
    "Flyash": "Flyash",
}

MASSFLOW_LABEL_TO_PRICE_ITEM: dict[str, str] = {
    "Ammonia Makeup": "Ammonia (25%)",
    "CH-90 Na resin makeup": "CH-90 Na resin",
    "Cyanex 272": "Cyanex 272",
    "D2EHPA": "D2EHPA",
    "DMF make-up": "DMF",
    "Ethanol": "Ethanol",
    "Hydrogen Peroxide": "Hydrogen peroxide",
    "Iron Powder": "Iron powder",
    "Limestone": "Limestone",
    "Nickel Sulfate": "Nickel sulfate",
    "Cobalt Sulfate": "Cobalt sulfate",
    "Manganese Sulfate": "Manganese sulfate",
    "Nitrogen": "Nitrogen",
    "Oxalic acid": "Oxalic acid",
    "Oxygen": "Oxygen",
    "PVP": "PVP",
    "Sand": "Sand",
    "Sodium Carbonate": "Sodium carbonate",
    "Sodium Hydroxide 50%": "Sodium hydroxide (50%)",
    "Sulfuric Acid 95%": "Sulfuric acid (95%)",
    "Water": "Water",
}


def resolve_output_item_key(item: str) -> str:
    """Map step/massflow output label to Excel economics/GWP item key."""
    s = str(item or "").strip()
    if not s:
        return s
    return OUTPUT_ITEM_ALIASES.get(s, s)


def flatten_outputs_kg_h(raw) -> dict[str, float]:
    """Normalize row['outputs_kg_h'] from dict or list-of-dict to {item: kg/h}."""
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = []
        for el in raw:
            if isinstance(el, dict):
                items.extend(el.items())
    else:
        return {}

    out: dict[str, float] = {}
    for k, v in items:
        try:
            q = float(v or 0.0)
        except (TypeError, ValueError):
            q = 0.0
        if q <= 0.0:
            continue
        key = resolve_output_item_key(str(k))
        out[key] = out.get(key, 0.0) + q
    return out


def _suppressed_reagent_columns(row: pd.Series) -> set[str]:
    suppressed: set[str] = set()
    for primary, blocked in REAGENT_SUPPRESS_IF_PRIMARY:
        try:
            primary_v = float(row.get(primary, 0.0) or 0.0)
        except (TypeError, ValueError):
            primary_v = 0.0
        if primary_v > 0.0:
            suppressed.update(blocked)
    return suppressed


def build_chem_use_kg_h_from_row(row: pd.Series, columns: pd.Index) -> dict[str, float]:
    """Build chem_use [kg/h] from step reporting columns (idempotent; no merge with prior chem_use)."""
    suppressed = _suppressed_reagent_columns(row)

    def _col_kg_h(col: str) -> float:
        if col in suppressed or col not in columns:
            return 0.0
        try:
            v = float(row.get(col, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return v if v > 0.0 else 0.0

    chem_use: dict[str, float] = {}
    for item, cols in REAGENT_COLUMNS_BY_PRICE_ITEM.items():
        qty = sum(_col_kg_h(c) for c in cols)
        if qty > 0.0:
            chem_use[item] = chem_use.get(item, 0.0) + qty
    return chem_use


def annual_input_tons_from_flow(flow: MassFlow, ctx: dict) -> float:
    # flow kg/h -> t/y
    return float(flow.mass_kg_per_h) * hours_per_year(ctx) / 1000.0


def prices(ctx: dict) -> dict:
    return (ctx.get("prices") or {})


# -------------------------- row helpers --------------------------

def _comp_abs_to_mass(comp_abs: dict, m_target: float) -> dict:
    comp_abs = {str(k): float(v) for k, v in (comp_abs or {}).items() if abs(float(v)) > 1e-12}
    m_target = float(m_target)
    if m_target <= 1e-12:
        return {}
    s = float(sum(comp_abs.values()))
    if s <= 1e-12:
        return {"__untracked__": m_target}
    if abs(s - m_target) > 1e-9:
        f = m_target / s
        comp_abs = {k: v * f for k, v in comp_abs.items()}
    return comp_abs


def nmc_filtration_apply_lye_split(
    flow_in: MassFlow,
    outputs: dict,
    *,
    forward_key: str,
    precursor_key: str = "NMC Precursor",
    loss_key: str = "loss",
) -> tuple[MassFlow, MassFlow, float, float, dict]:
    """
    Report the filtration split already produced by EFF.

    The inlet slurry contains the precursor solid. Precipitation has already
    moved the unrecovered solid to the loss sink, and the filtration yield
    keeps its share on the cake. This function does not put the cake back to
    the stoichiometric mass.
    """
    import Recycling_Efficiencies as rfx

    meta_in = dict(getattr(flow_in, "meta", {}) or {})
    m_in = float(flow_in.mass_kg_per_h)
    precursor_h = float(rfx.mf_get(outputs, precursor_key).mass_kg_per_h)
    lye_h = float(rfx.mf_get(outputs, forward_key).mass_kg_per_h)
    flow_report = MassFlow(m_in, meta=meta_in)
    return flow_report, flow_report, lye_h, precursor_h, outputs


def make_row(step: str, in_flow: MassFlow, out_flow: MassFlow, **extra) -> pd.DataFrame:
    base = {
        "Step": step,
        "In kg/h": float(in_flow.mass_kg_per_h),
        "Out forward kg/h": float(out_flow.mass_kg_per_h),
        # Economics reporting contract (defaults)
        "E_kWh_h": 0.0,
        "m_water_kg_h": 0.0,
        "labor_h_h": 0.0,
        "maintenance_per_y": 0.0,
        "depreciation_per_y": 0.0,
        "supplies_per_y": 0.0,
        "chem_use_kg_h": {},
    }
    base.update(extra)
    return pd.DataFrame([base])


def capex_breakdown_df(step: str, machine_name: str, sizing: dict) -> pd.DataFrame:
    """
    Save.py looks for extras[step]["breakdown"] or ["capex_breakdown"] with these columns.
    """
    return pd.DataFrame([{
        "Step": step,
        "Unit": machine_name,
        "n_lines": float(sizing.get("n_lines", 0.0)),
        "line_tph": float(sizing.get("line_capacity_tph", 0.0)),
        "CAPEX equip ($)": float(sizing.get("capex_equip", 0.0)),
        "CAPEX building ($)": float(sizing.get("capex_building", 0.0)),
    }])


# -------------------------- sizing --------------------------

def size_machine_for_mass(
    step: str,
    machine: ms.Machine,
    in_flow: MassFlow,
    ctx: dict,
    *,
    design_load: float = 0.85,
    max_lines: int = 600,
) -> dict:
    annual_t = annual_input_tons_from_flow(in_flow, ctx)

    sizing = machine.size_and_capex(
        annual_input_tons=annual_t,
        target_date=ctx.get("capex_target_date", ms.TARGET_DATE),
        indices=gp.INDICES,
        ctx=ctx,
        design_load=float(design_load),   # important
        max_lines=int(max_lines),
    )
    sizing["design_load"] = float(design_load)  # optional for reporting/debug

    # building
    try:
        bld = machine.calc_building_investment_costs(int(sizing.get("n_lines", 0)), ctx)
    except Exception:
        bld = 0.0
    sizing["capex_building"] = float(bld)

    return sizing

# -------------------------- OPEX attach --------------------------

def attach_opex_to_row(
    row: pd.DataFrame,
    *,
    machine: ms.Machine,
    sizing: dict,
    ctx: dict,
    load_actual: float = 1.0,
    energy_kwh_y: float = 0.0,
    water_m3_y: float = 0.0,
    materials_cost_y: float = 0.0,
    add_perkg: bool = True,
) -> pd.DataFrame:
    """
    Adds the Save.py-relevant OPEX columns:
      - Energy ($/y), Water ($/y), Materials ($/y), Operating Labor ($/y), Utilities ($/y)
    AND (your "old" analytics output extras):
      - Depreciation $/kg, Maintenance $/kg, Supplies $/kg, Building oper $/kg (and $/y)
    Normalized per kg ALWAYS by ctx['feed_mass_kg_per_year'] (mixed feed).
    """

    denom_kg_y = denom_mixed_feed_kg_y(ctx)

    pr = prices(ctx)
    el_price = float(pr.get("Electricity", 0.0) or 0.0)
    water_price = float(pr.get("Water", 0.0) or 0.0)
    wage = float(pr.get("Labor", 0.0) or 0.0)

    n_lines = float(sizing.get("n_lines", 0.0) or 0.0)

    # --- energy / water / materials ---
    energy_cost_y = float(energy_kwh_y) * el_price
    water_cost_y = float(water_m3_y) * water_price
    mat_cost_y = float(materials_cost_y)

    # --- operating labor ---
    # Your old logic was: labor per day * 365 * load_actual * n_lines
    working_days = float(gp.get_operating_days_per_year())
    labor_per_day_per_line = float(getattr(machine, "labor", 0.0) or 0.0)
    labor_h_y = labor_per_day_per_line * n_lines * working_days * float(load_actual)
    labor_cost_y = labor_h_y * wage

    utilities_cost_y = energy_cost_y + water_cost_y

    # --- "old" extras: depreciation, maintenance, supplies, building opex ---
    capex_equip = float(sizing.get("capex_equip", 0.0) or 0.0)
    capex_installed = float(sizing.get("capex_installed", 0.0) or 0.0)  # might not exist for all
    

    # depreciation
    depreciation_y = 0.0
    f = getattr(machine, "depreciation_from_purchased", None)
    if callable(f):
        try:
            depreciation_y = float(f(capex_equip))
        except Exception:
            depreciation_y = 0.0

    # maintenance
    maintenance_y = 0.0
    f = getattr(machine, "maintenance_from_installed", None)
    if callable(f):
        try:
            maintenance_y = float(f(capex_installed))
        except Exception:
            maintenance_y = 0.0

    # supplies
    supplies_y = 0.0
    f = getattr(machine, "supplies_from_maintenance", None)
    if callable(f):
        try:
            supplies_y = float(f(maintenance_y))
        except Exception:
            supplies_y = 0.0

    # building operating costs (either per-kg helper OR annual helper)
    building_oper_y = 0.0
    f = getattr(machine, "calc_annual_building_costs_per_kg", None)
    if callable(f) and denom_kg_y > 0:
        try:
            building_oper_y = float(f(int(n_lines), float(denom_kg_y), ctx)) * float(denom_kg_y)
        except Exception:
            building_oper_y = 0.0
    else:
        # optional: if you have an annual building cost helper
        f2 = getattr(machine, "calc_annual_building_costs", None)
        if callable(f2):
            try:
                building_oper_y = float(f2(int(n_lines), ctx))
            except Exception:
                building_oper_y = 0.0

    # --- write $/y columns Save.py reads ---
    row["Energy ($/y)"] = energy_cost_y
    row["Water ($/y)"] = water_cost_y
    row["Materials ($/y)"] = mat_cost_y
    row["Operating Labor ($/y)"] = labor_cost_y
    row["Utilities ($/y)"] = utilities_cost_y

    # --- optional per-kg columns (your analytics sheet used these) ---
    if add_perkg:
        fkg = (1.0 / denom_kg_y) if denom_kg_y > 0 else 0.0

        row["Energy $/kg"] = energy_cost_y * fkg
        row["Water $/kg"] = water_cost_y * fkg
        row["Materials $/kg"] = mat_cost_y * fkg
        row["Labor $/kg"] = labor_cost_y * fkg

        row["Depreciation $/kg"] = depreciation_y * fkg
        row["Maintenance $/kg"] = maintenance_y * fkg
        row["Supplies $/kg"] = supplies_y * fkg
        row["Building oper $/kg"] = building_oper_y * fkg

        row["OPEX $/kg (netto)"] = (
            row["Materials $/kg"].iloc[0]
            + row["Energy $/kg"].iloc[0]
            + row["Water $/kg"].iloc[0]
            + row["Labor $/kg"].iloc[0]
            + row["Depreciation $/kg"].iloc[0]
            + row["Maintenance $/kg"].iloc[0]
            + row["Supplies $/kg"].iloc[0]
            + row["Building oper $/kg"].iloc[0]
        )

        row["Annual OPEX ($/y)"] = float(row["OPEX $/kg (netto)"].iloc[0]) * float(denom_kg_y or 0.0)

    # keep some annual extras (optional but helpful)
    row["Depreciation ($/y)"] = depreciation_y
    row["Maintenance ($/y)"] = maintenance_y
    row["Supplies ($/y)"] = supplies_y
    row["Building oper ($/y)"] = building_oper_y

    # Economics reporting contract backfill (do not overwrite explicit values)
    h_y = float(hours_per_year(ctx) or 0.0)
    if "E_kWh_h" not in row.columns:
        row["E_kWh_h"] = (float(energy_kwh_y) / h_y) if h_y > 0 else 0.0
    if "m_water_kg_h" not in row.columns:
        row["m_water_kg_h"] = 0.0
    if "labor_h_h" not in row.columns:
        row["labor_h_h"] = (float(labor_h_y) / h_y) if h_y > 0 else 0.0
    if "maintenance_per_y" not in row.columns:
        row["maintenance_per_y"] = maintenance_y
    if "depreciation_per_y" not in row.columns:
        row["depreciation_per_y"] = depreciation_y
    if "supplies_per_y" not in row.columns:
        row["supplies_per_y"] = supplies_y
    if "chem_use_kg_h" not in row.columns:
        row["chem_use_kg_h"] = [{}]

    return row


def normalize_row_for_economics(row: pd.DataFrame, ctx: dict) -> pd.DataFrame:
    """
    Normalize a step reporting row so Economics/Opex.py and Economics/Overhead.py
    can use it as single source of truth without changing process logic.
    """
    if row is None or row.empty:
        return row

    out = row.copy()
    h_y = float(hours_per_year(ctx) or 0.0)
    denom_kg_y = float(denom_mixed_feed_kg_y(ctx) or 0.0)

    r0 = out.iloc[0]

    def _f(v, default=0.0):
        try:
            x = float(v)
            return x
        except Exception:
            return float(default)

    def _pick(*keys, default=0.0):
        for k in keys:
            if k in out.columns:
                v = _f(r0.get(k, default), default)
                if v != 0.0:
                    return v
        return float(default)

    # Energy / water / labor rates (per hour)
    e_kwh_h = _pick("E_kWh_h", "Energy (kWh/h)", default=0.0)
    if e_kwh_h == 0.0 and h_y > 0.0:
        e_kwh_h = _pick("Energy (kWh/y)", "Energy total (kWh/y)", "Heater energy (kWh/y)", default=0.0) / h_y

    # Process water is in chem_use (reagent columns). No machine supplies water (water_m3_y is always 0).
    m_water_kg_h = _pick("m_water_kg_h", default=0.0)
    labor_h_h = _pick("labor_h_h", default=0.0)

    # If only annual labor cost exists, estimate labor hours via wage
    if labor_h_h == 0.0 and h_y > 0.0:
        pr = prices(ctx)
        wage = float(pr.get("Labor", 0.0) or 0.0)
        labor_cost_y = _pick("Operating Labor ($/y)", "Labor ($/y)", default=0.0)
        if wage > 0.0:
            labor_h_h = labor_cost_y / wage / h_y

    # Maintenance / depreciation / supplies in $/y
    maintenance_per_y = _pick("maintenance_per_y", "Maintenance ($/y)", default=0.0)
    depreciation_per_y = _pick("depreciation_per_y", "Depreciation ($/y)", default=0.0)
    supplies_per_y = _pick("supplies_per_y", "Supplies ($/y)", default=0.0)

    # Backfill from $/kg if annual values are missing
    if denom_kg_y > 0.0:
        if maintenance_per_y == 0.0:
            maintenance_per_y = _pick("Maintenance $/kg", default=0.0) * denom_kg_y
        if depreciation_per_y == 0.0:
            depreciation_per_y = _pick("Depreciation $/kg", default=0.0) * denom_kg_y
        if supplies_per_y == 0.0:
            supplies_per_y = _pick("Supplies $/kg", default=0.0) * denom_kg_y

    chem_use = build_chem_use_kg_h_from_row(r0, out.columns)

    out["E_kWh_h"] = float(e_kwh_h)
    out["m_water_kg_h"] = float(m_water_kg_h)
    out["labor_h_h"] = float(labor_h_h)
    out["maintenance_per_y"] = float(maintenance_per_y)
    out["depreciation_per_y"] = float(depreciation_per_y)
    out["supplies_per_y"] = float(supplies_per_y)
    out["chem_use_kg_h"] = [chem_use]

    return out


# -------------------------- wastewater treatment --------------------------

WASTEWATER_WATER_KEYS: tuple[str, ...] = ("process:H2O", "hydro:H2O", "H2O")
# Solutes recovered at wastewater treatment — not scaled down when removing water.
WASTEWATER_PRESERVE_KEYS: tuple[str, ...] = ("process:Na2SO4",)


def wastewater_reduction_factor(params: dict | None) -> float:
    """Default 10× mass reduction before EFF routing (treated mass = inlet / factor)."""
    p = params or {}
    rf = float(p.get("reduction_factor", 10.0))
    return rf if rf > 0.0 else 10.0


def reduce_wastewater_mass(
    flow_in: MassFlow,
    *,
    reduction_factor: float | None = None,
    params: dict | None = None,
) -> tuple[MassFlow, float, float, float]:
    """
    Reduce wastewater to ``m_in / reduction_factor`` (default factor **10**).

    Removes mass from explicit water keys first, then scales non-preserved ``comp_abs``
    if needed (see ``WASTEWATER_PRESERVE_KEYS``, e.g. ``process:Na2SO4`` for side-product recovery).

    Returns:
    - reduced flow
    - inlet mass [kg/h]
    - reduced mass [kg/h]
    - mass removed from explicit water keys [kg/h]
    """
    m_in = float(flow_in.mass_kg_per_h)
    if m_in <= 0.0:
        return MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}), 0.0, 0.0, 0.0

    rf = float(reduction_factor) if reduction_factor is not None else wastewater_reduction_factor(params)
    if rf <= 0.0:
        rf = 10.0

    meta_in = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta_in.get("comp_abs") or {})

    preserve = set(WASTEWATER_PRESERVE_KEYS)
    preserved = {
        k: float(comp_abs[k])
        for k in preserve
        if k in comp_abs and abs(float(comp_abs[k])) > 1e-12
    }
    m_preserved = float(sum(preserved.values()))
    rest = {k: float(v or 0.0) for k, v in comp_abs.items() if k not in preserve}
    m_rest = float(sum(rest.values()))

    # Reduce only the non-recovered liquor; keep Na2SO4 (etc.) at full mass for side-product routing.
    m_rest_target = m_rest / rf if rf > 0.0 else m_rest
    m_remove = max(0.0, m_rest - m_rest_target)

    removed_water = 0.0
    rest_to_remove = m_remove
    for k in WASTEWATER_WATER_KEYS:
        if rest_to_remove <= 0.0:
            break
        v = float(rest.get(k, 0.0) or 0.0)
        take = min(v, rest_to_remove)
        if take > 0.0:
            rest[k] = v - take
            removed_water += take
            rest_to_remove -= take

    m_rest = float(sum(rest.values()))
    if m_rest > 1e-12 and abs(m_rest - m_rest_target) > 1e-9:
        if m_rest_target > 1e-12:
            scale = m_rest_target / m_rest
            rest = {k: v * scale for k, v in rest.items()}
        else:
            rest = {}

    comp_abs = dict(rest)
    comp_abs.update(preserved)
    m_after = float(sum(comp_abs.values()))

    flow_out = MassFlow(float(m_after), meta={"comp_abs": comp_abs})
    return flow_out, m_in, float(m_after), removed_water
