from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import h2o2_solution_demand_kg_h_from_slurry_mass
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




def run_hydro_nmc_fe_oxidation(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
 
    p = params or {}
    step = "Hydro NMC – Fe Oxidation"

    # 0) H2O2 as additive mass (for cost/massflow reporting only)
    h_y = hours_per_year(ctx)
    m_h2o2_h = h2o2_solution_demand_kg_h_from_slurry_mass(
        float(flow_in.mass_kg_per_h),
        vol_frac=float(p.get("h2o2_vol_frac", 0.04)),
    )
    m_h2o2_y = m_h2o2_h * h_y

    # 1) MASS BALANCE / Partition (chemically unchanged, additive only)
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="lye oxidation")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye oxidation")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) SIZING / CAPEX – reactor based on inlet
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.reactor,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.reactor.name, sizing)

    # 3) LOAD + ENERGY
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Reporting row
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye oxidation (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["H2O2 added (kg/h)"] = float(m_h2o2_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX – H2O2 costs
    pr = prices(ctx)
    h2o2_price = float(pr.get("Hydrogen peroxide", 0.0))  # €/kg
    materials_cost_y = m_h2o2_y * h2o2_price

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

    # 6) CAPEX fallback columns & extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras