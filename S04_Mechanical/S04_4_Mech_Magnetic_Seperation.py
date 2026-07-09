"""Mechanical magnetic separation process step.

This module models magnetic separation in the mechanical route. 
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


def run_magnetic_separation(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run the magnetic separation step.

    Parameters
    ----------
    ctx : dict
        Global scenario context (runtime and economic assumptions).
    flow_in : MassFlow
        Incoming material stream to magnetic separation.
    params : dict | None, optional
        Optional step overrides. Supported keys include:
        - ``design_load`` (default: 0.85)
        - ``max_lines`` (default: 600)

    Returns
    -------
    tuple
        (outputs, row, extras)
        - outputs: dict[str, MassFlow]
          Partitioned output streams.
        - row: pandas.DataFrame
          Single-row reporting summary.
        - extras: dict
          Supplemental data including CAPEX breakdown.
    """
    p = params or {}
    step = "Magnetic Separation"

    # 1) Apply configured partition/yield logic and validate mass balance.
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="non magnetic material")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="non magnetic material")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Extract key streams.
    m_nonmag = rfx.mf_get(outputs, "non magnetic material").mass_kg_per_h
    m_steel = rfx.mf_get(outputs, "steel").mass_kg_per_h

    steel_flow = rfx.mf_get(outputs, "steel")
    steel_comp = (steel_flow.meta or {}).get("comp_abs", {}) or {}
    m_steel_from_cell = float(steel_comp.get("cell:Packing Container:Nickel-plated steel", 0.0) or 0.0)
    m_steel_from_module = float(steel_comp.get("module:Steel", 0.0) or 0.0)

    m_loss = rfx.mf_get(outputs, loss_key).mass_kg_per_h if loss_key else 0.0

    # 3) Sizing/CAPEX based on inlet throughput.
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.magnetic_separation,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.magnetic_separation.name, sizing)

    # 4) Load and energy demand.
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.magnetic_separation.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 5) Reporting row.
    row = make_row(step, flow_in, out_forward)

    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Non-magnetic fraction (kg/h)"] = float(m_nonmag)
    row["Steel separated (kg/h)"] = float(m_steel)
    row["Steel separated – cell packaging (kg/h)"] = float(m_steel_from_cell)
    row["Steel separated – module steel (kg/h)"] = float(m_steel_from_module)

    row["Out forward kg/h"] = float(m_nonmag)
    row["Out sorted kg/h"] = float(m_steel + m_loss)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    row = attach_opex_to_row(
        row,
        machine=Eq.magnetic_separation,
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
    row["outputs_kg_h"] = [{
    "Steel scrap": float(m_steel),
    }]
    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras