from __future__ import annotations

from thermal_energy import (
    DIGESTION_THERMAL_DEFAULTS,
    THERMAL_DEFAULTS,
    crystallization_water_evaporation_kwh_h,
    digestion_heating_kwh_h,
    drying_water_evaporation_kwh_h,
    hydrate_water_in_crystal_kg_h,
    water_evaporation_heat_kj_h,
)


def test_eta_evaporation_default_is_0_8() -> None:
    assert THERMAL_DEFAULTS["eta_evaporation"] == 0.8
    q = water_evaporation_heat_kj_h(1.0)
    assert abs(q - 2257.0 / 0.8) < 1e-6


def test_hydrate_water_in_crystal_co_sulfate() -> None:
    m_crystal = 2.8111  # kg CoSO4·7H2O
    m_water = hydrate_water_in_crystal_kg_h(m_crystal, 281.11, 7)
    expected = m_crystal * (7 * 18.015) / 281.11
    assert abs(m_water - expected) < 1e-9


def test_crystallization_thermal_matches_drying_model() -> None:
    m_evap = 10.0
    cryst = crystallization_water_evaporation_kwh_h(m_evap)
    dry = drying_water_evaporation_kwh_h(m_evap)
    assert cryst["thermal_kwh_h"] == dry["thermal_kwh_h"]
    assert cryst["eta_evaporation"] == 0.8


def test_roasting_fepo4_c_sensible_heating() -> None:
    from thermal_energy import ROASTING_THERMAL_DEFAULTS, roasting_sensible_heating_kwh_h

    m = 50.0
    dT = 480.0
    eta = 0.6
    th = roasting_sensible_heating_kwh_h(m)
    q_expected = m * 1.0 * dT / eta
    assert ROASTING_THERMAL_DEFAULTS["roaster_efficiency"] == 0.6
    assert th["delta_t_k"] == dT
    assert abs(th["q_total_kj_h"] - q_expected) < 1e-6
    assert abs(th["thermal_kwh_h"] - q_expected / 3600.0) < 1e-9


def test_pyro_smelting_separate_cp_and_calcination() -> None:
    from thermal_energy import SMELTING_THERMAL_DEFAULTS, pyro_smelting_heat_kwh_h

    m_lib, m_lime, m_sand = 100.0, 40.0, 20.0
    dT = 1430.0
    eta = 0.6
    th = pyro_smelting_heat_kwh_h(m_lib, m_lime, m_sand)
    q_sens = (m_lib * 1.0 + m_lime * 0.8 + m_sand * 0.7) * dT
    q_calc = m_lime * 1780.0
    q_expected = (q_sens + q_calc) / eta
    assert SMELTING_THERMAL_DEFAULTS["t_out_c"] == 1450.0
    assert th["delta_t_k"] == dT
    assert abs(th["q_sensible_kj_h"] - q_sens) < 1e-6
    assert abs(th["q_total_kj_h"] - q_expected) < 1e-6


def test_mechanical_drying_electrolyte_evaporation_only() -> None:
    from thermal_energy import MECH_DRYING_THERMAL_DEFAULTS, mechanical_drying_thermal_kwh_h

    assert MECH_DRYING_THERMAL_DEFAULTS["dryer_efficiency"] == 0.8
    assert MECH_DRYING_THERMAL_DEFAULTS["dh_vap_electrolyte_kj_per_kg"] == 424.0
    m_electrolyte = 10.0
    th = mechanical_drying_thermal_kwh_h(100.0, m_electrolyte)
    q_expected = m_electrolyte * 424.0 / 0.8
    assert th["q_solid_sensible_kj_h"] == 0.0
    assert abs(th["q_electrolyte_evap_kj_h"] - q_expected) < 1e-6
    assert abs(th["thermal_kwh_h"] - q_expected / 3600.0) < 1e-9
    assert th["delta_t_k"] == 85.0


def test_digestion_heating_lib_and_acid_with_eta_0_8() -> None:
    assert DIGESTION_THERMAL_DEFAULTS["eta_heating"] == 0.8
    m_lib, m_acid = 100.0, 50.0
    dT = 120.0
    eta = 0.8
    th = digestion_heating_kwh_h(m_lib, m_acid)
    q_expected = (m_lib * 1.0 * dT + m_acid * 1.41 * dT) / eta
    assert abs(th["q_sensible_kj_h"] - q_expected) < 1e-6
    assert abs(th["thermal_kwh_h"] - q_expected / 3600.0) < 1e-9


def test_water_removed_for_thermal_priority() -> None:
    from thermal_energy import water_removed_for_thermal_kg_h

    assert water_removed_for_thermal_kg_h(eff_wastewater_kg_h=5.0, tagged_removed_kg_h=3.0) == 5.0
    assert water_removed_for_thermal_kg_h(eff_wastewater_kg_h=0.0, tagged_removed_kg_h=3.0) == 3.0
    assert water_removed_for_thermal_kg_h(stoich_required_kg_h=7.0) == 7.0


def test_e_kwh_h_matches_water_evaporated_in_scenarios() -> None:
    """Every step with Water evaporated (kg/h) must use that mass for E_kWh_h."""
    import pandas as pd

    from main import SCENARIOS, run_scenario

    for scen in SCENARIOS:
        steps_df, _, _ = run_scenario(scen)
        if "Water evaporated (kg/h)" not in steps_df.columns:
            continue
        sub = steps_df.copy()
        sub["_m"] = pd.to_numeric(sub["Water evaporated (kg/h)"], errors="coerce").fillna(0.0)
        sub = sub[sub["_m"] > 1e-12]
        for _, row in sub.iterrows():
            m_water = float(row["_m"])
            e_row = float(pd.to_numeric(row.get("E_kWh_h", 0.0), errors="coerce") or 0.0)
            e_th = float(
                pd.to_numeric(row.get("Thermal energy (kWh/h)", 0.0), errors="coerce") or 0.0
            )
            e_calc = drying_water_evaporation_kwh_h(m_water)["thermal_kwh_h"]
            step = str(row.get("Step", ""))
            assert abs(e_row - e_calc) < 1e-6, f"{scen['name']} / {step}: E_kWh_h"
            assert abs(e_th - e_calc) < 1e-6, f"{scen['name']} / {step}: Thermal energy"
