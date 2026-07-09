# S05_1_Hydro_Pyro_Slag_Digestion.py
from __future__ import annotations

import machine as Eq
import stoichiometry as st
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import digestion_heating_kwh_h
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
    prices,
)





def run_hydro_pyro_slag_digestion(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_1: Hydro Pyro - Slag Digestion.

    Digest granulated slag with concentrated sulfuric acid (95 wt-%).
    Reagent mass is added to the stream; partitioning follows EFF configuration.

    Forward stream:
    - 'digested slag solution'
    """
    p = params or {}
    step = "Hydro Pyro – Slag Digestion"

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs_in = dict(meta.get("comp_abs") or {})

    acid_safety_factor = float(p.get("acid_safety_factor", 1.1))
    m_h2so4_95_h = st.h2so4_95_digestion_demand_kg_h(
        comp_abs=comp_abs_in,
        species_rules=st.DIGESTION_RULES["slag"],
        safety_factor=acid_safety_factor,
    )

    comp_abs = dict(comp_abs_in)
    if m_h2so4_95_h > 0:
        comp_abs["process:H2SO4_95"] = comp_abs.get("process:H2SO4_95", 0.0) + m_h2so4_95_h
    # Convert all CaO to CaSO4 for downstream SiO2/CaSO4 filtration routing.
    m_cao_h = 0.0
    for k, v in list(comp_abs.items()):
        ks = str(k)
        if ks.endswith(":CaO") or ks == "CaO":
            m_cao_h += float(v or 0.0)
            comp_abs[k] = 0.0
    if m_cao_h > 0:
        m_caso4_h = m_cao_h * (st.MOLAR_MASS["CaSO4"] / st.MOLAR_MASS["CaO"])
        comp_abs["process:CaSO4"] = comp_abs.get("process:CaSO4", 0.0) + m_caso4_h

        # Keep total stream mass consistent: the extra sulfate mass is taken from the acid pool.
        delta_from_acid_h = max(0.0, m_caso4_h - m_cao_h)
        if delta_from_acid_h > 0:
            acid_pool_h = float(comp_abs.get("process:H2SO4_95", 0.0) or 0.0)
            comp_abs["process:H2SO4_95"] = max(0.0, acid_pool_h - delta_from_acid_h)

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_h2so4_95_h,
        meta={"comp_abs": comp_abs},
    )

    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="digested slag solution")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="digested slag solution")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.reactor,
        flow_aug,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.reactor.name, sizing)

    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    m_lib_h = float(flow_in.mass_kg_per_h)
    thermal = digestion_heating_kwh_h(m_lib_h, m_h2so4_95_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])

    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"
    row["Digested slag solution (kg/h)"] = float(out_forward.mass_kg_per_h)

    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat sensible (kJ/h)"] = float(thermal["q_sensible_kj_h"])
    row["Digestion heating delta T (K)"] = float(thermal["delta_t_k"])
    row["Digestion efficiency"] = float(thermal["eta_heating"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    row["H2SO4 95% added (kg/h)"] = float(m_h2so4_95_h)
    row["LIB feedstock heated (kg/h)"] = float(m_lib_h)
    pr = prices(ctx)
    acid_price = float(pr.get("Sulfuric acid (95%)", 0.0))
    materials_cost_y = m_h2so4_95_h * h_y * acid_price

    row = attach_opex_to_row(
        row,
        machine=Eq.reactor,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=materials_cost_y,
        add_perkg=True,
    )

    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras