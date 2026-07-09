from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from stoichiometry import (
    DRYING_RULES,
    drying_water_inventory_kg_h,
    drying_expected_water_to_remove_kg_h,
)
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import drying_water_evaporation_kwh_h, water_removed_for_thermal_kg_h
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)


def run_hydro_pyro_slag_li_drying(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_15: Hydro Pyro - Li Drying.

    Dries washed lithium carbonate to produce anhydrous lithium carbonate.
    Free water is tracked from upstream washing component keys and routed
    via EFF (e.g. process:H2O_wash -> wastewater drying).

    Streams:
    - Input:  'Lithium Carbonate washed'
    - Output (forward): 'Lithium Carbonate anhydrous'
    - Output (side):    'wastewater drying'
    """
    p = params or {}
    step = "Hydro Pyro – Li Drying"

    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs_in = dict(meta.get("comp_abs") or {})

    rule = DRYING_RULES["SLAG_LI2CO3"]

    m_in_h, m_h2o_h = drying_water_inventory_kg_h(
        comp_abs=comp_abs_in,
        water_keys=rule["water_keys"],
    )
    m_evap_expected_h = drying_expected_water_to_remove_kg_h(
        comp_abs=comp_abs_in,
        water_keys=rule["water_keys"],
        removal_fraction=float(
            p.get("water_removal_fraction", rule["water_removal_fraction_default"])
        ),
    )

    # Keep full wet stream for EFF routing
    flow_aug = MassFlow(
        float(flow_in.mass_kg_per_h),
        meta={"comp_abs": comp_abs_in},
    )

    # 1) Mass balance / partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="Lithium Carbonate anhydrous")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="Lithium Carbonate anhydrous")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    wastewater_flow = rfx.mf_get(outputs, "wastewater drying")
    wastewater_h = float(wastewater_flow.mass_kg_per_h)

    # Actual removed water by EFF routing (KPI proxy)
    m_evap_actual_h = wastewater_h

    # 2) Sizing / CAPEX (wet inlet basis)
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.dryer,
        flow_in,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.dryer.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_in.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    m_water_removed_h = water_removed_for_thermal_kg_h(
        eff_wastewater_kg_h=m_evap_actual_h,
        stoich_required_kg_h=m_evap_expected_h,
    )
    thermal = drying_water_evaporation_kwh_h(m_water_removed_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])

    # 4) Reporting
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Lithium Carbonate washed in (kg/h)"] = float(m_in_h)
    row["Tracked free water in (kg/h)"] = float(m_h2o_h)
    row["Lithium Carbonate anhydrous (kg/h)"] = float(out_forward.mass_kg_per_h)
    row["Wastewater drying (kg/h)"] = float(wastewater_h)
    row["Water evaporated (kg/h)"] = float(m_water_removed_h)
    row["Water evaporated expected (kg/h)"] = float(m_evap_expected_h)
    row["Water evaporated actual (kg/h)"] = float(m_evap_actual_h)

    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat evaporation (kJ/h)"] = float(thermal["q_evap_kj_h"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    # 5) OPEX - energy only
    row = attach_opex_to_row(
        row,
        machine=Eq.dryer,
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
    row["outputs_kg_h"] = [{"Lithium carbonate": float(out_forward.mass_kg_per_h)}]
    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras