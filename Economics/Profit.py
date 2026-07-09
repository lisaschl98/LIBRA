from __future__ import annotations

from typing import Any


def _safe(v: Any) -> float:
    try:
        x = float(v or 0.0)
        if x != x or x in (float("inf"), float("-inf")):
            return 0.0
        return x
    except Exception:
        return 0.0


def compute_profit(
    opex_result: dict[str, Any] | None,
    overhead_result: dict[str, Any] | None,
    revenue_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Aggregate result metrics into a clear profit block (all per year).

    Expected inputs:
    - opex_result from Economics/Opex.py
      -> direct_opex_total_per_y (optional, info only)
    - overhead_result from Economics/Overhead.py
      -> summary.total_product_costs_per_y (preferred)
      -> summary.overhead_total_per_y (optional, info only)
    - revenue_result from Economics/Revenue.py
      -> revenue_total_per_y
      -> output_cost_total_per_y
      -> net_output_value_total_per_y (optional, otherwise recalculated)
    """
    opex_result = opex_result or {}
    overhead_result = overhead_result or {}
    revenue_result = revenue_result or {}

    overhead_summary = dict(overhead_result.get("summary", {}) or {})

    # Cost basis: prefer full TPC from overhead
    total_product_costs_per_y = _safe(overhead_summary.get("total_product_costs_per_y", 0.0))

    # Direct costs for reference/transparency only
    direct_opex_total_per_y = _safe(opex_result.get("direct_opex_total_per_y", 0.0))
    overhead_total_per_y = _safe(overhead_summary.get("overhead_total_per_y", 0.0))

    # Output revenue/costs
    revenue_total_per_y = _safe(revenue_result.get("revenue_total_per_y", 0.0))
    output_cost_total_per_y = _safe(revenue_result.get("output_cost_total_per_y", 0.0))

    net_output_value_total_per_y = _safe(
        revenue_result.get(
            "net_output_value_total_per_y",
            revenue_total_per_y - output_cost_total_per_y,
        )
    )

    # Key metric
    profit_per_y = net_output_value_total_per_y - total_product_costs_per_y

    # Optional hilfreiche zweite Sicht:
    # "contribution margin" vs direct OPEX
    contribution_after_direct_opex_per_y = net_output_value_total_per_y - direct_opex_total_per_y

    return {
        "summary": {
            "revenue_total_per_y": revenue_total_per_y,
            "output_cost_total_per_y": output_cost_total_per_y,
            "net_output_value_total_per_y": net_output_value_total_per_y,
            "direct_opex_total_per_y": direct_opex_total_per_y,
            "overhead_total_per_y": overhead_total_per_y,
            "total_product_costs_per_y": total_product_costs_per_y,
            "contribution_after_direct_opex_per_y": contribution_after_direct_opex_per_y,
            "profit_per_y": profit_per_y,
        }
    }