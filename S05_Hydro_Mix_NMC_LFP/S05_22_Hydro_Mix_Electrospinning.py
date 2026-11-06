from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    FEPO4_C_PRODUCT_RULES,
    deduct_from_suffixes,
    liquor_inventory_preserve_keys,
    reconcile_comp_abs_to_mass,
)
from Massflow import MassFlow, assert_mass_balance
from step_utils import (
    hours_per_year,
    annual_input_tons_from_flow,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)


def _mother_liquor_comp_abs(
    comp_abs_in: dict,
    *,
    m_target: float,
    fe_used_kg_h: float,
    p_used_kg_h: float,
    rules: dict,
) -> dict:
    comp = {str(k): float(v) for k, v in (comp_abs_in or {}).items() if abs(float(v)) > 1e-12}
    deduct_from_suffixes(comp, list(rules["fe_suffixes"]), fe_used_kg_h)
    deduct_from_suffixes(comp, list(rules["p_suffixes"]), p_used_kg_h)
    return reconcile_comp_abs_to_mass(
        comp,
        max(0.0, float(m_target)),
        preserve_keys=liquor_inventory_preserve_keys(comp),
    )


def run_hydro_mix_electrospinning_precursor(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_22: Electrospinning – split carbon dispersion slurry into:
      - FePO4-C Intermediate (→ roasting)
      - Mother Liquor (Fe/P depleted) (→ wastewater)
      - DMF (circulating) (solvent recovery / recycle)
    """
    p = params or {}
    step = "Hydro Mix – Electrospinning Precursor Formation"
    rules = FEPO4_C_PRODUCT_RULES

    meta_in = dict(getattr(flow_in, "meta", {}) or {})
    comp_in = dict(meta_in.get("comp_abs") or {})
    m_in_h = float(flow_in.mass_kg_per_h)

    m_fepo4_c_h = float(meta_in.get("m_fepo4_c_kg_h", 0.0) or 0.0)
    if m_fepo4_c_h <= 0.0:
        m_fepo4 = float(comp_in.get(str(rules["fepo4_key"]), 0.0) or 0.0)
        m_pvp = float(comp_in.get(str(rules["pvp_key"]), 0.0) or 0.0)
        m_fepo4_c_h = m_fepo4 + m_pvp

    dmf_key = str(rules["dmf_circulating_key"])
    m_dmf_circ_h = float(
        meta_in.get("m_dmf_circulating_kg_h", 0.0) or comp_in.get(dmf_key, 0.0) or 0.0
    )

    m_precursor_h = max(0.0, m_fepo4_c_h)
    m_dmf_out_h = max(0.0, m_dmf_circ_h)
    m_mother_h = max(0.0, m_in_h - m_precursor_h - m_dmf_out_h)

    fe_used = float(meta_in.get("m_fe_used_kg_h", 0.0) or 0.0)
    p_used = float(meta_in.get("m_p_used_kg_h", 0.0) or 0.0)
    if fe_used <= 0.0 and p_used <= 0.0:
        sto = meta_in.get("fepo4_c_stoich") or {}
        fe_used = float(sto.get("m_fe_used_kg_h", 0.0) or 0.0)
        p_used = float(sto.get("m_p_used_kg_h", 0.0) or 0.0)

    fepo4_key = str(rules["fepo4_key"])
    pvp_key = str(rules["pvp_key"])
    product_key = str(rules["product_key"])

    comp_precursor = {
        fepo4_key: float(comp_in.get(fepo4_key, 0.0) or 0.0),
        pvp_key: float(comp_in.get(pvp_key, 0.0) or 0.0),
        product_key: m_precursor_h,
    }
    comp_precursor = reconcile_comp_abs_to_mass(
        comp_precursor,
        m_precursor_h,
        preserve_keys=(fepo4_key, pvp_key, product_key),
    )

    comp_mother = _mother_liquor_comp_abs(
        comp_in,
        m_target=m_mother_h,
        fe_used_kg_h=fe_used,
        p_used_kg_h=p_used,
        rules=rules,
    )

    comp_dmf = {dmf_key: m_dmf_out_h} if m_dmf_out_h > 0.0 else {}

    flow_precursor = MassFlow(
        m_precursor_h,
        meta={"comp_abs": comp_precursor, "m_fepo4_c_kg_h": m_precursor_h},
    )
    flow_mother = MassFlow(m_mother_h, meta={"comp_abs": comp_mother})
    flow_dmf = MassFlow(m_dmf_out_h, meta={"comp_abs": comp_dmf, "recycled": True})

    outputs = {
        "mix_electrospinning_precursor": flow_precursor,
        "fe_process_residue": flow_mother,
        "dmf_recovered": flow_dmf,
    }

    assert_mass_balance(step, m_in_h, outputs)

    out_forward = flow_precursor

    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.evaporator,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.evaporator.name, sizing)

    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.evaporator.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(out_forward.mass_kg_per_h)
    row["Loss (kg/h)"] = 0.0
    row["Side streams (kg/h)"] = float(m_mother_h + m_dmf_out_h)
    row["Forward key"] = "mix_electrospinning_precursor"
    row["Loss sink key"] = "-"
    row["Side keys"] = "fe_process_residue, dmf_recovered"

    row["FePO4-C Intermediate (kg/h)"] = float(m_precursor_h)
    row["Mother Liquor (Fe/P depleted) (kg/h)"] = float(m_mother_h)
    row["DMF circulating (kg/h)"] = float(m_dmf_out_h)
    row["DMF recovered (kg/h)"] = float(m_dmf_out_h)
    row["Solvent evaporated (kg/h)"] = float(m_dmf_out_h)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    row = attach_opex_to_row(
        row,
        machine=Eq.evaporator,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["CAPEX install ($)"] = float(sizing.get("capex_install_model", 0.0))
    row["CAPEX instr ($)"] = float(sizing.get("capex_instr", 0.0))
    row["CAPEX piping ($)"] = float(sizing.get("capex_piping", 0.0))
    row["CAPEX electrical ($)"] = float(sizing.get("capex_electrical", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras
