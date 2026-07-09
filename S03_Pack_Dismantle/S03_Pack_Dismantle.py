"""Pack dismantling process step.

This module models manual dismantling of battery packs into a forwarded
module/cell stream and separated pack side streams. 
"""

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
)


def run_pack_dismantle(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run the pack dismantling step.

    Parameters
    ----------
    ctx : dict
        Global scenario context (runtime and economic assumptions).
    flow_in : MassFlow
        Incoming pack stream to be dismantled.
    params : dict | None, optional
        Optional step overrides. Supported keys include:
        - ``design_load`` (default: 0.95)
        - ``max_lines`` (default: 600)

    Returns
    -------
    tuple
        (outputs, row, extras)
        - outputs: dict[str, MassFlow]
          Partitioned output streams (forward + side/loss streams).
        - row: pandas.DataFrame
          Single-row reporting summary.
        - extras: dict
          Supplementary data such as CAPEX breakdown.

    Notes
    -----
    The fallback forward stream is "modules".
    """
    p = params or {}
    step = "Pack Dismantle"

    # Apply configured partition/yield logic and validate overall mass balance.
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="modules")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="modules")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    forward_flow: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # Stream-level mass rates for transparent reporting (always defined).
    m_modules_h = rfx.mf_get(outputs, "modules").mass_kg_per_h
    m_al_h = rfx.mf_get(outputs, "Aluminium").mass_kg_per_h
    m_fe_h = rfx.mf_get(outputs, "Iron").mass_kg_per_h
    m_steel_h = rfx.mf_get(outputs, "Steel").mass_kg_per_h
    m_cu_h = rfx.mf_get(outputs, "Copper").mass_kg_per_h
    m_elec_h = rfx.mf_get(outputs, "Electronics").mass_kg_per_h
    m_waste_h = rfx.mf_get(outputs, "Waste").mass_kg_per_h

    m_sep_sum_h = m_al_h + m_fe_h + m_steel_h + m_cu_h + m_elec_h + m_waste_h

    # Equipment sizing is based on the forwarded modules stream.
    design_load = float(p.get("design_load", 0.95))
    sizing = size_machine_for_mass(
        step,
        Eq.dismantle,
        forward_flow,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.dismantle.name, sizing)

    # Compute actual utilization and annual energy demand.
    required_tph = float(forward_flow.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(forward_flow, ctx)
    annual_energy_kwh = Eq.dismantle.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # Assemble reporting row.
    row = make_row(step, flow_in, forward_flow)

    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    # Process split columns for downstream massflow reporting.
    row["Out sorted kg/h"] = float(m_sep_sum_h)
    row["Dismantled modules (kg/h)"] = float(m_modules_h)
    row["Pack Fe (kg/h)"] = float(m_fe_h)
    row["Pack Al (kg/h)"] = float(m_al_h)
    row["Pack Cu (kg/h)"] = float(m_cu_h)
    row["Pack Steel (kg/h)"] = float(m_steel_h)
    row["Pack Electronics (kg/h)"] = float(m_elec_h)
    row["Pack Other/Waste (kg/h)"] = float(m_waste_h)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    row = attach_opex_to_row(
        row,
        machine=Eq.dismantle,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # Keep explicit sizing/CAPEX fields for standardized economics reporting.
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["CAPEX install ($)"] = float(sizing.get("capex_install_model", 0.0))
    row["CAPEX instr ($)"] = float(sizing.get("capex_instr", 0.0))
    row["CAPEX piping ($)"] = float(sizing.get("capex_piping", 0.0))
    row["CAPEX electrical ($)"] = float(sizing.get("capex_electrical", 0.0))
    row["outputs_kg_h"] = [{
        "Aluminium scrap": float(m_al_h),
        "Iron scrap": float(m_fe_h),
        "Copper scrap": float(m_cu_h),
        "Steel scrap": float(m_steel_h),
        "Electronic scrap": float(m_elec_h),
        "Waste": float(m_waste_h),
    }]
    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras