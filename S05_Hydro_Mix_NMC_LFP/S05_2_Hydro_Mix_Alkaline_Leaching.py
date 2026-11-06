# S05_2_Hydro_Mix_Al_Removal.py
from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    fe_al_precipitation_stoich_kg_h,
    naoh_solution_from_pure_kg_h,
)
from Massflow import MassFlow, assert_mass_balance
from step_utils import (
    hours_per_year,
    annual_input_tons_from_flow,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
    prices,
)


def run_hydro_mix_alkaline_leaching(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_2: Hydro Mix - Alkaline Leaching.

    Removes dissolved aluminium from the mixed black-mass suspension by
    alkaline treatment with NaOH, precipitating aluminium as Al(OH)3.

    Stoichiometric NaOH pure demand is calculated first and then converted
    to NaOH solution mass flow (default: 50 wt-%).

    Streams:
    - Input:  'BM suspension'
    - Output (forward): 'lye alkaline leaching'
    """
    p = params or {}
    step = "Hydro Mix – Alkaline Leaching"
    h_y = hours_per_year(ctx)

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    # 0) Determine aluminium load
    m_al_in = 0.0
    for k, v in comp_abs.items():
        ks = str(k)
        if ks.endswith(":Aluminium") or ks.endswith(":Al"):
            m_al_in += float(v or 0.0)

    # 1) Stoichiometric precipitation + NaOH pure demand (Fe = 0 in this step)
    res = fe_al_precipitation_stoich_kg_h(
        m_fe_in_kg_h=0.0,
        m_al_in_kg_h=m_al_in,
        stoich_factor=float(p.get("naoh_stoich_factor", 1.1)),
    )
    m_naoh_pure_h = float(res["naoh_pure_kg_h"])
    m_aloh3_h = float(res["aloh3_kg_h"])

    # 2) Convert NaOH pure to NaOH solution (default 50 wt-%)
    naoh_solution_wtfrac = float(p.get("naoh_solution_wtfrac", 0.5))
    if naoh_solution_wtfrac <= 0.0:
        naoh_solution_wtfrac = 0.5

    m_naoh_h = naoh_solution_from_pure_kg_h(
        m_naoh_pure_kg_h=m_naoh_pure_h,
        solution_wtfrac=naoh_solution_wtfrac,
    )

    # Fallback manual input if needed
    if m_naoh_h <= 0.0:
        m_naoh_h = float(p.get("NaOH_50_kg_h", p.get("NaOH_kg_h", 0.0)) or 0.0)

    m_naoh_y = m_naoh_h * h_y

    # 3) Update composition (closed suspension mass: m_out = m_in + m_NaOH dose).
    #    OH in Al(OH)3 comes from the NaOH pool — book as transfer, not extra inlet mass.
    m_oh_in_hydroxide = max(0.0, m_aloh3_h - m_al_in) if m_al_in > 0.0 else 0.0
    m_naoh_in_lye = max(0.0, m_naoh_h - m_oh_in_hydroxide)

    if m_al_in > 0.0:
        for k in list(comp_abs.keys()):
            ks = str(k)
            if ks.endswith(":Aluminium") or ks.endswith(":Al"):
                comp_abs[k] = 0.0
        comp_abs["process:Al(OH)3"] = comp_abs.get("process:Al(OH)3", 0.0) + m_aloh3_h

    if m_naoh_in_lye > 0.0:
        comp_abs["process:NaOH_50"] = comp_abs.get("process:NaOH_50", 0.0) + m_naoh_in_lye

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_naoh_h,
        meta={"comp_abs": comp_abs},
    )

    # 4) Mass balance / partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye alkaline leaching")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye alkaline leaching")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 5) Sizing / CAPEX
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

    # 6) Load and energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 7) Reporting row
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye alkaline leaching (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Al(OH)3 produced (kg/h)"] = float(m_aloh3_h)
    row["NaOH added (kg/h)"] = float(m_naoh_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 8) OPEX - NaOH cost on 50 wt-% basis
    pr = prices(ctx)
    naoh_price = float(pr.get("Sodium hydroxide (50%)", 0.0))
    materials_cost_y = m_naoh_y * naoh_price

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

    # 9) CAPEX columns for standardized economics reporting and extras
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