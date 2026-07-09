from __future__ import annotations

from typing import Any
import General_Parameters as gp


def _safe(v: Any) -> float:
    try:
        x = float(v or 0.0)
        # NaN check: x != x
        if x != x or x in (float("inf"), float("-inf")):
            return 0.0
        return x
    except Exception:
        return 0.0


def _denom_kg_y(ctx: dict[str, Any]) -> float:
    """
    Consistent denominator for per-kg metrics.
    """
    return float(
        ctx.get("feed_mass_kg_per_year")
        or ctx.get("cell_mass_kg_per_year")
        or ctx.get("pack_mass_kg_per_year")
        or ctx.get("mass_kg_per_year")
        or (
            float(ctx.get("feed_kg_per_h", 0.0))
            * float(ctx.get("hours_per_year", gp.get_working_hours_per_year()))
        )
        or 1.0
    )


def _sum_step_field(step_totals: list[dict[str, Any]], key: str) -> float:
    return sum(_safe(s.get(key, 0.0)) for s in (step_totals or []))


def aggregate_net_gwp(
    ctx: dict[str, Any],
    burdens_result: dict[str, Any] | None,
    credits_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Aggregate environmental results to net GWP.

    Inputs:
    - burdens_result from Environmental/Burdens.py
      expected keys:
        * step_totals
        * direct_emissions_total_kgco2e_per_y
        * material_emission_by_step_item
    - credits_result from Environmental/Credits.py
      expected keys:
        * step_totals
        * credit_total_kgco2e_per_y
        * burden_total_kgco2e_per_y
        * net_output_effect_total_kgco2e_per_y
        * by_step_item

    Net logic:
      net_gwp_total = direct_input_burdens + output_burdens - output_credits
    """
    burdens_result = burdens_result or {}
    credits_result = credits_result or {}

    denom = _denom_kg_y(ctx)

    # --- Input-side burdens ---
    burden_step_totals = list(burdens_result.get("step_totals", []) or [])
    direct_inputs_total_kgco2e_per_y = _safe(
        burdens_result.get("direct_emissions_total_kgco2e_per_y", 0.0)
    )
    # fallback if top-level missing
    if direct_inputs_total_kgco2e_per_y <= 0.0 and burden_step_totals:
        direct_inputs_total_kgco2e_per_y = _sum_step_field(
            burden_step_totals, "emission_direct_total_kgco2e_per_y"
        )

    # --- Output-side credits/burdens ---
    credit_step_totals = list(credits_result.get("step_totals", []) or [])

    output_credits_total_kgco2e_per_y = _safe(
        credits_result.get("credit_total_kgco2e_per_y", 0.0)
    )
    output_burdens_total_kgco2e_per_y = _safe(
        credits_result.get("burden_total_kgco2e_per_y", 0.0)
    )

    # fallbacks from step totals
    if output_credits_total_kgco2e_per_y <= 0.0 and credit_step_totals:
        output_credits_total_kgco2e_per_y = _sum_step_field(
            credit_step_totals, "credit_kgco2e_per_y"
        )
    if output_burdens_total_kgco2e_per_y <= 0.0 and credit_step_totals:
        output_burdens_total_kgco2e_per_y = _sum_step_field(
            credit_step_totals, "burden_kgco2e_per_y"
        )

    # Net output effect (positive = additional burden)
    net_output_effect_kgco2e_per_y = (
        output_burdens_total_kgco2e_per_y - output_credits_total_kgco2e_per_y
    )

    # Final net GWP
    net_gwp_total_kgco2e_per_y = direct_inputs_total_kgco2e_per_y + net_output_effect_kgco2e_per_y

    def perkg(x: float) -> float:
        return x / denom if denom > 0 else 0.0

    return {
        "summary": {
            "direct_inputs_total_kgco2e_per_y": direct_inputs_total_kgco2e_per_y,
            "output_credits_total_kgco2e_per_y": output_credits_total_kgco2e_per_y,
            "output_burdens_total_kgco2e_per_y": output_burdens_total_kgco2e_per_y,
            "net_output_effect_kgco2e_per_y": net_output_effect_kgco2e_per_y,
            "net_gwp_total_kgco2e_per_y": net_gwp_total_kgco2e_per_y,
            "net_gwp_kgco2e_per_kg_feed": perkg(net_gwp_total_kgco2e_per_y),
        },
        "burdens": burdens_result,
        "credits": credits_result,
    }