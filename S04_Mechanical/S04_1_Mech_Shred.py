"""Mechanical shredding process step.

This module models the first mechanical size-reduction stage ("Shredding")
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


def run_mech_shred(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run the mechanical shredding step.

    Parameters
    ----------
    ctx : dict
        Global scenario context (runtime and economic assumptions).
    flow_in : MassFlow
        Incoming stream to shredding (modules/cells after front-end steps).
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
          Supplementary data such as CAPEX breakdown.

    Notes
    -----
    - Output streams are created via ``rfx.apply_step_cfg("Shredding", ...)``.
    - The fallback forward stream is ``"shredded"``.
    """
    p = params or {}
    step = "Shredding"
    mode = str(ctx.get("chemistry", "") or "")

    # Add inert nitrogen based on feed mass and include it in the step inlet.
    n2_ratio_kg_per_kg = float(p.get("n2_kg_per_kg_feed", 0.026))
    n2_density_kg_per_m3 = float(p.get("n2_density_kg_per_m3", 1.25))
    m_n2_h = float(flow_in.mass_kg_per_h) * n2_ratio_kg_per_kg
    v_n2_h = m_n2_h / n2_density_kg_per_m3 if n2_density_kg_per_m3 > 0 else 0.0

    comp_abs = dict((flow_in.meta or {}).get("comp_abs", {}) or {})
    comp_abs["process:N2"] = comp_abs.get("process:N2", 0.0) + m_n2_h
    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_n2_h,
        meta={"comp_abs": comp_abs},
    )

    # Apply configured partition/yield logic and validate overall mass balance.
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="shredded material")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="shredded material")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    forward_flow: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    m_shredded = rfx.mf_get(outputs, "shredded material").mass_kg_per_h
    m_offgas = rfx.mf_get(outputs, "n2_to_scrubber").mass_kg_per_h
    m_loss = rfx.mf_get(outputs, loss_key).mass_kg_per_h

    # Equipment sizing is based on the forwarded (shredded) stream.
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.crusher,
        forward_flow,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.crusher.name, sizing)

    # Compute actual utilization and annual energy demand.
    required_tph = float(forward_flow.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(forward_flow, ctx)
    annual_energy_kwh = Eq.crusher.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # Reporting label to preserve route-dependent semantics.
    fk_label = "Modules shredded" if mode == "PACK_MIX" else "Cells shredded"

    # Reporting inlet = feed without added N2; N2 appears as off-gas output.
    row = make_row(step, flow_in, forward_flow)

    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    # Process columns for downstream massflow reporting.
    row["Shredded material (kg/h)"] = float(m_shredded)
    row["Off gas (kg/h)"] = float(m_offgas)
    row["Nitrogen for shredding (kg/h)"] = float(m_n2_h)
    row["Nitrogen for shredding (m3/h)"] = float(v_n2_h)
    row["Forward keys"] = fk_label

    h_y = hours_per_year(ctx)
    m_n2_y = m_n2_h * h_y
    n2_price = float((ctx.get("prices") or {}).get("Nitrogen", 0.0) or 0.0)
    n2_cost_y = m_n2_y * n2_price
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    row = attach_opex_to_row(
        row,
        machine=Eq.crusher,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=n2_cost_y,
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

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras