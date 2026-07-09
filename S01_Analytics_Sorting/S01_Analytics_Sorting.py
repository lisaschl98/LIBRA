"""Analytics and sorting process step.

This module models the front-end analytics/sorting unit for incoming battery
systems. 
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


def run_analytics_sorting(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run the analytics and sorting step.

    Parameters
    ----------
    ctx : dict
        Global scenario context (economic assumptions, runtime basis, etc.).
    flow_in : MassFlow
        Incoming material stream to be sorted.
    params : dict | None, optional
        Optional step overrides. Supported keys include:
        - ``design_load`` (default: 0.95)
        - ``max_lines`` (default: 600)

    Returns
    -------
    tuple
        (outputs, row, extras)
        - outputs: dict[str, MassFlow]
          Output streams after partition/yield logic.
        - row: pandas.DataFrame
          Single-row process summary used in scenario reporting.
        - extras: dict
          Supplemental data (e.g., CAPEX breakdown) used by downstream export.

    Notes
    -----
    - The default forward stream fallback is ``"sorted stream"``.
    - Mass balance is checked after partitioning/yield application.
    - No explicit chemical reaction is modeled in this step.
    """
    p = params or {}
    step = "Analytics & Sorting"

    # Apply configured partition/yield and validate global mass balance.
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="sorted stream")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="sorted stream")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # Equipment sizing (capacity and line count) based on forward stream load.
    design_load = float(p.get("design_load", 0.95))
    max_lines = int(p.get("max_lines", 600))
    sizing = size_machine_for_mass(
        step,
        Eq.analytics,
        out_forward,
        ctx,
        design_load=design_load,
        max_lines=max_lines,
    )

    # Keep CAPEX breakdown in extras for compatibility with downstream export.
    breakdown = capex_breakdown_df(step, Eq.analytics.name, sizing)

    # Compute realized utilization and annual energy demand.
    hours = hours_per_year(ctx)
    required_tph = float(out_forward.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(out_forward, ctx)
    annual_energy_kwh = Eq.analytics.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # Assemble reporting row.
    row = make_row(step, flow_in, out_forward)

    # Unified mass-flow reporting fields used by exports.
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Battery systems sorted (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / hours if hours > 0 else 0.0

    # Attach standardized OPEX fields expected by downstream reporting.
    row = attach_opex_to_row(
        row,
        machine=Eq.analytics,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # Keep detailed sizing/CAPEX columns for standardized economics reporting.
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