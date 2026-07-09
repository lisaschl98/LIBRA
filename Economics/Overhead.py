from __future__ import annotations

from typing import Any
import math
import General_Parameters as gp


DEFAULTS = {
    # Capital surcharges
    "service_facilities_factor": 0.40,
    "land_factor": 0.01,
    "eng_supervision_on_I": 0.10,
    "construction_on_I": 0.10,
    "contingency_on_I": 0.05,

    # Working capital
    "working_capital_on_III": 0.10,

    # Manufacturing (A)
    "supervisory_on_oper_labor": 0.15,
    "lab_charges_on_oper_labor": 0.10,
    "supplies_on_maintenance": 0.15,

    # Fixed charges (B)
    "taxes_on_III": 0.02,
    "insurance_on_III": 0.01,
    "rent_$py": 0.0,
    "financing_$py": 0.0,
    "building_lifetime_y": 25.0,

    # Plant overhead (C)
    "plant_overhead_on_sum": 0.50,

    # General expenses (VII)
    "admin_on_sum": 0.15,
    "distribution_$py": 0.0,
    "rnd_$py": 0.0,
}


def _safe(v: Any) -> float:
    try:
        x = float(v or 0.0)
        if math.isnan(x) or math.isinf(x):
            return 0.0
        return x
    except Exception:
        return 0.0


def _sum_step_field(step_totals: list[dict[str, Any]], key: str) -> float:
    return sum(_safe(s.get(key, 0.0)) for s in step_totals)


def _sum_capex(step_totals: list[dict[str, Any]], key: str) -> float:
    return sum(_safe(s.get(key, 0.0)) for s in step_totals)


def _denom_kg_y(ctx: dict[str, Any]) -> float:
    return float(
        ctx.get("feed_mass_kg_per_year")
        or ctx.get("cell_mass_kg_per_year")
        or ctx.get("pack_mass_kg_per_year")
        or ctx.get("mass_kg_per_year")
        or (float(ctx.get("feed_kg_per_h", 0.0)) * float(ctx.get("hours_per_year", gp.get_working_hours_per_year())))
        or 1.0
    )


def aggregate_tea(
    ctx: dict[str, Any],
    step_totals: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = {**DEFAULTS, **(params or {})}

    if not step_totals:
        raise ValueError("No step_totals supplied to aggregate_tea().")

    denom = _denom_kg_y(ctx)

    # ------- CAPEX I/II/III/IV/V -------
    IA1 = _sum_capex(step_totals, "CAPEX equip ($)")
    IA2 = _sum_capex(step_totals, "CAPEX install ($)")
    IA3 = _sum_capex(step_totals, "CAPEX instr ($)")
    IA4 = _sum_capex(step_totals, "CAPEX piping ($)")
    IA5 = _sum_capex(step_totals, "CAPEX electrical ($)")
    IA = IA1 + IA2 + IA3 + IA4 + IA5

    IB = _sum_capex(step_totals, "CAPEX building ($)")
    IC = p["service_facilities_factor"] * IA1
    ID = p["land_factor"] * IA1
    I_direct = IA + IB + IC + ID

    II_A = p["eng_supervision_on_I"] * I_direct
    II_B = p["construction_on_I"] * I_direct
    II_C = p["contingency_on_I"] * I_direct
    II_indirect = II_A + II_B + II_C

    III_fixed_capital = I_direct + II_indirect
    IV_working_capital = p["working_capital_on_III"] * III_fixed_capital
    V_total_capital = III_fixed_capital + IV_working_capital

    # ------- VI.A -------
    VI_A1_raw_mat_py = _sum_step_field(step_totals, "cost_materials_per_y")
    VI_A2_utilities = (
        _sum_step_field(step_totals, "cost_energy_per_y")
        + _sum_step_field(step_totals, "cost_water_per_y")
    )
    VI_A3_oper_labor_py = _sum_step_field(step_totals, "cost_labor_per_y")
    VI_A4_supervisory_py = p["supervisory_on_oper_labor"] * VI_A3_oper_labor_py

    VI_A5_maintenance_py = _sum_step_field(step_totals, "maintenance_per_y")
    supplies_from_steps = _sum_step_field(step_totals, "supplies_per_y")
    VI_A6_supplies_py = supplies_from_steps if supplies_from_steps > 0.0 else p["supplies_on_maintenance"] * VI_A5_maintenance_py

    VI_A7_lab_py = p["lab_charges_on_oper_labor"] * VI_A3_oper_labor_py
    VI_A8_patents_py = 0.0

    VI_A_direct_products = (
        VI_A1_raw_mat_py + VI_A2_utilities + VI_A3_oper_labor_py + VI_A4_supervisory_py
        + VI_A5_maintenance_py + VI_A6_supplies_py + VI_A7_lab_py + VI_A8_patents_py
    )

    # ------- VI.B -------
    equip_depr_py = _sum_step_field(step_totals, "depreciation_per_y")
    building_life = float(p["building_lifetime_y"])
    building_depr_py = (IB / building_life) if building_life > 0 else 0.0

    VI_B1_depr_py = equip_depr_py + building_depr_py
    VI_B2_taxes_py = p["taxes_on_III"] * III_fixed_capital
    VI_B3_insurance_py = p["insurance_on_III"] * III_fixed_capital
    VI_B4_rent_py = float(p["rent_$py"])
    VI_B5_financing_py = float(p["financing_$py"])

    VI_B_fixed_charges = VI_B1_depr_py + VI_B2_taxes_py + VI_B3_insurance_py + VI_B4_rent_py + VI_B5_financing_py

    # ------- VI.C -------
    base_sum = VI_A3_oper_labor_py + VI_A4_supervisory_py + VI_A5_maintenance_py
    VI_C_overhead_py = p["plant_overhead_on_sum"] * base_sum

    VI_manufacturing_py = VI_A_direct_products + VI_B_fixed_charges + VI_C_overhead_py

    # ------- VII -------
    VII_A_admin_py = p["admin_on_sum"] * base_sum
    VII_B_distribution_py = float(p["distribution_$py"])
    VII_C_rnd_py = float(p["rnd_$py"])
    VII_general_py = VII_A_admin_py + VII_B_distribution_py + VII_C_rnd_py

    # ------- VIII -------
    VIII_total_product_cost_py = VI_manufacturing_py + VII_general_py

    def perkg(x: float) -> float:
        return x / denom if denom > 0 else 0.0

    # overhead here means "everything except direct opex"
    direct_opex_total_per_y = _sum_step_field(step_totals, "cost_direct_total_per_y")
    overhead_total_per_y = max(0.0, VIII_total_product_cost_py - direct_opex_total_per_y)

    return {
        "summary": {
            "TPC ($/y)": VIII_total_product_cost_py,
            "TPC ($/kg)": perkg(VIII_total_product_cost_py),
            "Manufacturing ($/y)": VI_manufacturing_py,
            "General ($/y)": VII_general_py,
            "Direct OPEX ($/y)": direct_opex_total_per_y,
            "Overhead total ($/y)": overhead_total_per_y,
            "Fixed capital III ($)": III_fixed_capital,
            "Total capital V ($)": V_total_capital,
        },
        "capex": {
            "I.A.1 Purchased equip ($)": IA1,
            "I.A.2 Installation ($)": IA2,
            "I.A.3 Instr & controls ($)": IA3,
            "I.A.4 Piping ($)": IA4,
            "I.A.5 Electrical ($)": IA5,
            "I.A Installed ($)": IA,
            "I.B Building ($)": IB,
            "I.C Service facilities ($)": IC,
            "I.D Land ($)": ID,
            "I Direct costs ($)": I_direct,
            "II.A Engineering ($)": II_A,
            "II.B Construction ($)": II_B,
            "II.C Contingency ($)": II_C,
            "II Indirect ($)": II_indirect,
            "III Fixed Capital ($)": III_fixed_capital,
            "IV Working Capital ($)": IV_working_capital,
            "V Total Capital ($)": V_total_capital,
        },
        "manufacturing": {
            "VI.A.1 Raw materials ($/y)": VI_A1_raw_mat_py,
            "VI.A.2 Utilities ($/y)": VI_A2_utilities,
            "VI.A.3 Oper. labor ($/y)": VI_A3_oper_labor_py,
            "VI.A.4 Supervisory ($/y)": VI_A4_supervisory_py,
            "VI.A.5 Maintenance ($/y)": VI_A5_maintenance_py,
            "VI.A.6 Supplies ($/y)": VI_A6_supplies_py,
            "VI.A.7 Laboratory ($/y)": VI_A7_lab_py,
            "VI.A.8 Patents ($/y)": VI_A8_patents_py,
            "VI.A Total ($/y)": VI_A_direct_products,
            "VI.B.1 Depreciation ($/y)": VI_B1_depr_py,
            "VI.B.2 Taxes ($/y)": VI_B2_taxes_py,
            "VI.B.3 Insurance ($/y)": VI_B3_insurance_py,
            "VI.B.4 Rent ($/y)": VI_B4_rent_py,
            "VI.B.5 Financing ($/y)": VI_B5_financing_py,
            "VI.B Total ($/y)": VI_B_fixed_charges,
            "VI.C Overhead ($/y)": VI_C_overhead_py,
            "VI Manufacturing ($/y)": VI_manufacturing_py,
            "VII General ($/y)": VII_general_py,
            "VIII Total Product Cost ($/y)": VIII_total_product_cost_py,
            "TPC ($/kg)": perkg(VIII_total_product_cost_py),
        },
    }