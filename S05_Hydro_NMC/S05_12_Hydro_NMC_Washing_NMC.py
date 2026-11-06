from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import WASHING_RULES, washing_water_demand_kg_h
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


def run_hydro_nmc_washing_nmc(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_12: Hydro NMC – NMC Washing.

    - Input:  'NMC Precursor'
    - Output (Forward): 'NMC Precursor washed'
    - Output (Side):    'wastewater washing'
    """
    p = params or {}
    step = "Hydro NMC – NMC Washing"

    h_y = hours_per_year(ctx)
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    # 0) Generic washing demand from stoichiometry.py
    rule = WASHING_RULES["NMC_PRECURSOR"]
    water_ratio = float(p.get("water_to_solid_ratio", rule["water_to_solid_ratio_default"]))
    water_sf = float(p.get("washing_water_safety_factor", 1.0))

    m_precursor_h, m_water_h = washing_water_demand_kg_h(
        comp_abs=comp_abs,
        solid_suffixes=rule["solid_suffixes"],
        water_to_solid_ratio=water_ratio,
        safety_factor=water_sf,
    )
    m_water_y = m_water_h * h_y

    if m_water_h > 0.0:
        comp_abs["process:H2O_nmc_wash"] = comp_abs.get("process:H2O_nmc_wash", 0.0) + m_water_h

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_water_h,
        meta={"comp_abs": comp_abs},
    )

    # 1) Mass balance / partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="NMC Precursor washed")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="NMC Precursor washed")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    wastewater_flow = rfx.mf_get(outputs, "wastewater washing")
    wastewater_h = float(wastewater_flow.mass_kg_per_h)

    # 2) Sizing / CAPEX
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.reactor,
        flow_aug,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.reactor.name, sizing)

    # 3) Load + energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Reporting
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["NMC precursor in (kg/h)"] = float(m_precursor_h)
    row["Water added for washing (kg/h)"] = float(m_water_h)
    row["NMC precursor washed (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Wastewater washing (kg/h)"] = float(wastewater_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX
    pr = prices(ctx)
    h2o_price = float(pr.get("Water", 0.0))
    materials_cost_y = m_water_y * h2o_price

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

    # 6) CAPEX fallback
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