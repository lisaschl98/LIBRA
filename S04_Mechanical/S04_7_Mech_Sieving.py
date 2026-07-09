"""Mechanical sieving process step.

This module models sieving in the mechanical route. 
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


def run_mech_sieving(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run the mechanical sieving step.

    Parameters
    ----------
    ctx : dict
        Global scenario context (runtime and economic assumptions).
    flow_in : MassFlow
        Inlet stream to sieving.
    params : dict | None, optional
        Optional step-level overrides (e.g., ``design_load``, ``max_lines``).

    Returns
    -------
    tuple
        (outputs, row, extras)
        - outputs: dict[str, MassFlow]
          Partitioned output streams.
        - row: pandas.DataFrame
          Single-row process summary for reporting/export.
        - extras: dict
          Supplemental data including CAPEX breakdown.
    """
    p = params or {}
    step = "Sieving"

    # 1) Apply configured partition/yield logic and validate mass balance.
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="coarse fraction")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="coarse fraction")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    m_coarse = rfx.mf_get(outputs, forward_key).mass_kg_per_h
    m_bm = rfx.mf_get(outputs, "black mass").mass_kg_per_h
    m_loss = rfx.mf_get(outputs, loss_key).mass_kg_per_h if loss_key else 0.0

    # 2) Sizing/CAPEX based on inlet throughput.
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.vibrating_screen,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.vibrating_screen.name, sizing)

    # 3) Load and energy demand.
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.vibrating_screen.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Reporting row.
    row = make_row(step, flow_in, out_forward)

    row["Out forward kg/h"] = float(m_coarse)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Coarse fraction (kg/h)"] = float(m_coarse)
    row["Black mass separated (kg/h)"] = float(m_bm)

    # Aggregate sorted-out side streams (including loss).
    row["Out sorted kg/h"] = float(m_bm + m_loss)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    row = attach_opex_to_row(
        row,
        machine=Eq.vibrating_screen,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
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

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras