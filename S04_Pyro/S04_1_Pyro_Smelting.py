"""Pyro smelting process step.

This module models pyro smelting with materials (limestone, sand,
oxygen) addded. 
"""

from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import pyro_smelting_heat_kwh_h
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
    prices,
)


MOLAR_MASS_CACO3 = 100.0865
MOLAR_MASS_CAO = 56.077
MOLAR_MASS_CO2 = 44.0095


def _augment_with_additives(flow_in: MassFlow, params: dict) -> MassFlow:
    """Augment inlet stream with smelting additives for mass-balance closure."""
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    m_in = float(flow_in.mass_kg_per_h)

    f_lime = float(params.get("limestone_frac_of_input", 0.257 / 0.61))
    f_sand = float(params.get("sand_frac_of_input", 0.133 / 0.61))

    m_lime = m_in * f_lime
    m_sand = m_in * f_sand

    # Oxygen demand based on specific Nm3 per ton feed.
    specific_o2_nm3_per_t = float(params.get("oxygen_Nm3_per_t", 422.0 / 1.2))
    density_o2_kg_per_nm3 = 1.429
    m_in_tph = m_in / 1000.0
    m_oxygen = m_in_tph * specific_o2_nm3_per_t * density_o2_kg_per_nm3

    # Split limestone (CaCO3) into reaction products for routing:
    # CaCO3 -> CaO (slag) + CO2 (offgas)
    if m_lime > 0:
        m_cao = m_lime * (MOLAR_MASS_CAO / MOLAR_MASS_CACO3)
        m_co2 = m_lime * (MOLAR_MASS_CO2 / MOLAR_MASS_CACO3)
        comp_abs["process:CaO"] = comp_abs.get("process:CaO", 0.0) + m_cao
        comp_abs["process:CO2_calcination"] = comp_abs.get("process:CO2_calcination", 0.0) + m_co2
    if m_sand > 0:
        comp_abs["process:sand"] = comp_abs.get("process:sand", 0.0) + m_sand
    if m_oxygen > 0:
        comp_abs["process:oxygen"] = comp_abs.get("process:oxygen", 0.0) + m_oxygen

    total_m = m_in + m_lime + m_sand + m_oxygen
    return MassFlow(total_m, meta={"comp_abs": comp_abs})


def run_pyro_smelting(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run pyro smelting and return outputs, reporting row, and extras."""
    p = params or {}
    step = "Pyro Smelting"

    # 0) Augment inlet with additives for process mass balance.
    flow_aug = _augment_with_additives(flow_in, p)

    # 1) Apply partition/yield and validate mass balance.
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="slag")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="slag")
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    # 2) Sizing/CAPEX on augmented inlet.
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.smelter,
        flow_aug,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.smelter.name, sizing)

    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    # 3) Smelter thermal energy (separate cp, 20->1450 °C, eta=0.6 + limestone calcination)
    h_y = hours_per_year(ctx)
    m_in_base_h = float(flow_in.mass_kg_per_h)  # modules feed into smelting [kg/h]
    f_lime = float(p.get("limestone_frac_of_input", 0.257 / 0.61))
    f_sand = float(p.get("sand_frac_of_input", 0.133 / 0.61))
    m_lime_h = m_in_base_h * f_lime
    m_sand_h = m_in_base_h * f_sand

    thermal = pyro_smelting_heat_kwh_h(
        m_in_base_h,
        m_lime_h,
        m_sand_h,
        params=p,
    )
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])
    annual_energy_kwh = e_thermal_kwh_h * h_y

    # 4) Gather output stream masses.
    m_alloy = rfx.mf_get(outputs, "alloy").mass_kg_per_h
    m_slag = rfx.mf_get(outputs, "slag").mass_kg_per_h
    m_flyash = rfx.mf_get(outputs, "flyash").mass_kg_per_h
    m_offgas = rfx.mf_get(outputs, "offgas").mass_kg_per_h

    # Forwarded process streams (alloy + slag + offgas).
    m_forward = m_alloy + m_slag + m_offgas
    m_out = float(summ["m_out_kg_h"])
    out_forward_total = MassFlow(m_forward, meta={})

    # 5) Reporting row.
    row = make_row(step, flow_in, out_forward_total)
    row["Out kg/h"] = m_out
    row["Out forward kg/h"] = m_forward
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = "ALL_PYRO_OUTPUT"
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Alloy (kg/h)"] = float(m_alloy)
    row["Slag (kg/h)"] = float(m_slag)
    row["Flyash (kg/h)"] = float(m_flyash)
    row["Offgas (kg/h)"] = float(m_offgas)
    row["Out sorted kg/h"] = float(m_flyash)  # Flyash leaves the pyro process path.

    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat sensible (kJ/h)"] = float(thermal["q_sensible_kj_h"])
    row["Thermal heat calcination (kJ/h)"] = float(thermal["q_calcination_kj_h"])
    row["Thermal heat total (kJ/h)"] = float(thermal["q_total_kj_h"])
    row["Smelting heating delta T (K)"] = float(thermal["delta_t_k"])
    row["Smelter efficiency"] = float(thermal["smelter_efficiency"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    # 5) Additive material costs from region prices.
    pr = prices(ctx)

    m_lime_y = m_lime_h * h_y
    m_sand_y = m_sand_h * h_y

    specific_o2_nm3_per_t = float(p.get("oxygen_Nm3_per_t", 422.0 / 1.2))
    density_o2_kg_per_nm3 = 1.429
    m_in_tph = m_in_base_h / 1000.0
    m_oxygen_h = m_in_tph * specific_o2_nm3_per_t * density_o2_kg_per_nm3
    m_oxygen_y = m_oxygen_h * h_y

    materials_cost_y = (
        m_lime_y * float(pr.get("Limestone", 0.0))
        + m_sand_y * float(pr.get("Sand", 0.0))
        + m_oxygen_y * float(pr.get("Oxygen", 0.0))
    )

    row["Limestone added (kg/h)"] = float(m_lime_h)
    row["Sand added (kg/h)"] = float(m_sand_h)
    row["Oxygen added (kg/h)"] = float(m_oxygen_h)

    if m_flyash > 1e-12:
        row["outputs_kg_h"] = [{"Flyash": float(m_flyash)}]

    row = attach_opex_to_row(
        row,
        machine=Eq.smelter,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=materials_cost_y,
        add_perkg=True,
    )

    # 6) CAPEX columns for standardized economics reporting.
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