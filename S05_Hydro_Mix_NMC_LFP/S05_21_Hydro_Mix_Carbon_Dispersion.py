from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    FEPO4_C_PRODUCT_RULES,
    fepo4_c_product_stoich_kg_h,
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
    prices,
)


def run_hydro_mix_carbon_dispersion(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_21: Hydro Mix – Carbon Dispersion (FePO4-C precursor).

    - Slurry mass = lye + PVP + circulating DMF (mother liquor remains in slurry until electrospinning).
    - DMF make-up is consumed (OPEX) but not part of the slurry mass definition.
    - Forward: single ``mix_carbon_dispersion`` stream → electrospinning.
    """
    p = params or {}
    step = "Hydro Mix – Carbon Dispersion"
    h_y = hours_per_year(ctx)
    rules = FEPO4_C_PRODUCT_RULES

    meta_in = dict(getattr(flow_in, "meta", {}) or {})
    comp_in = dict(meta_in.get("comp_abs") or {})
    m_in_h = float(flow_in.mass_kg_per_h)

    sto = fepo4_c_product_stoich_kg_h(
        comp_in,
        carbon_wt_frac=float(p.get("carbon_wt_frac", rules["carbon_wt_frac_default"])),
        dmf_loss_fraction=float(p.get("dmf_loss_fraction", rules["dmf_loss_fraction_default"])),
    )

    m_fe_h = float(sto["m_fe_kg_h"])
    m_p_h = float(sto["m_p_kg_h"])
    m_fepo4_h = float(sto["m_fepo4_kg_h"])
    m_fepo4_c_h = float(sto["m_fepo4_c_kg_h"])
    m_carbon_h = float(sto["m_carbon_kg_h"])
    m_pvp_h = float(sto["m_pvp_kg_h"])
    m_dmf_circ_h = float(sto["m_dmf_circulating_kg_h"])
    m_dmf_makeup_h = float(sto["m_dmf_makeup_kg_h"])
    limiting = str(sto["limiting_reactant"])

    m_slurry_h = m_in_h + m_pvp_h + m_dmf_circ_h

    pvp_key = str(rules["pvp_key"])
    dmf_key = str(rules["dmf_circulating_key"])
    fepo4_key = str(rules["fepo4_key"])

    comp_slurry = {str(k): float(v) for k, v in comp_in.items() if abs(float(v)) > 1e-12}
    comp_slurry[pvp_key] = float(comp_slurry.get(pvp_key, 0.0) or 0.0) + m_pvp_h
    comp_slurry[dmf_key] = m_dmf_circ_h
    if m_fepo4_h > 0.0:
        comp_slurry[fepo4_key] = m_fepo4_h

    comp_slurry = reconcile_comp_abs_to_mass(
        comp_slurry,
        m_slurry_h,
        preserve_keys=liquor_inventory_preserve_keys(
            comp_slurry,
            extra_preserve=(pvp_key, dmf_key, fepo4_key),
        ),
    )

    stoich_meta = {
        "fepo4_c_stoich": sto,
        "m_fepo4_c_kg_h": m_fepo4_c_h,
        "m_dmf_circulating_kg_h": m_dmf_circ_h,
        "m_fe_used_kg_h": float(sto["m_fe_used_kg_h"]),
        "m_p_used_kg_h": float(sto["m_p_used_kg_h"]),
        "carbon_wt_frac": float(p.get("carbon_wt_frac", rules["carbon_wt_frac_default"])),
        "dmf_loss_fraction": float(p.get("dmf_loss_fraction", rules["dmf_loss_fraction_default"])),
    }

    flow_slurry = MassFlow(m_slurry_h, meta={"comp_abs": comp_slurry, **stoich_meta})

    outputs = {"mix_carbon_dispersion": flow_slurry}

    assert_mass_balance(step, m_in_h + m_pvp_h + m_dmf_circ_h, outputs)

    out_forward = flow_slurry

    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.reactor,
        flow_slurry,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.reactor.name, sizing)

    required_tph = float(flow_slurry.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_slurry, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(flow_slurry.mass_kg_per_h)
    row["Loss (kg/h)"] = 0.0
    row["Side streams (kg/h)"] = 0.0
    row["Forward key"] = "mix_carbon_dispersion"
    row["Loss sink key"] = "-"
    row["Side keys"] = "-"

    row["Mix carbon dispersion (kg/h)"] = float(flow_slurry.mass_kg_per_h)
    row["Fe process residue (kg/h)"] = 0.0
    row["Fe mass in feed (kg/h)"] = m_fe_h
    row["P mass in feed (kg/h)"] = m_p_h
    row["Limiting reactant FePO4"] = limiting
    row["m_FePO4 (kg/h)"] = m_fepo4_h
    row["Target carbon mass (kg/h)"] = m_carbon_h
    row["m_FePO4_C (kg/h)"] = m_fepo4_c_h
    row["PVP added (kg/h)"] = m_pvp_h
    row["DMF circulating (kg/h)"] = m_dmf_circ_h
    row["DMF make-up (kg/h)"] = m_dmf_makeup_h

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    pr = prices(ctx)
    pvp_price = float(pr.get("PVP", 0.0))
    dmf_price = float(pr.get("DMF", 0.0))
    materials_cost_y = (m_pvp_h * h_y * pvp_price) + (m_dmf_makeup_h * h_y * dmf_price)

    row = attach_opex_to_row(
        row,
        machine=Eq.reactor,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=materials_cost_y,
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
