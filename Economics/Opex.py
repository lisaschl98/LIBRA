from __future__ import annotations

from collections import defaultdict
from typing import Any
import math
import General_Parameters as gp


def _hours_per_year(ctx: dict[str, Any]) -> float:
    return float(ctx.get("hours_per_year") or gp.get_working_hours_per_year() or 0.0)


def _prices(ctx: dict[str, Any]) -> dict[str, float]:
    return dict(ctx.get("prices", {}) or {})


def _safe(v: Any) -> float:
    try:
        x = float(v or 0.0)
        if math.isnan(x) or math.isinf(x):
            return 0.0
        return x
    except Exception:
        return 0.0


def _step_name(step_row: dict[str, Any]) -> str:
    return str(step_row.get("Step", "") or "")


def _dict_from_row(step_row: dict[str, Any], key: str) -> dict[str, float]:
    raw = step_row.get(key, {}) or {}
    if isinstance(raw, dict):
        return {str(k): _safe(v) for k, v in raw.items()}
    return {}


def build_material_lines_for_step(step_row: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    pr = _prices(ctx)
    h_y = _hours_per_year(ctx)
    step_name = _step_name(step_row)

    chem_use = _dict_from_row(step_row, "chem_use_kg_h")
    lines: list[dict[str, Any]] = []

    for item, qty_kg_h in chem_use.items():
        if qty_kg_h <= 0.0:
            continue
        qty_kg_y = qty_kg_h * h_y
        price_per_kg = _safe(pr.get(item, 0.0))
        cost_per_y = qty_kg_y * price_per_kg
        lines.append(
            {
                "step_name": step_name,
                "item": item,
                "qty_kg_h": qty_kg_h,
                "qty_kg_y": qty_kg_y,
                "price_per_kg": price_per_kg,
                "cost_per_y": cost_per_y,
            }
        )

    return lines


def _align_material_lines_to_step_materials_cost(
    material_lines: list[dict[str, Any]],
    materials_cost_y: float,
) -> list[dict[str, Any]]:
    """
    When a step sets Materials ($/y) from component prices but chem_use uses other
    reporting keys differ from component-priced materials_cost_y, scale line costs to match.
    Quantities (kg/y) are unchanged so Annual process Inputs stays aligned with massflow.
    """
    target = _safe(materials_cost_y)
    if target <= 0.0 or not material_lines:
        return material_lines

    subtotal = sum(_safe(ln.get("cost_per_y", 0.0)) for ln in material_lines)
    if subtotal <= 0.0:
        qty_total = sum(_safe(ln.get("qty_kg_y", 0.0)) for ln in material_lines)
        if qty_total <= 0.0:
            return material_lines
        for ln in material_lines:
            share = _safe(ln.get("qty_kg_y", 0.0)) / qty_total
            ln["cost_per_y"] = target * share
            ln["price_per_kg"] = (
                ln["cost_per_y"] / _safe(ln.get("qty_kg_y", 0.0))
                if _safe(ln.get("qty_kg_y", 0.0)) > 0.0
                else 0.0
            )
        return material_lines

    if abs(subtotal - target) / max(target, 1e-9) <= 0.005:
        return material_lines

    scale = target / subtotal
    for ln in material_lines:
        ln["cost_per_y"] = _safe(ln.get("cost_per_y", 0.0)) * scale
        qty_y = _safe(ln.get("qty_kg_y", 0.0))
        ln["price_per_kg"] = (ln["cost_per_y"] / qty_y) if qty_y > 0.0 else 0.0
    return material_lines


def compute_step_direct_cost(step_row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    pr = _prices(ctx)
    h_y = _hours_per_year(ctx)
    step_name = _step_name(step_row)

    material_lines = build_material_lines_for_step(step_row, ctx)
    material_lines = _align_material_lines_to_step_materials_cost(
        material_lines,
        _safe(step_row.get("Materials ($/y)", 0.0)),
    )
    cost_materials_per_y = sum(_safe(x["cost_per_y"]) for x in material_lines)

    e_kwh_h = _safe(step_row.get("E_kWh_h", 0.0))
    water_kg_h = _safe(step_row.get("m_water_kg_h", 0.0))
    labor_h_h = _safe(step_row.get("labor_h_h", 0.0))

    e_kwh_y = e_kwh_h * h_y
    water_kg_y = water_kg_h * h_y
    labor_h_y = labor_h_h * h_y

    cost_energy_per_y = e_kwh_y * _safe(pr.get("Electricity", 0.0))
    cost_water_per_y = water_kg_y * _safe(pr.get("Water", 0.0))
    cost_labor_per_y = labor_h_y * _safe(pr.get("Labor", 0.0))

    # from machine logic / step reporting
    maintenance_per_y = _safe(step_row.get("maintenance_per_y", 0.0))
    depreciation_per_y = _safe(step_row.get("depreciation_per_y", 0.0))
    supplies_per_y = _safe(step_row.get("supplies_per_y", 0.0))

    cost_direct_total_per_y = (
        cost_materials_per_y + cost_energy_per_y + cost_water_per_y + cost_labor_per_y
    )

    return {
        "step_name": step_name,
        "material_lines": material_lines,
        "cost_materials_per_y": cost_materials_per_y,
        "cost_energy_per_y": cost_energy_per_y,
        "cost_water_per_y": cost_water_per_y,
        "cost_labor_per_y": cost_labor_per_y,
        "cost_direct_total_per_y": cost_direct_total_per_y,
        "maintenance_per_y": maintenance_per_y,
        "depreciation_per_y": depreciation_per_y,
        "supplies_per_y": supplies_per_y,
        # Pass through CAPEX fields for overhead/CAPEX block:
        "CAPEX equip ($)": _safe(step_row.get("CAPEX equip ($)", 0.0)),
        "CAPEX install ($)": _safe(step_row.get("CAPEX install ($)", 0.0)),
        "CAPEX instr ($)": _safe(step_row.get("CAPEX instr ($)", 0.0)),
        "CAPEX piping ($)": _safe(step_row.get("CAPEX piping ($)", 0.0)),
        "CAPEX electrical ($)": _safe(step_row.get("CAPEX electrical ($)", 0.0)),
        "CAPEX building ($)": _safe(step_row.get("CAPEX building ($)", 0.0)),
    }


def compute_all_steps_direct_opex(step_rows: list[dict[str, Any]], ctx: dict[str, Any]) -> dict[str, Any]:
    all_material_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for row in step_rows:
        step_res = compute_step_direct_cost(row, ctx)
        all_material_lines.extend(step_res.pop("material_lines"))
        step_totals.append(step_res)

    direct_opex_total_per_y = sum(_safe(s["cost_direct_total_per_y"]) for s in step_totals)

    grouped_cost = defaultdict(float)
    grouped_qty_h = defaultdict(float)
    grouped_qty_y = defaultdict(float)

    for ln in all_material_lines:
        k = (ln["step_name"], ln["item"])
        grouped_cost[k] += _safe(ln["cost_per_y"])
        grouped_qty_h[k] += _safe(ln["qty_kg_h"])
        grouped_qty_y[k] += _safe(ln["qty_kg_y"])

    material_cost_by_step_item = [
        {
            "step_name": k[0],
            "item": k[1],
            "qty_kg_h": grouped_qty_h[k],
            "qty_kg_y": grouped_qty_y[k],
            "cost_per_y": v,
        }
        for k, v in grouped_cost.items()
    ]

    return {
        "material_lines": all_material_lines,
        "material_cost_by_step_item": material_cost_by_step_item,
        "step_totals": step_totals,
        "direct_opex_total_per_y": direct_opex_total_per_y,
    }