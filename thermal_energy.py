"""
Thermal energy helpers for LIBRA process steps.

Units (explicit):
  - mass:        kg/h
  - enthalpy:    kJ/kg
  - heat rate:   kJ/h
  - power/energy rate: kWh/h  (1 kWh = 3600 kJ)
"""

from __future__ import annotations

# ---------- defaults (overridable via params / Excel later) ----------
THERMAL_DEFAULTS = {
    "dh_vap_water_kj_per_kg": 2257.0,
    "eta_evaporation": 0.8,
}

DIGESTION_THERMAL_DEFAULTS = {
    "cp_lib_kj_per_kgk": 1.0,
    "cp_h2so4_kj_per_kgk": 1.41,
    "t_in_c": 20.0,
    "t_out_c": 140.0,
    "eta_heating": 0.8,
}

SMELTING_THERMAL_DEFAULTS = {
    "cp_lib_kj_per_kgk": 1.0,
    "cp_limestone_kj_per_kgk": 0.8,
    "cp_sand_kj_per_kgk": 0.7,
    "t_in_c": 20.0,
    "t_out_c": 1450.0,
    "smelter_efficiency": 0.6,
    "dh_calcination_kj_per_kg": 1780.0,
}

ROASTING_THERMAL_DEFAULTS = {
    "cp_fepo4_c_kj_per_kgk": 1.0,
    "t_in_c": 20.0,
    "t_out_c": 500.0,
    "roaster_efficiency": 0.6,
}

MECH_DRYING_THERMAL_DEFAULTS = {
    "t_in_c": 20.0,
    "t_process_c": 105.0,
    "dh_vap_electrolyte_kj_per_kg": 424.0,
    "dryer_efficiency": 0.8,
}


def sensible_heat_kj_h(
    m_kg_h: float,
    cp_kj_per_kgk: float,
    delta_t_k: float,
    *,
    eta: float | None = None,
) -> float:
    """
    Sensible heating power [kJ/h].

    Q = m * cp * delta_T / eta
    """
    m = max(0.0, float(m_kg_h))
    if m <= 0.0:
        return 0.0
    cp = float(cp_kj_per_kgk)
    dT = float(delta_t_k)
    eta_eff = float(
        eta if eta is not None else THERMAL_DEFAULTS.get("eta_evaporation", 1.0)
    )
    eta_eff = max(eta_eff, 1e-9)
    return m * cp * dT / eta_eff


def water_evaporation_heat_kj_h(
    m_water_kg_h: float,
    *,
    dh_vap_kj_per_kg: float | None = None,
    eta: float | None = None,
) -> float:
    """
    Latent heat for water evaporation [kJ/h].

    Q = m_water * dh_vap / eta
    """
    m = max(0.0, float(m_water_kg_h))
    if m <= 0.0:
        return 0.0
    dh = float(
        dh_vap_kj_per_kg
        if dh_vap_kj_per_kg is not None
        else THERMAL_DEFAULTS["dh_vap_water_kj_per_kg"]
    )
    eta_eff = float(
        eta if eta is not None else THERMAL_DEFAULTS["eta_evaporation"]
    )
    eta_eff = max(eta_eff, 1e-9)
    return m * dh / eta_eff


def kj_h_to_kwh_h(q_kj_h: float) -> float:
    """Convert heat rate [kJ/h] to equivalent energy rate [kWh/h]."""
    return max(0.0, float(q_kj_h)) / 3600.0


def water_removed_for_thermal_kg_h(
    *,
    eff_wastewater_kg_h: float = 0.0,
    tagged_removed_kg_h: float = 0.0,
    stoich_required_kg_h: float = 0.0,
) -> float:
    """
    Water mass basis for evaporation thermal energy [kg/h].

    Priority: EFF wastewater -> tagged removal in comp_abs -> stoichiometric demand.
    """
    ww = max(0.0, float(eff_wastewater_kg_h))
    if ww > 1e-12:
        return ww
    tagged = max(0.0, float(tagged_removed_kg_h))
    if tagged > 1e-12:
        return tagged
    return max(0.0, float(stoich_required_kg_h))


def hydrate_water_in_crystal_kg_h(
    m_crystal_kg_h: float,
    molar_mass_crystal_g_per_mol: float,
    n_hydrate_waters: int,
) -> float:
    """Hydrate water mass in crystal product [kg/h] (informational)."""
    m = max(0.0, float(m_crystal_kg_h))
    mm = float(molar_mass_crystal_g_per_mol)
    n = int(n_hydrate_waters)
    if m <= 0.0 or mm <= 0.0 or n <= 0:
        return 0.0
    m_h2o_per_mol = n * 18.015
    return m * m_h2o_per_mol / mm


def drying_water_evaporation_kwh_h(
    m_water_evaporated_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """
    Standard drying-step thermal demand from evaporated water [kg/h].

    Returns
    -------
    dict with keys:
      - m_water_evap_kg_h
      - q_evap_kj_h
      - thermal_kwh_h
    """
    p = params or {}
    m_evap = max(0.0, float(m_water_evaporated_kg_h))
    q_kj_h = water_evaporation_heat_kj_h(
        m_evap,
        dh_vap_kj_per_kg=p.get("dh_vap_water_kj_per_kg"),
        eta=p.get("eta_evaporation"),
    )
    eta_eff = float(
        p.get("eta_evaporation", THERMAL_DEFAULTS["eta_evaporation"])
    )
    return {
        "m_water_evap_kg_h": m_evap,
        "q_evap_kj_h": q_kj_h,
        "thermal_kwh_h": kj_h_to_kwh_h(q_kj_h),
        "eta_evaporation": eta_eff,
    }


def crystallization_water_evaporation_kwh_h(
    m_water_evaporated_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """
    Crystallization thermal demand from mother-liquor water removal [kWh/h].

    Same evaporation model as drying/concentration (eta = 0.8 by default).
    """
    return drying_water_evaporation_kwh_h(m_water_evaporated_kg_h, params=params)


def digestion_heating_kwh_h(
    m_lib_kg_h: float,
    m_h2so4_95_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """
    Digestion sensible heating [kWh/h].

    P = (m_LIB * cp_LIB * dT + m_H2SO4 * cp_H2SO4 * dT) / (3600 * eta)

    Defaults: cp_LIB = 1.0, cp_H2SO4 = 1.41 kJ/(kg·K), 20 °C -> 140 °C, eta = 0.8.
    """
    p = params or {}
    defaults = DIGESTION_THERMAL_DEFAULTS
    t_in = float(p.get("t_in_c", defaults["t_in_c"]))
    t_out = float(p.get("t_out_c", defaults["t_out_c"]))
    delta_t_k = t_out - t_in
    cp_lib = float(p.get("cp_lib_kj_per_kgk", defaults["cp_lib_kj_per_kgk"]))
    cp_acid = float(p.get("cp_h2so4_kj_per_kgk", defaults["cp_h2so4_kj_per_kgk"]))
    eta = float(p.get("eta_heating", defaults["eta_heating"]))
    m_lib = max(0.0, float(m_lib_kg_h))
    m_acid = max(0.0, float(m_h2so4_95_kg_h))
    q_lib_kj_h = m_lib * cp_lib * delta_t_k
    q_acid_kj_h = m_acid * cp_acid * delta_t_k
    eta_eff = max(eta, 1e-9)
    q_kj_h = (q_lib_kj_h + q_acid_kj_h) / eta_eff
    return {
        "m_lib_kg_h": m_lib,
        "m_h2so4_95_kg_h": m_acid,
        "delta_t_k": delta_t_k,
        "q_lib_sensible_kj_h": q_lib_kj_h,
        "q_acid_sensible_kj_h": q_acid_kj_h,
        "q_sensible_kj_h": q_kj_h,
        "thermal_kwh_h": kj_h_to_kwh_h(q_kj_h),
        "eta_heating": eta_eff,
    }


def digestion_h2so4_heating_kwh_h(
    m_h2so4_95_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """Backward-compatible wrapper: acid-only digestion heating."""
    return digestion_heating_kwh_h(0.0, m_h2so4_95_kg_h, params=params)


def pyro_smelting_heat_kwh_h(
    m_modules_kg_h: float,
    m_limestone_kg_h: float,
    m_sand_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """
    Pyro smelting thermal demand [kWh/h].

    P = (m_LIB*cp_LIB + m_limestone*cp_limestone + m_sand*cp_sand) * dT
        + m_limestone * dh_calcination) / (3600 * eta)

    Defaults: cp_LIB=1.0, cp_limestone=0.8, cp_sand=0.7 kJ/(kg·K),
    20 °C -> 1450 °C, dh_calc=1780 kJ/kg, eta=0.6.
    """
    p = params or {}
    defaults = SMELTING_THERMAL_DEFAULTS
    cp_lib = float(
        p.get(
            "cp_lib_kj_per_kgk",
            p.get("cp_kj_per_kgk", defaults["cp_lib_kj_per_kgk"]),
        )
    )
    cp_lime = float(p.get("cp_limestone_kj_per_kgk", defaults["cp_limestone_kj_per_kgk"]))
    cp_sand = float(p.get("cp_sand_kj_per_kgk", defaults["cp_sand_kj_per_kgk"]))
    t_in = float(p.get("t_in_c", defaults["t_in_c"]))
    t_out = float(p.get("t_out_c", defaults["t_out_c"]))
    delta_t_k = float(p.get("delta_t_k", t_out - t_in))
    eta = float(
        p.get("smelter_efficiency", p.get("eta", defaults["smelter_efficiency"]))
    )
    dh_calc = float(
        p.get("dh_calcination_kj_per_kg", defaults["dh_calcination_kj_per_kg"])
    )

    m_mod = max(0.0, float(m_modules_kg_h))
    m_lime = max(0.0, float(m_limestone_kg_h))
    m_sand = max(0.0, float(m_sand_kg_h))
    m_heat = m_mod + m_lime + m_sand

    q_lib_kj_h = m_mod * cp_lib * delta_t_k
    q_lime_sensible_kj_h = m_lime * cp_lime * delta_t_k
    q_sand_kj_h = m_sand * cp_sand * delta_t_k
    q_sensible_kj_h = q_lib_kj_h + q_lime_sensible_kj_h + q_sand_kj_h
    q_calcination_kj_h = m_lime * dh_calc
    eta_eff = max(eta, 1e-9)
    q_kj_h = (q_sensible_kj_h + q_calcination_kj_h) / eta_eff

    return {
        "m_lib_kg_h": m_mod,
        "m_limestone_kg_h": m_lime,
        "m_sand_kg_h": m_sand,
        "m_heated_kg_h": m_heat,
        "delta_t_k": delta_t_k,
        "q_lib_sensible_kj_h": q_lib_kj_h,
        "q_limestone_sensible_kj_h": q_lime_sensible_kj_h,
        "q_sand_sensible_kj_h": q_sand_kj_h,
        "q_sensible_kj_h": q_sensible_kj_h,
        "q_calcination_kj_h": q_calcination_kj_h,
        "q_total_kj_h": q_kj_h,
        "thermal_kwh_h": kj_h_to_kwh_h(q_kj_h),
        "smelter_efficiency": eta_eff,
    }


def roasting_sensible_heating_kwh_h(
    m_fepo4_c_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """
    Roasting sensible heating of FePO4-C [kWh/h].

    P = m_FePO4-C * cp_FePO4-C * (T_out - T_in) / (3600 * eta)

    Defaults: cp = 1.0 kJ/(kg·K), 20 °C -> 500 °C (ΔT = 480 K), eta = 0.6.
    """
    p = params or {}
    defaults = ROASTING_THERMAL_DEFAULTS
    cp = float(
        p.get(
            "cp_fepo4_c_kj_per_kgk",
            p.get("cp_kj_per_kgk", defaults["cp_fepo4_c_kj_per_kgk"]),
        )
    )
    t_in = float(p.get("t_in_c", defaults["t_in_c"]))
    t_out = float(p.get("t_out_c", defaults["t_out_c"]))
    delta_t_k = float(p.get("delta_t_k", t_out - t_in))
    eta = float(
        p.get("roaster_efficiency", p.get("eta", defaults["roaster_efficiency"]))
    )
    m = max(0.0, float(m_fepo4_c_kg_h))
    eta_eff = max(eta, 1e-9)
    q_sensible_uncorrected_kj_h = m * cp * delta_t_k
    q_kj_h = q_sensible_uncorrected_kj_h / eta_eff
    return {
        "m_fepo4_c_kg_h": m,
        "m_roasted_kg_h": m,
        "delta_t_k": delta_t_k,
        "q_sensible_kj_h": q_sensible_uncorrected_kj_h,
        "q_total_kj_h": q_kj_h,
        "thermal_kwh_h": kj_h_to_kwh_h(q_kj_h),
        "roaster_efficiency": eta_eff,
    }


def mechanical_drying_thermal_kwh_h(
    m_solid_kg_h: float,
    m_electrolyte_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """
    Mechanical drying thermal demand [kWh/h].

    P = m_electrolyte * dh_vap_electrolyte / (3600 * eta)

    Defaults: dh_vap = 424 kJ/kg, 20 °C -> 105 °C (ΔT = 85 K for reporting), eta = 0.8.
    ``m_solid_kg_h`` is kept for API compatibility but not used in the heat balance.
    """
    p = params or {}
    defaults = MECH_DRYING_THERMAL_DEFAULTS
    t_in = float(p.get("t_in_c", defaults["t_in_c"]))
    t_proc = float(p.get("t_process_c", p.get("t_evap_c", defaults["t_process_c"])))
    delta_t_k = float(p.get("delta_t_k", t_proc - t_in))
    eta = float(p.get("dryer_efficiency", p.get("eta", defaults["dryer_efficiency"])))
    dh_vap = float(
        p.get("dh_vap_electrolyte_kj_per_kg", defaults["dh_vap_electrolyte_kj_per_kg"])
    )

    m_solid = max(0.0, float(m_solid_kg_h))
    m_electrolyte = max(0.0, float(m_electrolyte_kg_h))
    eta_eff = max(eta, 1e-9)
    q_evap_kj_h = m_electrolyte * dh_vap / eta_eff

    return {
        "m_solid_kg_h": m_solid,
        "m_electrolyte_kg_h": m_electrolyte,
        "delta_t_k": delta_t_k,
        "t_process_c": t_proc,
        "dh_vap_electrolyte_kj_per_kg": dh_vap,
        "q_solid_sensible_kj_h": 0.0,
        "q_electrolyte_evap_kj_h": q_evap_kj_h,
        "q_total_kj_h": q_evap_kj_h,
        "thermal_kwh_h": kj_h_to_kwh_h(q_evap_kj_h),
        "dryer_efficiency": eta_eff,
    }


def concentration_water_evaporation_kwh_h(
    m_water_evaporated_kg_h: float,
    params: dict | None = None,
) -> dict[str, float]:
    """
    Thermal demand for concentration steps [kWh/h].

    Uses ``m_water_evap_kg_h`` from ``concentration_evaporation_kg_h`` (stoichiometry),
    not the full inlet or wastewater stream mass.
    """
    return drying_water_evaporation_kwh_h(m_water_evaporated_kg_h, params=params)
