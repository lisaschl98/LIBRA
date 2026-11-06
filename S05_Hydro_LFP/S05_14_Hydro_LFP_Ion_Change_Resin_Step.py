from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import ION_EXCHANGE_RULES, ion_exchange_resin_makeup_kg_h
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


def run_hydro_lfp_ion_exchange(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_14: Hydro LFP – Ion Exchange (Resin, through-pass model).

    Analog Hydro Mix – Ion Exchange Resin:
    - Input:  'lye iron clean'
    - Output (forward):  'lye clean' (liquid without metals bound on resin)
    - Output (separated): 'loaded_resin' (Fe on resin, EFF)

    Ion routing via EFF; CH-90 Na makeup is OPEX-only (not added to lye mass).
    """
    p = params or {}
    step = "Hydro LFP – Ion Exchange"

    h_y = hours_per_year(ctx)

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    ix_rule = dict(ION_EXCHANGE_RULES["LFP"])

    if "ix_capacity_eq_per_kg_resin" in p:
        ix_rule["capacity_eq_per_kg_resin"] = float(p["ix_capacity_eq_per_kg_resin"])
    if "ix_utilization" in p:
        ix_rule["utilization"] = float(p["ix_utilization"])
    if "ix_regeneration_efficiency" in p:
        ix_rule["regeneration_efficiency"] = float(p["ix_regeneration_efficiency"])
    if "ix_attrition_makeup_frac" in p:
        ix_rule["attrition_makeup_frac"] = float(p["ix_attrition_makeup_frac"])
    if "ix_safety_factor" in p:
        ix_rule["safety_factor"] = float(p["ix_safety_factor"])

    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="lye clean")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye clean")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    loaded_resin_flow = rfx.mf_get(outputs, "loaded_resin")
    loaded_resin_h = float(loaded_resin_flow.mass_kg_per_h)

    # Makeup from metals on resin (OPEX/reporting only — not added to lye mass), analog Mix
    resin_meta = dict(getattr(loaded_resin_flow, "meta", {}) or {})
    resin_comp = dict(resin_meta.get("comp_abs") or {})
    makeup_comp = resin_comp if sum(resin_comp.values()) > 1e-12 else comp_abs
    m_resin_makeup_h, loading_eq_h = ion_exchange_resin_makeup_kg_h(
        comp_abs=makeup_comp,
        rule=ix_rule,
    )

    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.ion_exchanger,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.ion_exchanger.name, sizing)

    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.ion_exchanger.energy_for_sized(
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

    row["Lye clean (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Loaded resin (kg/h)"] = loaded_resin_h
    row["CH-90 Na makeup (kg/h)"] = float(m_resin_makeup_h)
    row["IX loading (eq/h)"] = float(loading_eq_h)

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    pr = prices(ctx)
    resin_price = float(pr.get("CH-90 Na resin", 0.0))
    resin_cost_y = float(m_resin_makeup_h) * h_y * resin_price

    row = attach_opex_to_row(
        row,
        machine=Eq.ion_exchanger,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=resin_cost_y,
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
