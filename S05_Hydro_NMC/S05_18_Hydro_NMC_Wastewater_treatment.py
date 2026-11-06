from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance
from step_utils import (
    hours_per_year,
    annual_input_tons_from_flow,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
    reduce_wastewater_mass,
    wastewater_reduction_factor,
)


def run_hydro_nmc_wastewater_treatment(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    Hydro NMC - Wastewater Treatment.

    Treats wastewater from the NMC route. Routing is controlled by EFF,
    including optional recovery of sodium sulfate from process:Na2SO4.

    Streams:
    - Input:  wastewater stream(s) from upstream NMC Li steps
    - Output (forward): 'wastewater treated'
    - Output (side):    'Sodium Sulfate'
    """
    p = params or {}
    step = "Hydro NMC – Wastewater Treatment"

    reduction_factor = wastewater_reduction_factor(p)
    flow_aug, m_in_h, m_reduced_h, m_removed_water_h = reduce_wastewater_mass(
        flow_in, params=p
    )

    # 1) Mass balance / partition (on reduced stream)
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="wastewater treated")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="wastewater treated")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    na2so4_flow = rfx.mf_get(outputs, "Sodium Sulfate")
    na2so4_h = float(na2so4_flow.mass_kg_per_h)

    # 2) Sizing / CAPEX
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.wastewater_treatment,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.wastewater_treatment.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.wastewater_treatment.energy_for_sized(
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

    row["Wastewater in (kg/h)"] = float(m_in_h)
    row["Wastewater treated (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Sodium Sulfate (kg/h)"] = float(na2so4_h)
    row["Water removed (kg/h)"] = float(m_in_h - m_reduced_h)
    row["Water removed from H2O keys (kg/h)"] = float(m_removed_water_h)
    row["Wastewater reduction factor (-)"] = float(reduction_factor)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX - energy only
    row = attach_opex_to_row(
        row,
        machine=Eq.wastewater_treatment,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # 6) CAPEX columns for standardized economics reporting
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["CAPEX install ($)"] = float(sizing.get("capex_install_model", 0.0))
    row["CAPEX instr ($)"] = float(sizing.get("capex_instr", 0.0))
    row["CAPEX piping ($)"] = float(sizing.get("capex_piping", 0.0))
    row["CAPEX electrical ($)"] = float(sizing.get("capex_electrical", 0.0))
    row["outputs_kg_h"] = [{
        "Sodium sulfate": float(na2so4_h),
        "Wastewater treated": float(out_forward.mass_kg_per_h),
    }]

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras