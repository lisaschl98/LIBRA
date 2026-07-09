from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    LIH2PO4_CRYSTALLIZATION_RULES,
    lih2po4_crystallization_stoich_kg_h,
    deduct_from_suffixes,
    reconcile_comp_abs_to_mass,
)
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import (
    crystallization_water_evaporation_kwh_h,
    water_removed_for_thermal_kg_h,
)
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)


def _deduct_lih2po4_matrix_mass(comp_abs: dict, amount_kg_h: float) -> float:
    """Supply H/O mass for LiH2PO4 from existing liquor components, keeping crystallization closed."""
    remaining = max(0.0, float(amount_kg_h))
    if remaining <= 0.0:
        return 0.0

    # Prefer cathode oxygen / tracked water, then untracked solvent mass.
    removed = deduct_from_suffixes(
        comp_abs,
        [
            ":O",
            "O",
            "process:H2O_evap",
            "process:H2O_leaching",
            "process:H2O_pre_wetting",
            "process:H2O_oxalic_solution",
            "process:H2O_oxalate_wash",
            "process:H2O_wash",
            "process:H2O",
            "H2O",
            "__untracked__",
        ],
        remaining,
    )
    remaining -= removed
    if remaining <= 1e-12:
        return max(0.0, amount_kg_h)

    # Last resort for sparse compositions: remove from other non-product/non-Li/P liquor mass.
    for key in list(comp_abs.keys()):
        if remaining <= 1e-12:
            break
        key_s = str(key)
        key_l = key_s.lower()
        if "lih2po4" in key_l or key_s.endswith(":Li") or key_s == "Li" or key_s.endswith(":P") or key_s == "P":
            continue
        available = max(0.0, float(comp_abs.get(key, 0.0) or 0.0))
        take = min(available, remaining)
        if take > 0.0:
            comp_abs[key] = available - take
            remaining -= take

    return max(0.0, amount_kg_h - remaining)


def run_hydro_lfp_lih2po4_crystallization(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_16: Hydro LFP – LiH2PO4 Crystallization.

    Forms LiH2PO4 stoichiometrically from dissolved Li and P.
    EFF handles stream split into mother liquor and crystals.

    - Input:   'lye concentrated'
    - Forward: 'Li mother liquor'
    - Side:    'Lithium dihydrogenphosphate'
    """
    p = params or {}
    step = "Hydro LFP – LiH2PO4 Crystallization"

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    rules = dict(LIH2PO4_CRYSTALLIZATION_RULES["LFP"])

    # Recoveries from EFF yields (with fallback to rule defaults)
    cfg = rfx.get_step_cfg(step)
    yields = cfg.get("yield", {}) or {}

    li_recovery_eff = float(
        yields.get("Lithium recoverable", yields.get("eta_Li", rules["li_recovery_default"]))
        or rules["li_recovery_default"]
    )
    p_recovery_eff = float(
        yields.get("Phosphorus recoverable", yields.get("eta_P", rules["p_recovery_default"]))
        or rules["p_recovery_default"]
    )

    # Optional manual overrides via params
    li_recovery = float(p.get("li_recovery", li_recovery_eff))
    p_recovery = float(p.get("p_recovery", p_recovery_eff))

    sto = lih2po4_crystallization_stoich_kg_h(
        comp_abs=comp_abs,
        li_suffixes=rules["li_suffixes"],
        p_suffixes=rules["p_suffixes"],
        li_recovery=li_recovery,
        p_recovery=p_recovery,
    )

    m_lih2po4_h = float(sto["m_lih2po4_kg_h"])
    m_li_used_h = float(sto["m_li_used_kg_h"])
    m_p_used_h = float(sto["m_p_used_kg_h"])

    # Update composition
    if m_lih2po4_h > 0.0:
        prod_key = str(rules["product_key"])

        deduct_from_suffixes(comp_abs, rules["li_suffixes"], m_li_used_h)
        deduct_from_suffixes(comp_abs, rules["p_suffixes"], m_p_used_h)
        m_matrix_used_h = _deduct_lih2po4_matrix_mass(
            comp_abs,
            max(0.0, m_lih2po4_h - m_li_used_h - m_p_used_h),
        )
        comp_abs[prod_key] = float(comp_abs.get(prod_key, 0.0) or 0.0) + m_lih2po4_h
    else:
        m_matrix_used_h = 0.0

    m_in = float(flow_in.mass_kg_per_h)
    comp_abs = reconcile_comp_abs_to_mass(
        comp_abs,
        m_in,
        preserve_keys=[str(rules["product_key"])],
    )
    flow_aug = MassFlow(m_in, meta={"comp_abs": comp_abs})

    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="Li mother liquor")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="Li mother liquor")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    crystals_flow = rfx.mf_get(outputs, "Lithium dihydrogenphosphate")
    crystals_h = float(crystals_flow.mass_kg_per_h)

    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.crystallizer,
        flow_aug,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.crystallizer.name, sizing)

    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    mother_liquor_h = float(out_forward.mass_kg_per_h)
    m_water_removed_h = water_removed_for_thermal_kg_h(eff_wastewater_kg_h=mother_liquor_h)
    thermal = crystallization_water_evaporation_kwh_h(m_water_removed_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])
    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y

    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Li mother liquor (kg/h)"] = float(mother_liquor_h)
    row["Lithium dihydrogenphosphate (kg/h)"] = crystals_h
    row["LiH2PO4 crystallized (kg/h)"] = float(m_lih2po4_h)
    row["Li used for LiH2PO4 (kg/h)"] = float(m_li_used_h)
    row["P used for LiH2PO4 (kg/h)"] = float(m_p_used_h)
    row["H/O matrix used for LiH2PO4 (kg/h)"] = float(m_matrix_used_h)
    row["Water evaporated (kg/h)"] = float(m_water_removed_h)
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat evaporation (kJ/h)"] = float(thermal["q_evap_kj_h"])
    row["Evaporation efficiency"] = float(thermal["eta_evaporation"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    row = attach_opex_to_row(
        row,
        machine=Eq.crystallizer,
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
    row["outputs_kg_h"] = [{"Lithium dihydrogenphosphate": float(crystals_h)}]
    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras