from __future__ import annotations

from collections import defaultdict
from typing import Any
import math
import General_Parameters as gp


def _hours_per_year(ctx: dict[str, Any]) -> float:
    return float(ctx.get("hours_per_year") or gp.get_working_hours_per_year() or 0.0)


def _safe(v: Any) -> float:
    try:
        x = float(v or 0.0)
        if math.isnan(x) or math.isinf(x):
            return 0.0
        return x
    except Exception:
        return 0.0


def _gwp_factors(ctx: dict[str, Any]) -> dict[str, float]:
    # from General_Parameters.apply_region(...)
    return dict(ctx.get("gwp_factors", {}) or {})


def _electricity_gwp_factor(ctx: dict[str, Any]) -> float:
    """Electricity burden factor [kg CO2-eq/kWh] for the active region."""
    factor = _safe(_gwp_factors(ctx).get("Electricity", 0.0))
    if factor > 0.0:
        return factor
    # Hub regions (e.g. CN) may have cost data but no grid factor filled in yet.
    for region in ("EU", "DE", "US"):
        try:
            alt = _safe(gp.get_region_gwp(region).get("Electricity", 0.0))
        except Exception:
            alt = 0.0
        if alt > 0.0:
            return alt
    return 0.0


def _step_name(step_row: dict[str, Any]) -> str:
    return str(step_row.get("Step", "") or "")


def _dict_from_row(step_row: dict[str, Any], key: str) -> dict[str, float]:
    raw = step_row.get(key, {}) or {}
    if isinstance(raw, dict):
        return {str(k): _safe(v) for k, v in raw.items()}
    return {}


def build_material_emission_lines_for_step(
    step_row: dict[str, Any],
    ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    gwp = _gwp_factors(ctx)
    h_y = _hours_per_year(ctx)
    step_name = _step_name(step_row)

    chem_use = _dict_from_row(step_row, "chem_use_kg_h")
    lines: list[dict[str, Any]] = []

    for item, qty_kg_h in chem_use.items():
        if qty_kg_h <= 0.0:
            continue
        qty_kg_y = qty_kg_h * h_y
        ef_kgco2e_per_kg = _safe(gwp.get(item, 0.0))
        emission_kgco2e_y = qty_kg_y * ef_kgco2e_per_kg
        lines.append(
            {
                "step_name": step_name,
                "item": item,
                "qty_kg_h": qty_kg_h,
                "qty_kg_y": qty_kg_y,
                "ef_kgco2e_per_kg": ef_kgco2e_per_kg,
                "emission_kgco2e_per_y": emission_kgco2e_y,
            }
        )

    return lines


def compute_step_direct_emissions(step_row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    gwp = _gwp_factors(ctx)
    h_y = _hours_per_year(ctx)
    step_name = _step_name(step_row)

    material_lines = build_material_emission_lines_for_step(step_row, ctx)
    emission_materials_kgco2e_per_y = sum(_safe(x["emission_kgco2e_per_y"]) for x in material_lines)

    e_kwh_h = _safe(step_row.get("E_kWh_h", 0.0))
    water_kg_h = _safe(step_row.get("m_water_kg_h", 0.0))

    e_kwh_y = e_kwh_h * h_y
    water_kg_y = water_kg_h * h_y

    emission_energy_kgco2e_per_y = e_kwh_y * _electricity_gwp_factor(ctx)
    emission_water_kgco2e_per_y = water_kg_y * _safe(gwp.get("Water", 0.0))

    emission_direct_total_kgco2e_per_y = (
        emission_materials_kgco2e_per_y
        + emission_energy_kgco2e_per_y
        + emission_water_kgco2e_per_y
    )

    return {
        "step_name": step_name,
        "material_lines": material_lines,
        "emission_materials_kgco2e_per_y": emission_materials_kgco2e_per_y,
        "emission_energy_kgco2e_per_y": emission_energy_kgco2e_per_y,
        "emission_water_kgco2e_per_y": emission_water_kgco2e_per_y,
        "emission_direct_total_kgco2e_per_y": emission_direct_total_kgco2e_per_y,
    }


def compute_all_steps_direct_emissions(
    step_rows: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    all_material_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for row in step_rows:
        step_res = compute_step_direct_emissions(row, ctx)
        all_material_lines.extend(step_res.pop("material_lines"))
        step_totals.append(step_res)

    direct_emissions_total_kgco2e_per_y = sum(
        _safe(s["emission_direct_total_kgco2e_per_y"]) for s in step_totals
    )

    grouped_emissions = defaultdict(float)
    grouped_qty_h = defaultdict(float)
    grouped_qty_y = defaultdict(float)

    for ln in all_material_lines:
        k = (ln["step_name"], ln["item"])
        grouped_emissions[k] += _safe(ln["emission_kgco2e_per_y"])
        grouped_qty_h[k] += _safe(ln["qty_kg_h"])
        grouped_qty_y[k] += _safe(ln["qty_kg_y"])

    material_emission_by_step_item = [
        {
            "step_name": k[0],
            "item": k[1],
            "qty_kg_h": grouped_qty_h[k],
            "qty_kg_y": grouped_qty_y[k],
            "emission_kgco2e_per_y": v,
        }
        for k, v in grouped_emissions.items()
    ]

    return {
        "material_lines": all_material_lines,
        "material_emission_by_step_item": material_emission_by_step_item,
        "step_totals": step_totals,
        "direct_emissions_total_kgco2e_per_y": direct_emissions_total_kgco2e_per_y,
    }