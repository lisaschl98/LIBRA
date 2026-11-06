from __future__ import annotations
import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    LEACHING_RULES,
    leaching_water_demand_kg_h,
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

def run_hydro_pyro_alloy_leaching(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_2: Hydro Pyro - Alloy Leaching.
    Purpose:
    - Add process water to reach leaching conditions for dissolved metal sulfates.
    - Pass stream through configured EFF partition/yield.
    Forward stream:
    - 'alloy leachate'
    """
    p = params or {}
    step = "Hydro Pyro - Alloy Leaching"
    h_y = hours_per_year(ctx)

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})
    m_h2o_h = leaching_water_demand_kg_h(
        comp_abs=comp_abs,
        species_rules=LEACHING_RULES["alloy"],
        safety_factor=float(p.get("water_safety_factor", 1.1)),
    )

    if m_h2o_h > 0.0:
        comp_abs["process:H2O_leaching"] = comp_abs.get("process:H2O_leaching", 0.0) + m_h2o_h
    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_h2o_h,
        meta={"comp_abs": comp_abs},
    )
    # 1) Partition / yield
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="alloy leachate")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)
    summ = rfx.stream_summary(step, outputs, fallback_forward="alloy leachate")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]
    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    # 2) Equipment sizing and CAPEX
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
    # 3) Load and energy
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
    row["Alloy leachate (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["H2O added (kg/h)"] = float(m_h2o_h)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0
    # 5) OPEX: water as material cost
    pr = prices(ctx)
    m_h2o_y = m_h2o_h * h_y
    water_price = float(pr.get("Water", 0.0))  # assumed currency/m3
    water_cost_y = m_h2o_y * (water_price / 1000.0)  # convert kg -> m3
    row = attach_opex_to_row(
        row,
        machine=Eq.reactor,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=water_cost_y,
        add_perkg=True,
    )
    # 6) CAPEX columns for standardized economics reporting + extras
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