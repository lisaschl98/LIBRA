"""Pyro granulation for alloy process step.

This module models pyro granulation for alloy with a granulator. Granulated alloy is then used for further hydrometallurgical processing. 
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


def run_pyro_granulation_alloy(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """
    Run pyro granulation for the alloy stream.

    Purpose
    -------
    Convert alloy stream into a granulated alloy stream for downstream
    handling. No additional chemical separation is modeled in this step.
    Focus is on mass routing and CAPEX/OPEX.

    Inputs
    ------
    flow_in : alloy stream from pyro smelting

    Outputs
    -------
    outputs : configured streams from EFF (granulated alloy + optional loss)
    row     : standardized reporting row
    extras  : CAPEX breakdown for downstream export
    """
    p = params or {}
    step = "Pyro Granulation Alloy"

    # 1) Apply EFF partition/yield and validate mass balance.
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="granulated alloy")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="granulated alloy")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Size granulator on inlet throughput and compute CAPEX.
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.granulator,
        flow_in,  # inlet-based sizing
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.granulator.name, sizing)

    # 3) Compute load and annual energy demand.
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.granulator.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Build reporting row.
    row = make_row(step, flow_in, out_forward)

    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Granulated alloy (kg/h)"] = float(out_forward.mass_kg_per_h)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX (currently energy-only; no extra water/materials modeled here).
    row = attach_opex_to_row(
        row,
        machine=Eq.granulator,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # 6) CAPEX fields for standardized economics reporting.
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras