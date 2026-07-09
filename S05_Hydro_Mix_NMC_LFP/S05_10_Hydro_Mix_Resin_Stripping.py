from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import ix_stripping_h2so4_demand_kg_h, IX_STRIPPING_RULES
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


def run_hydro_mix_resin_stripping(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_10: Hydro-Mix ion-exchange stripping with H2SO4.

    Ziel:
    - The loaded resin is stripped with H2SO4.
    - H2SO4 demand is calculated centrally in stoichiometry.py
      (MIX: Mn + Ni + Co).

    - Input:  'loaded_resin'
    - Output (Forward): 'NMC solution'
    """
    p = params or {}
    step = "Hydro Mix – Resin Stripping"

    h_y = hours_per_year(ctx)
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    # 0) H2SO4 demand via central stoichiometry
    rule = dict(IX_STRIPPING_RULES["MIX"])

    acid_equiv = float(p.get("acid_equiv", rule.get("acid_equiv_default", 1.0)))
    h2so4_wtfrac = float(p.get("h2so4_wtfrac", rule.get("h2so4_wtfrac_default", 0.95)))
    stripping_sf = float(p.get("stripping_acid_safety_factor", rule.get("safety_factor_default", 1.1)))

    strip = ix_stripping_h2so4_demand_kg_h(
        comp_abs=comp_abs,
        species=rule["species"],
        acid_equiv=acid_equiv,
        h2so4_wtfrac=h2so4_wtfrac,
        safety_factor=stripping_sf,
    )

    m_H2SO4_95_h = float(strip["m_h2so4_solution_kg_h"])
    m_H2SO4_95_y = m_H2SO4_95_h * h_y

    if m_H2SO4_95_h > 0.0:
        comp_abs["process:H2SO4_95"] = float(comp_abs.get("process:H2SO4_95", 0.0) or 0.0) + m_H2SO4_95_h

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_H2SO4_95_h,
        meta={"comp_abs": comp_abs},
    )

    # 1) MASS BALANCE / Partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="NMC solution")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="NMC solution")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) SIZING / CAPEX – stripping as reactor
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

    # 3) LOAD + ENERGY
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
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

    row["Stripped NMC solution (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["H2SO4 95% added for stripping (kg/h)"] = float(m_H2SO4_95_h)
    row["Metals loading basis (mol/h)"] = float(strip["n_metals_mol_h"])
    row["H2SO4 demand pure (kg/h)"] = float(strip["m_h2so4_pure_kg_h"])

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX – H2SO4 + energy
    pr = prices(ctx)
    acid_price = float(pr.get("Sulfuric acid (95%)", 0.0))  # €/kg
    materials_cost_y = m_H2SO4_95_y * acid_price

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

    # 6) CAPEX fallback columns & extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras