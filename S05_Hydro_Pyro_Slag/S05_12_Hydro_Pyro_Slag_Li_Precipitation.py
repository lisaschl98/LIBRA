from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    LI2CO3_PRECIPITATION_RULES,
    li2co3_precipitation_stoich_kg_h,
    deduct_from_suffixes,
    liquor_inventory_preserve_keys,
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


def run_hydro_pyro_slag_li_precipitation(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_12: Hydro Pyro - Li Precipitation.

    Precipitates lithium as lithium carbonate (Li2CO3) by dosing sodium carbonate.
    The resulting slurry is passed to Li filtration.

    Streams:
    - Input:  'lye concentrated'
    - Output (forward): 'lye lithium precipitation'

    Process components introduced for downstream partitioning (EFF):
    - process:Li2CO3
    - process:Na2SO4
    """
    p = params or {}
    step = "Hydro Pyro – Li Precipitation"
    h_y = hours_per_year(ctx)

    # 0) Central stoichiometric conversion
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    # Fallback to MIX rules if SLAG profile is not yet present
    rule = LI2CO3_PRECIPITATION_RULES.get("SLAG", LI2CO3_PRECIPITATION_RULES["MIX"])

    res = li2co3_precipitation_stoich_kg_h(
        comp_abs=comp_abs,
        li_suffixes=rule["li_suffixes"],
        li_recovery=float(p.get("li_recovery", rule.get("li_recovery_default", 1.0))),
        na2co3_purity=float(p.get("na2co3_purity", rule.get("na2co3_purity_default", 1.0))),
        na2co3_excess=float(p.get("na2co3_excess", rule.get("na2co3_excess_default", 1.0))),
    )

    m_li2co3_h = float(res.get("m_li2co3_kg_h", 0.0))
    m_na2co3_h = float(res.get("m_na2co3_added_kg_h", 0.0))
    m_na2so4_h = float(res.get("m_na2so4_kg_h", 0.0))
    m_li_used_h = float(res.get("m_li_used_kg_h", 0.0))
    m_na2co3_y = m_na2co3_h * h_y

    deduct_from_suffixes(comp_abs, list(rule["li_suffixes"]), m_li_used_h)

    product_key = str(rule.get("product_key", "process:Li2CO3"))
    na2co3_key = str(rule.get("na2co3_key", "process:Na2CO3"))
    na2so4_key = str(rule.get("na2so4_key", "process:Na2SO4"))

    if m_li2co3_h > 0.0:
        comp_abs[product_key] = float(m_li2co3_h)
    else:
        comp_abs.pop(product_key, None)
    if m_na2co3_h > 0.0:
        comp_abs[na2co3_key] = float(m_na2co3_h)
    else:
        comp_abs.pop(na2co3_key, None)
    if m_na2so4_h > 0.0:
        tag_stoich_product_in_comp_abs(comp_abs, na2so4_key, m_na2so4_h)
    elif na2so4_key not in comp_abs:
        comp_abs.pop(na2so4_key, None)

    m_aug_h = float(flow_in.mass_kg_per_h) + m_na2co3_h
    comp_abs = reconcile_comp_abs_to_mass(
        comp_abs,
        m_aug_h,
        preserve_keys=liquor_inventory_preserve_keys(
            comp_abs,
            extra_preserve=(product_key, na2co3_key, na2so4_key),
        ),
    )

    flow_aug = MassFlow(m_aug_h, meta={"comp_abs": comp_abs})

    # 1) Mass balance / partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye lithium precipitation")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye lithium precipitation")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Sizing / CAPEX
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
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye lithium precipitation (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Li2CO3 produced (kg/h)"] = float(m_li2co3_h)
    row["Na2CO3 added (kg/h)"] = float(m_na2co3_h)
    row["Na2SO4 formed (kg/h)"] = float(m_na2so4_h)
    row["Li precipitated as Li2CO3 (kg/h)"] = float(m_li_used_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX - sodium carbonate reagent cost
    pr = prices(ctx)
    na2co3_price = float(pr.get("Sodium carbonate", 0.0))
    materials_cost_y = m_na2co3_y * na2co3_price

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

    # 6) CAPEX columns for standardized economics reporting + extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras