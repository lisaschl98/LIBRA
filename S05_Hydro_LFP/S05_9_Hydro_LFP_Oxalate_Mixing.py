from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import OXALATE_MIXING_RULES, oxalate_mixing_reagents_kg_h
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



def run_hydro_lfp_oxalate_mixing(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_9: Hydro LFP - Oxalate Mixing.

    Doses oxalic acid solution and ethanol into the LFP leach liquor after Cu
    removal, in preparation for Fe oxalate precipitation.

    The amount of oxalate is chosen such that the molar ratio
    Fe²⁺ : Oxalate²⁻ = 1 : fe_to_oxalate_ratio
    where Fe is the sum of `Cathode:Fe` and `process:Fe_cement`.

    Streams:
    - Input:  'lye copper clean'
    - Output (forward): 'lye oxalate mixing'

    Reagent components (in `comp_abs`):
    - process:Oxalic_Acid_pure
    - process:H2O_oxalic_solution
    - process:Ethanol_oxalic_mixing
    """
    p = params or {}
    step = "Hydro LFP – Oxalate Mixing"

    h_y = hours_per_year(ctx)
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    rule = OXALATE_MIXING_RULES["LFP"]

    

    m_fe_h, m_oxalic_pure_h, m_water_h, m_ethanol_h = oxalate_mixing_reagents_kg_h(
        comp_abs=comp_abs,
        fe_suffixes=rule["fe_suffixes"],
        fe_to_c2o4_molar_ratio=float(p.get("fe_to_oxalate_ratio", rule["fe_to_c2o4_molar_ratio"])),
        oxalic_solution_wtfrac=float(p.get("oxalic_solution_mass_fraction", rule["oxalic_solution_wtfrac"])),
        ethanol_frac_of_oxalic_solution=float(p.get("ethanol_fraction_of_oxalic_solution", rule["ethanol_frac_of_oxalic_solution"])),
    )
    # 2) Add reagents to composition
    if m_oxalic_pure_h > 0.0:
        comp_abs["process:Oxalic_Acid_pure"] = (
            comp_abs.get("process:Oxalic_Acid_pure", 0.0) + m_oxalic_pure_h
        )
    if m_water_h > 0.0:
        comp_abs["process:H2O_oxalic_solution"] = (
            comp_abs.get("process:H2O_oxalic_solution", 0.0) + m_water_h
        )
    if m_ethanol_h > 0.0:
        comp_abs["process:Ethanol_oxalic_mixing"] = (
            comp_abs.get("process:Ethanol_oxalic_mixing", 0.0) + m_ethanol_h
        )

    added_mass_h = m_oxalic_pure_h + m_water_h + m_ethanol_h

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + added_mass_h,
        meta={"comp_abs": comp_abs},
    )

    # 3) Mass balance / partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye oxalate mixing")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye oxalate mixing")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 4) Sizing / CAPEX – reactor based on augmented inlet throughput
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

    # 5) Load and energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 6) Reporting row
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye oxalate mixing (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Fe total for oxalate (kg/h)"] = float(m_fe_h)
    row["Oxalic acid pure added (kg/h)"] = float(m_oxalic_pure_h)
    row["Water for oxalic solution (kg/h)"] = float(m_water_h)
    row["Oxalic acid solution added (kg/h)"] = float(m_oxalic_pure_h + m_water_h)
    row["Ethanol added (kg/h)"] = float(m_ethanol_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 7) OPEX – oxalic acid, water and ethanol costs
    pr = prices(ctx)
    ox_price = float(pr.get("Oxalic acid", 0.0))   # currency/kg pure oxalic acid
    h2o_price = float(pr.get("Water", 0.0))        # currency/kg water (if priced)
    etoh_price = float(pr.get("Ethanol", 0.0))     # currency/kg ethanol

    materials_cost_y = (
        m_oxalic_pure_h * h_y * ox_price
        + m_water_h * h_y * h2o_price
        + m_ethanol_h * h_y * etoh_price
    )

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

    # 8) CAPEX columns for standardized economics reporting and extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras