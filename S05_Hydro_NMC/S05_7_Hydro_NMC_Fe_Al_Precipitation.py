# S05_7_Hydro_NMC_Fe_Al_Precipitation.py
from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    fe_al_precipitation_stoich_kg_h,
    naoh_solution_from_pure_kg_h,
    PRECIPITATION_FE_AL_RULES,
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

def run_hydro_nmc_fe_al_precipitation(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_7: Hydro NMC - Fe+Al Precipitation.

    Precipitates dissolved Fe and Al as hydroxides using NaOH solution.
    Stoichiometric NaOH pure demand is calculated first and then converted
    to NaOH solution mass flow (default: 50 wt-%).

    Streams:
    - Input:  'lye oxidation'
    - Output (forward): 'lye iron, aluminium precipitation'
    """
    p = params or {}
    step = "Hydro NMC – Fe+Al Precipitation"
    h_y = hours_per_year(ctx)

    rule = PRECIPITATION_FE_AL_RULES["nmc"]
    fe_suffixes = tuple(str(s) for s in rule["fe_suffixes"])
    al_suffixes = tuple(str(s) for s in rule["al_suffixes"])

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    def _mass_by_suffixes(d: dict, suffixes: tuple[str, ...]) -> float:
        total = 0.0
        for k, v in d.items():
            ks = str(k)
            if any(ks.endswith(s) or ks == s.strip(":") for s in suffixes):
                total += float(v or 0.0)
        return total

    def _zero_by_suffixes(d: dict, suffixes: tuple[str, ...]) -> None:
        for k in list(d.keys()):
            ks = str(k)
            if any(ks.endswith(s) or ks == s.strip(":") for s in suffixes):
                d[k] = 0.0

    # 0) Determine Fe and Al in inlet stream [kg/h] from configured source rules
    m_fe_in = _mass_by_suffixes(comp_abs, fe_suffixes)
    m_al_in = _mass_by_suffixes(comp_abs, al_suffixes)

    # 1) Stoichiometric precipitation + NaOH pure demand
    res = fe_al_precipitation_stoich_kg_h(
        m_fe_in_kg_h=m_fe_in,
        m_al_in_kg_h=m_al_in,
        stoich_factor=float(p.get("naoh_stoich_factor", 1.0)),
    )
    m_naoh_pure_h = float(res["naoh_pure_kg_h"])
    m_feoh3_h = float(res["feoh3_kg_h"])
    m_aloh3_h = float(res["aloh3_kg_h"])

    # 2) Convert NaOH pure to NaOH solution (default from rule: 50 wt-%)
    wtfrac_default = float(rule.get("naoh_solution_wtfrac_default", 0.5))
    naoh_solution_wtfrac = float(p.get("naoh_solution_wtfrac", wtfrac_default))
    if naoh_solution_wtfrac <= 0.0:
        naoh_solution_wtfrac = wtfrac_default

    m_naoh_h = naoh_solution_from_pure_kg_h(
        m_naoh_pure_kg_h=m_naoh_pure_h,
        solution_wtfrac=naoh_solution_wtfrac,
    )

    # Fallback manual input if needed
    if m_naoh_h <= 0.0:
        m_naoh_h = float(p.get("NaOH_50_kg_h", p.get("NaOH_kg_h", 0.0)) or 0.0)

    m_naoh_y = m_naoh_h * h_y

    # 3) Replace dissolved Fe/Al by hydroxides in comp_abs
    if m_fe_in > 0.0:
        _zero_by_suffixes(comp_abs, fe_suffixes)
        comp_abs["process:Fe(OH)3"] = comp_abs.get("process:Fe(OH)3", 0.0) + m_feoh3_h

    if m_al_in > 0.0:
        _zero_by_suffixes(comp_abs, al_suffixes)
        comp_abs["process:Al(OH)3"] = comp_abs.get("process:Al(OH)3", 0.0) + m_aloh3_h

    # Add NaOH solution as reagent component
    if m_naoh_h > 0.0:
        comp_abs["process:NaOH_50"] = comp_abs.get("process:NaOH_50", 0.0) + m_naoh_h

    # 4) Build augmented flow (strict mass basis for reporting/balance: In + NaOH solution)
    # Keep tracked species unchanged; close only via bulk/untracked bucket.
    m_aug_h = float(flow_in.mass_kg_per_h) + m_naoh_h
    m_comp = float(sum(float(v or 0.0) for v in comp_abs.values()))
    comp_abs["__untracked__"] = float(comp_abs.get("__untracked__", 0.0) or 0.0) + (m_aug_h - m_comp)
    flow_aug = MassFlow(m_aug_h, meta={"comp_abs": comp_abs})

    # 5) Partition / yield
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye iron, aluminium precipitation")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye iron, aluminium precipitation")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 6) Sizing / CAPEX
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

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 7) Reporting
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye iron, aluminium precipitation (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["NaOH added (kg/h)"] = float(m_naoh_h)
    row["Fe(OH)3 formed (kg/h)"] = float(m_feoh3_h)
    row["Al(OH)3 formed (kg/h)"] = float(m_aloh3_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 8) OPEX
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

    # 9) CAPEX columns for standardized economics reporting + extras
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