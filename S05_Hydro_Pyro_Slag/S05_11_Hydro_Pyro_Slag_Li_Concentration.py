from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import CONCENTRATION_RULES, concentration_evaporation_kg_h, reconcile_comp_abs_to_mass
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


def _tag_evaporated_water(
    comp_abs: dict,
    *,
    total_mass_kg_h: float,
    evap_key: str,
    water_evap_kg_h: float,
) -> tuple[dict, float, float]:
    """Move evaporated water from existing water/untracked mass to the EFF evaporation key."""
    comp = {str(k): float(v) for k, v in (comp_abs or {}).items() if abs(float(v or 0.0)) > 1e-12}
    total_mass = max(0.0, float(total_mass_kg_h))
    target_evap = max(0.0, float(water_evap_kg_h))

    current_sum = float(sum(comp.values()))
    if total_mass > current_sum + 1e-9:
        comp["__untracked__"] = comp.get("__untracked__", 0.0) + (total_mass - current_sum)

    remaining = target_evap
    water_keys = [
        "__untracked__",
        "process:H2O_leaching",
        "process:H2O_pre_wetting",
        "process:H2O_oxalic_solution",
        "process:H2O_oxalate_wash",
        "process:H2O_wash",
        "process:H2O_nmc_wash",
        "process:H2O",
        "H2O",
    ]
    for key in water_keys:
        if remaining <= 1e-12:
            break
        available = max(0.0, float(comp.get(key, 0.0) or 0.0))
        take = min(available, remaining)
        if take > 0.0:
            comp[key] = available - take
            remaining -= take

    for key in list(comp.keys()):
        if remaining <= 1e-12:
            break
        if key in water_keys or not key.endswith(":H2O"):
            continue
        available = max(0.0, float(comp.get(key, 0.0) or 0.0))
        take = min(available, remaining)
        if take > 0.0:
            comp[key] = available - take
            remaining -= take

    removed_from_water = target_evap - max(0.0, remaining)
    if target_evap > 1e-12:
        comp[evap_key] = float(comp.get(evap_key, 0.0) or 0.0) + target_evap

    if remaining > 1e-12:
        preserve_keys = [
            evap_key,
            *[
                k
                for k in comp
                if k.endswith(":Li")
                or k == "Li"
                or k.endswith(":P")
                or k == "P"
            ],
        ]
        comp = reconcile_comp_abs_to_mass(comp, total_mass, preserve_keys=preserve_keys)

    comp = {k: v for k, v in comp.items() if abs(float(v)) > 1e-12}
    shortfall = max(0.0, target_evap - removed_from_water)
    return comp, target_evap, shortfall


def run_hydro_li_concentration(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_11: Hydro Pyro - Li Concentration.

    Concentrates Li-bearing lye by evaporating water prior to Li precipitation.
    Evaporated water is represented as process component `process:H2O_evap`,
    which can be routed via EFF to the side stream `wastewater`.

    Streams:
    - Input:  'lye after Mn extraction'
    - Output (forward): 'lye concentrated'
    - Output (side):    'wastewater'
    """
    p = params or {}
    step = "Hydro Pyro – Li Concentration"

    # Centralized concentration rules
    rule = CONCENTRATION_RULES["SLAG_LI"]

    c_target_g_l = float(p.get("c_target_g_l", rule["c_target_g_l_default"]))
    c_min_g_l = float(p.get("c_min_g_l", rule["c_min_g_l_default"]))
    rho_sol = float(p.get("rho_solution_kg_m3", rule["rho_solution_kg_m3_default"]))
    design_load = float(p.get("design_load", 0.85))

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})
    m_in_h = float(flow_in.mass_kg_per_h)

    # 0) Central stoichiometry/helper calculation
    res = concentration_evaporation_kg_h(
        comp_abs=comp_abs,
        m_in_kg_h=float(flow_in.mass_kg_per_h),
        solute_suffixes=rule["solute_suffixes"],
        c_target_g_l=c_target_g_l,
        c_min_g_l=c_min_g_l,
        rho_solution_kg_m3=rho_sol,
    )

    m_li_h = float(res["m_solute_kg_h"])
    c_current_g_l = float(res["c_current_g_l"])
    c_new_g_l = float(res["c_new_g_l"])
    m_water_evap_h = float(res["m_water_evap_kg_h"])

    flow_aug = flow_in
    m_water_evap_actual_h = 0.0
    m_water_evap_shortfall_h = 0.0
    if m_water_evap_h > 0.0:
        evap_key = str(rule["evap_component_key"])
        comp_abs, m_water_evap_actual_h, m_water_evap_shortfall_h = _tag_evaporated_water(
            comp_abs,
            total_mass_kg_h=m_in_h,
            evap_key=evap_key,
            water_evap_kg_h=m_water_evap_h,
        )
        if m_water_evap_actual_h > 0.0 and m_li_h > 0.0 and rho_sol > 0.0:
            v_new_m3_h = max((m_in_h - m_water_evap_actual_h) / rho_sol, 0.0)
            c_new_g_l = (m_li_h / v_new_m3_h) if v_new_m3_h > 0.0 else c_new_g_l
        flow_aug = MassFlow(
            m_in_h,
            meta={**meta, "comp_abs": comp_abs},
        )

    # 1) Mass balance / partition
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

    # 2) Sizing / CAPEX (based on wet inlet throughput)
    sizing = size_machine_for_mass(
        step,
        Eq.evaporator,
        flow_aug,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.evaporator.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    m_water_removed_h = water_removed_for_thermal_kg_h(
        eff_wastewater_kg_h=wastewater_h,
        tagged_removed_kg_h=m_water_evap_actual_h,
        stoich_required_kg_h=m_water_evap_h,
    )
    thermal = concentration_water_evaporation_kwh_h(m_water_removed_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])

    # 4) Reporting row
    row = make_row(step, flow_aug, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lye concentrated (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Wastewater (kg/h)"] = float(wastewater_h)
    row["Li in feed (kg/h)"] = float(m_li_h)
    row["Li concentration in (g/L)"] = float(c_current_g_l)
    row["Li concentration (g/L)"] = float(c_new_g_l)
    row["Water evaporated (kg/h)"] = float(m_water_removed_h)
    row["Water evaporation required (kg/h)"] = float(m_water_evap_h)
    row["Water evaporation shortfall (kg/h)"] = float(m_water_evap_shortfall_h)

    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat evaporation (kJ/h)"] = float(thermal["q_evap_kj_h"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    # 5) OPEX
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

    # 6) CAPEX columns for standardized economics reporting and extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))

    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras