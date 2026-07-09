from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
import stoichiometry as st
from Massflow import MassFlow, assert_mass_balance
from step_utils import (
    hours_per_year,
    annual_input_tons_from_flow,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)


def run_hydro_pyro_alloy_co_scrubbing(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_9: Hydro-Pyro - Co Scrubbing.

    Purpose:
    - Wash/polish the Co-loaded organic phase before stripping.
    - Pass the scrubbed organic phase forward without additional reagents.

    Forward stream:
    - 'Co scrubbed phase'

    Reporting uses the same **organic inventory** mass as extraction (metal in organic
    plus circulating extractant and kerosene from ``meta['solvent_extraction']``) for
    ``In kg/h``, ``Out forward kg/h``, and ``Co scrubbed phase (kg/h)`` (Excel/Massenfluss).
    """
    p = params or {}
    step = "Hydro-Pyro - Co Scrubbing"

    # 1) Partition / yield from EFF
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="Co scrubbed phase")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="Co scrubbed phase")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Equipment sizing and CAPEX
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.solvent_extraction,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.solvent_extraction.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.solvent_extraction.energy_for_sized(
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

    solm = dict((getattr(flow_in, "meta", {}) or {}).get("solvent_extraction") or {})
    m_booked_organic = float(st.solvent_extract_organic_inventory_kg_h(flow_in, "Co"))
    row["Co scrubbed phase (kg/h)"] = m_booked_organic
    row["Out forward kg/h"] = m_booked_organic
    row["Cyanex 272 circulating (kg/h)"] = float(solm.get("organic_circulating_kg_h", 0.0))
    row["Kerosene circulating (kg/h)"] = float(solm.get("kerosene_circulating_kg_h", 0.0))
    row["In kg/h"] = m_booked_organic

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX (energy only)
    row = attach_opex_to_row(
        row,
        machine=Eq.solvent_extraction,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # 6) CAPEX columns for standardized economics reporting + extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras