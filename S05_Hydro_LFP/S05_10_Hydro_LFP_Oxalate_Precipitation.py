from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    fe_oxalate_precipitation_stoich_kg_h,
    MOLAR_MASS,
    OXALATE_MIXING_RULES,
    deduct_from_suffixes,
    reconcile_comp_abs_to_mass,
)
from Massflow import MassFlow, assert_mass_balance
from step_utils import (
    hours_per_year,
    annual_input_tons_from_flow,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)




def run_hydro_lfp_oxalate_precipitation(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_10: Hydro LFP - Fe Oxalate Precipitation.

    Precipitates dissolved iron as FeC2O4·2H2O using the previously dosed oxalic acid.
    The solid phase remains in the same stream; physical separation is performed in
    the subsequent filtration step.

    Streams:
    - Input:  'lye oxalate mixing'
    - Output (forward): 'lye oxalate precipitation'
    """
    p = params or {}
    step = "Hydro LFP – Fe Oxalate Precipitation"

    # 0) Stoichiometric precipitation from dissolved Fe and available oxalic acid
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})
    fe_suffixes = OXALATE_MIXING_RULES["LFP"]["fe_suffixes"]
    m_fe_in_h = 0.0
    fe_keys = []
    for k, v in comp_abs.items():
        ks = str(k)
        if any(ks.endswith(sfx) or ks == sfx.strip(":") for sfx in fe_suffixes):
            m_fe_in_h += float(v or 0.0)
            fe_keys.append(k)

    m_oxalic_pure_in_h = float(comp_abs.get("process:Oxalic_Acid_pure", 0.0) or 0.0)

    sto = fe_oxalate_precipitation_stoich_kg_h(
        m_fe_kg_h=m_fe_in_h,
        m_oxalic_pure_kg_h=m_oxalic_pure_in_h,
    )

    m_fe_reacted_h = float(sto["fe_reacted_kg_h"])
    m_ox_reacted_h = float(sto["oxalic_reacted_kg_h"])
    m_crystals_h = float(sto["fe_oxalate_2h2o_formed_kg_h"])

    # Fe should go to zero in this step
    if m_fe_reacted_h > 0.0:
        fe_to_remove = float(m_fe_reacted_h)
        for k in fe_keys:
            if fe_to_remove <= 0.0:
                break
            cur = float(comp_abs.get(k, 0.0) or 0.0)
            take = min(cur, fe_to_remove)
            if take > 0.0:
                comp_abs[k] = max(0.0, cur - take)
                fe_to_remove -= take

    # Subtract oxalic acid stoichiometrically (remainder may stay in lye system)
    if m_ox_reacted_h > 0.0:
        comp_abs["process:Oxalic_Acid_pure"] = max(
            0.0, float(comp_abs.get("process:Oxalic_Acid_pure", 0.0) or 0.0) - m_ox_reacted_h
        )

    # Produkt addieren
    if m_crystals_h > 0.0:
        comp_abs["process:FeC2O4_2H2O"] = (
            float(comp_abs.get("process:FeC2O4_2H2O", 0.0) or 0.0) + m_crystals_h
        )
    # Crystal water for FeC2O4·2H2O: 1 mol Fe -> 2 mol H2O from lye (not only oxalic acid pool)
    n_fe_reacted = (m_fe_reacted_h * 1000.0) / float(MOLAR_MASS["Fe"]) if m_fe_reacted_h > 0.0 else 0.0
    m_h2o_bound_req_h = (n_fe_reacted * 2.0 * float(MOLAR_MASS["H2O"])) / 1000.0
    m_h2o_bound_h = deduct_from_suffixes(
        comp_abs,
        [
            "process:H2O_oxalic_solution",
            "process:H2O_oxalate_wash",
            "process:H2O_leaching",
            "process:H2O_pre_wetting",
            ":H2O",
        ],
        m_h2o_bound_req_h,
    )
    m_h2o_shortfall_h = max(0.0, m_h2o_bound_req_h - m_h2o_bound_h)

    # Closed balance in same stream: inlet and outlet mass equal (Fe + oxalate + 2 H2O -> product)
    m_out_h = float(flow_in.mass_kg_per_h)
    if m_h2o_shortfall_h > 1e-9:
        comp_abs["__untracked__"] = comp_abs.get("__untracked__", 0.0) + m_h2o_shortfall_h
    comp_abs = reconcile_comp_abs_to_mass(
        comp_abs,
        m_out_h,
        preserve_keys=["process:FeC2O4_2H2O"],
    )
    flow_aug = MassFlow(m_out_h, meta={"comp_abs": comp_abs})
    
   
    # 1) Mass balance / partition – single forward stream
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye oxalate precipitation")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye oxalate precipitation")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Sizing / CAPEX – reactor based on augmented inlet throughput
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

    # 3) Load and energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
    annual_energy_kwh = Eq.reactor.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Reporting row
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(out_forward.mass_kg_per_h)
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"


    row["Oxalic acid reacted (kg/h)"] = float(m_ox_reacted_h)
    row["Fe reacted (kg/h)"] = float(m_fe_reacted_h)
    row["Crystal water required (kg/h)"] = float(m_h2o_bound_req_h)
    row["Crystal water removed (kg/h)"] = float(m_h2o_bound_h)
    row["Crystal water shortfall (kg/h)"] = float(m_h2o_shortfall_h)
    row["FeC2O4·2H2O formed (kg/h)"] = float(m_crystals_h)
    row["Lye oxalate precipitation (kg/h)"] = float(out_forward.mass_kg_per_h)

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX – energy only
    row = attach_opex_to_row(
        row,
        machine=Eq.reactor,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # 6) CAPEX columns for standardized economics reporting and extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras