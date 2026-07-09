# main.py
from __future__ import annotations
import os
import pandas as pd
import General_Parameters as gp
import machine as ms
import Recycling_Efficiencies as rfx
from Massflow import MassFlow
from step_utils import feed_has_pack_level, prices as step_prices
from stoichiometry import NMC_PRECURSOR_RULES
from hydro_recovery_scope import (
    resolve_lfp_hydro_recovery_scope,
    resolve_mix_hydro_recovery_scope,
    resolve_nmc_hydro_recovery_scope,
    resolve_pyro_hydro_recovery_scope,
)
from infrastructure import (
    aggregate_dual_region_overhead,
    compute_infrastructure,
    fork_ctx_region,
    is_hub_spoke_mode,
    process_site_for_step,
    resolve_hub_region,
    resolve_spoke_region,
)

NMC_PRECURSOR_CODES: tuple[str, ...] = tuple(NMC_PRECURSOR_RULES.keys())

NMC_TARGET_BASIS_OPTIONS: tuple[str, ...] = ("min", "ni", "co", "mn")

NMC_TARGET_BASIS_LABELS: dict[str, str] = {
    "min": "Limiting Metal Availability",
    "ni": "Nickel Anchor",
    "co": "Cobalt Anchor",
    "mn": "Manganese Anchor",
}

NMC_MAKEUP_POLICY_OPTIONS: tuple[str, ...] = ("none", "capped", "unlimited")

NMC_MAKEUP_POLICY_LABELS: dict[str, str] = {
    "none": "No Sulfate Addition",
    "capped": "Limited Sulfate Addition",
    "unlimited": "Unlimited Sulfate Addition",
}


def resolve_nmc_code(source: dict | None, default: str = "811") -> str:
    """Validate NMC precursor recipe code (811, 622, 532, 111)."""
    src = source or {}
    raw = str(src.get("nmc_code", default) or default).strip()
    if raw in NMC_PRECURSOR_RULES:
        return raw
    fallback = str(default).strip()
    if fallback in NMC_PRECURSOR_RULES:
        return fallback
    return "111"


def resolve_nmc_target_basis(source: dict | None, default: str = "min") -> str:
    """Normalize NMC target basis (min | ni | co | mn). Unknown values fall back to ``default``."""
    raw = str((source or {}).get("nmc_target_basis", default) or default).strip().lower()
    default_norm = str(default).strip().lower()
    if default_norm not in NMC_TARGET_BASIS_OPTIONS:
        default_norm = "min"
    return raw if raw in NMC_TARGET_BASIS_OPTIONS else default_norm


def resolve_nmc_makeup_policy(source: dict | None, default: str = "capped") -> str:
    """
    Sulfate makeup policy for NMC mixing / precipitation.

    - ``none``: no NiSO4/CoSO4/MnSO4 purchase.
    - ``capped``: stoichiometric sulfate makeup up to ``nmc_max_makeup_fill_fraction`` (0–1).
    - ``unlimited``: close full metal deficits vs. nominal target (fill = 1).
    """
    src = source or {}
    raw = str(src.get("nmc_makeup_policy", "") or "").strip().lower()
    if raw in NMC_MAKEUP_POLICY_OPTIONS:
        return raw
    if "nmc_makeup_policy" in src:
        return default if default in NMC_MAKEUP_POLICY_OPTIONS else "capped"
    frac = None
    if "nmc_max_makeup_fill_fraction" in src:
        frac = float(src.get("nmc_max_makeup_fill_fraction", 0.25) or 0.0)
    if frac is not None:
        if frac <= 0.0:
            return "none"
        if frac >= 1.0:
            return "unlimited"
        return "capped"
    return default if default in NMC_MAKEUP_POLICY_OPTIONS else "capped"


def resolve_nmc_makeup_fill_fraction(source: dict | None, default: float = 0.25) -> float:
    """
    Stoichiometric cap for ``capped`` policy: max share (0–1) of full Ni/Co/Mn deficits
    closed by sulfate makeup (uniform for all three metals).
    """
    src = source or {}
    policy = resolve_nmc_makeup_policy(src, default="capped")
    if policy == "none":
        return 0.0
    if policy == "unlimited":
        return 1.0
    if "nmc_max_makeup_fill_fraction" in src:
        v = float(src.get("nmc_max_makeup_fill_fraction", default) or default)
    else:
        v = float(default)
    return min(1.0, max(0.0, v))


def nmc_makeup_policy_summary(source: dict | None) -> str:
    """Human-readable policy line for reporting / UI."""
    policy = resolve_nmc_makeup_policy(source)
    label = NMC_MAKEUP_POLICY_LABELS.get(policy, policy)
    if policy == "capped":
        f = resolve_nmc_makeup_fill_fraction(source)
        return f"{label} (max. {f:.0%} Ni/Co/Mn deficit fill)"
    return label


def nmc_precip_params_from_ctx(ctx: dict) -> dict:
    """Params for NMC mixing / precipitation steps (reads ctx set from scenario)."""
    return {
        "nmc_code": resolve_nmc_code(ctx),
        "target_basis": resolve_nmc_target_basis(ctx),
        "makeup_policy": resolve_nmc_makeup_policy(ctx),
        "makeup_policy_label": nmc_makeup_policy_summary(ctx),
        "max_makeup_fill_fraction": resolve_nmc_makeup_fill_fraction(ctx),
        "nh3_coordination_number": float(ctx.get("nh3_coordination_number", 6.0) or 6.0),
        "nh3_loss_fraction": float(ctx.get("nh3_loss_fraction", 0.10) or 0.10),
        "nh3_solution_wtfrac": float(ctx.get("nh3_solution_wtfrac", 0.25) or 0.25),
    }


def nmc_precursor_product_label(nmc_code: str | None = None, source: dict | None = None) -> str:
    """Product name for dried NMC precursor, e.g. 'NMC 622 Precursor'."""
    if source is not None:
        code = resolve_nmc_code(source)
    else:
        code = resolve_nmc_code({"nmc_code": nmc_code or "811"})
    return f"NMC {code} Precursor"

from S01_Analytics_Sorting.S01_Analytics_Sorting import run_analytics_sorting
from S02_Discharge.S02_Discharge import run_discharge
from S03_Pack_Dismantle.S03_Pack_Dismantle import run_pack_dismantle
from S04_Mechanical.S04_1_Mech_Shred import run_mech_shred
from S04_Mechanical.S04_2_Mech_Drying import run_mech_drying
from S04_Mechanical.S04_3_Mech_Gas_Scrubbing import run_mech_gas_scrubbing
from S04_Mechanical.S04_4_Mech_Magnetic_Seperation import run_magnetic_separation
from S04_Mechanical.S04_5_Mech_ZigZag1 import run_zigzag1
from S04_Mechanical.S04_6_Mech_Crushing import run_mech_crush
from S04_Mechanical.S04_7_Mech_Sieving import run_mech_sieving
from S04_Mechanical.S04_8_Mech_ZigZag2 import run_zigzag2
from S04_Pyro.S04_1_Pyro_Smelting import run_pyro_smelting
from S04_Pyro.S04_2_Pyro_Gasscrubbing import run_pyro_gas_scrubbing
from S04_Pyro.S04_3_Pyro_Granulation_Alloy import run_pyro_granulation_alloy
from S04_Pyro.S04_4_Pyro_Granulation_Slag import run_pyro_granulation_slag
from S05_Hydro_Pyro_Alloy.S05_1_Hydro_Pyro_Alloy_Digestion import run_hydro_pyro_alloy_digestion
from S05_Hydro_Pyro_Alloy.S05_2_Hydro_Pyro_Alloy_Leaching import run_hydro_pyro_alloy_leaching
from S05_Hydro_Pyro_Alloy.S05_3_Hydro_Pyro_Alloy_Cu_Cementation import run_hydro_pyro_alloy_cu_cementation
from S05_Hydro_Pyro_Alloy.S05_4_Hydro_Pyro_Alloy_Cu_Filtration import run_hydro_pyro_alloy_cu_filtration
from S05_Hydro_Pyro_Alloy.S05_5_Hydro_Pyro_Alloy_Fe_Oxidation import run_hydro_pyro_alloy_fe_oxidation
from S05_Hydro_Pyro_Alloy.S05_6_Hydro_Pyro_Alloy_Fe_Precipitation import run_hydro_pyro_alloy_fe_precipitation
from S05_Hydro_Pyro_Alloy.S05_7_Hydro_Pyro_Alloy_Fe_Filtration import run_hydro_pyro_alloy_fe_filtration
from S05_Hydro_Pyro_Alloy.S05_8_Hydro_Pyro_Alloy_Co_Extraction import run_hydro_pyro_alloy_co_extraction
from S05_Hydro_Pyro_Alloy.S05_9_Hydro_Pyro_Alloy_Co_Scrubbing import run_hydro_pyro_alloy_co_scrubbing
from S05_Hydro_Pyro_Alloy.S05_10_Hydro_Pyro_Alloy_Co_Stripping import run_hydro_pyro_alloy_co_stripping
from S05_Hydro_Pyro_Alloy.S05_11_Hydro_Pyro_Alloy_Co_Crystallization import run_hydro_pyro_alloy_co_crystallization
from S05_Hydro_Pyro_Alloy.S05_12_Hydro_Pyro_Alloy_Ni_Crystallization import run_hydro_pyro_ni_crystallization
from S05_Hydro_Pyro_Alloy.S05_13_Hydro_Pyro_Alloy_Wastewater_treatment import run_hydro_pyro_alloy_wastewater_treatment
from S05_Hydro_Pyro_Slag.S05_1_Hydro_Pyro_Slag_Digestion import run_hydro_pyro_slag_digestion
from S05_Hydro_Pyro_Slag.S05_2_Hydro_Pyro_Slag_Leaching import run_hydro_pyro_slag_leaching
from S05_Hydro_Pyro_Slag.S05_3_Hydro_Pyro_Slag_SiO2_CaSO4_Filtration import run_hydro_pyro_slag_sio2_caso4_filtration
from S05_Hydro_Pyro_Slag.S05_4_Hydro_Pyro_Slag_Fe_Oxidation import run_hydro_pyro_slag_fe_oxidation
from S05_Hydro_Pyro_Slag.S05_5_Hydro_Pyro_Slag_Fe_Al_Precipitation import run_hydro_pyro_slag_fe_al_precipitation
from S05_Hydro_Pyro_Slag.S05_6_Hydro_Pyro_Slag_Fe_Al_Filtration import run_hydro_pyro_slag_fe_al_filtration
from S05_Hydro_Pyro_Slag.S05_7_Hydro_Pyro_Slag_Mn_Extraction import run_hydro_pyro_slag_mn_extraction
from S05_Hydro_Pyro_Slag.S05_8_Hydro_Pyro_Slag_Mn_Scrubbing import run_hydro_pyro_slag_mn_scrubbing
from S05_Hydro_Pyro_Slag.S05_9_Hydro_Pyro_Slag_Mn_Stripping import run_hydro_pyro_slag_mn_stripping
from S05_Hydro_Pyro_Slag.S05_10_Hydro_Pyro_Slag_Mn_Crystallization import run_hydro_pyro_slag_mn_crystallization
from S05_Hydro_Pyro_Slag.S05_11_Hydro_Pyro_Slag_Li_Concentration import run_hydro_li_concentration
from S05_Hydro_Pyro_Slag.S05_12_Hydro_Pyro_Slag_Li_Precipitation import run_hydro_pyro_slag_li_precipitation
from S05_Hydro_Pyro_Slag.S05_13_Hydro_Pyro_Slag_Li_Filtration import run_hydro_pyro_slag_li_filtration
from S05_Hydro_Pyro_Slag.S05_14_Hydro_Pyro_Slag_Li_Washing import run_hydro_pyro_slag_li_washing
from S05_Hydro_Pyro_Slag.S05_15_Hydro_Pyro_Slag_Li_Drying import run_hydro_pyro_slag_li_drying
from S05_Hydro_Pyro_Slag.S05_16_Hydro_Pyro_Slag_Wastewater_treatment import run_hydro_pyro_slag_li_wastewater_treatment
from S05_Hydro_LFP.S05_1_Hydro_LFP_Pre_Wetting import run_hydro_lfp_pre_wetting
from S05_Hydro_LFP.S05_2_Hydro_LFP_Alkaline_Leaching import run_hydro_lfp_alkaline_leaching
from S05_Hydro_LFP.S05_3_Hydro_LFP_BM_Filtration import run_hydro_lfp_bm_filtration
from S05_Hydro_LFP.S05_4_Hydro_LFP_Digestion import run_hydro_lfp_digestion
from S05_Hydro_LFP.S05_5_Hydro_LFP_Leaching import run_hydro_lfp_leaching
from S05_Hydro_LFP.S05_6_Hydro_LFP_Graphite_Filtration import run_hydro_lfp_graphite_filtration
from S05_Hydro_LFP.S05_7_Hydro_LFP_Cu_Cementation import run_hydro_lfp_cu_cementation
from S05_Hydro_LFP.S05_8_Hydro_LFP_Cu_Filtration import run_hydro_lfp_cu_filtration
from S05_Hydro_LFP.S05_9_Hydro_LFP_Oxalate_Mixing import run_hydro_lfp_oxalate_mixing
from S05_Hydro_LFP.S05_10_Hydro_LFP_Oxalate_Precipitation import run_hydro_lfp_oxalate_precipitation
from S05_Hydro_LFP.S05_11_Hydro_LFP_Oxalate_Filtration import run_hydro_lfp_oxalate_filtration
from S05_Hydro_LFP.S05_12_Hydro_LFP_Oxalate_Washing import run_hydro_lfp_oxalate_washing
from S05_Hydro_LFP.S05_13_Hydro_LFP_Oxalate_Drying import run_hydro_lfp_oxalate_drying
from S05_Hydro_LFP.S05_14_Hydro_LFP_Ion_Change_Resin_Step import run_hydro_lfp_ion_exchange
from S05_Hydro_LFP.S05_15_Hydro_LFP_Li_Concentration import run_hydro_lfp_li_concentration
from S05_Hydro_LFP.S05_16_Hydro_LFP_Li_Crystallization import run_hydro_lfp_lih2po4_crystallization
from S05_Hydro_LFP.S05_17_Hydro_LFP_Wastewater_treatment import run_hydro_lfp_wastewater_treatment
from S05_Hydro_Mix_NMC_LFP.S05_1_Hydro_Mix_Pre_Wetting import run_hydro_mix_pre_wetting
from S05_Hydro_Mix_NMC_LFP.S05_2_Hydro_Mix_Alkaline_Leaching import run_hydro_mix_alkaline_leaching
from S05_Hydro_Mix_NMC_LFP.S05_3_Hydro_Mix_BM_Filtration import run_hydro_mix_bm_filtration
from S05_Hydro_Mix_NMC_LFP.S05_4_Hydro_Mix_Digestion import run_hydro_mix_digestion
from S05_Hydro_Mix_NMC_LFP.S05_5_Hydro_Mix_Leaching import run_hydro_mix_leaching
from S05_Hydro_Mix_NMC_LFP.S05_6_Hydro_Mix_Graphite_Filtration import run_hydro_mix_graphite_filtration
from S05_Hydro_Mix_NMC_LFP.S05_7_Hydro_Mix_Cu_Cementation import run_hydro_mix_cu_cementation
from S05_Hydro_Mix_NMC_LFP.S05_8_Hydro_Mix_Cu_Filtration import run_hydro_mix_cu_filtration
from S05_Hydro_Mix_NMC_LFP.S05_9_Hydro_Mix_Ion_Change_Resin import run_hydro_mix_ion_change_resin
from S05_Hydro_Mix_NMC_LFP.S05_10_Hydro_Mix_Resin_Stripping import run_hydro_mix_resin_stripping
from S05_Hydro_Mix_NMC_LFP.S05_11_Hydro_Mix_NMC_Mixing import run_hydro_mix_mixing_nmc
from S05_Hydro_Mix_NMC_LFP.S05_12_Hydro_Mix_NMC_Precipitation import run_hydro_mix_precipitation_nmc
from S05_Hydro_Mix_NMC_LFP.S05_13_Hydro_Mix_Filtration_NMC import run_hydro_mix_filtration_nmc
from S05_Hydro_Mix_NMC_LFP.S05_14_Hydro_Mix_NMC_Washing import run_hydro_mix_nmc_washing
from S05_Hydro_Mix_NMC_LFP.S05_15_Hydro_Mix_NMC_Drying import run_hydro_mix_nmc_drying
from S05_Hydro_Mix_NMC_LFP.S05_16_Hydro_Mix_Li_Precipitation import run_hydro_mix_li_precipitation
from S05_Hydro_Mix_NMC_LFP.S05_17_Hydro_Mix_Li_Filtration import run_hydro_mix_li_filtration
from S05_Hydro_Mix_NMC_LFP.S05_18_Hydro_Mix_Li_Washing import run_hydro_mix_li_washing
from S05_Hydro_Mix_NMC_LFP.S05_19_Hydro_Mix_Li_Drying import run_hydro_mix_li_drying
from S05_Hydro_Mix_NMC_LFP.S05_20_Hydro_Mix_Concentration import run_hydro_mix_fe_concentration
from S05_Hydro_Mix_NMC_LFP.S05_21_Hydro_Mix_Carbon_Dispersion import run_hydro_mix_carbon_dispersion
from S05_Hydro_Mix_NMC_LFP.S05_22_Hydro_Mix_Electrospinning import run_hydro_mix_electrospinning_precursor
from S05_Hydro_Mix_NMC_LFP.S05_23_Hydro_Mix_Rosting import run_hydro_mix_roasting
from S05_Hydro_Mix_NMC_LFP.S05_24_Hydro_Mix_Wastewater_treatment import run_hydro_mix_wastewater_treatment
from S05_Hydro_NMC.S05_1_Hydro_NMC_Digestion import run_hydro_nmc_digestion
from S05_Hydro_NMC.S05_2_Hydro_NMC_Leaching import run_hydro_nmc_leaching
from S05_Hydro_NMC.S05_3_Hydro_NMC_Graphite_Filtration import run_hydro_nmc_graphite_filtration
from S05_Hydro_NMC.S05_4_Hydro_NMC_Cu_Cementation import run_hydro_nmc_cu_cementation
from S05_Hydro_NMC.S05_5_Hydro_NMC_Cu_Filtration import run_hydro_nmc_cu_filtration
from S05_Hydro_NMC.S05_6_Hydro_NMC_Fe_Oxidation import run_hydro_nmc_fe_oxidation
from S05_Hydro_NMC.S05_7_Hydro_NMC_Fe_Al_Precipitation import run_hydro_nmc_fe_al_precipitation
from S05_Hydro_NMC.S05_8_Hydro_NMC_Fe_Al_Filtration import run_hydro_nmc_fe_al_filtration
from S05_Hydro_NMC.S05_9_Hydro_NMC_Mixing import run_hydro_nmc_mixing_nmc
from S05_Hydro_NMC.S05_10_Hydro_NMC_Precipitation_NMC import run_hydro_nmc_precipitation_nmc
from S05_Hydro_NMC.S05_11_Hydro_NMC_Filtration_NMC import run_hydro_nmc_filtration_nmc
from S05_Hydro_NMC.S05_12_Hydro_NMC_Washing_NMC import run_hydro_nmc_washing_nmc
from S05_Hydro_NMC.S05_13_Hydro_NMC_Drying_NMC import run_hydro_nmc_drying_nmc
from S05_Hydro_NMC.S05_14_Hydro_NMC_Li_Precipitation import run_hydro_nmc_li_precipitation
from S05_Hydro_NMC.S05_15_Hydro_NMC_Li_Filtration import run_hydro_nmc_li_filtration
from S05_Hydro_NMC.S05_16_Hydro_NMC_Li_Washing import run_hydro_nmc_li_washing
from S05_Hydro_NMC.S05_17_Hydro_NMC_Li_Drying import run_hydro_nmc_li_drying
from S05_Hydro_NMC.S05_18_Hydro_NMC_Wastewater_treatment import run_hydro_nmc_wastewater_treatment

from cell_db import CellDB
from path import CELL_TECH_XLSX

DB = CellDB(CELL_TECH_XLSX)


def set_cell_tech_file(xlsx_path: str) -> None:
    """Switch the cell/module/pack technology workbook for subsequent scenario calculations."""
    global DB
    path = os.path.abspath(str(xlsx_path))
    if path == os.path.abspath(str(getattr(DB, "xlsx_path", CELL_TECH_XLSX))):
        return
    DB = CellDB(path)


# ----------------------- Helpers -----------------------

def _hours_per_year() -> int:
    return int(gp.get_working_hours_per_year())


def _route_flags_from_feed(scen: dict) -> tuple[bool, bool, bool]:
    """Return (lfp_only, mix_lfp_nmc, nmc_only) based on scenario feed."""
    feed = list(scen.get("feed", []) or [])
    chems = set()
    for it in feed:
        cell_id = str(it.get("cell_id", "")).strip()
        if not cell_id:
            continue
        chem, _ = parse_cell_id(cell_id)
        chems.add(chem.upper())

    lfp_only = bool(chems) and all(ch.startswith("LFP") for ch in chems)
    has_lfp = any(ch.startswith("LFP") for ch in chems)
    has_nmc = any(ch.startswith("NMC") for ch in chems)
    mix_lfp_nmc = has_lfp and has_nmc
    nmc_only = has_nmc and not has_lfp
    return lfp_only, mix_lfp_nmc, nmc_only


def parse_cell_id(cell_id: str) -> tuple[str, str]:
    parts = str(cell_id).split("_")
    chem = parts[0] if parts else "Unknown"
    geom = "_".join(parts[1:]) if len(parts) > 1 else "Unknown"
    return chem, geom


def abs_to_frac(comp_abs: dict[str, float], eps: float = 1e-12) -> dict[str, float]:
    if not isinstance(comp_abs, dict) or not comp_abs:
        return {}
    s = sum(max(float(v), 0.0) for v in comp_abs.values())
    if s <= eps:
        return {k: 0.0 for k in comp_abs}
    return {k: max(float(v), 0.0) / s for k, v in comp_abs.items()}


def _combine_flows(*flows: MassFlow) -> MassFlow:
    """Sum MassFlows (mass + comp_abs)."""
    total_m = 0.0
    comp_abs: dict[str, float] = {}

    for f in flows:
        if f is None:
            continue
        total_m += float(getattr(f, "mass_kg_per_h", 0.0) or 0.0)

        ca = (getattr(f, "meta", {}) or {}).get("comp_abs", {}) or {}
        if isinstance(ca, dict):
            for k, v in ca.items():
                comp_abs[str(k)] = comp_abs.get(str(k), 0.0) + float(v)

    return MassFlow(total_m, meta={"comp_abs": comp_abs, "comp": abs_to_frac(comp_abs)})


def _empty_mass_flow() -> MassFlow:
    return MassFlow(0.0, meta={"comp_abs": {}, "comp": {}})


def _mf_any(outputs: dict, *keys: str) -> MassFlow:
    """Return the first available output stream, otherwise a zero flow."""
    for key in keys:
        if key in outputs:
            return outputs[key]
    return _empty_mass_flow()


def _annotate_step_rows(step_rows: list[pd.DataFrame], scen: dict) -> list[pd.DataFrame]:
    """Tag each step with process site and applied region for dual-region reporting."""
    annotated: list[pd.DataFrame] = []
    hub_spoke = is_hub_spoke_mode(scen)
    spoke_region = resolve_spoke_region(scen)
    hub_region = resolve_hub_region(scen)
    default_region = str(scen.get("region", "DE") or "DE")

    for row in step_rows:
        if row is None or row.empty:
            annotated.append(row)
            continue
        out = row.copy()
        step_name = str(out.iloc[0].get("Step", "") or "")
        if hub_spoke:
            site = process_site_for_step(step_name)
            out["Process site"] = site
            out["Region"] = hub_region if site == "hub" else spoke_region
        else:
            out["Process site"] = "integrated"
            out["Region"] = default_region
        annotated.append(out)
    return annotated


def _transport_mass_kg_per_year_from_flow(mf: MassFlow | None, hours: float) -> float:
    if mf is None:
        return 0.0
    return float(getattr(mf, "mass_kg_per_h", 0.0) or 0.0) * float(hours or 0.0)


def _run_mech_preprocessing(ctx: dict, pyro_mech_input: MassFlow, step_rows: list[pd.DataFrame]):
    """Run mechanical route preprocessing up to sieving/zigzag2."""
    out_sh, row_sh, ex_sh = run_mech_shred(ctx, pyro_mech_input)
    step_rows.append(row_sh)

    flow_after_shred = out_sh["shredded material"]
    out_dry, row_dry, ex_dry = run_mech_drying(ctx, flow_after_shred, params=None)
    step_rows.append(row_dry)

    scrub_in = _combine_flows(
        out_sh.get("n2_to_scrubber", MassFlow(0.0, meta={"comp_abs": {}, "comp": {}})),
        out_dry.get("electrolyte", MassFlow(0.0, meta={"comp_abs": {}, "comp": {}})),
    )
    out_gs, row_gs, ex_gs = run_mech_gas_scrubbing(ctx, scrub_in, params=None)
    step_rows.append(row_gs)

    flow_after_drying = out_dry["dried material"]
    out_mag, row_mag, ex_mag = run_magnetic_separation(ctx, flow_after_drying, params=None)
    step_rows.append(row_mag)

    flow_after_mag = out_mag["non magnetic material"]
    out_z1, row_z1, ex_z1 = run_zigzag1(ctx, flow_after_mag, params=None)
    step_rows.append(row_z1)

    flow_after_zigzag1 = out_z1["fragment material"]
    out_cr, row_cr, ex_cr = run_mech_crush(ctx, flow_after_zigzag1, params=None)
    step_rows.append(row_cr)

    flow_after_crush = out_cr["crushed material"]
    out_sv, row_sv, ex_sv = run_mech_sieving(ctx, flow_after_crush, params=None)
    step_rows.append(row_sv)

    flow_after_sieving = out_sv["coarse fraction"]
    out_z2, row_z2, ex_z2 = run_zigzag2(ctx, flow_after_sieving, params=None)
    step_rows.append(row_z2)

    ex_mech = {
        "Shredding": ex_sh,
        "Drying": ex_dry,
        "Mechanical Gas Scrubbing": ex_gs,
        "Magnetic Separation": ex_mag,
        "Air-Classification 1": ex_z1,
        "Crushing": ex_cr,
        "Sieving": ex_sv,
        "Air-Classification 2": ex_z2,
    }
    return out_sv, ex_mech


def _run_hydro_lfp_route(ctx: dict, out_sv: dict, step_rows: list[pd.DataFrame]) -> dict:
    """Run LFP-only hydro route (scope: all = Fe + Li, fe = iron oxalate only)."""
    ex_lfp = {}
    if float(out_sv["black mass"].mass_kg_per_h) <= 0:
        return ex_lfp

    scope = resolve_lfp_hydro_recovery_scope(ctx)
    recover_li = scope == "all"
    empty_mf = MassFlow(0.0, meta={"comp_abs": {}, "comp": {}})

    black_mass = out_sv["black mass"]
    out_lfp1, row_lfp1, ex_lfp1 = run_hydro_lfp_pre_wetting(ctx, black_mass, params=None); step_rows.append(row_lfp1)
    out_lfp2, row_lfp2, ex_lfp2 = run_hydro_lfp_alkaline_leaching(ctx, out_lfp1["BM suspension"], params=None); step_rows.append(row_lfp2)
    out_lfp3, row_lfp3, ex_lfp3 = run_hydro_lfp_bm_filtration(ctx, out_lfp2["lye alkaline leaching"], params=None); step_rows.append(row_lfp3)
    out_lfp4, row_lfp4, ex_lfp4 = run_hydro_lfp_digestion(ctx, out_lfp3["BM aluminium clean"], params=None); step_rows.append(row_lfp4)
    out_lfp5, row_lfp5, ex_lfp5 = run_hydro_lfp_leaching(ctx, out_lfp4["digested BM solution"], params=None); step_rows.append(row_lfp5)
    out_lfp6, row_lfp6, ex_lfp6 = run_hydro_lfp_graphite_filtration(ctx, out_lfp5["BM leachate"], params=None); step_rows.append(row_lfp6)
    out_lfp7, row_lfp7, ex_lfp7 = run_hydro_lfp_cu_cementation(ctx, out_lfp6["lye graphite clean"], params=None); step_rows.append(row_lfp7)
    out_lfp8, row_lfp8, ex_lfp8 = run_hydro_lfp_cu_filtration(ctx, out_lfp7["lye copper cementation"], params=None); step_rows.append(row_lfp8)
    out_lfp9, row_lfp9, ex_lfp9 = run_hydro_lfp_oxalate_mixing(ctx, out_lfp8["lye copper clean"], params=None); step_rows.append(row_lfp9)
    out_lfp10, row_lfp10, ex_lfp10 = run_hydro_lfp_oxalate_precipitation(ctx, out_lfp9["lye oxalate mixing"], params=None); step_rows.append(row_lfp10)
    out_lfp11, row_lfp11, ex_lfp11 = run_hydro_lfp_oxalate_filtration(ctx, out_lfp10["lye oxalate precipitation"], params=None); step_rows.append(row_lfp11)
    out_lfp12, row_lfp12, ex_lfp12 = run_hydro_lfp_oxalate_washing(ctx, out_lfp11["Ferrous oxalate cake"], params=None); step_rows.append(row_lfp12)
    out_lfp13, row_lfp13, ex_lfp13 = run_hydro_lfp_oxalate_drying(ctx, out_lfp12["Ferrous oxalate washed"], params=None); step_rows.append(row_lfp13)

    ex_lfp = {
        "Hydro LFP – Pre Wetting": ex_lfp1, "Hydro LFP – Alkaline Leaching": ex_lfp2, "Hydro LFP – LFP Filtration 1": ex_lfp3,
        "Hydro LFP – Digestion": ex_lfp4, "Hydro LFP – Leaching": ex_lfp5, "Hydro LFP – Carbon Filtration": ex_lfp6,
        "Hydro LFP – Cu Cementation": ex_lfp7, "Hydro LFP – Cu Filtration": ex_lfp8, "Hydro LFP – Oxalate Mixing": ex_lfp9,
        "Hydro LFP – Fe Oxalate Precipitation": ex_lfp10, "Hydro LFP – Oxalate Filtration": ex_lfp11, "Hydro LFP – Oxalate Washing": ex_lfp12,
        "Hydro LFP – Oxalate Drying": ex_lfp13,
    }

    out_lfp14 = out_lfp15 = out_lfp16 = None
    if recover_li:
        out_lfp14, row_lfp14, ex_lfp14 = run_hydro_lfp_ion_exchange(ctx, out_lfp11["lye iron clean"], params=None); step_rows.append(row_lfp14)
        out_lfp15, row_lfp15, ex_lfp15 = run_hydro_lfp_li_concentration(ctx, out_lfp14["lye clean"], params=None); step_rows.append(row_lfp15)
        out_lfp16, row_lfp16, ex_lfp16 = run_hydro_lfp_lih2po4_crystallization(ctx, out_lfp15["lye concentrated"], params=None); step_rows.append(row_lfp16)
        ex_lfp.update({
            "Hydro LFP – Ion Exchange": ex_lfp14, "Hydro LFP – Li Concentration": ex_lfp15,
            "Hydro LFP – LiH2PO4 Crystallization": ex_lfp16,
        })

    ww_parts: list[MassFlow] = [out_lfp13.get("wastewater drying", empty_mf)]
    if scope == "fe":
        ww_parts.append(out_lfp11["lye iron clean"])
    elif recover_li and out_lfp16 is not None:
        ww_parts.append(out_lfp16["Li mother liquor"])
        ww_parts.append(out_lfp15.get("wastewater", empty_mf))

    ww_lfp_in = _combine_flows(*ww_parts)
    out_lfp17, row_lfp17, ex_lfp17 = run_hydro_lfp_wastewater_treatment(ctx, ww_lfp_in, params=None); step_rows.append(row_lfp17)
    ex_lfp["Hydro LFP – Wastewater Treatment"] = ex_lfp17
    return ex_lfp


def _run_hydro_mix_route(ctx: dict, out_sv: dict, step_rows: list[pd.DataFrame]) -> dict:
    """Run mixed LFP+NMC hydro route (scope: all | nmc | nmc_li)."""
    ex_mix = {}
    if float(out_sv["black mass"].mass_kg_per_h) <= 0:
        return ex_mix

    scope = resolve_mix_hydro_recovery_scope(ctx)
    run_nmc_line = scope in ("all", "nmc", "nmc_li")
    run_li_line = scope in ("all", "nmc_li")
    run_fe_line = scope == "all"
    empty_mf = MassFlow(0.0, meta={"comp_abs": {}, "comp": {}})

    black_mass_mix = out_sv["black mass"]
    out_mix1, row_mix1, ex_mix1 = run_hydro_mix_pre_wetting(ctx, black_mass_mix, params=None); step_rows.append(row_mix1)
    out_mix2, row_mix2, ex_mix2 = run_hydro_mix_alkaline_leaching(ctx, out_mix1["BM suspension"], params=None); step_rows.append(row_mix2)
    out_mix3, row_mix3, ex_mix3 = run_hydro_mix_bm_filtration(ctx, out_mix2["lye alkaline leaching"], params=None); step_rows.append(row_mix3)
    out_mix4, row_mix4, ex_mix4 = run_hydro_mix_digestion(ctx, out_mix3["BM aluminium clean"], params=None); step_rows.append(row_mix4)
    out_mix5, row_mix5, ex_mix5 = run_hydro_mix_leaching(ctx, out_mix4["digested BM solution"], params=None); step_rows.append(row_mix5)
    out_mix6, row_mix6, ex_mix6 = run_hydro_mix_graphite_filtration(ctx, out_mix5["BM leachate"], params=None); step_rows.append(row_mix6)
    out_mix7, row_mix7, ex_mix7 = run_hydro_mix_cu_cementation(ctx, out_mix6["lye graphite clean"], params=None); step_rows.append(row_mix7)
    out_mix8, row_mix8, ex_mix8 = run_hydro_mix_cu_filtration(ctx, out_mix7["lye copper cementation"], params=None); step_rows.append(row_mix8)
    out_mix9, row_mix9, ex_mix9 = run_hydro_mix_ion_change_resin(ctx, out_mix8["lye copper clean"], params=None); step_rows.append(row_mix9)
    loaded_resin = rfx.mf_get(out_mix9, "loaded_resin")
    out_mix10, row_mix10, ex_mix10 = run_hydro_mix_resin_stripping(ctx, loaded_resin, params=None); step_rows.append(row_mix10)
    nmc_solution = rfx.mf_get(out_mix10, "NMC solution")

    ex_mix = {
        "Hydro Mix – Pre Wetting": ex_mix1, "Hydro Mix – Alkaline Leaching": ex_mix2, "Hydro Mix – BM Filtration": ex_mix3,
        "Hydro Mix – Digestion": ex_mix4, "Hydro Mix – Leaching": ex_mix5, "Hydro Mix – Graphite Filtration": ex_mix6,
        "Hydro Mix – Cu Cementation": ex_mix7, "Hydro Mix – Cu Filtration": ex_mix8, "Hydro Mix – Ion Exchange Resin": ex_mix9,
        "Hydro Mix – Resin Stripping": ex_mix10,
    }

    out_mix13 = out_mix15 = None
    if run_nmc_line and float(nmc_solution.mass_kg_per_h) > 0:
        nmc_p = nmc_precip_params_from_ctx(ctx)
        out_mix11, row_mix11, ex_mix11 = run_hydro_mix_mixing_nmc(ctx, nmc_solution, params=nmc_p); step_rows.append(row_mix11)
        out_mix12, row_mix12, ex_mix12 = run_hydro_mix_precipitation_nmc(ctx, out_mix11["lye precursor mixing"], params=nmc_p); step_rows.append(row_mix12)
        out_mix13, row_mix13, ex_mix13 = run_hydro_mix_filtration_nmc(ctx, out_mix12["lye precursor precipitation"], params=None); step_rows.append(row_mix13)
        out_mix14, row_mix14, ex_mix14 = run_hydro_mix_nmc_washing(ctx, out_mix13["NMC Precursor"], params=None); step_rows.append(row_mix14)
        out_mix15, row_mix15, ex_mix15 = run_hydro_mix_nmc_drying(ctx, out_mix14["NMC Precursor washed"], params=nmc_p); step_rows.append(row_mix15)
        ex_mix.update({
            "Hydro Mix – NMC Mixing": ex_mix11, "Hydro Mix – NMC Precipitation": ex_mix12,
            "Hydro Mix – NMC Filtration": ex_mix13, "Hydro Mix – NMC Washing": ex_mix14,
            "Hydro Mix – NMC Drying": ex_mix15,
        })

    out_mix16 = out_mix17 = out_mix18 = out_mix19 = None
    if run_li_line:
        out_mix16, row_mix16, ex_mix16 = run_hydro_mix_li_precipitation(ctx, out_mix9["lye NMC clean"], params=None); step_rows.append(row_mix16)
        out_mix17, row_mix17, ex_mix17 = run_hydro_mix_li_filtration(ctx, out_mix16["lye lithium precipitation"], params=None); step_rows.append(row_mix17)
        out_mix18, row_mix18, ex_mix18 = run_hydro_mix_li_washing(ctx, out_mix17["Lithium Carbonate"], params=None); step_rows.append(row_mix18)
        out_mix19, row_mix19, ex_mix19 = run_hydro_mix_li_drying(ctx, out_mix18["Lithium Carbonate washed"], params=None); step_rows.append(row_mix19)
        ex_mix.update({
            "Hydro Mix – Li Precipitation": ex_mix16,
            "Hydro Mix – Li Filtration": ex_mix17,
            "Hydro Mix – Li Washing": ex_mix18,
            "Hydro Mix – Li Drying": ex_mix19,
        })

    out_mix20 = out_mix21 = out_mix22 = out_mix23 = None
    if run_fe_line and out_mix17 is not None:
        out_mix20, row_mix20, ex_mix20 = run_hydro_mix_fe_concentration(ctx, out_mix17["filtration solution"], params=None); step_rows.append(row_mix20)
        out_mix21, row_mix21, ex_mix21 = run_hydro_mix_carbon_dispersion(ctx, out_mix20["lye concentrated"], params=None); step_rows.append(row_mix21)
        out_mix22, row_mix22, ex_mix22 = run_hydro_mix_electrospinning_precursor(ctx, out_mix21["mix_carbon_dispersion"], params=None); step_rows.append(row_mix22)
        out_mix23, row_mix23, ex_mix23 = run_hydro_mix_roasting(ctx, out_mix22["mix_electrospinning_precursor"], params=None); step_rows.append(row_mix23)
        ex_mix.update({
            "Hydro Mix – Fe Concentration": ex_mix20,
            "Hydro Mix – Carbon Dispersion": ex_mix21,
            "Hydro Mix – Electrospinning Precursor Formation": ex_mix22,
            "Hydro Mix – Roasting": ex_mix23,
        })

    ww_parts: list[MassFlow] = []
    if scope == "all":
        ww_parts.extend([
            out_mix13.get("lye NMC clean", empty_mf) if out_mix13 is not None else empty_mf,
            out_mix17.get("filtration solution", empty_mf) if out_mix17 is not None else empty_mf,
            out_mix22.get("fe_process_residue", empty_mf) if out_mix22 is not None else empty_mf,
            out_mix15.get("wastewater drying", empty_mf) if out_mix15 is not None else empty_mf,
            out_mix18.get("wastewater washing", empty_mf) if out_mix18 is not None else empty_mf,
            out_mix19.get("wastewater drying", empty_mf) if out_mix19 is not None else empty_mf,
            out_mix20.get("wastewater", empty_mf) if out_mix20 is not None else empty_mf,
        ])
    elif scope == "nmc":
        ww_parts.append(out_mix9["lye NMC clean"])
        if out_mix13 is not None:
            ww_parts.append(out_mix13.get("lye NMC clean", empty_mf))
        if out_mix15 is not None:
            ww_parts.append(out_mix15.get("wastewater drying", empty_mf))
    elif scope == "nmc_li":
        if out_mix13 is not None:
            ww_parts.append(out_mix13.get("lye NMC clean", empty_mf))
        if out_mix17 is not None:
            ww_parts.append(out_mix17.get("filtration solution", empty_mf))
        if out_mix15 is not None:
            ww_parts.append(out_mix15.get("wastewater drying", empty_mf))
        if out_mix18 is not None:
            ww_parts.append(out_mix18.get("wastewater washing", empty_mf))
        if out_mix19 is not None:
            ww_parts.append(out_mix19.get("wastewater drying", empty_mf))

    ww_mix_in = _combine_flows(*ww_parts) if ww_parts else empty_mf
    out_mix24, row_mix24, ex_mix24 = run_hydro_mix_wastewater_treatment(ctx, ww_mix_in, params=None); step_rows.append(row_mix24)
    ex_mix["Hydro Mix – Wastewater Treatment"] = ex_mix24
    return ex_mix


def _run_hydro_nmc_route(ctx: dict, out_sv: dict, step_rows: list[pd.DataFrame]) -> dict:
    """Run NMC-only hydro route (scope: all = NMC + Li, nmc = NMC only)."""
    ex_nmc = {}
    if float(out_sv["black mass"].mass_kg_per_h) <= 0:
        return ex_nmc

    scope = resolve_nmc_hydro_recovery_scope(ctx)
    recover_li = scope == "all"
    empty_mf = MassFlow(0.0, meta={"comp_abs": {}, "comp": {}})

    black_mass_nmc = out_sv["black mass"]
    out_nmc1, row_nmc1, ex_nmc1 = run_hydro_nmc_digestion(ctx, black_mass_nmc, params=None); step_rows.append(row_nmc1)
    out_nmc2, row_nmc2, ex_nmc2 = run_hydro_nmc_leaching(ctx, out_nmc1["digested BM solution"], params=None); step_rows.append(row_nmc2)
    out_nmc3, row_nmc3, ex_nmc3 = run_hydro_nmc_graphite_filtration(ctx, out_nmc2["BM leachate"], params=None); step_rows.append(row_nmc3)
    out_nmc4, row_nmc4, ex_nmc4 = run_hydro_nmc_cu_cementation(ctx, out_nmc3["lye graphite clean"], params=None); step_rows.append(row_nmc4)
    out_nmc5, row_nmc5, ex_nmc5 = run_hydro_nmc_cu_filtration(ctx, out_nmc4["lye copper cementation"], params=None); step_rows.append(row_nmc5)
    out_nmc6, row_nmc6, ex_nmc6 = run_hydro_nmc_fe_oxidation(ctx, out_nmc5["lye copper clean"], params=None); step_rows.append(row_nmc6)
    out_nmc7, row_nmc7, ex_nmc7 = run_hydro_nmc_fe_al_precipitation(ctx, out_nmc6["lye oxidation"], params=None); step_rows.append(row_nmc7)
    out_nmc8, row_nmc8, ex_nmc8 = run_hydro_nmc_fe_al_filtration(ctx, out_nmc7["lye iron, aluminium precipitation"], params=None); step_rows.append(row_nmc8)
    nmc_p = nmc_precip_params_from_ctx(ctx)
    out_nmc9, row_nmc9, ex_nmc9 = run_hydro_nmc_mixing_nmc(ctx, out_nmc8["lye iron, aluminium clean"], params=nmc_p); step_rows.append(row_nmc9)
    out_nmc10, row_nmc10, ex_nmc10 = run_hydro_nmc_precipitation_nmc(ctx, out_nmc9["lye precursor mixing"], params=nmc_p); step_rows.append(row_nmc10)
    out_nmc11, row_nmc11, ex_nmc11 = run_hydro_nmc_filtration_nmc(ctx, out_nmc10["lye precursor precipitation"], params=None); step_rows.append(row_nmc11)
    out_nmc12, row_nmc12, ex_nmc12 = run_hydro_nmc_washing_nmc(ctx, out_nmc11["NMC Precursor"], params=None); step_rows.append(row_nmc12)
    out_nmc13, row_nmc13, ex_nmc13 = run_hydro_nmc_drying_nmc(ctx, out_nmc12["NMC Precursor washed"], params=nmc_p); step_rows.append(row_nmc13)

    ex_nmc = {
        "Hydro NMC – Digestion": ex_nmc1, "Hydro NMC – Leaching": ex_nmc2, "Hydro NMC – Graphite Filtration": ex_nmc3,
        "Hydro NMC – Cu Cementation": ex_nmc4, "Hydro NMC – Cu Filtration": ex_nmc5, "Hydro NMC – Fe Oxidation": ex_nmc6,
        "Hydro NMC – Fe+Al Precipitation": ex_nmc7, "Hydro NMC – Fe+Al Filtration": ex_nmc8, "Hydro NMC – NMC Mixing": ex_nmc9,
        "Hydro NMC – NMC Precipitation": ex_nmc10, "Hydro NMC – NMC Filtration": ex_nmc11, "Hydro NMC – NMC Washing": ex_nmc12,
        "Hydro NMC – NMC Drying": ex_nmc13,
    }

    out_nmc14 = out_nmc15 = out_nmc16 = out_nmc17 = None
    if recover_li:
        out_nmc14, row_nmc14, ex_nmc14 = run_hydro_nmc_li_precipitation(ctx, out_nmc11["lye NMC clean"], params=None); step_rows.append(row_nmc14)
        out_nmc15, row_nmc15, ex_nmc15 = run_hydro_nmc_li_filtration(ctx, out_nmc14["lye lithium precipitation"], params=None); step_rows.append(row_nmc15)
        out_nmc16, row_nmc16, ex_nmc16 = run_hydro_nmc_li_washing(ctx, out_nmc15["Lithium Carbonate"], params=None); step_rows.append(row_nmc16)
        out_nmc17, row_nmc17, ex_nmc17 = run_hydro_nmc_li_drying(ctx, out_nmc16["Lithium Carbonate washed"], params=None); step_rows.append(row_nmc17)
        ex_nmc.update({
            "Hydro NMC – Li Precipitation": ex_nmc14, "Hydro NMC – Li Filtration": ex_nmc15,
            "Hydro NMC – Li Washing": ex_nmc16, "Hydro NMC – Li Drying": ex_nmc17,
        })

    ww_parts: list[MassFlow] = [out_nmc13.get("wastewater drying", empty_mf)]
    if scope == "nmc":
        ww_parts.append(out_nmc11["lye NMC clean"])
    elif recover_li and out_nmc15 is not None:
        ww_parts.append(out_nmc15.get("wastewater filtration", empty_mf))
        ww_parts.append(out_nmc16.get("wastewater washing", empty_mf))
        ww_parts.append(out_nmc17.get("wastewater drying", empty_mf))

    ww_nmc_in = _combine_flows(*ww_parts)
    out_nmc18, row_nmc18, ex_nmc18 = run_hydro_nmc_wastewater_treatment(ctx, ww_nmc_in, params=None); step_rows.append(row_nmc18)
    ex_nmc["Hydro NMC – Wastewater Treatment"] = ex_nmc18
    return ex_nmc


# ----------------------- UNIFIED FEED BUILDER -----------------------

def build_ctx_unified_feed(scen: dict) -> tuple[dict, dict[str, MassFlow], dict]:
    """
    scen:
      - mass_feed_kg_y (total annual mass across all items)
      - feed: list of {cell_id, level: pack/module/cell, share}
      - pack_energy_kWh (default)
      - pack_energy_by_id (optional)
    """
    hours = _hours_per_year()

    mass_feed_y = float(scen.get("mass_feed_kg_y", 0.0) or 0.0)
    if mass_feed_y <= 0:
        raise ValueError("UNIFIED requires scen['mass_feed_kg_y'] > 0")

    feed_list = list(scen.get("feed", []) or [])
    if not feed_list:
        raise ValueError("UNIFIED requires scen['feed'] list")

    raw_shares = [max(float(it.get("share", 0.0) or 0.0), 0.0) for it in feed_list]
    s = sum(raw_shares)
    if s <= 0:
        raise ValueError("UNIFIED: feed shares sum to 0")
    shares_norm = [x / s for x in raw_shares]

    pack_kWh_default = float(scen.get("pack_energy_kWh", 100.0))
    pack_kWh_by_id = dict(scen.get("pack_energy_by_id", {}) or {})

    comp_abs_pack_kgh: dict[str, float] = {}
    comp_abs_mod_kgh: dict[str, float] = {}
    comp_abs_cell_kgh: dict[str, float] = {}

    details_by_item: list[dict] = []

    pack_mass_y_total = 0.0
    module_mass_y_total = 0.0
    cell_mass_y_total = 0.0

    for it, share in zip(feed_list, shares_norm):
        cell_id = str(it.get("cell_id", "")).strip()
        level = str(it.get("level", "")).strip().lower()

        if not cell_id:
            continue
        if level not in {"pack", "module", "cell"}:
            raise ValueError(f"UNIFIED: invalid level='{level}' for cell_id='{cell_id}'")

        pack_kWh = float(pack_kWh_by_id.get(cell_id, pack_kWh_default))
        batt = DB.build_battery(cell_id, pack_energy_kWh=pack_kWh)

        if level == "pack":
            unit_mass = float(batt.get("System weight", 0.0) or 0.0)
            comp_per_unit = batt.get("system_comp_abs") or {}
        elif level == "module":
            unit_mass = float(batt.get("Module weight total", 0.0) or 0.0)
            comp_per_unit = batt.get("module_comp_abs") or {}
        else:  # cell
            unit_mass = float(batt.get("Cell weight", 0.0) or 0.0)
            comp_per_unit = batt.get("cell_comp_abs") or {}

        if unit_mass <= 0:
            raise ValueError(f"UNIFIED: unit_mass missing/zero for {cell_id} level={level}")
        if not isinstance(comp_per_unit, dict) or not comp_per_unit:
            raise ValueError(f"UNIFIED: comp_abs missing for {cell_id} level={level}")

        mass_y_item = mass_feed_y * float(share)
        units_y = mass_y_item / unit_mass
        units_h = units_y / hours

        target = (
            comp_abs_pack_kgh if level == "pack"
            else comp_abs_mod_kgh if level == "module"
            else comp_abs_cell_kgh
        )
        for k, v in comp_per_unit.items():
            target[str(k)] = target.get(str(k), 0.0) + float(v) * units_h

        if level == "pack":
            pack_mass_y_total += mass_y_item
        elif level == "module":
            module_mass_y_total += mass_y_item
        else:
            cell_mass_y_total += mass_y_item

        chem, geom = parse_cell_id(cell_id)
        details_by_item.append({
            "cell_id": cell_id,
            "chemistry": chem,
            "geometry": geom,
            "level": level,
            "share": float(share),
            "unit_mass_kg": unit_mass,
            "units_per_year": units_y,
            "units_per_h": units_h,
            "comp_abs_kg_per_unit": dict(comp_per_unit),
            "pack_energy_kWh": pack_kWh,
            "cell_energy_Wh": float(batt.get("cell_energy_Wh", 0.0) or 0.0),
            "cells_per_module": int(batt.get("Cells per module", 0) or 0),
            "cells_per_pack": int(batt.get("Cells per pack", 0) or 0),
        })

    flow_pack = MassFlow(pack_mass_y_total / hours, meta={"comp_abs": comp_abs_pack_kgh, "comp": abs_to_frac(comp_abs_pack_kgh)})
    flow_mod  = MassFlow(module_mass_y_total / hours, meta={"comp_abs": comp_abs_mod_kgh,  "comp": abs_to_frac(comp_abs_mod_kgh)})
    flow_cell = MassFlow(cell_mass_y_total / hours, meta={"comp_abs": comp_abs_cell_kgh, "comp": abs_to_frac(comp_abs_cell_kgh)})

    flow_total = _combine_flows(flow_pack, flow_mod, flow_cell)

    nmc_code = resolve_nmc_code(scen)

    ctx = {
        "scenario": scen["name"],
        "chemistry": "UNIFIED_FEED",
        "mix": {"UNIFIED": 1.0},
        "hours_per_year": hours,
        "nmc_code": nmc_code,
        "nmc_target_basis": resolve_nmc_target_basis(scen),
        "nmc_makeup_policy": resolve_nmc_makeup_policy(scen),
        "nmc_max_makeup_fill_fraction": resolve_nmc_makeup_fill_fraction(scen),
        "nh3_coordination_number": float(scen.get("nh3_coordination_number", 6.0) or 6.0),
        "nh3_loss_fraction": float(scen.get("nh3_loss_fraction", 0.10) or 0.10),
        "nh3_solution_wtfrac": float(scen.get("nh3_solution_wtfrac", 0.25) or 0.25),
        "nmc_hydro_recovery_scope": resolve_nmc_hydro_recovery_scope(scen),
        "lfp_hydro_recovery_scope": resolve_lfp_hydro_recovery_scope(scen),
        "mix_hydro_recovery_scope": resolve_mix_hydro_recovery_scope(scen),
        "pyro_hydro_recovery_scope": resolve_pyro_hydro_recovery_scope(scen),

        # ✅ Mixed feed normalization basis
        "feed_mass_kg_per_year": mass_feed_y,
        "feed_kg_per_h": float(flow_total.mass_kg_per_h),

        # optional reporting
        "pack_mass_kg_per_year": pack_mass_y_total,
        "module_mass_kg_per_year": module_mass_y_total,
        "cell_mass_kg_per_year": cell_mass_y_total,
        "feed_has_pack": pack_mass_y_total > 1e-12,
        "feed_details": details_by_item,
    }

    p_dis = {"treat_as": "mixed"}  # discharge treats as mixed
    flows = {"pack": flow_pack, "module": flow_mod, "cell": flow_cell, "total": flow_total}
    return ctx, flows, p_dis


# ----------------------- Runner -----------------------

def _run_pyro_spoke(
    ctx: dict,
    pyro_mech_input: MassFlow,
    step_rows: list[pd.DataFrame],
) -> tuple[dict, MassFlow, MassFlow | None, dict]:
    """Run pyro smelting and granulation at the spoke site."""
    scope = resolve_pyro_hydro_recovery_scope(ctx)
    run_pyro_slag_granulation = scope in ("all", "co_ni_mn")

    out_py1, row_py1, ex_py1 = run_pyro_smelting(ctx, pyro_mech_input)
    step_rows.append(row_py1)

    out_py2, row_py2, ex_py2 = run_pyro_gas_scrubbing(ctx, _mf_any(out_py1, "offgas"))
    step_rows.append(row_py2)

    out_py3a, row_py3a, ex_py3a = run_pyro_granulation_alloy(ctx, _mf_any(out_py1, "alloy"))
    step_rows.append(row_py3a)

    ex_pyro: dict = {
        "Pyro Smelting": ex_py1,
        "Pyro Gas scrubbing": ex_py2,
        "Pyro Granulation (Alloy)": ex_py3a,
    }
    out_py3b = None
    if run_pyro_slag_granulation:
        out_py3b, row_py3b, ex_py3b = run_pyro_granulation_slag(ctx, _mf_any(out_py1, "slag"))
        step_rows.append(row_py3b)
        ex_pyro["Pyro Granulation (Slag)"] = ex_py3b

    scope_flags = {
        "scope": scope,
        "run_pyro_slag_granulation": run_pyro_slag_granulation,
        "run_hydro_slag_branch": scope in ("all", "co_ni_mn"),
        "run_slag_li_line": scope == "all",
        "run_ni_crystallization": scope in ("all", "co_ni", "co_ni_mn"),
    }
    granulated_alloy = _mf_any(out_py3a, "granulated alloy")
    granulated_slag = _mf_any(out_py3b, "granulated slag") if out_py3b is not None else None
    return ex_pyro, granulated_alloy, granulated_slag, scope_flags


def _run_hydro_pyro_hub(
    ctx: dict,
    granulated_alloy: MassFlow,
    granulated_slag: MassFlow | None,
    scope_flags: dict,
    step_rows: list[pd.DataFrame],
) -> dict:
    """Run hydro-pyro refining at the hub site."""
    run_hydro_slag_branch = bool(scope_flags.get("run_hydro_slag_branch"))
    run_slag_li_line = bool(scope_flags.get("run_slag_li_line"))
    run_ni_crystallization = bool(scope_flags.get("run_ni_crystallization"))

    ex_hy: dict = {}

    if run_hydro_slag_branch and granulated_slag is not None:
        out_slag1, row_slag1, ex_slag1 = run_hydro_pyro_slag_digestion(ctx, granulated_slag)
        step_rows.append(row_slag1)

        out_slag2, row_slag2, ex_slag2 = run_hydro_pyro_slag_leaching(ctx, _mf_any(out_slag1, "digested slag solution"))
        step_rows.append(row_slag2)

        out_slag3, row_slag3, ex_slag3 = run_hydro_pyro_slag_sio2_caso4_filtration(ctx, _mf_any(out_slag2, "slag leachate"))
        step_rows.append(row_slag3)

        out_slag4, row_slag4, ex_slag4 = run_hydro_pyro_slag_fe_oxidation(ctx, _mf_any(out_slag3, "lye slagformer clean"))
        step_rows.append(row_slag4)

        out_slag5, row_slag5, ex_slag5 = run_hydro_pyro_slag_fe_al_precipitation(ctx, _mf_any(out_slag4, "lye oxidation"))
        step_rows.append(row_slag5)

        out_slag6, row_slag6, ex_slag6 = run_hydro_pyro_slag_fe_al_filtration(
            ctx, _mf_any(out_slag5, "lye iron,aluminium precipitation"))
        step_rows.append(row_slag6)

        out_slag7, row_slag7, ex_slag7 = run_hydro_pyro_slag_mn_extraction(ctx, _mf_any(out_slag6, "lye iron,aluminium clean"))
        step_rows.append(row_slag7)

        mn_loaded_phase = _mf_any(out_slag7, "mn_loaded_phase", "Mn loaded organic phase")
        out_slag8, row_slag8, ex_slag8 = run_hydro_pyro_slag_mn_scrubbing(ctx, mn_loaded_phase)
        step_rows.append(row_slag8)

        mn_scrubbed_phase = _mf_any(out_slag8, "mn_scrubbed_phase", "Mn scrubbed phase")
        out_slag9, row_slag9, ex_slag9 = run_hydro_pyro_slag_mn_stripping(ctx, mn_scrubbed_phase)
        step_rows.append(row_slag9)

        out_slag10, row_slag10, ex_slag10 = run_hydro_pyro_slag_mn_crystallization(
            ctx, _mf_any(out_slag9, "Mn stripped solution")
        )
        step_rows.append(row_slag10)

        ex_hy.update({
            "Hydro Pyro – Slag Digestion": ex_slag1,
            "Hydro Pyro – Slag Leaching": ex_slag2,
            "Hydro Pyro – Slag SiO2/CaSO4 Filtration": ex_slag3,
            "Hydro Pyro – Slag Fe Oxidation": ex_slag4,
            "Hydro Pyro – Fe+Al Precipitation": ex_slag5,
            "Hydro Pyro – Fe+Al Filtration": ex_slag6,
            "Hydro Pyro – Mn Extraction": ex_slag7,
            "Hydro Pyro – Mn Scrubbing": ex_slag8,
            "Hydro Pyro – Mn Stripping": ex_slag9,
            "Hydro Pyro – Mn Crystallization": ex_slag10,
        })

        if run_slag_li_line:
            out_li1, row_li1, ex_li1 = run_hydro_li_concentration(ctx, _mf_any(out_slag7, "lye after Mn extraction"))
            step_rows.append(row_li1)

            out_li2, row_li2, ex_li2 = run_hydro_pyro_slag_li_precipitation(ctx, _mf_any(out_li1, "lye concentrated"))
            step_rows.append(row_li2)

            out_li3, row_li3, ex_li3 = run_hydro_pyro_slag_li_filtration(ctx, _mf_any(out_li2, "lye lithium precipitation"))
            step_rows.append(row_li3)

            out_li4, row_li4, ex_li4 = run_hydro_pyro_slag_li_washing(ctx, _mf_any(out_li3, "Lithium Carbonate"))
            step_rows.append(row_li4)

            out_li5, row_li5, ex_li5 = run_hydro_pyro_slag_li_drying(ctx, _mf_any(out_li4, "Lithium Carbonate washed"))
            step_rows.append(row_li5)

            li_ww_from_conc = out_li1.get("wastewater")
            if li_ww_from_conc is None:
                li_ww_from_conc = out_li1.get("Wastewater", MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}))

            li_ww_from_filtration = out_li3.get("wastewater filtration")
            if li_ww_from_filtration is None:
                li_ww_from_filtration = out_li3.get("Wastewater filtration", MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}))

            li_ww_from_washing = out_li4.get("wastewater washing")
            if li_ww_from_washing is None:
                li_ww_from_washing = out_li4.get("Wastewater washing", MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}))

            li_ww_from_drying = out_li5.get("wastewater drying")
            if li_ww_from_drying is None:
                li_ww_from_drying = out_li5.get("Wastewater drying", MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}))
            ww_li_in = _combine_flows(
                li_ww_from_conc,
                li_ww_from_filtration,
                li_ww_from_washing,
                li_ww_from_drying,
                _mf_any(out_slag10, "Mn mother liquor"),
            )
            ex_hy.update({
                "Hydro Pyro – Li Concentration": ex_li1,
                "Hydro Pyro – Li Precipitation": ex_li2,
                "Hydro Pyro – Li Filtration": ex_li3,
                "Hydro Pyro – Li Washing": ex_li4,
                "Hydro Pyro – Li Drying": ex_li5,
            })
        else:
            ww_li_in = _combine_flows(
                _mf_any(out_slag7, "lye after Mn extraction"),
                _mf_any(out_slag10, "Mn mother liquor"),
            )

        out_li6, row_li6, ex_li6 = run_hydro_pyro_slag_li_wastewater_treatment(ctx, ww_li_in)
        step_rows.append(row_li6)
        ex_hy["Hydro Pyro – Li Wastewater Treatment"] = ex_li6

    out_hy1, row_hy1, ex_hy1 = run_hydro_pyro_alloy_digestion(ctx, granulated_alloy)
    step_rows.append(row_hy1)

    out_hy2, row_hy2, ex_hy2 = run_hydro_pyro_alloy_leaching(ctx, _mf_any(out_hy1, "digested alloy solution"))
    step_rows.append(row_hy2)

    out_hy3, row_hy3, ex_hy3 = run_hydro_pyro_alloy_cu_cementation(ctx, _mf_any(out_hy2, "alloy leachate"))
    step_rows.append(row_hy3)

    out_hy4, row_hy4, ex_hy4 = run_hydro_pyro_alloy_cu_filtration(ctx, _mf_any(out_hy3, "lye copper cementation"))
    step_rows.append(row_hy4)

    out_hy5, row_hy5, ex_hy5 = run_hydro_pyro_alloy_fe_oxidation(ctx, _mf_any(out_hy4, "lye copper clean"))
    step_rows.append(row_hy5)

    out_hy6, row_hy6, ex_hy6 = run_hydro_pyro_alloy_fe_precipitation(ctx, _mf_any(out_hy5, "lye oxidation"))
    step_rows.append(row_hy6)

    out_hy7, row_hy7, ex_hy7 = run_hydro_pyro_alloy_fe_filtration(ctx, _mf_any(out_hy6, "lye iron precipitation"))
    step_rows.append(row_hy7)

    out_hy8, row_hy8, ex_hy8 = run_hydro_pyro_alloy_co_extraction(ctx, _mf_any(out_hy7, "lye iron clean"))
    step_rows.append(row_hy8)

    out_hy9, row_hy9, ex_hy9 = run_hydro_pyro_alloy_co_scrubbing(ctx, _mf_any(out_hy8, "Co loaded organic phase"))
    step_rows.append(row_hy9)

    out_hy10, row_hy10, ex_hy10 = run_hydro_pyro_alloy_co_stripping(ctx, _mf_any(out_hy9, "Co scrubbed phase"))
    step_rows.append(row_hy10)

    out_hy11, row_hy11, ex_hy11 = run_hydro_pyro_alloy_co_crystallization(ctx, _mf_any(out_hy10, "Co stripped solution"))
    step_rows.append(row_hy11)

    if run_ni_crystallization:
        out_hy12, row_hy12, ex_hy12 = run_hydro_pyro_ni_crystallization(ctx, _mf_any(out_hy8, "lye after Co extraction"))
        step_rows.append(row_hy12)
        ww_in = _combine_flows(
            _mf_any(out_hy11, "Co mother liquor"),
            _mf_any(out_hy12, "Ni mother liquor"),
        )
    else:
        ww_in = _mf_any(out_hy11, "Co mother liquor")

    out_hy13, row_hy13, ex_hy13 = run_hydro_pyro_alloy_wastewater_treatment(ctx, ww_in)
    step_rows.append(row_hy13)

    ex_hy.update({
        "Hydro Pyro – Alloy Digestion": ex_hy1,
        "Hydro Pyro – Alloy Leaching": ex_hy2,
        "Hydro Pyro – Cu Cementation": ex_hy3,
        "Hydro Pyro – Cu Filtration": ex_hy4,
        "Hydro Pyro – Fe Oxidation": ex_hy5,
        "Hydro Pyro – Fe Precipitation": ex_hy6,
        "Hydro-Pyro - Fe Filtration": ex_hy7,
        "Hydro-Pyro - Co Extraction": ex_hy8,
        "Hydro-Pyro - Co Scrubbing": ex_hy9,
        "Hydro-Pyro - Co Stripping": ex_hy10,
        "Hydro-Pyro - Co Crystallization": ex_hy11,
        "Hydro-Pyro - Alloy Wastewater Treatment": ex_hy13,
    })
    if run_ni_crystallization:
        ex_hy["Hydro-Pyro - Ni Crystallization"] = ex_hy12

    return ex_hy


def run_scenario(scen: dict) -> tuple[pd.DataFrame, dict, dict]:
    if "feed" not in scen or "mass_feed_kg_y" not in scen:
        raise ValueError("Use unified scenario: mass_feed_kg_y + feed list")

    if scen.get("cost_region_xlsx"):
        gp.set_region_file(str(scen["cost_region_xlsx"]))
        ms.reload_machines_from_excel(str(scen["cost_region_xlsx"]))
    if scen.get("cell_tech_xlsx"):
        set_cell_tech_file(str(scen["cell_tech_xlsx"]))
    if scen.get("eff_xlsx"):
        rfx.set_eff_file(str(scen["eff_xlsx"]))

    mode = "UNIFIED"
    ctx, flows, p_dis = build_ctx_unified_feed(scen)
    lfp_only, mix_lfp_nmc, nmc_only = _route_flags_from_feed(scen)
    route = str(scen.get("route", "mech")).strip().lower()
    hub_spoke = is_hub_spoke_mode(scen)

    spoke_region = resolve_spoke_region(scen)
    hub_region = resolve_hub_region(scen)
    ctx_spoke = fork_ctx_region(ctx, spoke_region)
    ctx_hub = fork_ctx_region(ctx, hub_region) if hub_spoke else ctx_spoke

    ctx["infrastructure_mode"] = "hub_spoke" if hub_spoke else "integrated"
    ctx["spoke_region"] = spoke_region
    ctx["hub_region"] = hub_region
    ctx["region"] = spoke_region if hub_spoke else str(scen.get("region", "DE") or "DE")
    gp.apply_region(ctx, ctx["region"])

    step_rows: list[pd.DataFrame] = []
    transported_mass_kg_per_year = 0.0
    hours_y = float(ctx.get("hours_per_year") or 0.0)

    # 1) Analytics on TOTAL (spoke site)
    out_an, row_an, ex_an = run_analytics_sorting(ctx_spoke, flows["total"], params=None)
    step_rows.append(row_an)
    flow_total_after_an = out_an["sorted stream"]

    # 2) Discharge on TOTAL (spoke site)
    out_dis, row_dis, ex_dis = run_discharge(ctx_spoke, flow_total_after_an, p_dis)
    step_rows.append(row_dis)

    flow_pack_after = flows["pack"]
    flow_mod_after  = flows["module"]
    flow_cell_after = flows["cell"]

    ex_pack = {}
    modules_from_packs = MassFlow(0.0, meta={"comp_abs": {}, "comp": {}})
    if feed_has_pack_level(ctx_spoke):
        out_pack, row_pack, ex_pack = run_pack_dismantle(ctx_spoke, flow_pack_after, params=None)
        modules_from_packs = out_pack["modules"]
        step_rows.append(row_pack)

    pyro_mech_input = _combine_flows(modules_from_packs, flow_mod_after, flow_cell_after)

    ex_pyro = {}
    ex_hy = {}
    ex_mech = {}

    if route == "pyro":
        ex_pyro, granulated_alloy, granulated_slag, scope_flags = _run_pyro_spoke(
            ctx_spoke, pyro_mech_input, step_rows
        )
        ex_hy = _run_hydro_pyro_hub(ctx_hub, granulated_alloy, granulated_slag, scope_flags, step_rows)
        transported_mass_kg_per_year = _transport_mass_kg_per_year_from_flow(granulated_alloy, hours_y)
        if granulated_slag is not None:
            transported_mass_kg_per_year += _transport_mass_kg_per_year_from_flow(granulated_slag, hours_y)
    else:
        out_sv, ex_mech = _run_mech_preprocessing(ctx_spoke, pyro_mech_input, step_rows)
        black_mass_flow = out_sv.get("black mass")
        transported_mass_kg_per_year = _transport_mass_kg_per_year_from_flow(black_mass_flow, hours_y)
        ctx["black_mass_kg_per_year"] = transported_mass_kg_per_year

        ex_lfp = {}
        if lfp_only:
            ex_lfp = _run_hydro_lfp_route(ctx_hub, out_sv, step_rows)

        ex_mix = {}
        if mix_lfp_nmc:
            ex_mix = _run_hydro_mix_route(ctx_hub, out_sv, step_rows)

        ex_nmc = {}
        if nmc_only:
            ex_nmc = _run_hydro_nmc_route(ctx_hub, out_sv, step_rows)

    infra_payload = compute_infrastructure(
        scen,
        ctx,
        route=route,
        feed_mass_kg_per_year=float(ctx.get("feed_mass_kg_per_year") or 0.0),
        transported_mass_kg_per_year=transported_mass_kg_per_year,
    )
    ctx["infrastructure"] = infra_payload

    step_rows = _annotate_step_rows(step_rows, scen)
    overhead_payload = aggregate_dual_region_overhead(ctx, flows, step_rows, scen, infra_payload)

    # Reporting frame (meta columns via concat — avoids fragmented insert)
    steps_df = pd.concat(step_rows, ignore_index=True)
    n = len(steps_df)
    meta_df = pd.DataFrame(
        {
            "Scenario": [ctx["scenario"]] * n,
            "Mode": [mode] * n,
            "Chemistry": [ctx["chemistry"]] * n,
        }
    )
    steps_df = pd.concat([meta_df, steps_df], axis=1)

    extras_all = {
        "Analytics & Sorting": ex_an,
        "Discharge": ex_dis,
        "Overhead": overhead_payload,
    }
    if feed_has_pack_level(ctx):
        extras_all["Pack Dismantle"] = ex_pack

    if route == "pyro":
        extras_all.update(ex_pyro)
        extras_all.update(ex_hy)
    else:
        extras_all.update(ex_mech)
        if lfp_only:
            extras_all.update(ex_lfp)
        if mix_lfp_nmc:
            extras_all.update(ex_mix)
        if nmc_only:
            extras_all.update(ex_nmc)
    ctx["route"] = route
    ctx["recovery_flags"] = {
        "lfp_only": lfp_only,
        "mix_lfp_nmc": mix_lfp_nmc,
        "nmc_only": nmc_only,
    }
    if route == "pyro":
        ctx["recovery_route"] = "pyro"
    elif mix_lfp_nmc:
        ctx["recovery_route"] = "mix"
    elif lfp_only:
        ctx["recovery_route"] = "lfp"
    elif nmc_only:
        ctx["recovery_route"] = "nmc"
    else:
        ctx["recovery_route"] = "mech"
    return steps_df, extras_all, ctx


# ----------------------- Example Scenarios -----------------------

SCENARIOS = [
        {
        "name": "TEST_10tpy",
        "region": "DE",
        "route": "pyro",   # <-- Pyro-Route
        "mass_feed_kg_y": 10000,
        "pack_energy_kWh": 100.0,
        "pack_energy_by_id": {},
        "feed": [
            {"cell_id": "LFP_Pouch",              "level": "cell",   "share": 0.1},
            {"cell_id": "NMC811_Prismatic",      "level": "pack",   "share": 0.4},
            {"cell_id": "NMC111_Pouch",          "level": "module", "share": 0.5},
        ],
    },
        {
        "name": "Pyro_10tpy",
        "region": "DE",
        "route": "pyro",   # <-- Pyro-Route
        "mass_feed_kg_y": 10000,
        "pack_energy_kWh": 100.0,
        "pack_energy_by_id": {},
        "feed": [
            {"cell_id": "LFP_Pouch",              "level": "cell",   "share": 0.2},
            {"cell_id": "LFP_Cylindrical_4680",  "level": "pack",   "share": 0.2},
            {"cell_id": "NMC811_Prismatic",      "level": "pack",   "share": 0.4},
            {"cell_id": "NMC111_Pouch",          "level": "module", "share": 0.2},
        ],
    },
        {
        "name": "Mech_10tpy_LFP",
        "region": "DE",
        "route": "mech",   # <-- mechanische Route
        "mass_feed_kg_y": 10000,
        "pack_energy_kWh": 100.0,
        "pack_energy_by_id": {},
        "feed": [
            {"cell_id": "LFP_Pouch",              "level": "cell",   "share": 0.2},
            {"cell_id": "LFP_Cylindrical_4680",  "level": "pack",   "share": 0.2},
            {"cell_id": "LFP_Prismatic",      "level": "pack",   "share": 0.4},
            {"cell_id": "LFP_Pouch",          "level": "module", "share": 0.2},
        ],
        },
        {
        "name": "Mech_10tpy_MIX_unlimited_Co_basis",
        "region": "DE",
        "route": "mech",
        "nmc_code": "622",
        "nmc_target_basis": "co",
        "nmc_makeup_policy": "unlimited",
        "mass_feed_kg_y": 10000,
        "pack_energy_kWh": 100.0,
        "pack_energy_by_id": {},
        "feed": [
            {"cell_id": "NMC111_Pouch",              "level": "cell",   "share": 0.1},
            {"cell_id": "NMC811_Prismatic",  "level": "pack",   "share": 0.1},
            {"cell_id": "NMC622_Cylindrical_4680",      "level": "pack",   "share": 0.2},
            {"cell_id": "NMC532_Pouch",          "level": "module", "share": 0.05},
            {"cell_id": "LFP_Pouch",              "level": "cell",   "share": 0.05},
            {"cell_id": "LFP_Cylindrical_4680",  "level": "pack",   "share": 0.2},
            {"cell_id": "LFP_Prismatic",      "level": "module",   "share": 0.3},
        ],
    },
    {
        "name": "Mech_10tpy_NMC_unlimited_Co_basis",
        "region": "DE",
        "route": "mech",
        "nmc_code": "622",
        "nmc_target_basis": "co",
        "nmc_makeup_policy": "unlimited",
        "mass_feed_kg_y": 10000,
        "pack_energy_kWh": 100.0,
        "pack_energy_by_id": {},
        "feed": [
            {"cell_id": "NMC111_Pouch",              "level": "cell",   "share": 0.2},
            {"cell_id": "NMC811_Prismatic",  "level": "pack",   "share": 0.2},
            {"cell_id": "NMC622_Cylindrical_4680",      "level": "pack",   "share": 0.4},
            {"cell_id": "NMC532_Pouch",          "level": "module", "share": 0.2},
        ],
    },

]


if __name__ == "__main__":
    for scen in SCENARIOS:
        run_scenario(scen)