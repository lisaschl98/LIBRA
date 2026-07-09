"""Discharge process step.

This module models industrial battery discharge before downstream mechanical or pyrometallurgical
processing.
"""

from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance

from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)


def cells_per_feed_unit(
    level: str,
    *,
    cells_per_module: int,
    cells_per_pack: int,
) -> int:
    """Return the number of cells represented by one feed unit (cell / module / pack)."""
    lv = str(level).strip().lower()
    if lv == "cell":
        return 1
    if lv == "module":
        return max(1, int(cells_per_module))
    if lv == "pack":
        return max(1, int(cells_per_pack))
    raise ValueError(f"Unknown feed level for discharge recovery: {level!r}")


def discharge_recovery_from_feed(
    ctx: dict,
    params: dict | None = None,
) -> dict[str, float | list[dict[str, float | str]]]:
    """
    Estimate recoverable electrical energy from stored energy in the UNIFIED feed.

    E_stored,y = sum(units_y * n_cells_per_unit * cell_energy_kWh)
    E_rec,y    = E_stored,y * delta_soc * recovery_eta
    """
    p = params or {}
    delta_soc = float(
        p.get("delta_soc", p.get("discharge_delta_soc", 0.30))
    )
    eta = float(p.get("recovery_eta", 0.90))

    h_y = float(hours_per_year(ctx) or 0.0)
    e_stored_kwh_y = 0.0
    n_cells_total_y = 0.0
    by_feed_item: list[dict[str, float | str]] = []

    for item in ctx.get("feed_details") or []:
        cell_energy_wh = float(item.get("cell_energy_Wh", 0.0) or 0.0)
        if cell_energy_wh <= 0.0:
            continue

        units_y = float(item.get("units_per_year", 0.0) or 0.0)
        if units_y <= 0.0:
            continue

        n_cells_per_unit = cells_per_feed_unit(
            str(item.get("level", "cell")),
            cells_per_module=int(item.get("cells_per_module", 1) or 1),
            cells_per_pack=int(item.get("cells_per_pack", 1) or 1),
        )
        n_cells_y = units_y * float(n_cells_per_unit)
        cell_energy_kwh = cell_energy_wh / 1000.0
        e_item_y = n_cells_y * cell_energy_kwh

        e_stored_kwh_y += e_item_y
        n_cells_total_y += n_cells_y
        by_feed_item.append({
            "cell_id": str(item.get("cell_id", "")),
            "level": str(item.get("level", "")),
            "units_per_year": units_y,
            "cells_per_unit": float(n_cells_per_unit),
            "cells_per_year": n_cells_y,
            "stored_energy_kWh_y": e_item_y,
        })

    e_rec_y = e_stored_kwh_y * delta_soc * eta
    e_rec_h = e_rec_y / h_y if h_y > 0.0 else 0.0

    return {
        "delta_soc": delta_soc,
        "recovery_eta": eta,
        "stored_energy_kWh_y": e_stored_kwh_y,
        "cells_discharged_per_y": n_cells_total_y,
        "kWh_y_recovered": e_rec_y,
        "kWh_h_recovered": e_rec_h,
        "by_feed_item": by_feed_item,
    }


def run_discharge(ctx: dict, flow_in: MassFlow, params: dict | None = None):
    """Run the discharge step.

    Parameters
    ----------
    ctx : dict
        Global scenario context (economic assumptions, runtime basis, etc.).
    flow_in : MassFlow
        Incoming battery-system stream.
    params : dict | None, optional
        Optional overrides. Typical keys:
        - ``design_load`` (default: 0.95)
        - ``max_lines`` (default: 600)
        - ``delta_soc`` / ``discharge_delta_soc`` (default: 0.30)
        - ``recovery_eta`` (default: 0.90)

    Returns
    -------
    tuple
        (outputs, row, extras)

    Notes
    -----
    - Discharge recovery is treated as an energy credit.
    - Energy credit is passed as negative kWh/y to OPEX costing.
    - Recovery scales with stored energy in ``ctx['feed_details']`` (cells per pack/module).
    """
    p = params or {}
    step = "Discharge"

    outputs = rfx.apply_step_cfg(step, flow_in, fallback_default_stream="discharge system")
    assert_mass_balance(step, float(flow_in.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="discharge system")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    forward_flow: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )

    design_load = float(p.get("design_load", 0.95))
    sizing = size_machine_for_mass(
        step,
        Eq.discharge,
        forward_flow,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )

    breakdown = capex_breakdown_df(step, Eq.discharge.name, sizing)

    required_tph = float(forward_flow.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    recovery = discharge_recovery_from_feed(ctx, p)
    kwh_recovered_per_h = float(recovery["kWh_h_recovered"])
    kwh_recovered_per_y = float(recovery["kWh_y_recovered"])

    h_y = hours_per_year(ctx)
    energy_kwh_y_for_costing = -kwh_recovered_per_y

    row = make_row(step, flow_in, forward_flow)

    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Battery systems discharged (kg/h)"] = float(forward_flow.mass_kg_per_h)
    row["Stored energy in feed (kWh/y)"] = float(recovery["stored_energy_kWh_y"])
    row["Cells discharged (1/y)"] = float(recovery["cells_discharged_per_y"])
    row["Discharge delta SOC (-)"] = float(recovery["delta_soc"])
    row["Discharge recovery eta (-)"] = float(recovery["recovery_eta"])

    row["E_kWh_h"] = -float(kwh_recovered_per_h)
    row["kWh/h recovered"] = float(kwh_recovered_per_h)
    row["kWh/y recovered"] = float(kwh_recovered_per_y)

    row = attach_opex_to_row(
        row,
        machine=Eq.discharge,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=energy_kwh_y_for_costing,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["CAPEX install ($)"] = float(sizing.get("capex_install_model", 0.0))
    row["CAPEX instr ($)"] = float(sizing.get("capex_instr", 0.0))
    row["CAPEX piping ($)"] = float(sizing.get("capex_piping", 0.0))
    row["CAPEX electrical ($)"] = float(sizing.get("capex_electrical", 0.0))

    extras = {
        step: {
            "breakdown": breakdown,
            "recovery": recovery,
        }
    }
    return outputs, row, extras
