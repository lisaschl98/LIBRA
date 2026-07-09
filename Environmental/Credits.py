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


def _gwp_factors(ctx: dict[str, Any]) -> dict[str, float]:
    return dict(ctx.get("gwp_factors", {}) or {})


def _gwp_meta(ctx: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return dict(ctx.get("gwp_meta", {}) or {})


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _step_name(step_row: dict[str, Any]) -> str:
    return str(step_row.get("Step", "") or "")


def _outputs(step_row: dict[str, Any]) -> dict[str, float]:
    """
    Step contract:
      row['outputs_kg_h'] = {"ItemName from Excel": kg_h, ...} or [{...}]
    """
    return flatten_outputs_kg_h(step_row.get("outputs_kg_h", {}) or {})


def get_output_item_classes(ctx: dict[str, Any]) -> dict[str, set[str]]:
    """
    Reads ctx['gwp_meta'] and classifies output items by:
      - role == output
      - environmental type == credit / burden
      - category == product / residue
    """
    meta = _gwp_meta(ctx)

    credit_items: set[str] = set()
    burden_items: set[str] = set()
    product_items: set[str] = set()
    residue_items: set[str] = set()

    for item, m in meta.items():
        mm = m or {}
        role = _norm(mm.get("role"))
        et = _norm(mm.get("environmental type"))
        cat = _norm(mm.get("category"))

        if role != "output":
            continue

        if et == "credit":
            credit_items.add(str(item))
        elif et == "burden":
            burden_items.add(str(item))

        if cat == "product":
            product_items.add(str(item))
        elif cat == "residue":
            residue_items.add(str(item))

    return {
        "credit_items": credit_items,
        "burden_items": burden_items,
        "product_items": product_items,
        "residue_items": residue_items,
    }


def build_output_emission_lines_for_step(
    step_row: dict[str, Any],
    ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    classes = get_output_item_classes(ctx)
    credit_items = classes["credit_items"]
    burden_items = classes["burden_items"]
    product_items = classes["product_items"]
    residue_items = classes["residue_items"]

    step = _step_name(step_row)
    h_y = _hours_per_year(ctx)
    gwp = _gwp_factors(ctx)
    outputs = _outputs(step_row)

    lines: list[dict[str, Any]] = []
    for item, qty_kg_h in outputs.items():
        item_key = resolve_output_item_key(item)
        qty_kg_y = qty_kg_h * h_y

        if item_key in credit_items:
            environmental_type = "credit"
            ef_kgco2e_per_kg = _safe(gwp.get(item_key, 0.0))
            amount_kgco2e_per_y = qty_kg_y * ef_kgco2e_per_kg
            category = "product" if item_key in product_items else (
                "residue" if item_key in residue_items else ""
            )
        elif item_key in burden_items:
            environmental_type = "burden"
            ef_kgco2e_per_kg = _safe(gwp.get(item_key, 0.0))
            amount_kgco2e_per_y = qty_kg_y * ef_kgco2e_per_kg
            category = "product" if item_key in product_items else (
                "residue" if item_key in residue_items else ""
            )
        else:
            environmental_type = "unpriced"
            ef_kgco2e_per_kg = 0.0
            amount_kgco2e_per_y = 0.0
            category = "product"

        lines.append(
            {
                "step_name": step,
                "item": item_key,
                "environmental_type": environmental_type,
                "category": category,
                "qty_kg_h": qty_kg_h,
                "qty_kg_y": qty_kg_y,
                "ef_kgco2e_per_kg": ef_kgco2e_per_kg,
                "amount_kgco2e_per_y": amount_kgco2e_per_y,
            }
        )

    return lines


def compute_step_output_emission_credits(
    step_row: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    lines = build_output_emission_lines_for_step(step_row, ctx)

    credit_kgco2e_per_y = sum(
        _safe(x["amount_kgco2e_per_y"]) for x in lines if x["environmental_type"] == "credit"
    )
    burden_kgco2e_per_y = sum(
        _safe(x["amount_kgco2e_per_y"]) for x in lines if x["environmental_type"] == "burden"
    )

    net_output_effect_kgco2e_per_y = burden_kgco2e_per_y - credit_kgco2e_per_y

    return {
        "step_name": _step_name(step_row),
        "output_lines": lines,
        "credit_kgco2e_per_y": credit_kgco2e_per_y,
        "burden_kgco2e_per_y": burden_kgco2e_per_y,
        "net_output_effect_kgco2e_per_y": net_output_effect_kgco2e_per_y,
    }


def compute_all_steps_output_emission_credits(
    step_rows: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    all_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for r in step_rows:
        s = compute_step_output_emission_credits(r, ctx)
        all_lines.extend(s.pop("output_lines"))
        step_totals.append(s)

    credit_total_kgco2e_per_y = sum(_safe(x["credit_kgco2e_per_y"]) for x in step_totals)
    burden_total_kgco2e_per_y = sum(_safe(x["burden_kgco2e_per_y"]) for x in step_totals)
    net_output_effect_total_kgco2e_per_y = burden_total_kgco2e_per_y - credit_total_kgco2e_per_y

    by_step_item = defaultdict(float)
    for ln in all_lines:
        by_step_item[
            (ln["step_name"], ln["item"], ln["environmental_type"], ln["category"])
        ] += _safe(ln["amount_kgco2e_per_y"])

    by_step_item_rows = [
        {
            "step_name": k[0],
            "item": k[1],
            "environmental_type": k[2],
            "category": k[3],
            "amount_kgco2e_per_y": v,
        }
        for k, v in by_step_item.items()
    ]

    return {
        "output_lines": all_lines,
        "by_step_item": by_step_item_rows,
        "step_totals": step_totals,
        "credit_total_kgco2e_per_y": credit_total_kgco2e_per_y,
        "burden_total_kgco2e_per_y": burden_total_kgco2e_per_y,
        "net_output_effect_total_kgco2e_per_y": net_output_effect_total_kgco2e_per_y,
    }