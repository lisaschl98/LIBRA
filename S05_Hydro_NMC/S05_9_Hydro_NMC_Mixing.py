from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import nmc_mixing_naoh_demand_kg_h, _sum_by_suffixes
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


def run_hydro_nmc_mixing_nmc(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_9: Hydro NMC – NMC Mixing.

    Plans and doses NaOH for the target NixCoyMnz(OH)2 stoichiometry (2 mol NaOH / mol
    precursor at the selected target rate). No precursor solid is formed here — metals
    stay in the lye. Actual precipitation, sulfate makeup, NH3, and sulfate-neutralization
    NaOH are in step 10 (NMC Precipitation).

    Target modes (``target_basis`` + ``max_makeup_fill_fraction``):
      - min: limiting dissolved Ni/Co/Mn in lye.
      - ni / co / mn: anchor metal cap.
      - with deficit fill: in-situ cap + fill × (nominal − in-situ).

    Streams:
    - Input:  'lye iron, aluminium clean'
    - Output (forward): 'lye precursor mixing'
    """
    p = params or {}
    step = "Hydro NMC – NMC Mixing"

    h_y = hours_per_year(ctx)
    nmc_code = str(p.get("nmc_code") or ctx.get("nmc_code") or "811")
    fill_frac = float(p.get("max_makeup_fill_fraction", 0.0) or 0.0)

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    plan = nmc_mixing_naoh_demand_kg_h(
        comp_abs=comp_abs,
        nmc_code=nmc_code,
        target_basis=str(p.get("target_basis", "min")),
        max_makeup_fill_fraction=fill_frac,
        naoh_solution_wtfrac=float(p.get("naoh_solution_wtfrac", 0.5)),
    )

    m_naoh_50_h = float(plan["m_naoh_solution_kg_h"])
    n_target_nominal_h = float(plan["n_nominal_mol_h"])
    n_naoh_basis_h = float(plan["n_naoh_basis_mol_h"])
    n_physical_h = float(plan["n_physical_mol_h"])

    if m_naoh_50_h > 0.0:
        comp_abs["process:NaOH_50"] = float(comp_abs.get("process:NaOH_50", 0.0) or 0.0) + m_naoh_50_h

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_naoh_50_h,
        meta={
            "comp_abs": comp_abs,
            "nmc_precursor_effective_mol_h": 0.0,
            "nmc_precursor_target_nominal_mol_h": n_target_nominal_h,
            "nmc_precursor_naoh_basis_mol_h": n_naoh_basis_h,
            "nmc_precursor_physical_cap_mol_h": n_physical_h,
            "nmc_nh3_solution_step9_kg_h": 0.0,
        },
    )
    m_naoh_50_y = m_naoh_50_h * h_y

    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye precursor mixing")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye precursor mixing")
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

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
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

    row["NixCoyMnz(OH)2 formed (kg/h)"] = 0.0
    row["NaOH 50% (kg/h)"] = float(m_naoh_50_h)
    row["NH3 solution (kg/h)"] = 0.0
    row["Precursor rate nominal (mol/h)"] = float(n_target_nominal_h)
    row["Precursor rate NaOH basis (mol/h)"] = float(n_naoh_basis_h)
    row["NMC code"] = nmc_code
    row["Target basis"] = str(p.get("target_basis", "min"))
    row["Sulfate makeup policy"] = str(p.get("makeup_policy_label", "-"))
    row["Deficit fill cap"] = float(fill_frac)
    row["Precursor rate in-situ max (mol/h)"] = float(n_physical_h)
    row["Precursor rate effective (mol/h)"] = 0.0

    row["Ni in lye after step (kg/h)"] = _sum_by_suffixes(comp_abs, (":Ni", "Ni"))
    row["Co in lye after step (kg/h)"] = _sum_by_suffixes(comp_abs, (":Co", "Co"))
    row["Mn in lye after step (kg/h)"] = _sum_by_suffixes(comp_abs, (":Mn", "Mn"))

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    pr = prices(ctx)
    naoh_price = float(pr.get("Sodium hydroxide (50%)", 0.0))
    materials_cost_y = m_naoh_50_y * naoh_price

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
    row["CAPEX install ($)"] = float(sizing.get("capex_install_model", 0.0))
    row["CAPEX instr ($)"] = float(sizing.get("capex_instr", 0.0))
    row["CAPEX piping ($)"] = float(sizing.get("capex_piping", 0.0))
    row["CAPEX electrical ($)"] = float(sizing.get("capex_electrical", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras
