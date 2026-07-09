from __future__ import annotations
import io

import pandas as pd
import numpy as np
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment
from datetime import datetime
import json

import General_Parameters as gp
import machine as ms
from infrastructure import infrastructure_export_row, run_info_infrastructure_fields


OUTPUT_XLSX = "Results.xlsx"

# ==== Target columns ====

CAPEX_COLS = [
    "Scenario","Step",
    "In kg/h","Output forwarded (kg/h)",
    "Machines","Line capacity (t/h)",
    "Machine name(s)",
    "CAPEX equip per machine($)","CAPEX equip per step ($)",
    "Building per machine $","Building per step $",
]
COST_STRUCTURE_COLS = ["Cost Item","$/year","Scenario"]
MASSFLOW_LONG_COLS = [
    "Scenario","Step","Input (kg/h)","Materials added (kg/h)", "Name Material added", 
    "Output forwarded (kg/h)","Name Output forwarded ",
    "Output separated (kg/h)","Name Output Separated",
]
# ==== Helpers ====
def _num(s):
    if isinstance(s, pd.DataFrame):
        return s.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if isinstance(s, pd.Series):
        return pd.to_numeric(s, errors="coerce").fillna(0.0)
    if isinstance(s, (list, tuple, np.ndarray)):
        return pd.to_numeric(pd.Series(s), errors="coerce").fillna(0.0)
    try:
        v = float(s)
        if np.isnan(v):       # NEU: NaN -> 0
            return 0.0
        return v
    except Exception:
        return 0.0

def _autosize(writer: pd.ExcelWriter):
    for _, ws in writer.sheets.items():
        for col_idx, col_cells in enumerate(ws.columns, start=1):
            max_len = 0
            for c in col_cells:
                try:
                    v = "" if c.value is None else str(c.value)
                    max_len = max(max_len, len(v))
                except Exception:
                    pass
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 60)
        for cell in next(ws.iter_rows(min_row=1, max_row=1)):
            cell.alignment = Alignment(horizontal="center", vertical="center")


def _run_info_row(scen: dict, ctx: dict):
    throughput = float(ctx.get("feed_mass_kg_per_year", 0.0) or 0.0)

    feed_repr = [
        {"cell_id": d.get("cell_id"), "level": d.get("level"), "share": d.get("share")}
        for d in (ctx.get("feed_details") or [])
    ]

    row = {
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "scenario_name": scen.get("name",""),
        "date_time": datetime.now().isoformat(timespec="seconds"),
        "throughput_kg_y": throughput,
        "feed": json.dumps(feed_repr),
        "region": ctx.get("region", scen.get("region","")),
    }
    row.update(run_info_infrastructure_fields(scen, ctx))
    return row


def _kpi_from_economics(oh: dict, mass_y: float) -> dict[str, float]:
    """
    Extract per-year economics (TPC, revenue, profit) from centralized payload
    and normalize to $/kg battery.
    """
    if not isinstance(oh, dict):
        return {
            "tpc_per_kg": 0.0,
            "revenue_per_kg": 0.0,
            "profit_per_kg": 0.0,
            "net_gwp_per_kg": 0.0,
        }

    # Overhead summary is stored as DataFrame in extras["Overhead"]["summary"].
    summary_df = oh.get("summary")
    tpc_per_y = 0.0
    if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
        row0 = summary_df.iloc[0].to_dict()
        tpc_per_y = float(_num(row0.get("TPC ($/y)", row0.get("total_product_costs_per_y", 0.0))))

    revenue_block = oh.get("revenue", {}) if isinstance(oh.get("revenue", {}), dict) else {}
    revenue_per_y = float(_num(revenue_block.get("net_output_value_total_per_y", 0.0)))

    profit_block = oh.get("profit", {}) if isinstance(oh.get("profit", {}), dict) else {}
    profit_summary = profit_block.get("summary", {}) if isinstance(profit_block.get("summary", {}), dict) else {}
    profit_per_y = float(_num(profit_summary.get("profit_per_y", 0.0)))

    env_block = oh.get("environmental", {}) if isinstance(oh.get("environmental", {}), dict) else {}
    net_gwp_block = env_block.get("net_gwp", {}) if isinstance(env_block.get("net_gwp", {}), dict) else {}
    net_gwp_summary = net_gwp_block.get("summary", {}) if isinstance(net_gwp_block.get("summary", {}), dict) else {}
    net_gwp_per_y = float(_num(net_gwp_summary.get("net_gwp_total_kgco2e_per_y", 0.0)))

    denom = float(mass_y or 0.0)
    if denom <= 0.0:
        return {
            "tpc_per_kg": 0.0,
            "revenue_per_kg": 0.0,
            "profit_per_kg": 0.0,
            "net_gwp_per_kg": 0.0,
        }

    return {
        "tpc_per_kg": tpc_per_y / denom,
        "revenue_per_kg": revenue_per_y / denom,
        "profit_per_kg": profit_per_y / denom,
        "net_gwp_per_kg": net_gwp_per_y / denom,
    }


def _annual_process_inputs_sheet(
    oh: dict,
    ctx: dict,
    scen_name: str,
) -> pd.DataFrame:
    """
    Build one combined annual input sheet from economics + environmental blocks.
    Columns:
      Scenario, step_name, item, category, Quantity, Quantity unit, Costs ($/y), Emissions (kg CO2e/y)
    """
    if not isinstance(oh, dict):
        return pd.DataFrame()

    opex = oh.get("opex", {}) if isinstance(oh.get("opex", {}), dict) else {}
    env = oh.get("environmental", {}) if isinstance(oh.get("environmental", {}), dict) else {}
    burdens = env.get("burdens", {}) if isinstance(env.get("burdens", {}), dict) else {}

    opex_items = pd.DataFrame(opex.get("material_cost_by_step_item", []) or [])
    opex_steps = pd.DataFrame(opex.get("step_totals", []) or [])
    burdens_items = pd.DataFrame(burdens.get("material_emission_by_step_item", []) or [])
    burdens_steps = pd.DataFrame(burdens.get("step_totals", []) or [])

    pr = dict((ctx or {}).get("prices", {}) or {})
    gwp = dict((ctx or {}).get("gwp_factors", {}) or {})

    # --- Reagents: merge OPEX item rows + burden item rows on (step,item) ---
    if opex_items.empty:
        reag = pd.DataFrame(columns=["step_name", "item", "qty_y", "costs_per_y"])
    else:
        reag = opex_items.copy()
        if "qty_kg_y" in reag.columns:
            reag["qty_y"] = pd.to_numeric(reag["qty_kg_y"], errors="coerce").fillna(0.0)
        else:
            reag["qty_y"] = 0.0
        if "cost_per_y" in reag.columns:
            reag["costs_per_y"] = pd.to_numeric(reag["cost_per_y"], errors="coerce").fillna(0.0)
        else:
            reag["costs_per_y"] = 0.0
        reag = reag[[c for c in ["step_name", "item", "qty_y", "costs_per_y"] if c in reag.columns]]

    if burdens_items.empty:
        bui = pd.DataFrame(columns=["step_name", "item", "emissions_per_y"])
    else:
        bui = burdens_items.copy()
        if "emission_kgco2e_per_y" in bui.columns:
            bui["emissions_per_y"] = pd.to_numeric(bui["emission_kgco2e_per_y"], errors="coerce").fillna(0.0)
        else:
            bui["emissions_per_y"] = 0.0
        bui = bui[[c for c in ["step_name", "item", "emissions_per_y"] if c in bui.columns]]

    reag_join = pd.merge(reag, bui, on=["step_name", "item"], how="outer")
    if reag_join.empty:
        reag_rows = pd.DataFrame(columns=["step_name", "item", "category", "qty_y", "qty_unit", "costs_per_y", "emissions_per_y"])
    else:
        for c in ["qty_y", "costs_per_y", "emissions_per_y"]:
            if c not in reag_join.columns:
                reag_join[c] = 0.0
            reag_join[c] = pd.to_numeric(reag_join[c], errors="coerce").fillna(0.0)
        reag_join["category"] = "reagent"
        reag_join["qty_unit"] = "kg/y"
        reag_rows = reag_join[["step_name", "item", "category", "qty_y", "qty_unit", "costs_per_y", "emissions_per_y"]]

    # --- Utilities + labor from step totals ---
    util_rows = []
    if not opex_steps.empty:
        # Join step-level burdens for electricity/water emissions
        bs = burdens_steps.copy() if not burdens_steps.empty else pd.DataFrame(columns=["step_name"])
        if "step_name" not in bs.columns:
            bs["step_name"] = ""

        merged_steps = pd.merge(opex_steps, bs, on="step_name", how="left", suffixes=("", "_bur"))
        for c in [
            "cost_energy_per_y",
            "cost_water_per_y",
            "cost_labor_per_y",
            "depreciation_per_y",
            "emission_energy_kgco2e_per_y",
            "emission_water_kgco2e_per_y",
        ]:
            if c not in merged_steps.columns:
                merged_steps[c] = 0.0
            merged_steps[c] = pd.to_numeric(merged_steps[c], errors="coerce").fillna(0.0)

        p_elec = float(_num(pr.get("Electricity", 0.0)))
        p_water = float(_num(pr.get("Water", 0.0)))
        p_labor = float(_num(pr.get("Labor", 0.0)))
        ef_labor = float(_num(gwp.get("Labor", 0.0)))

        for _, r in merged_steps.iterrows():
            step_name = str(r.get("step_name", ""))
            c_e = float(_num(r.get("cost_energy_per_y", 0.0)))
            c_w = float(_num(r.get("cost_water_per_y", 0.0)))
            c_l = float(_num(r.get("cost_labor_per_y", 0.0)))

            e_e = float(_num(r.get("emission_energy_kgco2e_per_y", 0.0)))
            e_w = float(_num(r.get("emission_water_kgco2e_per_y", 0.0)))

            q_e = (c_e / p_elec) if p_elec > 0 else 0.0
            q_w = (c_w / p_water) if p_water > 0 else 0.0
            q_l = (c_l / p_labor) if p_labor > 0 else 0.0

            e_l = q_l * ef_labor

            util_rows.extend(
                [
                    {
                        "step_name": step_name,
                        "item": "Electricity",
                        "category": "utility",
                        "qty_y": q_e,
                        "qty_unit": "kWh/y",
                        "costs_per_y": c_e,
                        "emissions_per_y": e_e,
                    },
                    {
                        "step_name": step_name,
                        "item": "Labor",
                        "category": "labor",
                        "qty_y": q_l,
                        "qty_unit": "h/y",
                        "costs_per_y": c_l,
                        "emissions_per_y": e_l,
                    },
                ]
            )
            # Machine/plant water utility (cost_water_per_y) — only if explicitly modeled; process water is reagent.
            if c_w > 0.0 or e_w > 0.0:
                util_rows.append(
                    {
                        "step_name": step_name,
                        "item": "Water",
                        "category": "utility",
                        "qty_y": q_w,
                        "qty_unit": "kg/y",
                        "costs_per_y": c_w,
                        "emissions_per_y": e_w,
                    }
                )

    util_df = pd.DataFrame(util_rows)
    combined = pd.concat([reag_rows, util_df], ignore_index=True) if not util_df.empty else reag_rows.copy()
    if combined.empty:
        return pd.DataFrame(columns=["Scenario", "step_name", "item", "category", "Quantity", "Quantity unit", "Costs ($/y)", "Emissions (kg CO2e/y)"])

    for c in ["qty_y", "costs_per_y", "emissions_per_y"]:
        combined[c] = pd.to_numeric(combined[c], errors="coerce").fillna(0.0)
    if "qty_unit" not in combined.columns:
        combined["qty_unit"] = ""
    combined["qty_unit"] = combined["qty_unit"].fillna("")

    # Aggregate potential duplicates and sort by process order + category order.
    combined = (
        combined.groupby(["step_name", "item", "category", "qty_unit"], as_index=False)[["qty_y", "costs_per_y", "emissions_per_y"]]
        .sum()
    )

    step_order: dict[str, int] = {}
    if "step_name" in opex_steps.columns:
        idx = 0
        for s in opex_steps["step_name"].tolist():
            ss = str(s)
            if ss not in step_order:
                step_order[ss] = idx
                idx += 1
    combined["_step_sort"] = combined["step_name"].map(step_order).fillna(10**9)
    cat_order = {"reagent": 0, "utility": 1, "labor": 2}
    combined["_cat_sort"] = combined["category"].map(cat_order).fillna(99)
    combined = combined.sort_values(["_step_sort", "step_name", "_cat_sort", "item"], kind="mergesort").drop(
        columns=["_step_sort", "_cat_sort"]
    )

    combined.insert(0, "Scenario", scen_name)
    combined = combined.rename(
        columns={
            "qty_y": "Quantity",
            "qty_unit": "Quantity unit",
            "costs_per_y": "Costs ($/y)",
            "emissions_per_y": "Emissions (kg CO2e/y)",
        }
    )
    return combined[
        ["Scenario", "step_name", "item", "category", "Quantity", "Quantity unit", "Costs ($/y)", "Emissions (kg CO2e/y)"]
    ]


def _annual_process_outputs_sheet(
    oh: dict,
    scen_name: str,
) -> pd.DataFrame:
    """
    Build one combined annual output sheet from economics revenue + environmental credits.
    Columns:
      Scenario, step_name, item, category, Quantity, Quantity unit,
      revenue_per_y, credit_kgco2eq_per_y
    Sign convention:
      - Revenue ($/y): positive for revenue, negative for cost (e.g. residues with treatment cost)
      - Credit (kg CO2e/y): positive for credit, negative for burden
    """
    if not isinstance(oh, dict):
        return pd.DataFrame()

    revenue = oh.get("revenue", {}) if isinstance(oh.get("revenue", {}), dict) else {}
    env = oh.get("environmental", {}) if isinstance(oh.get("environmental", {}), dict) else {}
    credits = env.get("credits", {}) if isinstance(env.get("credits", {}), dict) else {}

    rev_lines = pd.DataFrame(revenue.get("output_lines", []) or [])
    cred_lines = pd.DataFrame(credits.get("output_lines", []) or [])

    # Revenue lines with signed amounts
    if rev_lines.empty:
        rev_df = pd.DataFrame(columns=["step_name", "item", "category", "Quantity", "Quantity unit", "revenue_per_y"])
    else:
        rr = rev_lines.copy()
        rr["qty_kg_y"] = pd.to_numeric(rr.get("qty_kg_y", 0.0), errors="coerce").fillna(0.0)
        rr["amount_per_y"] = pd.to_numeric(rr.get("amount_per_y", 0.0), errors="coerce").fillna(0.0)
        rr["economic_type"] = rr.get("economic_type", "").astype(str).str.strip().str.lower()
        rr["category"] = rr.get("category", "").astype(str).str.strip().str.lower()
        rr["revenue_per_y"] = rr.apply(
            lambda r: (
                float(r["amount_per_y"])
                if r["economic_type"] == "revenue"
                else (-float(r["amount_per_y"]) if r["economic_type"] == "cost" else 0.0)
            ),
            axis=1,
        )
        rr["Quantity"] = rr["qty_kg_y"]
        rr["Quantity unit"] = "kg/y"
        rev_df = rr[["step_name", "item", "category", "Quantity", "Quantity unit", "revenue_per_y"]]

    # Environmental credit/burden lines with signed credit value
    if cred_lines.empty:
        cred_df = pd.DataFrame(columns=["step_name", "item", "category", "Quantity", "Quantity unit", "credit_kgco2eq_per_y"])
    else:
        cc = cred_lines.copy()
        cc["qty_kg_y"] = pd.to_numeric(cc.get("qty_kg_y", 0.0), errors="coerce").fillna(0.0)
        cc["amount_kgco2e_per_y"] = pd.to_numeric(cc.get("amount_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0)
        cc["environmental_type"] = cc.get("environmental_type", "").astype(str).str.strip().str.lower()
        cc["category"] = cc.get("category", "").astype(str).str.strip().str.lower()
        cc["credit_kgco2eq_per_y"] = cc.apply(
            lambda r: (
                float(r["amount_kgco2e_per_y"])
                if r["environmental_type"] == "credit"
                else (-float(r["amount_kgco2e_per_y"]) if r["environmental_type"] == "burden" else 0.0)
            ),
            axis=1,
        )
        cc["Quantity"] = cc["qty_kg_y"]
        cc["Quantity unit"] = "kg/y"
        cred_df = cc[["step_name", "item", "category", "Quantity", "Quantity unit", "credit_kgco2eq_per_y"]]

    if not rev_df.empty and not cred_df.empty:
        combined = pd.merge(
            rev_df,
            cred_df,
            on=["step_name", "item"],
            how="outer",
            suffixes=("_rev", "_cred"),
        )
        for base_col, rev_col, cred_col in (
            ("Quantity", "Quantity_rev", "Quantity_cred"),
            ("Quantity unit", "Quantity unit_rev", "Quantity unit_cred"),
            ("category", "category_rev", "category_cred"),
        ):
            if rev_col in combined.columns and cred_col in combined.columns:
                combined[base_col] = combined[rev_col].fillna(combined[cred_col])
                combined = combined.drop(columns=[rev_col, cred_col], errors="ignore")
            elif rev_col in combined.columns:
                combined[base_col] = combined[rev_col]
                combined = combined.drop(columns=[rev_col], errors="ignore")
            elif cred_col in combined.columns:
                combined[base_col] = combined[cred_col]
                combined = combined.drop(columns=[cred_col], errors="ignore")
        if "revenue_per_y" not in combined.columns and "revenue_per_y_rev" in combined.columns:
            combined["revenue_per_y"] = combined["revenue_per_y_rev"]
        if "credit_kgco2eq_per_y" not in combined.columns and "credit_kgco2eq_per_y_cred" in combined.columns:
            combined["credit_kgco2eq_per_y"] = combined["credit_kgco2eq_per_y_cred"]
        combined = combined.drop(
            columns=[c for c in combined.columns if c.endswith("_rev") or c.endswith("_cred")],
            errors="ignore",
        )
    elif rev_df.empty:
        combined = cred_df.rename(columns={"credit_kgco2eq_per_y": "credit_kgco2eq_per_y"})
        if "revenue_per_y" not in combined.columns:
            combined["revenue_per_y"] = 0.0
    else:
        combined = rev_df.copy()
        if "credit_kgco2eq_per_y" not in combined.columns:
            combined["credit_kgco2eq_per_y"] = 0.0

    if combined.empty:
        return pd.DataFrame(
            columns=[
                "Scenario",
                "step_name",
                "item",
                "category",
                "Quantity",
                "Quantity unit",
                "revenue_per_y",
                "credit_kgco2eq_per_y",
            ]
        )

    combined["revenue_per_y"] = pd.to_numeric(combined.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
    combined["credit_kgco2eq_per_y"] = pd.to_numeric(combined.get("credit_kgco2eq_per_y", 0.0), errors="coerce").fillna(0.0)
    combined["Quantity"] = pd.to_numeric(combined.get("Quantity", 0.0), errors="coerce").fillna(0.0)
    combined["Quantity unit"] = combined.get("Quantity unit", "").fillna("")

    # Keep process order by first appearance in revenue lines, fallback by name.
    step_order: dict[str, int] = {}
    if not rev_lines.empty and "step_name" in rev_lines.columns:
        idx = 0
        for s in rev_lines["step_name"].tolist():
            ss = str(s)
            if ss not in step_order:
                step_order[ss] = idx
                idx += 1
    combined["_step_sort"] = combined["step_name"].map(step_order).fillna(10**9)
    cat_order = {"product": 0, "residue": 1}
    combined["_cat_sort"] = combined["category"].map(cat_order).fillna(99)
    combined = combined.sort_values(["_step_sort", "step_name", "_cat_sort", "item"], kind="mergesort").drop(
        columns=["_step_sort", "_cat_sort"]
    )

    combined.insert(0, "Scenario", scen_name)
    return combined[
        [
            "Scenario",
            "step_name",
            "item",
            "category",
            "Quantity",
            "Quantity unit",
            "revenue_per_y",
            "credit_kgco2eq_per_y",
        ]
    ]


def _economics_environment_sheets(oh: dict, ctx: dict, scen_name: str) -> dict[str, pd.DataFrame]:
    """
    Build standardized economics/environmental export frames from centralized payload.
    """
    if not isinstance(oh, dict):
        return {}

    out: dict[str, pd.DataFrame] = {
        "Annual process Inputs": _annual_process_inputs_sheet(oh, ctx, scen_name),
        "Annual process Outputs": _annual_process_outputs_sheet(oh, scen_name),
    }
    return out


_RECOVERY_EXPORT_COLS: tuple[str, ...] = (
    "Scenario",
    "Recovery route",
    "Category",
    "Target",
    "Input mass (kg/y)",
    "Recovered mass (kg/y)",
    "Recovery (%)",
    "Products counted",
    "Notes",
)

def _round_recovery_pct(v) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
        if np.isnan(x) or np.isinf(x):
            return None
        return round(x, 2)
    except (TypeError, ValueError):
        return None


def _format_recovery_table_df(recovery_df: pd.DataFrame, scen_name: str, recovery_route: str) -> pd.DataFrame:
    if recovery_df is None or recovery_df.empty:
        return pd.DataFrame(columns=list(_RECOVERY_EXPORT_COLS))

    out = recovery_df.copy()
    out.insert(0, "Scenario", str(scen_name))
    out.insert(1, "Recovery route", str(recovery_route))
    if "Recovery (%)" in out.columns:
        out["Recovery (%)"] = out["Recovery (%)"].apply(_round_recovery_pct)
    for col in ("Input mass (kg/y)", "Recovered mass (kg/y)"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(4)
    for c in _RECOVERY_EXPORT_COLS:
        if c not in out.columns:
            out[c] = ""
    return out.loc[:, list(_RECOVERY_EXPORT_COLS)]


def _recovery_df_for_export(
    steps_df: pd.DataFrame,
    ctx: dict,
    oh: dict,
    scen_name: str,
) -> pd.DataFrame:
    """Recovery table for Excel export (one sheet per workbook)."""
    from recovery_config import resolve_recovery_route
    from recovery_metrics import compute_libra_recovery

    revenue = oh.get("revenue", {}) if isinstance(oh, dict) else {}
    econ = {"revenue_raw": revenue if isinstance(revenue, dict) else {}}
    res = compute_libra_recovery(ctx, steps_df, econ)
    recovery_route = resolve_recovery_route(ctx)
    return _format_recovery_table_df(res.recovery_df, scen_name, recovery_route)


# ==== Material-Input: Helper ==============================


def _cell_label(cell_id: str, info: dict | None = None) -> str:
    """
    Pretty label for Material Input sheet:
      e.g. 'NMC622 Pouch (pack)', 'LFP Pouch (cell)'
    """
    level = ""
    if isinstance(info, dict):
        level = str(info.get("level") or "").strip().lower()
        geom = str(info.get("geometry") or "").strip().replace("_", " ")
        if geom:
            return f"{geom} ({level})" if level else geom

    parts = str(cell_id).split("_")
    chem = parts[0] if parts else str(cell_id)
    geom = " ".join(parts[1:]) if len(parts) > 1 else ""
    base = (chem + (" " + geom if geom else "")).strip()
    return f"{base} ({level})" if level else base



def _rows_for_material_input(scen_name: str, ctx: dict) -> list[dict]:
    """
    UNIFIED-only:
    Input comes from ctx["feed_details"] (list of dicts).
    Output rows:
      Scenario, Basis, Component, Material, CellVariant, kg/year
    """
    rows = []
    details_list = ctx.get("feed_details") or []
    if not isinstance(details_list, list) or not details_list:
        return rows

    def parse_key(k: str) -> tuple[str, str, str]:
        k = str(k)
        if k.startswith("cell:"):
            rest = k.split(":", 1)[1]
            if ":" in rest:
                comp, mat = rest.split(":", 1)
                return "Cell", comp.strip(), mat.strip()
            return "Cell", "Cell", rest.strip()
        if k.startswith("module:"):
            return "Module", "", k.split(":", 1)[1].strip()
        if k.startswith("pack:"):
            return "Pack", "", k.split(":", 1)[1].strip()
        return "Other", "", k.strip()

    for info in details_list:
        if not isinstance(info, dict):
            continue

        cell_id = str(info.get("cell_id") or "").strip()
        variant = _cell_label(cell_id, info)

        units_y = float(info.get("units_per_year") or 0.0)
        comp_per_unit = info.get("comp_abs_kg_per_unit") or {}
        if units_y <= 0 or not isinstance(comp_per_unit, dict) or not comp_per_unit:
            continue

        for k, kg_per_unit in comp_per_unit.items():
            try:
                kg_y = float(kg_per_unit) * units_y
            except Exception:
                continue
            if kg_y == 0 or not np.isfinite(kg_y):
                continue

            basis, component, material = parse_key(k)
            rows.append({
                "Scenario": scen_name,
                "Basis": basis,
                "Component": component,
                "Material": material,
                "CellVariant": variant,
                "kg/year": kg_y,
            })

    return rows
def _massflow_long(steps_df: pd.DataFrame, scen_name: str) -> pd.DataFrame:
    rows = []

    def _standardize_display_name(name) -> object:
        """Standardize dashboard/export stream labels across all routes."""
        if not isinstance(name, str):
            return name
        s = str(name).strip()
        if not s:
            return s

        # Exact harmonization first
        exact = {
            "Battery systems sorted": "Sorted Battery Systems",
            "Modules": "Battery Modules",
            "Dried material": "Dried Shredded Material",
            "Shredded material": "Shredded Material",
            "Fragments": "Intermediate Fragments",
            "Crushed material": "Crushed Fragments",
            "BM leachate": "Pregnant Leach Solution",
            "alloy leachate": "Pregnant Leach Solution",
            "Slag lye": "Pregnant Leach Solution",
            "Slag clean lye": "Pregnant Leach Solution",
            "Digested slag solution": "Digested Slag Slurry",
            "digested alloy solution": "Digested Alloy Slurry",
            "digested BM solution": "Digested Black Mass Slurry",
            "Mix slurry": "Digested Black Mass Slurry",
            "Mix digested solution 2": "Digested Black Mass Slurry",
            "lye graphite clean": "Graphite-Depleted Solution",
            "lye copper clean": "Cu-Depleted Solution",
            "lye copper cementation": "Cu Cementation Slurry",
            "lye oxidation": "Oxidized Leach Solution",
            "lye iron precipitation": "Fe Precipitation Slurry",
            "lye iron, aluminium precipitation": "Fe/Al Precipitation Slurry",
            "Lye with Fe/Al precipitated": "Fe/Al Precipitation Slurry",
            "lye iron clean": "Fe-Depleted Solution",
            "lye iron, aluminium clean": "Fe/Al-Depleted Solution",
            "Lye Fe+Al filtered": "Fe/Al-Depleted Solution",
            "lye precursor mixing": "Precursor Mixing Slurry",
            "lye precursor precipitation": "Precursor Precipitation Slurry",
            "lye NMC clean": "NMC Mother Liquor (Wastewater)",
            "Li lye after precipitation": "Lithium Precipitation Slurry",
            "lye lithium precipitation": "Lithium Precipitation Slurry",
            "residual lye": "Wastewater",
            "filtration solution": "Wastewater",
            "Mix lye 2": "Pregnant Leach Solution",
            "Mix lye after Al removal": "Aluminium-Depleted Black Mass",
            "Mix lye after Cu cementation": "Cu Cementation Slurry",
            "NMC solution": "NMC Sulfate Solution",
            "Mix Fe concentrated lye": "Iron-Concentrated Solution",
            "Mix carbon dispersion": "Carbon Dispersion Slurry",
            "Roasted product": "Roasted Precursor Powder",
            "wastewater treated": "Wastewater Treated",
            "Wastewater treated": "Wastewater Treated",
            "Treated Wastewater": "Wastewater Treated",
            "alloy wastewater treated": "Wastewater Treated",
            "Li wastewater treated": "Wastewater Treated",
            "Clean gas": "Clean Off-Gas",
            "Off gas": "Off-Gas",
            "clean offgas": "Clean Off-Gas",
            "granulated alloy": "Granulated Alloy",
            "granulated slag": "Granulated Slag",
            "clean offgas": "Clean Off-Gas",
            "Offgas": "Off-Gas",
            "Cu foil": "Copper Foil",
            "Al foil": "Aluminium Foil",
            "Pack Al": "Pack Aluminium",
            "Pack Fe": "Pack Iron",
            "Pack Cu": "Pack Copper",
            "Mix NMC cake": "NMC Precursor",
            "Mix NMC filtrate": "NMC Mother Liquor (Wastewater)",
            "Mother Liquor (Wastewater)": "Ni-Mn-Co-Depleted Solution",
            "loaded_resin": "Ni-Mn-Co-Loaded Resin",
            "BM suspension": "Black Mass Slurry",
            "Black Mass suspension": "Black Mass Slurry",
            "BM aluminium clean": "Aluminium-Depleted Black Mass",
            "Black Mass aluminium clean": "Aluminium-Depleted Black Mass",
            "NMC Precursor washed": "Washed NMC Precursor",
            "NMC precursor washed": "Washed NMC Precursor",
            "Lye after Mn extraction": "Manganese-Depleted Solution",
            "lye after Co extraction": "Cobalt-Depleted Solution",
            "Lye after Co extraction": "Cobalt-Depleted Solution",
            "Mn scrubbed phase": "Manganese Scrubbed Organic Phase",
            "Co scrubbed phase": "Cobalt Scrubbed Organic Phase",
            "Mn stripped solution": "Manganese Stripped Solution",
            "Co stripped solution": "Cobalt Stripped Solution",
            "Manganese mother liquor": "Manganese Mother Liquor",
            "Manganese Mother Liquor": "Manganese Mother Liquor (Wastewater)",
            "Manganese mother liquor": "Manganese Mother Liquor (Wastewater)",
            "Co mother liquor": "Cobalt Mother Liquor (Wastewater)",
            "Cobalt mother liquor": "Cobalt Mother Liquor (Wastewater)",
            "Ni mother liquor": "Nickel Mother Liquor (Wastewater)",
            "Nickel mother liquor": "Nickel Mother Liquor (Wastewater)",
            "Li mother liquor": "Lithium Mother Liquor (Wastewater)",
            "Lithium Carbonate washed": "Lithium Carbonate Washed",
            "wastewater drying": "Wastewater",
            "Wastewater Drying": "Wastewater",
            "lye concentrated": "Concentrated Lithium Solution",
            "lye clean": "Purified Solution",
            "lye alkaline leaching": "Alkaline Leach Slurry",
            "lye oxalate mixing": "Oxalate Mixing Slurry",
            "lye oxalate precipitation": "Iron Oxalate Precipitation Slurry",
            "lye iron clean": "Iron-Depleted Solution",
            "lye iron, aluminium precipitation": "Fe/Al Precipitation Slurry",
            "lye iron, aluminium clean": "Fe/Al-Depleted Solution",
            "lye NMC clean": "NMC Mother Liquor (Wastewater)",
            "residual lye": "Wastewater",
            "CaSO4": "Calcium Sulfate",
            "MnSO4·H2O": "Manganese Sulfate (MnSO4·H2O)",
            "CoSO4*7H2O": "Cobalt Sulfate (CoSO4·7 H2O)",
            "NiSO4*6H2O": "Nickel Sulfate (NiSO4·6 H2O)",
            "Al separated (cell packaging)": "Aluminium From Cell Packaging",
            "Al separated (module)": "Aluminium From Modules",
            "Cu separated (module)": "Copper From Modules",
            "Plastic separated (module)": "Plastic From Modules",
            "Electronics separated (module)": "Electronics From Modules",
            "Aluminium hydroxide": "Aluminium Hydroxide",
            "Ammonia makeup": "Ammonia Makeup",
            "Black mass": "Black Mass",
            "Coarse fraction": "Coarse Fraction",
            "Cobalt loaded organic phase": "Cobalt Loaded Organic Phase",
            "Cyanex 272 (circulating)": "Cyanex 272 (Circulating)",
            "D2EHPA (circulating)": "D2EHPA (Circulating)",
            "Electrospinning precursor": "Electrospinning Precursor",
            "Hydrogen peroxide": "Hydrogen Peroxide",
            "Iron Oxalate cake": "Iron Oxalate Cake",
            "Iron Oxalate washed": "Iron Oxalate Washed",
            "Iron hydroxide": "Iron Hydroxide",
            "Kerosene (circulating)": "Kerosene (Circulating)",
            "Lithium Carbonate anhydrous": "Lithium Carbonate Anhydrous",
            "Lye aluminium and binder": "Aluminium/Binder Slurry",
            "Manganese loaded organic phase": "Manganese Loaded Organic Phase",
            "Nickel sulfate": "Nickel Sulfate",
            "Non-magnetic fraction": "Non-Magnetic Fraction",
            "Oxalic acid": "Oxalic acid",
            "Plastic (separator + pouch foil)": "Plastic (Separator + Pouch Foil)",
            "Sodium carbonate": "Sodium Carbonate",
            "Sodium hydroxide 50%": "Sodium Hydroxide 50%",
            "Steel from cell packaging": "Steel From Cell Packaging",
            "Steel from modules": "Steel From Modules",
            "Sulfuric acid 95%": "Sulfuric Acid 95%",
        }
        if s in exact:
            return exact[s]

        # Formula and abbreviation cleanup for readability
        repl = {
            "H2SO4": "Sulfuric Acid",
            "NaOH": "Sodium Hydroxide",
            "H2O2": "Hydrogen Peroxide",
            "Na2CO3": "Sodium Carbonate",
            "NH3": "Ammonia",
            "Li2CO3": "Lithium Carbonate",
            "Fe(OH)3": "Iron Hydroxide",
            "Al(OH)3": "Aluminium Hydroxide",
            "FeC2O4": "Iron Oxalate",
            "LiH2PO4": "Lithium Dihydrogen Phosphate",
            "CuSO4": "Copper Sulfate",
            "NiSO4": "Nickel Sulfate",
            "CoSO4": "Cobalt Sulfate",
            "MnSO4": "Manganese Sulfate",
            "Cu ": "Copper ",
            "Co ": "Cobalt ",
            "Ni ": "Nickel ",
            "Mn ": "Manganese ",
            "BM ": "Black Mass ",
        }
        out = s
        for a, b in repl.items():
            out = out.replace(a, b)

        out = out.replace("dihydrogenphosphate", "Dihydrogen Phosphate")
        out = out.replace("Ferrous oxalate", "Iron Oxalate")
        out = out.replace("Lithium Carbonate", "Lithium Carbonate")
        out = out.replace(" loaded organic phase", " Loaded Organic Phase")
        out = out.replace("Iron Oxalate cake", "Iron Oxalate Cake")
        out = out.replace("Iron Oxalate washed", "Iron Oxalate Washed")
        return out

    # which step-specific "separated" streams may exist:
    separated_map = {
    "Pack Dismantle": [
        ("Pack Fe (kg/h)", "Pack Fe"),
        ("Pack Al (kg/h)", "Pack Al"),
        ("Pack Cu (kg/h)", "Pack Cu"),
        ("Pack Steel (kg/h)", "Pack Steel"),
        ("Pack Electronics (kg/h)", "Pack Electronics"),
        ("Pack Other/Waste (kg/h)", "Pack Other/Waste"),
    ],
    "Gas Scrubbing": [
        ("Clean gas (N2+Electrolyte) (kg/h)", "Clean gas"),
    ],
    "Magnetic Separation": [
        ("Steel separated – cell packaging (kg/h)", "Steel from cell packaging"),
        ("Steel separated – module steel (kg/h)", "Steel from modules"),
    ],
    "Air-Classification 1": [
        ("Al separated (cell packaging) (kg/h)", "Al separated (cell packaging)"),
        ("Al separated (module) (kg/h)", "Al separated (module)"),
        ("Cu separated (module) (kg/h)", "Cu separated (module)"),
        ("Plastic separated (module) (kg/h)", "Plastic separated (module)"),
        ("Electronics separated (module) (kg/h)", "Electronics separated (module)"),
    ],
    "Sieving": [
        ("Black mass separated (kg/h)", "Black mass"),
    ],
    "Air-Classification 2": [
        ("Plastic separated (separator + pouch foil) (kg/h)", "Plastic (separator + pouch foil)"),
        ("Cu separated (foil) (kg/h)", "Cu foil"),
        ("Al separated (foil) (kg/h)", "Al foil"),
    ],
    "Pyro Smelting": [
        ("Flyash (kg/h)", "Flyash"), 
    ],
    "Pyro Gas scrubbing": [
    ("Clean gas (kg/h)", "Clean gas"),
    ],
    "Hydro Pyro – Cu Filtration": [
    ("Cu metal separated (kg/h)", "Copper"),
    ],
    "Hydro-Pyro - Fe Filtration": [
        ("Iron hydroxide separated (kg/h)", "Iron hydroxide"),
        ("Fe(OH)3 separated (kg/h)", "Fe(OH)3"),
    ],
    "Hydro-Pyro - Co Crystallization": [
        ("CoSO4*7H2O crystals (kg/h)", "CoSO4*7H2O"),
    ],
    "Hydro-Pyro - Ni Crystallization": [
        ("NiSO4*6H2O crystals (kg/h)", "NiSO4*6H2O"),
    ],
    "Hydro LFP – BM Filtration": [
        ("Lye aluminium and binder (kg/h)", "Lye aluminium and binder"),
    ],
    "Hydro Mix – BM Filtration": [
        ("Lye aluminium and binder (kg/h)", "Lye aluminium and binder"),
    ],
    "Hydro LFP – Graphite Filtration": [
        ("Graphite (kg/h)", "Graphite"),
    ],
    "Hydro LFP – Cu Filtration": [
        ("Copper (kg/h)", "Copper"),
    ],
    "Hydro LFP – Oxalate Drying": [
        ("Ferrous oxalate (kg/h)", "Ferrous oxalate"),
    ],
    "Hydro LFP – LiH2PO4 Crystallization": [
        ("Lithium dihydrogenphosphate (kg/h)", "Lithium dihydrogenphosphate"),
    ],
        "Hydro Pyro – Slag SiO2/CaSO4 Filtration": [
        ("SiO2 (kg/h)", "Sand"),
        ("CaSO4 (kg/h)", "CaSO4"),
    ],
    "Hydro Pyro – Fe+Al Filtration": [
        ("Iron hydroxide (kg/h)", "Iron hydroxide"),
        ("Aluminium hydroxide (kg/h)", "Aluminium hydroxide"),
    ],
    "Hydro Pyro – Mn Crystallization": [
        ("MnSO4·H2O crystals (kg/h)", "MnSO4·H2O"),
    ],
    "Hydro Pyro – Li Drying": [
        ("Lithium Carbonate anhydrous (kg/h)", "Lithium Carbonate anhydrous"),
    ],
    "Hydro Pyro – Li Wastewater Treatment": [
        ("Wastewater treated (kg/h)", "Wastewater Treated"),
        ("Sodium Sulfate (kg/h)", "Sodium Sulfate"),
    ],
    "Hydro-Pyro - Alloy Wastewater Treatment": [
        ("Wastewater treated (kg/h)", "Wastewater Treated"),
        ("Sodium Sulfate (kg/h)", "Sodium Sulfate"),
    ],
    "Hydro LFP – Wastewater Treatment": [
        ("Wastewater treated (kg/h)", "Wastewater Treated"),
        ("Sodium Sulfate (kg/h)", "Sodium Sulfate"),
    ],
    "Hydro NMC – Wastewater Treatment": [
        ("Wastewater treated (kg/h)", "Wastewater Treated"),
        ("Sodium Sulfate (kg/h)", "Sodium Sulfate"),
    ],
    "Hydro Mix – Wastewater Treatment": [
        ("Wastewater treated (kg/h)", "Wastewater Treated"),
        ("Sodium Sulfate (kg/h)", "Sodium Sulfate"),
    ],
    "Hydro Mix – Roasting": [
        ("FePO4-C product (kg/h)", "Carbon coated Iron Phosphate (FePO4-C)"),
        ("Off-gas (kg/h)", "Off-gas"),
    ],
        "Hydro Mix – NMC Filtration": [
        ("Mix NMC cake (kg/h)", "Mix NMC cake"),
    ],
    "Hydro Mix – Al Filtration": [
        ("Mix filtered lye separated (kg/h)", "Mix filtered lye"),
    ],
    "Hydro Mix – Graphite Filtration": [
        ("Graphite (kg/h)", "Graphite"),
    ],
    "Hydro Mix – Cu Filtration": [
        ("Copper (kg/h)", "Copper"),
    ],
     "Hydro NMC – Graphite Filtration": [
        ("Graphite (kg/h)", "Graphite"),
    ],
    "Hydro NMC – Cu Filtration": [
        ("Copper (kg/h)", "Copper"),
    ],
        "Hydro NMC – Fe+Al Filtration": [
        ("Iron hydroxide (kg/h)", "Iron hydroxide"),
        ("Aluminium hydroxide (kg/h)", "Aluminium hydroxide"),
    ],
    }

    def _append_yield_loss_separated_row(row) -> None:
        """Yield-based mass in the dedicated *loss* sink as Output-separated (Loss (kg/h)).

        If EFF sets ``loss_sink`` to a normal stream name (e.g. ``Waste`` on Pack Dismantle),
        ``Loss (kg/h)`` duplicates that stream's row and must not be exported again.
        """
        import Recycling_Efficiencies as rfx

        step_name = str(row.get("Step", "")).strip()
        cfg = rfx.get_step_cfg(step_name)
        loss_sink = str(cfg.get("loss_sink", "loss")).strip().lower()
        if loss_sink != "loss":
            return

        m_loss = float(_num(row.get("Loss (kg/h)", 0.0)))
        if not m_loss or m_loss == 0.0:
            return
        label_out = "Waste (process loss)"
        rows.append({
            "Scenario": np.nan,
            "Step": np.nan,
            "Input (kg/h)": np.nan,
            "Output forwarded (kg/h)": np.nan,
            "Name Output forwarded ": np.nan,
            "Materials added (kg/h)": np.nan,
            "Name Material added": np.nan,
            "Output separated (kg/h)": m_loss,
            "Name Output Separated": label_out,
        })


    forwarded_name_map = {
        "Analytics & Sorting": "Battery systems sorted",
        "Discharge": "Battery Systems Discharged",
        "Pack Dismantle": "Modules",
        "Shredding": "Shredded material",
        "Drying": "Dried material",
        "Magnetic Separation": "Non-magnetic fraction",
        "Air-Classification 1": "Intermediate Fragments",
        "Crushing": "Crushed material",
        "Sieving": "Coarse fraction",
        "Air-Classification 2": "Residual coarse fraction",
        "Pyro Smelting": "Alloy, Slag, Offgas",
        "Pyro Gas scrubbing": "clean offgas",
        "Pyro Granulation Alloy": "granulated alloy",
        "Pyro Granulation Slag": "granulated slag",
        "Hydro LFP – Pre Wetting": "BM suspension",
        "Hydro LFP – Alkaline Leaching": "lye alkaline leaching",
        "Hydro LFP – BM Filtration": "BM aluminium clean",
        "Hydro LFP – Digestion": "digested BM solution",
        "Hydro LFP – Leaching": "BM leachate",
        "Hydro LFP – Graphite Filtration": "lye graphite clean",
        "Hydro LFP – Cu Cementation": "lye copper cementation",
        "Hydro LFP – Cu Filtration": "lye copper clean",
        "Hydro LFP – Oxalate Mixing": "lye oxalate mixing",
        "Hydro LFP – Fe Oxalate Precipitation": "lye oxalate precipitation",
        "Hydro LFP – Oxalate Filtration": "lye iron clean",
        "Hydro LFP – Oxalate Washing": "Ferrous oxalate washed",
        "Hydro LFP – Oxalate Drying": "wastewater drying",
        "Hydro LFP – Ion Exchange": "lye clean",
        "Hydro LFP – Li Concentration": "lye concentrated",
        "Hydro LFP – LiH2PO4 Crystallization": "Li mother liquor",
        "Hydro LFP – Wastewater Treatment": "wastewater treated",
        "Hydro Pyro – Alloy Digestion": "digested alloy solution",
        "Hydro Pyro - Alloy Leaching": "alloy leachate",
        "Hydro Pyro – Cu Cementation": "lye copper cementation",
        "Hydro Pyro – Cu Filtration": "lye copper clean",
        "Hydro Pyro – Fe Oxidation": "lye oxidation",
        "Hydro-Pyro - Fe Precipitation": "lye iron precipitation",
        "Hydro-Pyro - Fe Filtration": "lye iron clean",
        "Hydro-Pyro - Co Extraction": "lye after Co extraction",
        "Hydro-Pyro - Co Scrubbing": "Co scrubbed phase",
        "Hydro-Pyro - Co Stripping": "Co stripped solution",
        "Hydro-Pyro - Co Crystallization": "Cobalt Mother Liquor (Wastewater)",
        "Hydro-Pyro - Ni Crystallization": "Nickel Mother Liquor (Wastewater)",
        "Hydro-Pyro - Alloy Wastewater Treatment": "alloy wastewater treated",
        "Hydro Pyro – Slag Digestion": "Digested slag solution",
        "Hydro Pyro – Slag Leaching": "Slag lye",
        "Hydro Pyro – Slag SiO2/CaSO4 Filtration": "Slag clean lye",
        "Hydro Pyro – Slag Fe Oxidation": "Fe-oxidized slag lye",
        "Hydro Pyro – Fe+Al Precipitation": "Lye with Fe/Al precipitated",
        "Hydro Pyro – Fe+Al Filtration": "Lye Fe+Al filtered",
        "Hydro Pyro – Mn Extraction": "Lye after Mn extraction",
        "Hydro Pyro – Mn Scrubbing": "Mn scrubbed phase",
        "Hydro Pyro – Mn Stripping": "Mn stripped solution",
        "Hydro Pyro – Mn Crystallization": "Manganese Mother Liquor (Wastewater)",
        "Hydro Pyro – Li Concentration": "lye concentrated",
        "Hydro Pyro – Li Precipitation": "Li lye after precipitation",
        "Hydro Pyro – Li Filtration": "Li wastewater",
        "Hydro Pyro – Li Washing": "Lithium Carbonate washed",
        "Hydro Pyro – Li Drying": "Lithium Carbonate anhydrous",
        "Hydro Pyro – Li Wastewater Treatment": "Li wastewater treated",
        "Hydro Mix – Digestion": "Mix slurry",
        "Hydro Mix – Al Removal": "Mix lye after Al removal",
        "Hydro Mix – Al Filtration": "Mix solid",
        "Hydro Mix – H2SO4 Digestion": "Mix digested solution 2",
        "Hydro Mix – Leaching": "Mix lye 2",
        "Hydro Mix – Graphite Filtration": "lye graphite clean",
        "Hydro Mix – Cu Cementation": "Mix lye after Cu cementation",
        "Hydro Mix – Cu Filtration": "lye copper clean",
        "Hydro Mix – Ion Exchange Resin": "lye NMC clean",
        "Hydro Mix – Ion Exchange Stripping": "Mix IX stripped solution",
        "Hydro Mix – NMC Mixing": "lye precursor mixing",
        "Hydro Mix – NMC Precipitation": "lye precursor precipitation",
        "Hydro Mix – NMC Filtration": "Mix NMC filtrate",
        "Hydro Mix – NMC Drying": "wastewater drying",
        "Hydro Mix – Li Precipitation": "lye lithium precipitation",
        "Hydro Mix – Li Filtration": "filtration solution",
        "Hydro Mix – Li Washing": "Lithium Carbonate washed",
        "Hydro Mix – Li Drying": "wastewater drying",
        "Hydro Mix – Fe Concentration": "Iron-Concentrated Solution",
        "Hydro Mix – Carbon Dispersion": "Carbon Dispersion Slurry",
        "Hydro Mix – Electrospinning Precursor Formation": "FePO4-C Intermediate",
        "Hydro Mix – Roasting": "Carbon coated Iron Phosphate (FePO4-C)",
        "Hydro NMC – Digestion": "digested BM solution",
        "Hydro NMC – Leaching": "BM leachate",
        "Hydro NMC – Graphite Filtration": "lye graphite clean",
        "Hydro NMC – Cu Cementation": "lye copper cementation",
        "Hydro NMC – Cu Filtration": "lye copper clean",
        "Hydro NMC – Fe Oxidation": "lye oxidation",
        "Hydro NMC – Fe+Al Precipitation": "lye iron, aluminium precipitation",
        "Hydro NMC – Fe+Al Filtration": "lye iron, aluminium clean",
        "Hydro NMC – NMC Precipitation": "lye precursor precipitation",
        "Hydro NMC – NMC Filtration": "lye NMC clean",
        "Hydro NMC – NMC Drying": "wastewater drying",
        "Hydro NMC – Li Precipitation": "lye lithium precipitation",
        "Hydro NMC – Li Drying": "wastewater drying",
    }

    nmc_precip_materials_cols = [
        ("NaOH 50% for sulfate neutralization (kg/h)", "Sodium hydroxide 50%"),
        ("NH3 solution (kg/h)", "Ammonia makeup"),
        ("NiSO4 makeup (kg/h)", "Nickel sulfate"),
        ("CoSO4 makeup (kg/h)", "Cobalt sulfate"),
        ("MnSO4 makeup (kg/h)", "Manganese sulfate"),
    ]
    # IX: resin attrition/regeneration makeup — reporting/OPEX only (not in liquid mass flow)
    ix_resin_materials_cols = [
        ("CH-90 Na makeup (kg/h)", "CH-90 Na resin makeup"),
    ]
    materials_added_cols = [
        ("Limestone added (kg/h)", "Limestone"),
        ("Sand added (kg/h)", "Sand"),
        ("Oxygen added (kg/h)", "Oxygen"),
        ("H2SO4 95% added (kg/h)", "Sulfuric acid 95%"),
        ("H2O added (kg/h)", "Water"),
        ("Fe added (kg/h)", "Iron Powder"),
        ("H2O2 added (kg/h)", "Hydrogen peroxide"),
        ("NaOH added (kg/h)", "Sodium hydroxide 50%"),
        ("Na2CO3 added (kg/h)", "Sodium carbonate"),
        ("Oxalic acid pure added (kg/h)", "Oxalic acid"),
        ("Water for oxalic solution (kg/h)", "Water"),
        ("Ethanol added (kg/h)", "Ethanol"),
        ("H2SO4 95% added for stripping (kg/h)", "Sulfuric acid 95%"),
        ("NaOH 50% added for NMC precipitation (kg/h)", "Sodium hydroxide 50%"),
        ("NaOH 50% for sulfate neutralization (kg/h)", "Sodium hydroxide 50%"),
        ("NaOH 50% (kg/h)", "Sodium hydroxide 50%"),
        ("NH3 solution (kg/h)", "Ammonia makeup"),
        ("NiSO4 makeup (kg/h)", "Nickel sulfate"),
        ("CoSO4 makeup (kg/h)", "Cobalt sulfate"),
        ("MnSO4 makeup (kg/h)", "Manganese sulfate"),
        ("H2O added 2 (kg/h)", "Water"),
        ("Water added (kg/h)", "Water"),
        ("Water added for washing (kg/h)", "Water"),
        ("Wash water added (kg/h)", "Water"),
        ("NaOH pure added (kg/h)", "Sodium hydroxide"),
        ("NaOH solution water added (kg/h)", "Water for sodium hydroxide solution"),
        ("PVP added (kg/h)", "PVP"),
        ("DMF added (kg/h)", "DMF (Circulating)"),
        ("DMF make-up (kg/h)", "DMF make-up"),
        ("DMF circulating (kg/h)", "DMF (Circulating)"),
        ("D2EHPA added (kg/h)", "D2EHPA"),
        ("NaOH 50% for extraction pH (kg/h)", "Sodium hydroxide 50%"),
        ("Cyanex 272 added (kg/h)", "Cyanex 272"),
        ("Cyanex 272 circulating (kg/h)", "Cyanex 272 (circulating)"),
        ("Cyanex 301GN added (kg/h)", "Cyanex 301GN"),
        ("D2EHPA circulating (kg/h)", "D2EHPA (circulating)"),
        ("Kerosene circulating (kg/h)", "Kerosene (circulating)"),
        ("H2O added NMC (kg/h)", "Water"),
        ("CH-90 Na makeup (kg/h)", "CH-90 Na resin makeup"),
        ("Nitrogen for shredding (kg/h)", "Nitrogen"),
    ]

    _STRIPPING_SOLVENT_CIRC_COLS = frozenset({
        "D2EHPA circulating (kg/h)",
        "Kerosene circulating (kg/h)",
        "Cyanex 272 circulating (kg/h)",
    })
    _SOLVENT_CIRC_SKIP_MATERIAL_STEPS = frozenset({
        "Hydro Pyro – Mn Scrubbing",
        "Hydro-Pyro - Co Scrubbing",
        "Hydro Pyro – Mn Stripping",
        "Hydro-Pyro - Co Stripping",
    })

    def _materials_added_entries(step_name: str, row) -> list[tuple[float, str]]:
        """Non-zero process materials: first on main row, rest as sub-rows below."""
        if step_name in ("Hydro NMC – NMC Precipitation", "Hydro Mix – NMC Precipitation"):
            cols = nmc_precip_materials_cols
        elif step_name in ("Hydro LFP – Ion Exchange", "Hydro Mix – Ion Exchange Resin"):
            cols = ix_resin_materials_cols
        elif step_name == "Hydro Mix – Carbon Dispersion":
            cols = [
                ("PVP added (kg/h)", "PVP"),
                ("DMF make-up (kg/h)", "DMF make-up"),
                ("DMF circulating (kg/h)", "DMF (Circulating)"),
            ]
        elif step_name == "Hydro Mix – Electrospinning Precursor Formation":
            cols = []
        else:
            cols = materials_added_cols
        out: list[tuple[float, str]] = []
        for col, label in cols:
            if step_name in _SOLVENT_CIRC_SKIP_MATERIAL_STEPS and col in _STRIPPING_SOLVENT_CIRC_COLS:
                continue
            v = _num(row.get(col, 0.0))
            if v and v != 0:
                out.append((float(v), str(label)))
        return out

    def _append_material_subrows(mat_sub: list[tuple[float, str]]) -> None:
        for v, name in mat_sub:
            rows.append({
                "Scenario": np.nan,
                "Step": np.nan,
                "Input (kg/h)": np.nan,
                "Materials added (kg/h)": v,
                "Name Material added": name,
                "Output forwarded (kg/h)": np.nan,
                "Name Output forwarded ": np.nan,
                "Output separated (kg/h)": np.nan,
                "Name Output Separated": np.nan,
            })

    def _append_separated_subrows_from_map(step_name: str, row) -> None:
        for col, label in separated_map.get(step_name, []):
            v = _num(row.get(col, 0.0))
            if v and v != 0:
                rows.append({
                    "Scenario": np.nan,
                    "Step": np.nan,
                    "Input (kg/h)": np.nan,
                    "Output forwarded (kg/h)": np.nan,
                    "Name Output forwarded ": np.nan,
                    "Materials added (kg/h)": np.nan,
                    "Name Material added": np.nan,
                    "Output separated (kg/h)": v,
                    "Name Output Separated": label,
                })

    # Wastewater treatment: all products as "Output separated", not as forward in the main row
    steps_wastewater_outputs_as_separated = {
        "Hydro NMC – Wastewater Treatment",
        "Hydro Mix – Wastewater Treatment",
        "Hydro Pyro – Li Wastewater Treatment",
        "Hydro LFP – Wastewater Treatment",
        "Hydro-Pyro - Alloy Wastewater Treatment",
        "Pyro Gas scrubbing",
    }

    # First separated product on the main row (next to input); rest as sub-rows
    steps_separated_on_main = {
        "Gas Scrubbing",
        "Air-Classification 2",
    }

    # Products as „Output separated“ only (no forward on main row).
    steps_products_as_separated_only = frozenset({
        "Hydro Mix – Roasting",
    })

    # For some steps all "Output forwarded" sub-rows should appear directly below each other,
    # before additional "Materials added" sub-rows (default: material subs first, then additional forwards).
    _MULTI_FWD_FORWARDS_BEFORE_MATERIAL_SUBROWS = frozenset({
        "Hydro Pyro – Mn Extraction",
        "Hydro-Pyro - Co Extraction",
        "Hydro Mix – Electrospinning Precursor Formation",
    })

    # Multiple forward outputs per step (each with its own "Output forwarded" row)
    forwarded_streams_map = {
        "Shredding": [
            ("Shredded material (kg/h)", "Shredded material"),
            ("Off gas (kg/h)", "Off gas"),
        ],
        "Drying": [
            ("Dried material (kg/h)", "Dried material"),
            ("Electrolyte (kg/h)", "Electrolyte"),
        ],
        "Hydro NMC – NMC Filtration": [
            ("NMC Precursor (kg/h)", "NMC Precursor"),
            ("Lye NMC clean (kg/h)", "lye NMC clean"),
        ],
        "Hydro Mix – NMC Filtration": [
            ("NMC Precursor (kg/h)", "NMC Precursor"),
            ("Lye NMC clean (kg/h)", "lye NMC clean"),
        ],
        "Hydro LFP – Oxalate Filtration": [
            ("Lye iron clean (kg/h)", "lye iron clean"),
            ("Ferrous oxalate cake (kg/h)", "Ferrous oxalate cake"),
        ],
        "Hydro LFP – Ion Exchange": [
            ("Lye clean (kg/h)", "lye clean"),
            ("Loaded resin (kg/h)", "loaded_resin"),
        ],
        "Hydro LFP – Li Concentration": [
            ("Lye concentrated (kg/h)", "lye concentrated"),
            ("Wastewater (kg/h)", "wastewater"),
        ],
        "Hydro Pyro – Li Concentration": [
            ("Lye concentrated (kg/h)", "lye concentrated"),
            ("Wastewater (kg/h)", "wastewater"),
        ],
        "Hydro Pyro – Li Precipitation": [
            ("Lye lithium precipitation (kg/h)", "lye lithium precipitation"),
        ],
        "Hydro Pyro – Li Filtration": [
            ("Lithium Carbonate (kg/h)", "Lithium Carbonate"),
            ("Wastewater filtration (kg/h)", "Li wastewater"),
        ],
        "Hydro Pyro – Li Washing": [
            ("Lithium Carbonate washed (kg/h)", "Lithium Carbonate washed"),
            ("Wastewater washing (kg/h)", "wastewater washing"),
        ],
        "Hydro Pyro – Li Drying": [
            ("Wastewater drying (kg/h)", "wastewater drying"),
        ],
        "Hydro Mix – Ion Exchange Resin": [
            ("Lye NMC clean (kg/h)", "Ni-Mn-Co-Depleted Solution"),
            ("Loaded resin (kg/h)", "Ni-Mn-Co-Loaded Resin"),
        ],
        "Hydro NMC – Li Filtration": [
            ("Lithium Carbonate (kg/h)", "Lithium Carbonate"),
            ("Residual lye (kg/h)", "residual lye"),
        ],
        "Hydro Mix – Li Filtration": [
            ("Lithium Carbonate (kg/h)", "Lithium Carbonate"),
            ("Filtration solution (kg/h)", "filtration solution"),
        ],
        "Hydro Mix – Fe Concentration": [
            ("Lye concentrated (kg/h)", "Iron-Concentrated Solution"),
            ("Wastewater (kg/h)", "Wastewater"),
        ],
        "Hydro Mix – Electrospinning Precursor Formation": [
            ("FePO4-C Intermediate (kg/h)", "FePO4-C Intermediate"),
            ("Mother Liquor (Fe/P depleted) (kg/h)", "Mother Liquor (Fe/P depleted, Wastewater)"),
            ("DMF circulating (kg/h)", "DMF (Circulating)"),
        ],
        "Hydro Pyro – Mn Extraction": [
            ("Lye after Mn extraction (kg/h)", "Lye after Mn extraction"),
            ("Mn loaded organic phase (kg/h)", "Mn loaded organic phase"),
        ],
        "Hydro-Pyro - Co Extraction": [
            ("Lye after Co extraction (kg/h)", "Lye after Co extraction"),
            ("Co loaded organic phase (kg/h)", "Co loaded organic phase"),
        ],
        "Hydro Pyro – Mn Stripping": [
            ("Mn stripped solution (kg/h)", "Mn stripped solution"),
            ("D2EHPA circulating (kg/h)", "D2EHPA (circulating)"),
            ("Kerosene circulating (kg/h)", "Kerosene (circulating)"),
        ],
        "Hydro-Pyro - Co Stripping": [
            ("Co stripped solution (kg/h)", "Co stripped solution"),
            ("Cyanex 272 circulating (kg/h)", "Cyanex 272 (circulating)"),
            ("Kerosene circulating (kg/h)", "Kerosene (circulating)"),
        ],
    }

    for _, r in steps_df.iterrows():
        step = str(r.get("Step","")).strip()
        if not step:
            continue

        skip_global_multi_fwd_sep = False
        in_kgh = _num(r.get("In kg/h", 0.0))
        out_fwd = _num(r.get("Out forward kg/h", r.get("Out kg/h", 0.0)))
        mat_entries = _materials_added_entries(step, r)
        if mat_entries:
            mat_main_v, mat_main_name = mat_entries[0]
            mat_sub_entries = mat_entries[1:]
        else:
            mat_main_v, mat_main_name = np.nan, np.nan
            mat_sub_entries = []
        sep_entries = [
            (col, label)
            for col, label in separated_map.get(step, [])
            if (_v := _num(r.get(col, 0.0))) and _v != 0
        ]
        sep_rows_for_sub = list(sep_entries)

        multi_fwd = forwarded_streams_map.get(step)
        if multi_fwd:
            fwd_entries = [
                (col, label)
                for col, label in multi_fwd
                if (_v := _num(r.get(col, 0.0))) and _v != 0
            ]
            if fwd_entries:
                first_col, first_label = fwd_entries[0]
                first_v = _num(r.get(first_col, 0.0))
                rows.append({
                    "Scenario": scen_name,
                    "Step": step,
                    "Input (kg/h)": in_kgh,
                    "Materials added (kg/h)": mat_main_v,
                    "Name Material added": mat_main_name,
                    "Output separated (kg/h)": np.nan,
                    "Name Output Separated": np.nan,
                    "Output forwarded (kg/h)": first_v,
                    "Name Output forwarded ": first_label,
                })
                if step in _MULTI_FWD_FORWARDS_BEFORE_MATERIAL_SUBROWS:
                    for col, label in fwd_entries[1:]:
                        v = _num(r.get(col, 0.0))
                        rows.append({
                            "Scenario": np.nan,
                            "Step": np.nan,
                            "Input (kg/h)": np.nan,
                            "Materials added (kg/h)": np.nan,
                            "Name Material added": np.nan,
                            "Output separated (kg/h)": np.nan,
                            "Name Output Separated": np.nan,
                            "Output forwarded (kg/h)": v,
                            "Name Output forwarded ": label,
                        })
                    _append_material_subrows(mat_sub_entries)
                    _append_separated_subrows_from_map(step, r)
                    skip_global_multi_fwd_sep = True
                else:
                    _append_material_subrows(mat_sub_entries)
                    for col, label in fwd_entries[1:]:
                        v = _num(r.get(col, 0.0))
                        rows.append({
                            "Scenario": np.nan,
                            "Step": np.nan,
                            "Input (kg/h)": np.nan,
                            "Materials added (kg/h)": np.nan,
                            "Name Material added": np.nan,
                            "Output separated (kg/h)": np.nan,
                            "Name Output Separated": np.nan,
                            "Output forwarded (kg/h)": v,
                            "Name Output forwarded ": label,
                        })
            else:
                rows.append({
                    "Scenario": scen_name,
                    "Step": step,
                    "Input (kg/h)": in_kgh,
                    "Materials added (kg/h)": mat_main_v,
                    "Name Material added": mat_main_name,
                    "Output separated (kg/h)": np.nan,
                    "Name Output Separated": np.nan,
                    "Output forwarded (kg/h)": np.nan,
                    "Name Output forwarded ": np.nan,
                })
                _append_material_subrows(mat_sub_entries)
        else:
            # 1) Main row per step (one forward output)
            ww_sep_only = step in steps_wastewater_outputs_as_separated
            sep_only_products = step in steps_products_as_separated_only
            main_sep_v = np.nan
            main_sep_label = np.nan
            if ww_sep_only and sep_entries:
                main_sep_v = _num(r.get(sep_entries[0][0], 0.0))
                main_sep_label = sep_entries[0][1]
                sep_rows_for_sub = sep_entries[1:]
            elif step in steps_separated_on_main and sep_entries:
                main_sep_v = _num(r.get(sep_entries[0][0], 0.0))
                main_sep_label = sep_entries[0][1]
                sep_rows_for_sub = sep_entries[1:]
            elif sep_only_products and sep_entries:
                main_sep_v = _num(r.get(sep_entries[0][0], 0.0))
                main_sep_label = sep_entries[0][1]
                sep_rows_for_sub = sep_entries[1:]

            rows.append({
                "Scenario": scen_name,
                "Step": step,
                "Input (kg/h)": in_kgh,
                "Materials added (kg/h)": mat_main_v,
                "Name Material added": mat_main_name,
                "Output separated (kg/h)": main_sep_v,
                "Name Output Separated": main_sep_label,
                "Output forwarded (kg/h)": np.nan if (ww_sep_only or sep_only_products) else (out_fwd if out_fwd != 0 else np.nan),
                "Name Output forwarded ": np.nan if (ww_sep_only or sep_only_products) else (
                    forwarded_name_map.get(step, r.get("Forward key", np.nan))
                    if out_fwd != 0
                    else np.nan
                ),
            })
            _append_material_subrows(mat_sub_entries)

        # 2) individual "separated" rows below (as before)
        sep_rows = (
            []
            if (multi_fwd and skip_global_multi_fwd_sep)
            else (list(separated_map.get(step, [])) if multi_fwd else sep_rows_for_sub)
        )
        for col, label in sep_rows:
            v = _num(r.get(col, 0.0))
            if v and v != 0:
                rows.append({
                    "Scenario": np.nan,
                    "Step": np.nan,
                    "Input (kg/h)": np.nan,
                    "Output forwarded (kg/h)": np.nan,
                    "Name Output forwarded ": np.nan,
                    "Materials added (kg/h)": np.nan,
                    "Name Material added": np.nan,
                    "Output separated (kg/h)": v,
                    "Name Output Separated": label,
                })
        if step in ("Hydro NMC – NMC Drying", "Hydro Mix – NMC Drying"):
            prod_label = str(r.get("NMC precursor product", "")).strip()
            if not prod_label:
                code = str(r.get("NMC code", "811")).strip()
                prod_label = f"NMC {code} Precursor"
            v = _num(r.get("NMC precursor dried (kg/h)", 0.0))
            if v and v != 0:
                rows.append({
                    "Scenario": np.nan,
                    "Step": np.nan,
                    "Input (kg/h)": np.nan,
                    "Output forwarded (kg/h)": np.nan,
                    "Name Output forwarded ": np.nan,
                    "Materials added (kg/h)": np.nan,
                    "Name Material added": np.nan,
                    "Output separated (kg/h)": v,
                    "Name Output Separated": prod_label,
                })
        if step in ("Hydro NMC – Li Drying", "Hydro Mix – Li Drying"):
            v = _num(r.get("Lithium Carbonate anhydrous (kg/h)", 0.0))
            if v and v != 0:
                rows.append({
                    "Scenario": np.nan,
                    "Step": np.nan,
                    "Input (kg/h)": np.nan,
                    "Output forwarded (kg/h)": np.nan,
                    "Name Output forwarded ": np.nan,
                    "Materials added (kg/h)": np.nan,
                    "Name Material added": np.nan,
                    "Output separated (kg/h)": v,
                    "Name Output Separated": "Lithium Carbonate anhydrous",
                })
        _append_yield_loss_separated_row(r)
    df_out = pd.DataFrame(rows, columns=MASSFLOW_LONG_COLS)
    for c in ("Name Output forwarded ", "Name Output Separated", "Name Material added"):
        if c in df_out.columns:
            df_out[c] = df_out[c].map(_standardize_display_name)
    if "Name Output forwarded " in df_out.columns:
        def _normalize_forwarded_wastewater(v):
            if not isinstance(v, str):
                return v
            vv = v.strip().lower()
            if vv in {
                "wastewater",
                "li wastewater",
                "alloy wastewater treated",
                "li wastewater treated",
            }:
                return "Wastewater"
            return v
        df_out["Name Output forwarded "] = df_out["Name Output forwarded "].map(_normalize_forwarded_wastewater)
    return df_out

# ==== CAPEX (works with Discharge breakdown) ====
def _norm_step_name(name: str) -> str:
    """Normalize step labels for lookup (dash variants, whitespace)."""
    s = str(name or "").strip()
    for ch in ("\u2013", "\u2014", "\u2212"):
        s = s.replace(ch, "-")
    return " ".join(s.split()).lower()


def _resolve_step_key(step_name: str, steps_index: dict[str, float]) -> str:
    """
    Map extras/breakdown step label -> steps_df Step key for mass lookup.
    """
    if step_name in steps_index:
        return step_name
    norm_map = {_norm_step_name(k): k for k in steps_index}
    hit = norm_map.get(_norm_step_name(step_name))
    if hit:
        return hit
    return step_name


def _find_breakdown_frames(extras: dict) -> list[tuple[str, pd.DataFrame]]:
    out: list[tuple[str, pd.DataFrame]] = []
    ACCEPT_SUBKEYS = {"breakdown"}

    def normalize_one(df: pd.DataFrame) -> pd.DataFrame | None:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None

        required = ["Unit", "n_lines", "line_tph", "CAPEX equip ($)", "CAPEX building ($)"]
        if any(c not in df.columns for c in required):
            return None

        df2 = df[required].copy()
        df2["n_lines"] = pd.to_numeric(df2["n_lines"], errors="coerce").fillna(0.0)
        df2["line_tph"] = pd.to_numeric(df2["line_tph"], errors="coerce").fillna(0.0)
        df2["CAPEX equip ($)"]    = pd.to_numeric(df2["CAPEX equip ($)"],    errors="coerce").fillna(0.0)
        df2["CAPEX building ($)"] = pd.to_numeric(df2["CAPEX building ($)"], errors="coerce").fillna(0.0)
        if (df2["CAPEX equip ($)"].sum() == 0) and (df2["CAPEX building ($)"].sum() == 0):
            return None
        return df2[["Unit","n_lines","line_tph","CAPEX equip ($)","CAPEX building ($)"]]

    def walk(node, parent_step=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, pd.DataFrame):
                    if str(k).strip().lower() in ACCEPT_SUBKEYS and parent_step:
                        df2 = normalize_one(v)
                        if df2 is not None:
                            out.append((parent_step, df2))
                elif isinstance(v, dict):
                    # Use inner dict key (module step name), not outer main.py alias.
                    walk(v, parent_step=str(k))
        elif isinstance(node, list):
            for v in node:
                walk(v, parent_step=parent_step)
    walk(extras or {})
    return out

def _capex_collect(steps_df: pd.DataFrame, scen_name: str, extras: dict | None) -> pd.DataFrame:
    s_in, s_out = {}, {}
    if "Step" in steps_df.columns:
        for _, r in steps_df.iterrows():
            step = str(r.get("Step",""))
            s_in[step]  = float(pd.to_numeric(pd.Series([r.get("In kg/h", 0)]), errors="coerce").fillna(0.0).iloc[0])
            s_out[step] = float(pd.to_numeric(pd.Series([r.get("Out forward kg/h", r.get("Out kg/h", 0))]), errors="coerce").fillna(0.0).iloc[0])
    rows: list[dict] = []
    for step_name, dfb in _find_breakdown_frames(extras or {}):
        report_step = step_name
        if "Step" in dfb.columns and len(dfb):
            report_step = str(dfb["Step"].iloc[0])
        lookup_step = _resolve_step_key(report_step, s_in)
        n_lines  = pd.to_numeric(dfb["n_lines"], errors="coerce").fillna(0.0)
        line_tph = pd.to_numeric(dfb["line_tph"], errors="coerce").fillna(0.0)
        cap_step = pd.to_numeric(dfb["CAPEX equip ($)"], errors="coerce").fillna(0.0)
        bld_step = pd.to_numeric(dfb["CAPEX building ($)"], errors="coerce").fillna(0.0)
        cap_per_m = (cap_step / n_lines.replace(0, np.nan)).fillna(0.0)
        bld_per_m = (bld_step / n_lines.replace(0, np.nan)).fillna(0.0)
        for i in range(len(dfb)):
            rows.append({
                "Scenario": scen_name, "Step": lookup_step,
                "In kg/h": s_in.get(lookup_step, 0.0),
                "Output forwarded (kg/h)": s_out.get(lookup_step, 0.0),
                "Machines": n_lines.iloc[i], "Line capacity (t/h)": line_tph.iloc[i],
                "Machine name(s)": str(dfb["Unit"].iloc[i]),
                "CAPEX equip per machine($)": cap_per_m.iloc[i], "CAPEX equip per step ($)": cap_step.iloc[i],
                "Building per machine $": bld_per_m.iloc[i], "Building per step $": bld_step.iloc[i],
            })

    covered_steps = {str(r["Step"]) for r in rows}
    if "Step" in steps_df.columns:
        for _, r in steps_df.iterrows():
            step = str(r.get("Step", "")).strip()
            if not step or step in covered_steps:
                continue
            n_lines = float(pd.to_numeric(r.get("Machines", 0), errors="coerce") or 0.0)
            cap_step = float(pd.to_numeric(r.get("CAPEX equip ($)", 0), errors="coerce") or 0.0)
            bld_step = float(pd.to_numeric(r.get("CAPEX building ($)", 0), errors="coerce") or 0.0)
            if n_lines < 1 and cap_step <= 0.0 and bld_step <= 0.0:
                continue
            line_tph = float(pd.to_numeric(r.get("Line capacity (t/h)", 0), errors="coerce") or 0.0)
            cap_per_m = cap_step / n_lines if n_lines > 0 else 0.0
            bld_per_m = bld_step / n_lines if n_lines > 0 else 0.0
            rows.append({
                "Scenario": scen_name,
                "Step": step,
                "In kg/h": s_in.get(step, 0.0),
                "Output forwarded (kg/h)": s_out.get(step, 0.0),
                "Machines": n_lines,
                "Line capacity (t/h)": line_tph,
                "Machine name(s)": "-",
                "CAPEX equip per machine($)": cap_per_m,
                "CAPEX equip per step ($)": cap_step,
                "Building per machine $": bld_per_m,
                "Building per step $": bld_step,
            })
            covered_steps.add(step)

    return pd.DataFrame(rows, columns=CAPEX_COLS)

# ==== Cost_Structure & Normal_costs (keep; will be empty with Discharge-only) ====
def _cost_structure_from_economics_overhead(oh: dict, scen_name: str) -> pd.DataFrame:
    if not isinstance(oh, dict): 
        return pd.DataFrame(columns=COST_STRUCTURE_COLS)

    capex = oh.get("capex"); manuf = oh.get("manufacturing")
    if not isinstance(capex, pd.DataFrame) or capex.empty or not isinstance(manuf, pd.DataFrame) or manuf.empty:
        return pd.DataFrame(columns=COST_STRUCTURE_COLS)

    cap = capex.iloc[0].to_dict()
    mf  = manuf.iloc[0].to_dict()

    def g(d, key, default=0.0):
        try:
            return float(d.get(key, default) or 0.0)
        except Exception:
            return default

    # ---- CAPEX (I, II, III, IV, V) ----
    IA1 = g(cap,"I.A.1 Purchased equip ($)")
    IA2 = g(cap,"I.A.2 Installation ($)")
    IA3 = g(cap,"I.A.3 Instr & controls ($)")
    IA4 = g(cap,"I.A.4 Piping ($)")
    IA5 = g(cap,"I.A.5 Electrical ($)")
    IA  = g(cap,"I.A Installed ($)")
    IB  = g(cap,"I.B Building ($)")
    IC  = g(cap,"I.C Service facilities ($)")
    ID  = g(cap,"I.D Land ($)")
    I   = g(cap,"I Direct costs ($)")

    IIA = g(cap,"II.A Engineering ($)")
    IIB = g(cap,"II.B Construction ($)")
    IIC = g(cap,"II.C Contingency ($)")
    II  = g(cap,"II Indirect ($)")
    III = g(cap,"III Fixed Capital ($)")
    IV  = g(cap,"IV Working Capital ($)")
    V   = g(cap,"V Total Capital ($)")

    # ---- Manufacturing (VI) & General (VII) from Economics Overhead ----
    VI_A1 = g(mf,"VI.A.1 Raw materials ($/y)")
    VI_A2 = g(mf,"VI.A.2 Utilities ($/y)")   # <- utilities exactly like Opex (energy+water) from overhead
    VI_A3 = g(mf,"VI.A.3 Oper. labor ($/y)")
    VI_A4 = g(mf,"VI.A.4 Supervisory ($/y)")
    VI_A5 = g(mf,"VI.A.5 Maintenance ($/y)")
    VI_A6 = g(mf,"VI.A.6 Supplies ($/y)")
    VI_A7 = g(mf,"VI.A.7 Laboratory ($/y)")
    VI_A8 = g(mf,"VI.A.8 Patents ($/y)")
    VI_A  = g(mf,"VI.A Total ($/y)")

    VI_B1 = g(mf,"VI.B.1 Depreciation ($/y)")
    VI_B2 = g(mf,"VI.B.2 Taxes ($/y)")
    VI_B3 = g(mf,"VI.B.3 Insurance ($/y)")
    VI_B4 = g(mf,"VI.B.4 Rent ($/y)")
    VI_B5 = g(mf,"VI.B.5 Financing ($/y)")
    VI_B  = g(mf,"VI.B Total ($/y)")

    VI_C  = g(mf,"VI.C Overhead ($/y)")
    VI    = g(mf,"VI Manufacturing ($/y)")

    # Admin: use explicit value if provided; otherwise compute from base formula.
    VII_A_admin_from_df = g(mf, "VII.A Administrative ($/y)")
    VII_A_calc = 0.15 * (VI_A3 + VI_A4 + VI_A5)
    VII_A = VII_A_admin_from_df if VII_A_admin_from_df > 0 else VII_A_calc

    VII_B = g(mf,"VII.B Distribution ($/y)", 0.0)  # if not maintained -> 0
    VII_C = g(mf,"VII.C R&D ($/y)", 0.0)          # if not maintained -> 0
    VII   = g(mf,"VII General ($/y)")

    VIII  = g(mf,"VIII Total Product Cost ($/y)")

    rows = [
        # I
        ("I.A.1 Purchased equipment", IA1),
        ("I.A.2 Installation (15%)",  IA2),
        ("I.A.3 Instr. & controls (10%)", IA3),
        ("I.A.4 Piping (10%)", IA4),
        ("I.A.5 Electrical (incl.)", IA5),
        ("I.A Equipment subtotal", IA),
        ("I.B Building (area×price)", IB),
        ("I.C Services & yard (40% of I.A.1)", IC),
        ("I.D Land (1% of I.A.1)", ID),
        ("I Direct Costs", I),

        # II–V
        ("II.A Eng. & supervision (10% of I)", IIA),
        ("II.B Construction (10% of I)", IIB),
        ("II.C Contingency (5% of I)", IIC),
        ("II Indirect Costs", II),
        ("III Fixed Capital Investment", III),
        ("IV Working Capital (10% of III)", IV),
        ("V Total Capital Investment", V),

        # VI.A
        ("VI.A.1 Raw materials", VI_A1),
        ("VI.A.2 Utilities (energy+water)", VI_A2),     # <- comes 1:1 from overhead
        ("VI.A.3 Operating labor", VI_A3),
        ("VI.A.4 Direct supervisory (15% of VI.A.3)", VI_A4),
        ("VI.A.5 Maintenance (5% of I.A)", VI_A5),
        ("VI.A.6 Operating supplies (15% of VI.A.5)", VI_A6),
        ("VI.A.7 Laboratory (10% of VI.A.3)", VI_A7),
        ("VI.A.8 Patents & royalties", VI_A8),
        ("VI.A Direct product costs", VI_A),

        # VI.B/C + VI
        ("VI.B.1 Depreciation", VI_B1),
        ("VI.B.2 Local taxes (2% of III)", VI_B2),
        ("VI.B.3 Insurance (1% of III)", VI_B3),
        ("VI.B.4 Rent", VI_B4),
        ("VI.B.5 Financing", VI_B5),
        ("VI.B Fixed charges", VI_B),
        ("VI.C Plant overhead (50% of (VI.A.3+VI.A.4+VI.A.5))", VI_C),
        ("VI Manufacturing costs", VI),

        # VII
        ("VII.A Administrative (15% of (VI.A.3+VI.A.4+VI.A.5))", VII_A),
        ("VII.B Distribution & selling", VII_B),
        ("VII.C R&D", VII_C),
        ("VII General expenses", VII),

        # VIII
        ("VIII Total Product Cost", VIII),
    ]

    df2 = pd.DataFrame(rows, columns=["Cost Item","$/year"])
    df2["Scenario"] = scen_name
    return df2[["Cost Item","$/year","Scenario"]]

def _empty_cost_structure(scen_name: str) -> pd.DataFrame:
    # Empty structure if centralized economics overhead block is unavailable.
    return pd.DataFrame(columns=COST_STRUCTURE_COLS)

# ==== Normal_costs ====
# ==== Main ====
def main():
    hours_y = float(gp.get_working_hours_per_year())

    overview_rows = []
    runinfo_rows = []
    scen2mass = {}      # Scenario -> Battery cell mass (kg/year) for per-kg normalization
    scen2mix = {}       # Scenario -> CellVariant mix (shares)
    scen2packmass = {}  # Scenario -> Feed mass (kg/year)

    # Collectors
    material_raw_all = []
    massflow_all, capex_all = [], []
    coststruct_all = []
    recovery_all: list[pd.DataFrame] = []
    econ_env_sheet_collectors: dict[str, list[pd.DataFrame]] = {}
    infrastructure_rows: list[dict] = []
    kpi_rows = []

    # === Run scenarios ===
    from main import SCENARIOS, run_scenario

    for scen in SCENARIOS:
        scen_name = str(scen["name"])
        steps_df, extras, ctx = run_scenario(scen)
        runinfo_rows.append(_run_info_row(scen, ctx))

        in_kgh = float(pd.to_numeric(steps_df.get("In kg/h", pd.Series([0.0])).iloc[0], errors="coerce") or 0.0)
        feed_kgh = in_kgh

        cell_mass_y = float(ctx.get("cell_mass_kg_per_year", 0.0) or 0.0)
        if cell_mass_y <= 0:
            cell_mass_y = in_kgh * hours_y

        pack_mass_y = float(ctx.get("feed_mass_kg_per_year", 0.0) or (in_kgh * hours_y))
        scen2mass[scen_name] = pack_mass_y
        scen2packmass[scen_name] = pack_mass_y

        overview_rows.append({
            "Scenario": scen_name,
            "Battery cell mass (kg/year)": cell_mass_y,
            "Feed (kg/h)": feed_kgh,
            "Feed mass (kg/year)": pack_mass_y,
        })

        # --- Material Input: Variant mix label (CellVariant) ---
        variant_mix = {}
        for d in (ctx.get("feed_details") or []):
            cid = str(d.get("cell_id") or "").strip()
            share = float(d.get("share") or 0.0)
            label = _cell_label(cid, d)
            variant_mix[label] = variant_mix.get(label, 0.0) + share

        s = sum(max(v, 0.0) for v in variant_mix.values())
        if s > 0:
            variant_mix = {k: v/s for k, v in variant_mix.items()}

        scen2mix[scen_name] = variant_mix

        # --- Material Input RAW rows ---
        rows_raw = _rows_for_material_input(scen_name=scen_name, ctx=ctx)
        material_raw_all.extend(rows_raw)

        # --- Massflow / Capex / Cost structure ---
        mf = _massflow_long(steps_df, scen_name)
        massflow_all += [mf, pd.DataFrame([[""] * len(MASSFLOW_LONG_COLS)] * 2, columns=MASSFLOW_LONG_COLS)]

        oh = extras.get("Overhead", {})
        if not isinstance(oh, dict):
            raise ValueError("extras['Overhead'] missing or invalid.")

        capex = _capex_collect(steps_df, scen_name, extras)
        capex_all += [capex, pd.DataFrame([[""] * len(CAPEX_COLS)] * 2, columns=CAPEX_COLS)]

        cs = _cost_structure_from_economics_overhead(oh, scen_name)
        if cs is None or cs.empty:
            cs = _empty_cost_structure(scen_name)
        coststruct_all += [cs, pd.DataFrame([[""] * len(COST_STRUCTURE_COLS)] * 2, columns=COST_STRUCTURE_COLS)]

        kpi = _kpi_from_economics(oh, pack_mass_y)
        kpi_rows.append({
            "Scenario": scen_name,
            "Total product costs ($/kg)": float(kpi["tpc_per_kg"]),
            "Revenue ($/kg battery)": float(kpi["revenue_per_kg"]),
            "Profit ($/kg battery)": float(kpi["profit_per_kg"]),
            "Net GWP (kg CO2e/kg battery)": float(kpi["net_gwp_per_kg"]),
        })

        rc_df = _recovery_df_for_export(steps_df, ctx, oh, scen_name)
        if not rc_df.empty:
            recovery_all.append(rc_df)
            recovery_all.append(pd.DataFrame([[""] * len(rc_df.columns)], columns=rc_df.columns))

        sheet_map = _economics_environment_sheets(oh, ctx, scen_name)
        for sheet_name, df_sheet in sheet_map.items():
            if df_sheet is None or df_sheet.empty:
                continue
            econ_env_sheet_collectors.setdefault(sheet_name, []).append(df_sheet)
            # visual separation between scenarios in multi-scenario exports
            econ_env_sheet_collectors[sheet_name].append(
                pd.DataFrame([[""] * len(df_sheet.columns)] * 2, columns=df_sheet.columns)
            )

        infrastructure_rows.append(infrastructure_export_row(scen, ctx, scen_name))

    # === Assemble outputs ===
    runinfo_df = pd.DataFrame(runinfo_rows)
    overview_df = pd.DataFrame(overview_rows)
    if kpi_rows:
        overview_df = overview_df.merge(pd.DataFrame(kpi_rows), on="Scenario", how="left")

    massflow_df = pd.concat(massflow_all, ignore_index=True)
    capex_df = pd.concat(capex_all, ignore_index=True)
    cs_df = pd.concat(coststruct_all, ignore_index=True)
    recovery_df = pd.concat(recovery_all, ignore_index=True) if recovery_all else pd.DataFrame()
    econ_env_sheets_final = {
        k: pd.concat(v, ignore_index=True)
        for k, v in econ_env_sheet_collectors.items()
        if isinstance(v, list) and v
    }

    # === Material Input Pivot (NEW: Component + ordering) ===
    material_raw_df = pd.DataFrame(material_raw_all)

    if material_raw_df.empty:
        material_pivot_df = pd.DataFrame(columns=["Scenario","Basis","Component","Material","Unit","Total kg/year"])
    else:
        # Ensure Material column name
        if "Element" in material_raw_df.columns and "Material" not in material_raw_df.columns:
            material_raw_df = material_raw_df.rename(columns={"Element": "Material"})

        # Ensure Component column exists
        if "Component" not in material_raw_df.columns:
            material_raw_df["Component"] = ""

        # For Pack/Module rows: assign Component labels for ordering
        material_raw_df["Component"] = np.where(
            material_raw_df["Basis"].eq("Pack"), "Pack",
            np.where(material_raw_df["Basis"].eq("Module"), "Module", material_raw_df["Component"])
        )

        component_order = [
            "Cathode",
            "Anode",
            "Electrolyte",
            "Separator",
            "Packing Container",
            "Cell",
            "Module",
            "Pack",
            "Other",
            "",
        ]

        material_order = [
            # elements
            "Li","Ni","Mn","Co","Fe","P","O","Al","Cu","C",
            # named materials (extend as needed)
            "Graphite",
            "Carbon Black",
            "Binder PVDF",
            "Binder Anode",
            "Electrolyte (LiPF6:DMC:EC)",
            "Separator",
            "PET foil",
            # module / pack
            "Steel","Plastic","Electronics","Other",
        ]

        def component_sort_key(x: str) -> int:
            x = "" if pd.isna(x) else str(x).strip()
            try:
                return component_order.index(x)
            except ValueError:
                return len(component_order) + 1

        def material_sort_key(x: str) -> int:
            x = "" if pd.isna(x) else str(x).strip()
            try:
                return material_order.index(x)
            except ValueError:
                return len(material_order) + 1

        material_pivot_df = (
            material_raw_df
            .assign(Unit="kg")
            .pivot_table(
                index=["Scenario","Basis","Component","Unit","Material"],
                columns="CellVariant",
                values="kg/year",
                aggfunc="sum",
                fill_value=0.0
            )
            .reset_index()
        )

        order_basis = {"Cell":0, "Module":1, "Pack":2, "Other":3}
        material_pivot_df["BasisSort"] = material_pivot_df["Basis"].map(order_basis).fillna(9)
        material_pivot_df["CompSort"] = material_pivot_df["Component"].apply(component_sort_key)
        material_pivot_df["MatSort"]  = material_pivot_df["Material"].apply(material_sort_key)

        material_pivot_df = (
            material_pivot_df
            .sort_values(by=["Scenario","BasisSort","CompSort","MatSort","Material"], kind="mergesort")
            .drop(columns=["BasisSort","CompSort","MatSort"])
        )

        base_cols = ["Scenario","Basis","Component","Unit","Material"]
        variant_cols = [c for c in material_pivot_df.columns if c not in base_cols]
        material_pivot_df["Total kg/year"] = material_pivot_df[variant_cols].sum(axis=1)

        base_cols2 = ["Scenario","Basis","Component","Material","Unit"]
        variant_cols2 = [c for c in material_pivot_df.columns if c not in base_cols2 + ["Total kg/year"]]
        desired_cols = base_cols2 + variant_cols2 + ["Total kg/year"]
        keep_cols = [c for c in desired_cols if c in material_pivot_df.columns]
        remaining = [c for c in material_pivot_df.columns if c not in keep_cols]
        material_pivot_df = material_pivot_df[keep_cols + remaining]

    # === Insert Cell Variant mix row on top of each scenario block ===
    if not material_pivot_df.empty:
        out_blocks = []
        for scen in list(overview_df["Scenario"]):
            mix = scen2mix.get(scen, {})
            total_y = float(scen2packmass.get(scen, scen2mass.get(scen, 0.0)) or 0.0)

            mix_row = {
                "Scenario": scen,
                "Basis": "—",
                "Component": "—",
                "Unit": "%",
                "Material": "Cell Variant mix (share)",
                "Total kg/year": total_y
            }

            base_cols = ["Scenario","Basis","Component","Material","Unit","Total kg/year"]
            variant_cols = [c for c in material_pivot_df.columns if c not in base_cols]
            for v in variant_cols:
                mix_row[v] = float(mix.get(v, 0.0))

            df_s = material_pivot_df[material_pivot_df["Scenario"].astype(str).eq(scen)]
            out_blocks.append(pd.DataFrame([mix_row], columns=material_pivot_df.columns))
            out_blocks.append(df_s)
            out_blocks.append(pd.DataFrame([[""] * len(df_s.columns)] * 2, columns=df_s.columns))

        material_pivot_df = pd.concat(out_blocks, ignore_index=True)

    # === Excel Export ===
    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as w:
        runinfo_df.to_excel(w, sheet_name="Run_Info", index=False)
        overview_df.to_excel(w, sheet_name="Overview", index=False)
        massflow_df.to_excel(w, sheet_name="Massflow", index=False)
        capex_df.to_excel(w, sheet_name="Capex", index=False)

        if not material_pivot_df.empty:
            material_pivot_df.to_excel(w, sheet_name="Material Input – by Variant", index=False)

        for sheet_name, df_sheet in econ_env_sheets_final.items():
            if df_sheet is not None and not df_sheet.empty:
                df_sheet.to_excel(w, sheet_name=sheet_name, index=False)

        if cs_df is not None and not cs_df.empty:
            cs_df.to_excel(w, sheet_name="Cost structure", index=False)

        if recovery_df is not None and not recovery_df.empty:
            recovery_df.to_excel(w, sheet_name="Recovery", index=False)

        if infrastructure_rows:
            pd.DataFrame(infrastructure_rows).to_excel(w, sheet_name="Infrastructure", index=False)

        _autosize(w)


def export_single_run_to_excel_bytes(
    scen: dict,
    steps_df: pd.DataFrame,
    extras: dict,
    ctx: dict,
) -> bytes:
    """
    Create the same Excel structure as Save.py's Results.xlsx,
    but for ONE scenario and returned as bytes (for Streamlit download).
    """

    scen_name = str(scen.get("name", "scenario"))

    # ---------- Run_Info ----------
    runinfo_df = pd.DataFrame([_run_info_row(scen, ctx)])

    # ---------- Overview ----------
    in_kgh = float(pd.to_numeric(steps_df.get("In kg/h", pd.Series([0.0])).iloc[0], errors="coerce") or 0.0)
    hours_y = float(ctx.get("hours_per_year") or 0.0) or float(gp.get_working_hours_per_year() or 0.0)
    cell_mass_y = float(ctx.get("cell_mass_kg_per_year", 0.0) or 0.0)
    if cell_mass_y <= 0:
        cell_mass_y = in_kgh * hours_y
    pack_mass_y = float(ctx.get("feed_mass_kg_per_year", 0.0) or (in_kgh * hours_y))
    

    overview_df = pd.DataFrame([{
        "Scenario": scen_name,
        "Battery cell mass (kg/year)": cell_mass_y,
        "Feed (kg/h)": in_kgh,
        "Feed mass (kg/year)": pack_mass_y,
        "Total product costs ($/kg)": float(_kpi_from_economics((extras or {}).get("Overhead", {}), pack_mass_y)["tpc_per_kg"]),
        "Revenue ($/kg battery)": float(_kpi_from_economics((extras or {}).get("Overhead", {}), pack_mass_y)["revenue_per_kg"]),
        "Profit ($/kg battery)": float(_kpi_from_economics((extras or {}).get("Overhead", {}), pack_mass_y)["profit_per_kg"]),
        "Net GWP (kg CO2e/kg battery)": float(_kpi_from_economics((extras or {}).get("Overhead", {}), pack_mass_y)["net_gwp_per_kg"]),
    }])

    # ---------- Material Input (RAW + Pivot) ----------
    material_raw_all = _rows_for_material_input(scen_name=scen_name, ctx=ctx)
    material_raw_df = pd.DataFrame(material_raw_all)

    # ----- Pivot bauen (single scenario; NEW: Component + ordering) -----
    if material_raw_df.empty:
        material_pivot_df = pd.DataFrame(columns=["Scenario","Basis","Component","Material","Unit","Total kg/year"])
    else:
        if "Element" in material_raw_df.columns and "Material" not in material_raw_df.columns:
            material_raw_df = material_raw_df.rename(columns={"Element": "Material"})

        if "Component" not in material_raw_df.columns:
            material_raw_df["Component"] = ""

        material_raw_df["Component"] = np.where(
            material_raw_df["Basis"].eq("Pack"), "Pack",
            np.where(material_raw_df["Basis"].eq("Module"), "Module", material_raw_df["Component"])
        )

        component_order = [
            "Cathode",
            "Anode",
            "Electrolyte",
            "Separator",
            "Packing Container",
            "Cell",
            "Module",
            "Pack",
            "Other",
            "",
        ]

        material_order = [
            "Li","Ni","Mn","Co","Fe","P","O","Al","Cu","C",
            "Graphite",
            "Carbon Black",
            "Binder PVDF",
            "Binder Anode",
            "Electrolyte (LiPF6:DMC:EC)",
            "Separator",
            "PET foil",
            "Steel","Plastic","Electronics","Other",
        ]

        def component_sort_key(x: str) -> int:
            x = "" if pd.isna(x) else str(x).strip()
            try:
                return component_order.index(x)
            except ValueError:
                return len(component_order) + 1

        def material_sort_key(x: str) -> int:
            x = "" if pd.isna(x) else str(x).strip()
            try:
                return material_order.index(x)
            except ValueError:
                return len(material_order) + 1

        material_pivot_df = (
            material_raw_df
            .assign(Unit="kg")
            .pivot_table(
                index=["Scenario","Basis","Component","Unit","Material"],
                columns="CellVariant",
                values="kg/year",
                aggfunc="sum",
                fill_value=0.0
            )
            .reset_index()
        )

        order_basis = {"Cell":0, "Module":1, "Pack":2, "Other":3}
        material_pivot_df["BasisSort"] = material_pivot_df["Basis"].map(order_basis).fillna(9)
        material_pivot_df["CompSort"]  = material_pivot_df["Component"].apply(component_sort_key)
        material_pivot_df["MatSort"]   = material_pivot_df["Material"].apply(material_sort_key)

        material_pivot_df = (
            material_pivot_df
            .sort_values(by=["Scenario","BasisSort","CompSort","MatSort","Material"], kind="mergesort")
            .drop(columns=["BasisSort","CompSort","MatSort"])
        )

        base_cols = ["Scenario","Basis","Component","Unit","Material"]
        variant_cols = [c for c in material_pivot_df.columns if c not in base_cols]
        material_pivot_df["Total kg/year"] = material_pivot_df[variant_cols].sum(axis=1)

        base_cols2 = ["Scenario","Basis","Component","Material","Unit"]
        variant_cols2 = [c for c in material_pivot_df.columns if c not in base_cols2 + ["Total kg/year"]]
        desired_cols = base_cols2 + variant_cols2 + ["Total kg/year"]
        keep_cols = [c for c in desired_cols if c in material_pivot_df.columns]
        remaining = [c for c in material_pivot_df.columns if c not in keep_cols]
        material_pivot_df = material_pivot_df[keep_cols + remaining]
        total_y = float(pack_mass_y or cell_mass_y or 0.0)
        variant_mix = {}
        for d in (ctx.get("feed_details") or []):
            cid = str(d.get("cell_id") or "").strip()
            share = float(d.get("share") or 0.0)
            label = _cell_label(cid, d)
            variant_mix[label] = variant_mix.get(label, 0.0) + share

        s = sum(max(v, 0.0) for v in variant_mix.values())
        if s > 0:
            variant_mix = {k: v/s for k, v in variant_mix.items()}

        mix_row = {
            "Scenario": scen_name,
            "Basis": "—",
            "Component": "—",
            "Unit": "%",
            "Material": "Cell Variant mix (share)",
            "Total kg/year": total_y
        }

        base_cols_mix = ["Scenario","Basis","Component","Material","Unit","Total kg/year"]
        variant_cols_mix = [c for c in material_pivot_df.columns if c not in base_cols_mix]
        for v in variant_cols_mix:
            mix_row[v] = float(variant_mix.get(v, 0.0))

        material_pivot_df = pd.concat(
            [pd.DataFrame([mix_row], columns=material_pivot_df.columns), material_pivot_df],
            ignore_index=True
        )

    # ---------- Massflow ----------
    massflow_long_df = _massflow_long(steps_df, scen_name)

    oh = (extras or {}).get("Overhead", {})
    if not isinstance(oh, dict):
        raise ValueError("extras['Overhead'] missing or invalid.")

    # ---------- CAPEX ----------
    capex_df = _capex_collect(steps_df, scen_name, extras)

    # ---------- Cost structure ----------
    cs_df = _cost_structure_from_economics_overhead(oh, scen_name)
    if cs_df is None or cs_df.empty:
        cs_df = _empty_cost_structure(scen_name)
    econ_env_sheet_map = _economics_environment_sheets(oh, ctx, scen_name)
    recovery_df = _recovery_df_for_export(steps_df, ctx, oh, scen_name)
    infrastructure_df = pd.DataFrame([infrastructure_export_row(scen, ctx, scen_name)])

    # ---------- Write Excel to bytes ----------
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as w:
        runinfo_df.to_excel(w, sheet_name="Run_Info", index=False)
        overview_df.to_excel(w, sheet_name="Overview", index=False)
        infrastructure_df.to_excel(w, sheet_name="Infrastructure", index=False)

        massflow_long_df.to_excel(w, sheet_name="Massflow", index=False)
        capex_df.to_excel(w, sheet_name="Capex", index=False)

        if not material_pivot_df.empty:
            material_pivot_df.to_excel(w, sheet_name="Material Input – by Variant", index=False)

        for sheet_name, df_sheet in econ_env_sheet_map.items():
            if df_sheet is not None and not df_sheet.empty:
                df_sheet.to_excel(w, sheet_name=sheet_name, index=False)

        if cs_df is not None and not cs_df.empty:
            cs_df.to_excel(w, sheet_name="Cost structure", index=False)

        if recovery_df is not None and not recovery_df.empty:
            recovery_df.to_excel(w, sheet_name="Recovery", index=False)

        _autosize(w)

    return output.getvalue()

if __name__ == "__main__":
    main()
