"""Mechanical drying process step.

This module models the drying stage in the mechanical route. 
"""

from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance

from thermal_energy import mechanical_drying_thermal_kwh_h
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)


def run_mech_drying(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run the mechanical drying step.

    Parameters
    ----------
    ctx : dict
        Global scenario context (runtime and economic assumptions).
    flow_in : MassFlow
        Incoming wet stream to drying.
    params : dict | None, optional
        Optional step overrides. Supported keys include:
        - ``design_load`` (default: 0.85)
        - ``max_lines`` (default: 600)

    Returns
    -------
    tuple
        (outputs, row, extras)
        - outputs: dict[str, MassFlow]
          Partitioned output streams after drying.
        - row: pandas.DataFrame
          Single-row reporting summary.
        - extras: dict
          Supplementary data such as CAPEX breakdown.

    Notes
    -----
    - The fallback forward stream is ``"dried"``.
    - The dryer is sized on wet inlet throughput (``flow_in``).
    """
    p = params or {}
    step = "Drying"

    # Apply configured partition/yield logic and validate overall mass balance.
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="dried material")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="dried material")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    forward_flow: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    m_dried = rfx.mf_get(outputs, "dried material").mass_kg_per_h
    m_electrolyte_out = rfx.mf_get(outputs, "electrolyte").mass_kg_per_h
    m_loss = rfx.mf_get(outputs, loss_key).mass_kg_per_h

    # Dryer sizing is based on wet inlet throughput, not only dried solids.
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.dryer,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.dryer.name, sizing)

    # Compute actual utilization and annual energy demand.
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    thermal = mechanical_drying_thermal_kwh_h(
        float(m_dried),
        float(m_electrolyte_out),
        params=p,
    )
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])

    # Assemble reporting row.
    row = make_row(step, flow_in, forward_flow)

    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    # Process columns for downstream massflow reporting.
    row["Dried material (kg/h)"] = float(m_dried)
    row["Electrolyte (kg/h)"] = float(m_electrolyte_out)
    row["Electrolyte separated (kg/h)"] = float(m_electrolyte_out)
    row["Out forward kg/h"] = float(m_dried)
    row["Out sorted kg/h"] = float(m_electrolyte_out + m_loss)
    row["Forward keys"] = "Dried material, Electrolyte"
    row["Drying process temperature (°C)"] = float(thermal["t_process_c"])

    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat solid sensible (kJ/h)"] = float(thermal["q_solid_sensible_kj_h"])
    row["Thermal heat electrolyte evap (kJ/h)"] = float(thermal["q_electrolyte_evap_kj_h"])
    row["Thermal heat total (kJ/h)"] = float(thermal["q_total_kj_h"])
    row["Drying heating delta T (K)"] = float(thermal["delta_t_k"])
    row["Electrolyte dh_vap (kJ/kg)"] = float(thermal["dh_vap_electrolyte_kj_per_kg"])
    row["Drying efficiency"] = float(thermal["dryer_efficiency"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    row = attach_opex_to_row(
        row,
        machine=Eq.dryer,
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

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras