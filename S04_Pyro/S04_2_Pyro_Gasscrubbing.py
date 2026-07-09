"""Pyro gas scrubbing process step.

This module models pyro gas scrubbing with a scrubber. 
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


def run_pyro_gas_scrubbing(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """
    Run pyro gas scrubbing.

    Purpose
    -------
    Treat offgas from pyro smelting and produce a cleaned gas stream for
    downstream handling/reporting. Chemical detail is intentionally simplified;
    the model focus is mass routing and CAPEX/OPEX.

    Inputs
    ------
    flow_in : offgas stream from pyro smelting

    Outputs
    -------
    outputs : configured streams from EFF (typically clean gas + optional side/loss)
    row     : standardized reporting row
    extras  : CAPEX breakdown for downstream export
    """
    p = params or {}
    step = "Pyro Gas scrubbing"

    # 1) Apply EFF partition/yield and validate mass balance.
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="clean gas")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="clean gas")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Size scrubber on inlet load and compute CAPEX.
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.gas_scrubbing,
        flow_in,  # inlet-based sizing
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.gas_scrubbing.name, sizing)

    # 3) Compute load and annual energy.
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.gas_scrubbing.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Build reporting row.
    row = make_row(step, flow_in, out_forward)

    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Out forward kg/h"] = float(out_forward.mass_kg_per_h)
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Clean gas (kg/h)"] = float(out_forward.mass_kg_per_h)
    # Optional future stream:
    # row["Captured dust (kg/h)"] = float(rfx.mf_get(outputs, "captured_dust").mass_kg_per_h)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX (currently no extra water/materials for this unit).
    row = attach_opex_to_row(
        row,
        machine=Eq.gas_scrubbing,
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