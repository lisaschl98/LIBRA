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

# Molar masses — stripping acid uses ``stoichiometry`` helpers.


def _h2so4_for_stripping(
    flow_in: MassFlow,
    safety_factor: float = 1.2,
    mol_h2so4_per_mol_metal: float = 1.0,
) -> tuple[float, float]:
    """
    Pure H2SO4 demand [kg/h] for Co stripping from loaded organic phase.

    **Reverse reaction:** ``CoR₂ + 2 H⁺ → Co²⁺ + 2 HR`` (free HR in organic phase / balance via EFF).
    **1 mol H₂SO₄ per mol Co** (2 H⁺), × ``safety_factor``. Optional ``mol_h2so4_per_mol_metal``.

    Returns:
    - m_h2so4_pure_kg_h
    - m_co_kg_h
    """
    m_co = float(st.metal_mass_in_flow_kg_h(flow_in, "Co"))
    if m_co <= 1e-15:
        return 0.0, 0.0
    m_pure = float(
        st.h2so4_pure_for_divalent_stripping_kg_h(
            m_co,
            "Co",
            safety_factor=float(safety_factor),
            mol_h2so4_per_mol_metal=float(mol_h2so4_per_mol_metal),
        )
    )
    return m_pure, m_co


def run_hydro_pyro_alloy_co_stripping(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_10: Hydro-Pyro - Co Stripping.

    Purpose:
    - Transfer Co from the scrubbed organic phase to an aqueous sulfate solution.
    - Dose sulfuric acid and pass stream through configured EFF partition/yield.

    **Stripping (reverse reaction):** ``CoR₂ + 2 H⁺ → Co²⁺ + 2 HR``. Acid demand: **1 mol H₂SO₄ per mol Co** (2 H⁺), × ``h2so4_safety_factor`` (default **1.2**).

    Forward stream:
    - 'Co stripped solution'

    Reporting repeats **Cyanex 272 / kerosene circulating** from the organic phase ``meta``
    (same inventory as at Co extraction).
    """
    p = params or {}
    step = "Hydro-Pyro - Co Stripping"
    h_y = hours_per_year(ctx)

    solm = dict((getattr(flow_in, "meta", {}) or {}).get("solvent_extraction") or {})

    # 0) Reagent demand
    m_h2so4_pure_h, m_co_h = _h2so4_for_stripping(
        flow_in,
        safety_factor=float(p.get("h2so4_safety_factor", 1.2)),
        mol_h2so4_per_mol_metal=float(p.get("mol_h2so4_per_mol_metal_stripped", 1.0)),
    )
    if m_h2so4_pure_h <= 0.0:
        m_h2so4_pure_h = float(p.get("H2SO4_kg_h", 0.0) or 0.0)

    # Convert pure acid demand to 95 wt-% solution
    m_h2so4_95_h = m_h2so4_pure_h / 0.95 if m_h2so4_pure_h > 0.0 else 0.0
    m_h2so4_95_y = m_h2so4_95_h * h_y

    # Add acid to stream composition for strict mass balance
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})
    if m_h2so4_95_h > 0.0:
        comp_abs["process:H2SO4_95"] = comp_abs.get("process:H2SO4_95", 0.0) + m_h2so4_95_h

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) + m_h2so4_95_h,
        meta={"comp_abs": comp_abs},
    )

    # 1) Partition / yield
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="Co stripped solution")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="Co stripped solution")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    # 2) Equipment sizing and CAPEX
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.solvent_extraction,
        flow_aug,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.solvent_extraction.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    annual_tons = annual_input_tons_from_flow(flow_aug, ctx)
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

    row["Co stripped solution (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["H2SO4 95% added (kg/h)"] = float(m_h2so4_95_h)
    row["Co stripped (kg/h)"] = float(m_co_h)
    row["Cyanex 272 circulating (kg/h)"] = float(solm.get("organic_circulating_kg_h", 0.0))
    row["Kerosene circulating (kg/h)"] = float(solm.get("kerosene_circulating_kg_h", 0.0))
    row["In kg/h"] = float(st.solvent_extract_organic_inventory_kg_h(flow_in, "Co"))

    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(annual_energy_kwh) / h_y if h_y > 0 else 0.0

    # 5) OPEX: acid cost
    pr = prices(ctx)
    h2so4_price = float(pr.get("Sulfuric acid (95%)", 0.0))  # currency/kg (95 wt-% basis)
    materials_cost_y = m_h2so4_95_y * h2so4_price

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