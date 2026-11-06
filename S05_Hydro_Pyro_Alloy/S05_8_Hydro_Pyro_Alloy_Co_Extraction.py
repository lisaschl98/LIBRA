from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
import stoichiometry as st
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


def run_hydro_pyro_alloy_co_extraction(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_8: Hydro-Pyro - Co Extraction.

    Purpose:
    - Extract cobalt from Fe-filtered leachate into an organic phase.
    - Forward Co-depleted aqueous raffinate to downstream Ni processing.

    **Stoichiometry (Cyanex 272 monomer HR, M = 290,43 g/mol; 30 % / 70 % in kerosene):**
    ``Co²⁺ + 2 HR → CoR₂ + 2 H⁺`` — extractant circulation from **2 mol HR per mol Co²⁺**
    with ``solvent_overstoich_factor`` (default **1.3**).
    **NaOH 50 wt-%** for pH: **2 mol NaOH per mol Co** transferred; mass is added to **Lye-Forward**
    added (``process:NaOH_50`` in ``comp_abs``), balance: ``m_in + m_NaOH``.

    Forward stream:
    - 'lye after Co extraction'

    Side stream:
    - 'Co loaded organic phase'

    Reporting: **Co loaded organic phase** mass = Co in organic + Cyanex 272 circulating +
    kerosene circulating; **Co extracted** from organic ``comp_abs``. Make-up from
    ``solvent_extraction_makeup_kg_h`` (basis: Co transferred to organic).

    **Stripping** (reverse): ``CoR₂ + 2 H⁺ → Co²⁺ + 2 HR`` (routing via EFF).
    """
    p = params or {}
    step = "Hydro-Pyro - Co Extraction"

    # 1) Partition / yield from EFF
    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="lye after Co extraction")

    summ_pre = rfx.stream_summary(step, outputs, fallback_forward="lye after Co extraction")
    forward_key = summ_pre["forward_key"]
    loss_key = summ_pre["loss_key"]
    side_keys = summ_pre["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    co_loaded_flow = rfx.mf_get(outputs, "Co loaded organic phase")
    co_loaded_h = float(co_loaded_flow.mass_kg_per_h)
    m_co_transferred = float(st.metal_mass_in_flow_kg_h(co_loaded_flow, "Co"))
    if m_co_transferred <= 1e-15:
        m_co_transferred = float(co_loaded_h)
    comp_for_solvent = {":Co": m_co_transferred}
    solvent = st.solvent_extraction_makeup_kg_h(
        comp_for_solvent,
        "Co",
        overstoichiometric_factor=float(p.get("solvent_overstoich_factor", 1.3)),
        organic_mass_fraction=float(p.get("organic_solvent_mass_fraction", 0.30)),
        kerosene_mass_fraction=float(p.get("kerosene_mass_fraction", 0.70)),
        annual_solvent_loss_fraction=float(p.get("annual_solvent_loss_fraction", 0.10)),
    )
    if co_loaded_h > 0.0:
        meta = dict(getattr(co_loaded_flow, "meta", {}) or {})
        meta["solvent_extraction"] = dict(solvent)
        co_loaded_flow.meta = meta

    m_naoh_50_h = float(
        st.solvent_extraction_naoh_50_for_acid_from_transfer_kg_h(
            m_co_transferred,
            "Co",
            mol_naoh_per_mol_metal=float(p.get("naoh_mol_per_mol_metal_extracted", 2.0)),
            naoh_solution_wtfrac=float(p.get("naoh_solution_wtfrac", 0.5)),
        )
    )
    if m_naoh_50_h > 0.0:
        meta_lye = dict(getattr(out_forward, "meta", {}) or {})
        comp_lye = dict(meta_lye.get("comp_abs") or {})
        comp_lye["process:NaOH_50"] = float(comp_lye.get("process:NaOH_50", 0.0) or 0.0) + m_naoh_50_h
        meta_lye["comp_abs"] = comp_lye
        out_forward = MassFlow(
            float(out_forward.mass_kg_per_h) + m_naoh_50_h,
            meta=meta_lye,
        )
        outputs[forward_key] = out_forward

    assert_mass_balance(
        step,
        float(flow_in.mass_kg_per_h) + m_naoh_50_h,
        outputs,
    )

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye after Co extraction")

    # 2) Equipment sizing and CAPEX
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.solvent_extraction,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.solvent_extraction.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_in, ctx)
    annual_energy_kwh = Eq.solvent_extraction.energy_for_sized(
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

    m_co_tagged = st.metal_mass_in_flow_kg_h(co_loaded_flow, "Co")
    m_co_for_sum = float(m_co_tagged) if m_co_tagged > 1e-15 else float(co_loaded_h)
    org_c = float(solvent.get("organic_circulating_kg_h", 0.0))
    ker_c = float(solvent.get("kerosene_circulating_kg_h", 0.0))
    row["Lye after Co extraction (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Co loaded organic phase (kg/h)"] = float(m_co_for_sum + org_c + ker_c)
    row["Co extracted (kg/h)"] = float(m_co_tagged if m_co_tagged > 1e-15 else float(co_loaded_h))
    row["Cyanex 272 added (kg/h)"] = float(solvent.get("organic_makeup_kg_h", 0.0))
    row["Cyanex 272 circulating (kg/h)"] = float(solvent.get("organic_circulating_kg_h", 0.0))
    row["Kerosene circulating (kg/h)"] = float(solvent.get("kerosene_circulating_kg_h", 0.0))
    row["NaOH 50% for extraction pH (kg/h)"] = m_naoh_50_h

    h_y = hours_per_year(ctx)
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX (solvent make-up + NaOH 50 % + energy)
    pr = prices(ctx)
    materials_cost_y = h_y * (
        float(solvent.get("organic_makeup_kg_h", 0.0)) * float(pr.get("Cyanex 272", 0.0))
        + m_naoh_50_h * float(pr.get("Sodium hydroxide (50%)", 0.0))
    )
    row = attach_opex_to_row(
        row,
        machine=Eq.solvent_extraction,
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
    row["CAPEX install ($)"] = float(sizing.get("capex_install_model", 0.0))
    row["CAPEX instr ($)"] = float(sizing.get("capex_instr", 0.0))
    row["CAPEX piping ($)"] = float(sizing.get("capex_piping", 0.0))
    row["CAPEX electrical ($)"] = float(sizing.get("capex_electrical", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras