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
    nmc_filtration_apply_lye_split,
)


def run_hydro_mix_filtration_nmc(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_13: Hydro Mix – NMC Filtration.

    EFF-driven split; reporting: filtrate = liquid input − NMC precursor.

    Streams:
    - Input:  'lye precursor precipitation'
    - Output (Separated): 'NMC Precursor'
    - Output (Forward):   'wastewater filtration' (remaining lye)
    """
    p = params or {}
    step = "Hydro Mix – NMC Filtration"
    forward_key = "lye NMC clean"
    precursor_key = "NMC Precursor"

    meta_in = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta_in.get("comp_abs") or {})
    m_solid_h = float(meta_in.get("nmc_precursor_solid_kg_h", 0.0) or 0.0)
    if m_solid_h > 0.0:
        comp_abs["process:NixCoyMnz(OH)2"] = (
            float(comp_abs.get("process:NixCoyMnz(OH)2", 0.0) or 0.0) + m_solid_h
        )
    flow_for_partition = MassFlow(
        float(flow_in.mass_kg_per_h) + m_solid_h,
        meta={**meta_in, "comp_abs": comp_abs},
    )

    outputs = rfx.apply_step_cfg(step, flow_for_partition, fallback_default_stream="lye NMC clean")

    cfg = rfx.get_step_cfg(step)
    loss_key = str(cfg.get("loss_sink", "loss"))
    flow_in_report, flow_sizing, lye_h, precursor_h, outputs = nmc_filtration_apply_lye_split(
        flow_in,
        outputs,
        forward_key=forward_key,
        precursor_key=precursor_key,
        loss_key=loss_key,
    )
    out_forward = outputs[forward_key]

    m_in_report = float(flow_in_report.mass_kg_per_h)
    loss_h = float(rfx.mf_get(outputs, loss_key).mass_kg_per_h)
    assert_mass_balance(
        step,
        m_in_report,
        {
            forward_key: MassFlow(lye_h, meta=out_forward.meta),
            precursor_key: outputs[precursor_key],
            **({loss_key: rfx.mf_get(outputs, loss_key)} if loss_h > 1e-12 else {}),
        },
    )

    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.filterpress,
        flow_sizing,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.filterpress.name, sizing)

    required_tph = float(flow_sizing.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_sizing, ctx)
    annual_energy_kwh = Eq.filterpress.energy_for_sized(
        annual_input_tons=annual_tons,
        n_lines=int(sizing.get("n_lines", 0) or 0),
        line_tph=float(sizing.get("line_capacity_tph", 0.0) or 0.0),
    )

    row = make_row(step, flow_in_report, out_forward)
    row["Out kg/h"] = float(lye_h + precursor_h + loss_h)
    row["Loss (kg/h)"] = loss_h
    row["Side streams (kg/h)"] = precursor_h
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = loss_key
    row["Side keys"] = precursor_key if precursor_h > 1e-12 else "-"

    row["Liquid in (kg/h)"] = float(flow_in.mass_kg_per_h)
    row["NMC Precursor (kg/h)"] = precursor_h
    row["NixCoyMnz(OH)2 separated (kg/h)"] = precursor_h
    row["Lye NMC clean (kg/h)"] = lye_h

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

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

    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras
