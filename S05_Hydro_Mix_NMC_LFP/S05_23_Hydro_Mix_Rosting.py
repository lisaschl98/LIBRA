from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import FEPO4_C_PRODUCT_RULES, reconcile_comp_abs_to_mass
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import roasting_sensible_heating_kwh_h
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
    prices,
)


def run_hydro_mix_roasting(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_23: Roasting – thermal treatment under O2 atmosphere.

    No chemical conversion: FePO4-C mass in = FePO4-C mass out.
    O2 is supplied for the furnace atmosphere only; off-gas mass equals O2 feed (sweep).
    Default O2 feed: 10 wt% of FePO4-C precursor mass (atmospheric_o2_kg_per_kg_precursor=0.10).
    """
    p = params or {}
    step = "Hydro Mix – Roasting"
    rules = FEPO4_C_PRODUCT_RULES

    meta_in = dict(getattr(flow_in, "meta", {}) or {})
    comp_in = dict(meta_in.get("comp_abs") or {})
    m_in_h = float(flow_in.mass_kg_per_h)

    m_fepo4_c_h = float(meta_in.get("m_fepo4_c_kg_h", 0.0) or 0.0)
    if m_fepo4_c_h <= 0.0:
        m_fepo4 = float(comp_in.get(str(rules["fepo4_key"]), 0.0) or 0.0)
        m_pvp = float(comp_in.get(str(rules["pvp_key"]), 0.0) or 0.0)
        m_fepo4_c_h = m_fepo4 + m_pvp

    m_fepo4_h = float(comp_in.get(str(rules["fepo4_key"]), 0.0) or 0.0)
    if m_fepo4_h <= 0.0 and m_fepo4_c_h > 0.0:
        w_c = float(p.get("carbon_wt_frac", rules["carbon_wt_frac_default"]))
        m_fepo4_h = m_fepo4_c_h * (1.0 - w_c) if w_c < 1.0 else m_fepo4_c_h
    m_carbon_h = max(0.0, m_fepo4_c_h - m_fepo4_h)

    o2_per_kg = float(p.get("atmospheric_o2_kg_per_kg_precursor", 0.10))
    m_oxygen_h = max(0.0, m_fepo4_c_h * o2_per_kg)
    m_offgas_h = m_oxygen_h

    product_key = str(rules["product_key"])
    product_mass_h = m_fepo4_c_h

    comp_product = {str(k): float(v) for k, v in comp_in.items() if abs(float(v)) > 1e-12}
    comp_product[product_key] = product_mass_h
    comp_product = reconcile_comp_abs_to_mass(
        comp_product,
        product_mass_h,
        preserve_keys=tuple(comp_product.keys()),
    )

    flow_product = MassFlow(
        product_mass_h,
        meta={"comp_abs": comp_product, "m_fepo4_c_kg_h": m_fepo4_c_h},
    )
    flow_offgas = MassFlow(m_offgas_h, meta={"comp_abs": {"process:Offgas": m_offgas_h}})

    outputs = {
        "mix_roasted_product": flow_product,
        "roasting_offgas": flow_offgas,
    }

    assert_mass_balance(step, m_in_h + m_oxygen_h, outputs)

    out_forward = flow_product

    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.roaster,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.roaster.name, sizing)

    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    thermal = roasting_sensible_heating_kwh_h(m_fepo4_c_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])

    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(product_mass_h)
    row["Loss (kg/h)"] = 0.0
    row["Side streams (kg/h)"] = float(m_offgas_h)
    row["Forward key"] = "mix_roasted_product"
    row["Loss sink key"] = "-"
    row["Side keys"] = "roasting_offgas"

    row["FePO4-C product (kg/h)"] = float(product_mass_h)
    row["FePO4-C heated (kg/h)"] = float(m_fepo4_c_h)
    row["m_FePO4 in product (kg/h)"] = float(m_fepo4_h)
    row["Carbon in product (kg/h)"] = float(m_carbon_h)
    row["Oxygen added (kg/h)"] = float(m_oxygen_h)
    row["Off-gas (kg/h)"] = float(m_offgas_h)
    row["Roasting temperature (°C)"] = float(p.get("t_out_c", 500.0))

    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat sensible (kJ/h)"] = float(thermal["q_sensible_kj_h"])
    row["Thermal heat total (kJ/h)"] = float(thermal["q_total_kj_h"])
    row["Roasting heating delta T (K)"] = float(thermal["delta_t_k"])
    row["Roaster efficiency"] = float(thermal["roaster_efficiency"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    pr = prices(ctx)
    materials_cost_y = float(m_oxygen_h) * h_y * float(pr.get("Oxygen", 0.0))

    row = attach_opex_to_row(
        row,
        machine=Eq.roaster,
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
    row["outputs_kg_h"] = [
        {"Carbon coated Iron Phosphate (FePO4-C)": float(product_mass_h)},
    ]

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras
