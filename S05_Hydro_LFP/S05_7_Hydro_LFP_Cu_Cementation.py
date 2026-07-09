from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    CEMENTATION_RULES,
    cementation_reductant_demand_kg_h,
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




def run_hydro_lfp_cu_cementation(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_7: Hydro LFP - Cu Cementation.

    Removes dissolved copper from the LFP leach liquor by cementation with iron.
    Iron is added explicitly to the mass balance; precipitated copper is reported
    as KPI but not routed to a dedicated stream in this step (EFF can be extended
    later if needed).

    Streams:
    - Input:  'lye graphite clean'
    - Output (forward): 'lye copper cementation'
    """
    p = params or {}
    step = "Hydro LFP – Cu Cementation"

    h_y = hours_per_year(ctx)

    # 0) Add Fe reagent to the stream for strict mass balance tracking
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})



    m_fe_h, m_cu_h = cementation_reductant_demand_kg_h(
        comp_abs=comp_abs,
        rule=CEMENTATION_RULES["Cu_with_Fe"],
        safety_factor=float(p.get("fe_safety_factor", 1.1)),
    )
    if m_fe_h > 0.0:
        comp_abs["process:Fe_cement"] = comp_abs.get("process:Fe_cement", 0.0) + m_fe_h

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_fe_h,
        meta={"comp_abs": comp_abs},
    )

    # 1) Mass balance / partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye copper cementation")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye copper cementation")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Sizing / CAPEX – reactor based on augmented inlet throughput
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

    # 4) Reporting row
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye copper cementation (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Cu cemented (kg/h)"] = float(m_cu_h)
    row["Fe added (kg/h)"] = float(m_fe_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX – Fe reagent cost
    pr = prices(ctx)
    m_fe_y = m_fe_h * h_y
    fe_price = float(pr.get("Iron powder", 0.0))  # currency per kg of Fe
    materials_cost_y = m_fe_y * fe_price

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

    # 6) CAPEX columns for standardized economics reporting and extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras