from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance
from step_utils import (
    hours_per_year,
    annual_input_tons_from_flow,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
    _comp_abs_to_mass,
)


def run_hydro_lfp_oxalate_filtration(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_11: Hydro LFP - Oxalate Filtration.

    Separates the precipitated iron oxalate solids from the liquor after Fe oxalate
    precipitation. Stream routing is controlled via EFF (Recycling_Efficiencies).

    Streams (aligned with EFF, reporting like Hydro NMC – NMC Filtration):
    - Input:  'lye oxalate precipitation'
    - Output (forward):  'lye iron clean'
    - Output (separated): 'Ferrous oxalate cake'
    """
    p = params or {}
    step = "Hydro LFP – Oxalate Filtration"
    forward_key = "lye iron clean"
    cake_key = "Ferrous oxalate cake"

    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream=forward_key)

    cfg = rfx.get_step_cfg(step)
    loss_key = str(cfg.get("loss_sink", "loss"))

    m_in = float(flow_in.mass_kg_per_h)
    cake_h = float(rfx.mf_get(outputs, cake_key).mass_kg_per_h)
    loss_h = float(rfx.mf_get(outputs, loss_key).mass_kg_per_h)
    lye_h = max(0.0, m_in - cake_h - loss_h)

    meta_in = dict(getattr(flow_in, "meta", {}) or {})
    lye_src = rfx.mf_get(outputs, forward_key)
    lye_meta = dict(getattr(lye_src, "meta", {}) or {})
    lye_comp = dict(lye_meta.get("comp_abs") or meta_in.get("comp_abs") or {})
    for k in list(lye_comp.keys()):
        if "fec2o4" in str(k).lower():
            lye_comp.pop(k, None)
    s_comp = float(sum(lye_comp.values()))
    if lye_h > 1e-12 and s_comp < lye_h - 1e-9:
        lye_comp["__untracked__"] = lye_comp.get("__untracked__", 0.0) + (lye_h - s_comp)
    elif s_comp > lye_h + 1e-9 and s_comp > 0.0:
        trim = s_comp - lye_h
        if "__untracked__" in lye_comp and lye_comp["__untracked__"] >= trim:
            lye_comp["__untracked__"] -= trim
        else:
            f = lye_h / s_comp
            lye_comp = {k: v * f for k, v in lye_comp.items()}
    lye_frac = {k: float(v) / lye_h for k, v in lye_comp.items()} if lye_h > 1e-12 else {}

    cake_src = rfx.mf_get(outputs, cake_key)
    cake_meta = dict(getattr(cake_src, "meta", {}) or {})
    cake_comp = dict(cake_meta.get("comp_abs") or {})
    if cake_h > 1e-12 and not any("fec2o4" in str(k).lower() for k in cake_comp):
        cake_comp = _comp_abs_to_mass({"process:FeC2O4_2H2O": cake_h}, cake_h)
    cake_frac = (
        {k: float(v) / cake_h for k, v in cake_comp.items()} if cake_h > 1e-12 else {}
    )

    outputs = dict(outputs)
    outputs[forward_key] = MassFlow(
        lye_h,
        meta={**meta_in, "comp_abs": lye_comp, "comp": lye_frac},
    )
    outputs[cake_key] = MassFlow(
        cake_h,
        meta={"comp_abs": cake_comp, "comp": cake_frac},
    )

    out_forward = outputs[forward_key]
    assert_mass_balance(
        step,
        m_in,
        {
            forward_key: outputs[forward_key],
            cake_key: outputs[cake_key],
            **({loss_key: rfx.mf_get(outputs, loss_key)} if loss_h > 1e-12 else {}),
        },
    )

    # 2) Sizing / CAPEX – belt filter based on inlet throughput
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.filterpress,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.filterpress.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.filterpress.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    # 4) Reporting row
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(lye_h + cake_h + loss_h)
    row["Loss (kg/h)"] = loss_h
    row["Side streams (kg/h)"] = cake_h
    row["Forward key"] = forward_key
    row["Loss sink key"] = loss_key
    row["Side keys"] = cake_key if cake_h > 1e-12 else "-"

    row["Lye iron clean (kg/h)"] = lye_h
    row["Ferrous oxalate cake (kg/h)"] = cake_h

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX – energy only (no additional reagents in this step)
    row = attach_opex_to_row(
        row,
        machine=Eq.filterpress,
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