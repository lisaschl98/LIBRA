# S05_6_Hydro_Pyro_Slag_Fe_Al_Filtration.py
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


def run_hydro_pyro_slag_fe_al_filtration(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_6: Filtration after Fe/Al precipitation (slag route).

    Separates Fe/Al hydroxide solids from the lye. Stream routing is controlled via
    EFF (Recycling_Efficiencies).

    Streams:
    - In (forward from step 5):  lye iron,aluminium precipitation
    - Out (forward):             lye iron,aluminium clean
    - Solids:                    Iron hydroxide, Aluminium hydroxide (combined for reporting)
    """
    p = params or {}
    step = "Hydro Pyro – Fe+Al Filtration"

    # 1) Mass balance / partition (EFF + fallbacks)
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="lye iron,aluminium clean")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye iron,aluminium clean")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    fe_oh3_h = float(rfx.mf_get(outputs, "Iron hydroxide").mass_kg_per_h)
    al_oh3_h = float(rfx.mf_get(outputs, "Aluminium hydroxide").mass_kg_per_h)
    sludge_h = fe_oh3_h + al_oh3_h

    # 2) Sizing / CAPEX — belt filter sized on inlet throughput
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.filterpress,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.filterpress.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.filterpress.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Reporting row
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye after Fe+Al filtration (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Iron hydroxide (kg/h)"] = fe_oh3_h
    row["Aluminium hydroxide (kg/h)"] = al_oh3_h
    row["Fe+Al hydroxides separated (kg/h)"] = sludge_h

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX — energy only here
    row = attach_opex_to_row(
        row,
        machine=Eq.filterpress,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # 6) CAPEX columns and extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["outputs_kg_h"] = [{
        "Iron hydroxide": float(fe_oh3_h),
        "Aluminium hydroxide": float(al_oh3_h),
    }]
    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras