from __future__ import annotations

from collections import defaultdict
from typing import Any
import math
import General_Parameters as gp
from step_utils import flatten_outputs_kg_h, resolve_output_item_key


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


def _prices(ctx: dict[str, Any]) -> dict[str, float]:
    return dict(ctx.get("prices", {}) or {})


def _price_meta(ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(ctx.get("price_meta", {}) or {})


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def get_output_item_classes(ctx: dict[str, Any]) -> dict[str, set[str]]:
    """
    Read Excel meta from ctx['price_meta'] and classify output items.
    Expects per item among others:
      - role
      - economic type (cost/revenue)
      - category (product/residue)
    """
    meta = _price_meta(ctx)

    revenue_items: set[str] = set()
    cost_items: set[str] = set()
    product_items: set[str] = set()
    residue_items: set[str] = set()

    for item, m in meta.items():
        mm = m or {}
        role = _norm(mm.get("role"))
        et = _norm(mm.get("economic type"))
        cat = _norm(mm.get("category"))

        # Evaluate output items economically only
        if role != "output":
            continue

        if et == "revenue":
            revenue_items.add(str(item))
        elif et == "cost":
            cost_items.add(str(item))

        if cat == "product":
            product_items.add(str(item))
        elif cat == "residue":
            residue_items.add(str(item))

    return {
        "revenue_items": revenue_items,
        "cost_items": cost_items,
        "product_items": product_items,
        "residue_items": residue_items,
    }


def _step_name(step_row: dict[str, Any]) -> str:
    return str(step_row.get("Step", "") or "")


def _econ_outputs(step_row: dict[str, Any]) -> dict[str, float]:
    """
    Step contract for outputs:
      row['outputs_kg_h'] = {"ItemName from Excel": kg_h, ...} or [{...}]
    """
    return flatten_outputs_kg_h(step_row.get("outputs_kg_h", {}) or {})


def build_output_value_lines_for_step(step_row: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    classes = get_output_item_classes(ctx)
    revenue_items = classes["revenue_items"]
    cost_items = classes["cost_items"]
    product_items = classes["product_items"]
    residue_items = classes["residue_items"]

    step = _step_name(step_row)
    h_y = _hours_per_year(ctx)
    pr = _prices(ctx)
    outputs = _econ_outputs(step_row)

    lines: list[dict[str, Any]] = []
    for item, qty_kg_h in outputs.items():
        item_key = resolve_output_item_key(item)
        qty_kg_y = qty_kg_h * h_y

        if item_key in revenue_items:
            economic_type = "revenue"
            price_per_kg = _safe(pr.get(item_key, 0.0))
            amount_per_y = qty_kg_y * price_per_kg
            category = "product" if item_key in product_items else (
                "residue" if item_key in residue_items else ""
            )
        elif item_key in cost_items:
            economic_type = "cost"
            price_per_kg = _safe(pr.get(item_key, 0.0))
            amount_per_y = qty_kg_y * price_per_kg
            category = "product" if item_key in product_items else (
                "residue" if item_key in residue_items else ""
            )
        else:
            # Report quantity for Annual process Outputs / massflow alignment (no Excel price yet).
            economic_type = "unpriced"
            price_per_kg = 0.0
            amount_per_y = 0.0
            category = "product"

        lines.append(
            {
                "step_name": step,
                "item": item_key,
                "economic_type": economic_type,
                "category": category,
                "qty_kg_h": qty_kg_h,
                "qty_kg_y": qty_kg_y,
                "price_per_kg": price_per_kg,
                "amount_per_y": amount_per_y,
            }
        )

    return lines


def compute_step_output_economics(step_row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    lines = build_output_value_lines_for_step(step_row, ctx)

    revenue_per_y = sum(_safe(x["amount_per_y"]) for x in lines if x["economic_type"] == "revenue")
    output_cost_per_y = sum(_safe(x["amount_per_y"]) for x in lines if x["economic_type"] == "cost")
    net_output_value_per_y = revenue_per_y - output_cost_per_y

    return {
        "step_name": _step_name(step_row),
        "output_lines": lines,
        "revenue_per_y": revenue_per_y,
        "output_cost_per_y": output_cost_per_y,
        "net_output_value_per_y": net_output_value_per_y,
    }


def compute_all_steps_output_economics(step_rows: list[dict[str, Any]], ctx: dict[str, Any]) -> dict[str, Any]:
    all_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for r in step_rows:
        s = compute_step_output_economics(r, ctx)
        all_lines.extend(s.pop("output_lines"))
        step_totals.append(s)

    revenue_total_per_y = sum(_safe(x["revenue_per_y"]) for x in step_totals)
    output_cost_total_per_y = sum(_safe(x["output_cost_per_y"]) for x in step_totals)
    net_output_value_total_per_y = revenue_total_per_y - output_cost_total_per_y

    by_step_item = defaultdict(float)
    for ln in all_lines:
        by_step_item[(ln["step_name"], ln["item"], ln["economic_type"], ln["category"])] += _safe(ln["amount_per_y"])

    by_step_item_rows = [
        {
            "step_name": k[0],
            "item": k[1],
            "economic_type": k[2],
            "category": k[3],
            "amount_per_y": v,
        }
        for k, v in by_step_item.items()
    ]

    return {
        "output_lines": all_lines,
        "by_step_item": by_step_item_rows,
        "step_totals": step_totals,
        "revenue_total_per_y": revenue_total_per_y,
        "output_cost_total_per_y": output_cost_total_per_y,
        "net_output_value_total_per_y": net_output_value_total_per_y,
    }