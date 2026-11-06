from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import (
    crystallization_water_evaporation_kwh_h,
    hydrate_water_in_crystal_kg_h,
    water_removed_for_thermal_kg_h,
)

from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)

# Molar masses [g/mol]
M_CO = 58.933
M_COSO4_7H2O = 281.11  # CoSO4·7H2O


def _coso4_7h2o_from_solution(flow_in: MassFlow) -> tuple[float, float]:
    """
    Convert dissolved Co to equivalent CoSO4·7H2O crystal mass [kg/h].

    Assumption:
    - All dissolved Co crystallizes as CoSO4·7H2O.
    """
    comp_abs = dict(getattr(flow_in, "meta", {}).get("comp_abs") or {})

    m_co = 0.0
    for k, v in comp_abs.items():
        ks = str(k)
        if ks.endswith(":Co") or ks == "Co":
            m_co += float(v or 0.0)

    if m_co <= 0.0:
        return 0.0, 0.0

    factor = M_COSO4_7H2O / M_CO if M_CO > 0 else 1.0
    m_crystals = m_co * factor
    return m_crystals, m_co


def run_hydro_pyro_alloy_co_crystallization(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_11: Hydro-Pyro - Co Crystallization.

    Purpose:
    - Crystallize cobalt sulfate heptahydrate from Co-bearing stripping solution.

    Forward stream:
    - 'Co mother liquor'

    Side stream:
    - 'CoSO4*7H2O'
    """
    p = params or {}
    step = "Hydro-Pyro - Co Crystallization"

    # 0) Determine crystallized mass and update composition
    m_crystals_h, m_co_h = _coso4_7h2o_from_solution(flow_in)

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    if m_co_h > 0.0:
        for k in list(comp_abs.keys()):
            ks = str(k)
            if ks.endswith(":Co") or ks == "Co":
                comp_abs[k] = 0.0
        comp_abs["process:CoSO4*7H2O"] = comp_abs.get("process:CoSO4*7H2O", 0.0) + m_crystals_h

    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h) - m_co_h + m_crystals_h,
        meta={"comp_abs": comp_abs},
    )

    # 1) Partition / yield
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="Co mother liquor")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="Co mother liquor")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    crystals_flow = rfx.mf_get(outputs, "CoSO4*7H2O")
    crystals_h = float(crystals_flow.mass_kg_per_h)

    # 2) Equipment sizing and CAPEX
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

    # 3) Load and energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    mother_liquor_h = float(out_forward.mass_kg_per_h)
    m_water_in_crystal_h = hydrate_water_in_crystal_kg_h(crystals_h, M_COSO4_7H2O, 7)
    m_water_removed_h = water_removed_for_thermal_kg_h(eff_wastewater_kg_h=mother_liquor_h)
    thermal = crystallization_water_evaporation_kwh_h(m_water_removed_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])
    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y

    # 4) Reporting
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Co mother liquor (kg/h)"] = float(mother_liquor_h)
    row["CoSO4*7H2O crystals (kg/h)"] = float(crystals_h)
    row["Co crystallized (kg/h)"] = float(m_co_h)
    row["Water in crystal (kg/h)"] = float(m_water_in_crystal_h)
    row["Water evaporated (kg/h)"] = float(m_water_removed_h)
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat evaporation (kJ/h)"] = float(thermal["q_evap_kj_h"])
    row["Evaporation efficiency"] = float(thermal["eta_evaporation"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    # 5) OPEX (energy only)
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

    # 6) CAPEX columns for standardized economics reporting + extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["CAPEX install ($)"] = float(sizing.get("capex_install_model", 0.0))
    row["CAPEX instr ($)"] = float(sizing.get("capex_instr", 0.0))
    row["CAPEX piping ($)"] = float(sizing.get("capex_piping", 0.0))
    row["CAPEX electrical ($)"] = float(sizing.get("capex_electrical", 0.0))
    row["outputs_kg_h"] = [{"Cobalt sulfate": float(crystals_h)}]

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras