from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import CONCENTRATION_RULES, concentration_evaporation_kg_h, _sum_by_suffixes
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import (
    concentration_water_evaporation_kwh_h,
    water_removed_for_thermal_kg_h,
)
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)


def run_hydro_mix_fe_concentration(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_20: Hydro Mix – Fe Concentration.

    Concentrates filtration solution by evaporating water to reach target
    dissolved Fe concentration (if feasible).

    Streams:
    - Input:  'filtration solution'
    - Output (Forward): 'lye concentrated'
    - Output (Side):    'wastewater' (via EFF partition of process:H2O_evap)
    """
    p = params or {}
    step = "Hydro Mix – Fe Concentration"

    # 0) Concentration logic from stoichiometry.py
    rule = dict(CONCENTRATION_RULES["MIX_FE"])

    c_target_g_l = float(p.get("c_target_g_l", rule["c_target_g_l_default"]))
    c_min_g_l = float(p.get("c_min_g_l", rule["c_min_g_l_default"]))
    rho_sol = float(p.get("rho_solution_kg_m3", rule["rho_solution_kg_m3_default"]))
    design_load = float(p.get("design_load", 0.85))

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})
    m_in_h = float(flow_in.mass_kg_per_h)

    conc = concentration_evaporation_kg_h(
        comp_abs=comp_abs,
        m_in_kg_h=m_in_h,
        solute_suffixes=rule["solute_suffixes"],
        c_target_g_l=c_target_g_l,
        c_min_g_l=c_min_g_l,
        rho_solution_kg_m3=rho_sol,
    )

    m_fe_h = float(conc["m_solute_kg_h"])
    c_current_g_l = float(conc["c_current_g_l"])
    c_new_g_l = float(conc["c_new_g_l"])
    m_water_evap_h = float(conc["m_water_evap_kg_h"])

    # Track evaporated water for EFF routing
    evap_key = str(rule.get("evap_component_key", "process:H2O_evap"))
    if m_water_evap_h > 0.0:
        comp_abs[evap_key] = float(comp_abs.get(evap_key, 0.0) or 0.0) + m_water_evap_h

    # Keep total mass unchanged; EFF partitions evaporated water to wastewater
    flow_aug = MassFlow(
        m_in_h,
        meta={"comp_abs": comp_abs},
    )

    # 1) MASS BALANCE / Partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="lye concentrated")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="lye concentrated")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    wastewater_flow = rfx.mf_get(outputs, "wastewater")
    wastewater_h = float(wastewater_flow.mass_kg_per_h)

    # 2) SIZING / CAPEX – Evaporator on wet inlet
    sizing = size_machine_for_mass(
        step,
        Eq.evaporator,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.evaporator.name, sizing)

    # 3) LOAD + ENERGY
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    m_water_removed_h = water_removed_for_thermal_kg_h(
        eff_wastewater_kg_h=wastewater_h,
        stoich_required_kg_h=m_water_evap_h,
    )
    thermal = concentration_water_evaporation_kwh_h(m_water_removed_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])

    # 4) Reporting
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye concentrated (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Wastewater (kg/h)"] = float(wastewater_h)
    row["Fe in feed (kg/h)"] = float(m_fe_h)
    row["P mass in feed (kg/h)"] = float(_sum_by_suffixes(comp_abs, [":P", "P"]))
    row["Fe concentration in (g/L)"] = float(c_current_g_l)
    row["Fe concentration out (g/L)"] = float(c_new_g_l)
    row["Water evaporated (kg/h)"] = float(m_water_removed_h)
    row["Water evaporation required (kg/h)"] = float(m_water_evap_h)

    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat evaporation (kJ/h)"] = float(thermal["q_evap_kj_h"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    # 5) OPEX – energy only
    row = attach_opex_to_row(
        row,
        machine=Eq.evaporator,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # 6) CAPEX columns for standardized economics reporting
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