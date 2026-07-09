from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    MOLAR_MASS,
    nmc_precip_reagent_demand_kg_h,
    nmc_hydroxide_precipitation_stoich_kg_h,
    nmc_sulfate_makeup_naoh_solution_kg_h,
    reconcile_comp_abs_to_mass,
    tag_stoich_product_in_comp_abs,
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


def _nmc_ppt_reconcile_preserve_keys(comp_abs: dict) -> tuple[str, ...]:
    """Keep liquor inventory and stoich products; scale only bulk solvent / untracked."""
    keys: list[str] = []
    for k in comp_abs:
        ks = str(k)
        if ks.startswith("cell:"):
            keys.append(ks)
        elif ks.startswith("process:") and not ks.startswith("process:H2O"):
            keys.append(ks)
    return tuple(keys)


def _deduct_from_matching_keys(comp_abs: dict, suffixes: tuple[str, ...], amount_kg_h: float) -> None:
    remaining = max(0.0, float(amount_kg_h))
    if remaining <= 0.0:
        return
    for k in list(comp_abs.keys()):
        if remaining <= 0.0:
            break
        ks = str(k)
        if not any(ks.endswith(s) or ks == s.strip(":") for s in suffixes):
            continue
        v = float(comp_abs.get(k, 0.0) or 0.0)
        if v <= 0.0:
            continue
        take = min(v, remaining)
        comp_abs[k] = v - take
        remaining -= take


def run_hydro_mix_precipitation_nmc(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_12: Hydro Mix – NMC Precipitation (analog Hydro NMC – NMC Precipitation).
    """
    p = params or {}
    step = "Hydro Mix – NMC Precipitation"

    h_y = hours_per_year(ctx)
    nmc_code = str(p.get("nmc_code") or ctx.get("nmc_code") or "811")

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})
    fill_frac = float(p.get("max_makeup_fill_fraction", 1.0))
    nom_mol_h = float(meta.get("nmc_precursor_target_nominal_mol_h", 0.0) or 0.0)
    step9_eff_mol_h = float(meta.get("nmc_precursor_effective_mol_h", 0.0) or 0.0)

    reag = nmc_precip_reagent_demand_kg_h(
        comp_abs=comp_abs,
        nmc_code=nmc_code,
        nh3_coordination_number=float(p.get("nh3_coordination_number", 6.0)),
        nh3_loss_fraction=float(p.get("nh3_loss_fraction", 0.10)),
        nh3_solution_wtfrac=float(p.get("nh3_solution_wtfrac", 0.25)),
        target_basis=str(p.get("target_basis", "min")),
        max_makeup_fill_fraction=fill_frac,
        nominal_target_mol_h=nom_mol_h if nom_mol_h > 0.0 else None,
        cap_precursor_mol_h=step9_eff_mol_h if step9_eff_mol_h > 0.0 else None,
    )

    m_niso4_makeup_h = float(reag["m_niso4_makeup_kg_h"])
    m_coso4_makeup_h = float(reag["m_coso4_makeup_kg_h"])
    m_mnso4_makeup_h = float(reag["m_mnso4_makeup_kg_h"])
    m_nh3_total_h = float(reag["m_nh3_solution_makeup_kg_h"])
    n_precip_target_h = float(reag["n_target_final_mol_h"])

    if m_niso4_makeup_h > 0.0:
        comp_abs["process:NiSO4_makeup"] = float(comp_abs.get("process:NiSO4_makeup", 0.0) or 0.0) + m_niso4_makeup_h
    if m_coso4_makeup_h > 0.0:
        comp_abs["process:CoSO4_makeup"] = float(comp_abs.get("process:CoSO4_makeup", 0.0) or 0.0) + m_coso4_makeup_h
    if m_mnso4_makeup_h > 0.0:
        comp_abs["process:MnSO4_makeup"] = float(comp_abs.get("process:MnSO4_makeup", 0.0) or 0.0) + m_mnso4_makeup_h
    if m_nh3_total_h > 0.0:
        comp_abs["process:NH3_solution_makeup"] = (
            float(comp_abs.get("process:NH3_solution_makeup", 0.0) or 0.0) + m_nh3_total_h
        )

    if m_niso4_makeup_h > 0.0:
        comp_abs["process:Ni_makeup:Ni"] = (
            float(comp_abs.get("process:Ni_makeup:Ni", 0.0) or 0.0)
            + m_niso4_makeup_h * (float(MOLAR_MASS["Ni"]) / float(MOLAR_MASS["NiSO4"]))
        )
    if m_coso4_makeup_h > 0.0:
        comp_abs["process:Co_makeup:Co"] = (
            float(comp_abs.get("process:Co_makeup:Co", 0.0) or 0.0)
            + m_coso4_makeup_h * (float(MOLAR_MASS["Co"]) / float(MOLAR_MASS["CoSO4"]))
        )
    if m_mnso4_makeup_h > 0.0:
        comp_abs["process:Mn_makeup:Mn"] = (
            float(comp_abs.get("process:Mn_makeup:Mn", 0.0) or 0.0)
            + m_mnso4_makeup_h * (float(MOLAR_MASS["Mn"]) / float(MOLAR_MASS["MnSO4"]))
        )

    sto = nmc_hydroxide_precipitation_stoich_kg_h(
        comp_abs=comp_abs,
        nmc_code=nmc_code,
        naoh_solution_wtfrac=float(p.get("naoh_solution_wtfrac", 0.5)),
        product_key="process:NixCoyMnz(OH)2",
        naoh_key="process:NaOH_50",
        m_niso4_makeup_kg_h=m_niso4_makeup_h,
        m_coso4_makeup_kg_h=m_coso4_makeup_h,
        m_mnso4_makeup_kg_h=m_mnso4_makeup_h,
        apply_target_cap=True,
        target_basis=str(p.get("target_basis", "min")),
        max_makeup_fill_fraction=fill_frac,
        precip_target_mol_h=n_precip_target_h if n_precip_target_h > 0.0 else None,
        include_base_naoh=False,
    )

    m_nmc_solid_h = float(sto["m_nmc_solid_kg_h"])
    naoh_wtfrac = float(p.get("naoh_solution_wtfrac", 0.5))
    naoh_so4 = nmc_sulfate_makeup_naoh_solution_kg_h(
        m_niso4_makeup_kg_h=m_niso4_makeup_h,
        m_coso4_makeup_kg_h=m_coso4_makeup_h,
        m_mnso4_makeup_kg_h=m_mnso4_makeup_h,
        naoh_solution_wtfrac=naoh_wtfrac,
    )
    m_naoh_50_for_sulfate_h = float(naoh_so4["m_naoh_solution_kg_h"])
    m_ni_used_h = float(sto["m_ni_used_kg_h"])
    m_co_used_h = float(sto["m_co_used_kg_h"])
    m_mn_used_h = float(sto["m_mn_used_kg_h"])

    _deduct_from_matching_keys(comp_abs, (":Ni", "Ni"), m_ni_used_h)
    _deduct_from_matching_keys(comp_abs, (":Co", "Co"), m_co_used_h)
    _deduct_from_matching_keys(comp_abs, (":Mn", "Mn"), m_mn_used_h)

    if m_naoh_50_for_sulfate_h > 0.0:
        comp_abs["process:NaOH_50"] = float(comp_abs.get("process:NaOH_50", 0.0) or 0.0) + m_naoh_50_for_sulfate_h

    m_na2so4_h = float(sto.get("m_na2so4_kg_h", 0.0) or 0.0)
    tag_stoich_product_in_comp_abs(comp_abs, "process:Na2SO4", m_na2so4_h)
    if m_nmc_solid_h > 0.0:
        tag_stoich_product_in_comp_abs(comp_abs, "process:NixCoyMnz(OH)2", m_nmc_solid_h)

    m_added_h = (
        m_naoh_50_for_sulfate_h
        + m_nh3_total_h
        + m_niso4_makeup_h
        + m_coso4_makeup_h
        + m_mnso4_makeup_h
    )
    m_aug_h = float(flow_in.mass_kg_per_h) + m_added_h
    comp_abs = reconcile_comp_abs_to_mass(
        comp_abs,
        m_aug_h,
        preserve_keys=_nmc_ppt_reconcile_preserve_keys(comp_abs),
    )
    flow_aug = MassFlow(
        m_aug_h,
        meta={"comp_abs": comp_abs, "nmc_precursor_solid_kg_h": float(m_nmc_solid_h)},
    )

    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye precursor precipitation")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye precursor precipitation")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    out_meta = dict(getattr(out_forward, "meta", {}) or {})
    out_meta["nmc_precursor_solid_kg_h"] = float(m_nmc_solid_h)
    out_meta["nmc_precursor_target_nominal_mol_h"] = float(
        meta.get("nmc_precursor_target_nominal_mol_h", 0.0) or reag.get("n_target_nominal_mol_h", 0.0) or 0.0
    )
    out_forward = MassFlow(float(out_forward.mass_kg_per_h), meta=out_meta)

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

    row["NaOH 50% for sulfate neutralization (kg/h)"] = float(m_naoh_50_for_sulfate_h)
    row["NH3 solution (kg/h)"] = float(m_nh3_total_h)
    row["NiSO4 makeup (kg/h)"] = float(m_niso4_makeup_h)
    row["CoSO4 makeup (kg/h)"] = float(m_coso4_makeup_h)
    row["MnSO4 makeup (kg/h)"] = float(m_mnso4_makeup_h)
    row["Ni from battery feed (kg/h)"] = float(m_ni_used_h)
    row["Co from battery feed (kg/h)"] = float(m_co_used_h)
    row["Mn from battery feed (kg/h)"] = float(m_mn_used_h)
    row["Na2SO4 formed (kg/h)"] = float(m_na2so4_h)
    row["NMC code"] = nmc_code
    row["Target basis"] = str(p.get("target_basis", "min"))
    row["Sulfate makeup policy"] = str(p.get("makeup_policy_label", "-"))
    row["Deficit fill cap"] = float(fill_frac)
    row["Precursor rate nominal (mol/h)"] = float(reag.get("n_target_nominal_mol_h", 0.0) or 0.0)
    row["Precursor rate achievable (mol/h)"] = float(sto.get("n_nmc_mol_h", 0.0) or 0.0)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    pr = prices(ctx)
    materials_cost_y = h_y * (
        m_naoh_50_for_sulfate_h * float(pr.get("Sodium hydroxide (50%)", 0.0))
        + m_nh3_total_h * float(pr.get("Ammonia (25%)", 0.0))
        + m_niso4_makeup_h * float(pr.get("Nickel sulfate", 0.0))
        + m_coso4_makeup_h * float(pr.get("Cobalt sulfate", 0.0))
        + m_mnso4_makeup_h * float(pr.get("Manganese sulfate", 0.0))
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

    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras
