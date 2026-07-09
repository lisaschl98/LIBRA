# S05_3_Hydro_Pyro_Slag_SiO2_CaSO4_Filtration.py
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


def _sand_and_caso4_from_residue_kg_h(residue_flow: MassFlow, residue_mass_kg_h: float) -> tuple[float, float]:
    """Split combined SiO2/CaSO4 residue into sand-like vs CaSO4 mass for reporting (kg/h)."""
    comp_abs = dict((getattr(residue_flow, "meta", {}) or {}).get("comp_abs") or {})
    m_caso4 = 0.0
    m_sand = 0.0
    for k, v in comp_abs.items():
        vv = float(v or 0.0)
        if vv <= 0.0:
            continue
        ks = str(k).lower()
        if "caso4" in ks:
            m_caso4 += vv
        elif "sand" in ks or "sio2" in ks:
            m_sand += vv
    rem = max(0.0, float(residue_mass_kg_h) - m_caso4 - m_sand)
    if rem > 1e-12:
        m_sand += rem
    return m_sand, m_caso4


def run_hydro_pyro_slag_sio2_caso4_filtration(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_3: Hydro Pyro - Slag SiO2/CaSO4 Filtration.

    Purpose:
    - Separate insoluble solids (e.g. SiO2, CaSO4 from limestone/sand digestion)
      from leached slag liquor.

    Forward stream:
    - 'lye slagformer clean'

    Side stream:
    - 'SiO2/CaSO4 residue'

    Component routing is configured in EFF (partition rules), for example:
    - pyro:Limestone -> SiO2/CaSO4 residue
    - pyro:Sand -> SiO2/CaSO4 residue
    with default_stream = lye slagformer clean.
    """
    p = params or {}
    step = "Hydro Pyro – Slag SiO2/CaSO4 Filtration"

    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="lye slagformer clean")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye slagformer clean")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    sio2_flow = rfx.mf_get(outputs, "SiO2")
    caso4_flow = rfx.mf_get(outputs, "CaSO4")
    sio2_h = float(sio2_flow.mass_kg_per_h)
    caso4_h = float(caso4_flow.mass_kg_per_h)
    residue_flow = rfx.mf_get(outputs, "SiO2/CaSO4 residue")
    residue_h = float(residue_flow.mass_kg_per_h)

    # EFF often routes all solids into "SiO2/CaSO4 residue" only; split for Excel as Sand + CaSO4.
    if residue_h > 1e-12 and sio2_h < 1e-12 and caso4_h < 1e-12:
        sio2_h, caso4_h = _sand_and_caso4_from_residue_kg_h(residue_flow, residue_h)

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

    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.filterpress.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Slag clean lye (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["SiO2 (kg/h)"] = sio2_h
    row["CaSO4 (kg/h)"] = caso4_h

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

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

    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["outputs_kg_h"] = [{"Sand": float(sio2_h), "Calcium sulfate": float(caso4_h)}]
    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras