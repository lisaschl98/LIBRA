from __future__ import annotations

from io import BytesIO

import pandas as pd

from main import SCENARIOS, run_scenario
from Save import (
    _annual_process_inputs_sheet,
    _annual_process_outputs_sheet,
    _massflow_long,
    export_single_run_to_excel_bytes,
)
from step_utils import (
    MASSFLOW_LABEL_TO_PRICE_ITEM,
    MASSFLOW_SEPARATED_TO_OUTPUT_ITEM,
    build_chem_use_kg_h_from_row,
    normalize_row_for_economics,
)


def _scenario_by_route(route: str) -> dict:
    for scen in SCENARIOS:
        if str(scen.get("route", "")).strip().lower() == route:
            return scen
    raise AssertionError(f"No scenario found for route='{route}'")


def _scenario_by_name(name: str) -> dict:
    for scen in SCENARIOS:
        if str(scen.get("name", "")).strip() == name:
            return scen
    raise AssertionError(f"No scenario found for name='{name}'")


def test_e2e_mech_runs_and_builds_overhead() -> None:
    scen = _scenario_by_route("mech")
    steps_df, extras, _ctx = run_scenario(scen)

    assert not steps_df.empty
    assert "Overhead" in extras
    assert isinstance(extras["Overhead"], dict)
    assert isinstance(extras["Overhead"].get("revenue", {}), dict)

    revenue_lines = extras["Overhead"]["revenue"].get("output_lines", [])
    assert isinstance(revenue_lines, list)
    assert len(revenue_lines) > 0


def test_e2e_pyro_contains_pyro_and_hydropyro_outputs() -> None:
    scen = _scenario_by_route("pyro")
    steps_df, extras, _ctx = run_scenario(scen)

    step_names = set(steps_df["Step"].astype(str).tolist())
    assert "Pyro Smelting" in step_names
    assert "Pyro Granulation Alloy" in step_names

    extra_keys = set(extras.keys())
    assert "Pyro Smelting" in extra_keys
    assert any(("Hydro Pyro" in k) or ("Hydro-Pyro" in k) for k in extra_keys)


def test_e2e_mix_contains_roasting_and_wastewater_steps() -> None:
    scen = _scenario_by_name("Mech_10tpy_MIX_unlimited_Co_basis")
    steps_df, _extras, _ctx = run_scenario(scen)

    step_names = set(steps_df["Step"].astype(str).tolist())
    assert "Hydro Mix – Roasting" in step_names
    assert "Hydro Mix – Wastewater Treatment" in step_names


CIRC_MASSFLOW_LABELS = frozenset({
    "Cyanex 272 (Circulating)",
    "D2EHPA (Circulating)",
    "DMF (Circulating)",
    "Kerosene (Circulating)",
})


def test_annual_process_inputs_match_massflow_materials() -> None:
    for scen in SCENARIOS:
        name = scen["name"]
        steps_df, extras, ctx = run_scenario(scen)
        h_y = float(ctx.get("hours_per_year", 8000))
        oh = extras.get("Overhead", {}) or {}
        ann = _annual_process_inputs_sheet(oh, ctx, name)
        reag = ann[ann["category"] == "reagent"].groupby("item")["Quantity"].sum()

        mf = _massflow_long(steps_df, name)
        mat = mf.dropna(subset=["Name Material added"])
        mat = mat[pd.to_numeric(mat["Materials added (kg/h)"], errors="coerce").fillna(0) > 0]
        mf_by_price: dict[str, float] = {}
        for _, r in mat.iterrows():
            label = str(r["Name Material added"]).strip()
            if label in CIRC_MASSFLOW_LABELS:
                continue
            price_item = MASSFLOW_LABEL_TO_PRICE_ITEM.get(label)
            assert price_item is not None, f"{name}: unmapped massflow material '{label}'"
            mf_by_price[price_item] = mf_by_price.get(price_item, 0.0) + float(r["Materials added (kg/h)"]) * h_y

        for price_item, mf_qty in mf_by_price.items():
            ann_qty = float(reag.get(price_item, 0.0) if price_item in reag.index else 0.0)
            assert abs(mf_qty - ann_qty) < 0.1, (
                f"{name}: {price_item} massflow={mf_qty:.4f} annual={ann_qty:.4f}"
            )


def test_normalize_row_for_economics_is_idempotent() -> None:
    scen = next(s for s in SCENARIOS if s["name"] == "Mech_10tpy_LFP")
    steps_df, _, ctx = run_scenario(scen)
    sub = steps_df[steps_df["Step"].astype(str).str.contains("Oxalate Mixing", na=False)]
    once = normalize_row_for_economics(sub, ctx).iloc[0]["chem_use_kg_h"]
    twice = normalize_row_for_economics(normalize_row_for_economics(sub, ctx), ctx).iloc[0]["chem_use_kg_h"]
    assert once == twice


def test_process_water_is_reagent_not_machine_utility() -> None:
    """Water is dosed via chem_use; attach_opex always passes water_m3_y=0."""
    scen = next(s for s in SCENARIOS if s["name"] == "Mech_10tpy_LFP")
    _steps_df, extras, ctx = run_scenario(scen)
    oh = extras.get("Overhead", {}) or {}
    opex = oh.get("opex", {}) or {}
    util_water = sum(
        float(s.get("cost_water_per_y", 0.0) or 0.0)
        for s in (opex.get("step_totals") or [])
    )
    assert util_water == 0.0

    ann = _annual_process_inputs_sheet(oh, ctx, scen["name"])
    water = ann[ann["item"] == "Water"]
    assert float(water.loc[water["category"] == "utility", "Costs ($/y)"].sum()) == 0.0
    assert float(water.loc[water["category"] == "reagent", "Quantity"].sum()) > 0.0


def test_annual_process_outputs_match_massflow_products() -> None:
    for scen in SCENARIOS:
        name = scen["name"]
        steps_df, extras, ctx = run_scenario(scen)
        h_y = float(ctx.get("hours_per_year", 8000))
        oh = extras.get("Overhead", {}) or {}
        ann = _annual_process_outputs_sheet(oh, name)
        qty_ann = ann.groupby("item")["Quantity"].sum()

        mf = _massflow_long(steps_df, name)
        sep = mf.dropna(subset=["Name Output Separated"])
        sep = sep[pd.to_numeric(sep["Output separated (kg/h)"], errors="coerce").fillna(0) > 0]

        mf_by: dict[str, float] = {}
        for _, r in sep.iterrows():
            label = str(r["Name Output Separated"]).strip()
            key = MASSFLOW_SEPARATED_TO_OUTPUT_ITEM.get(label)
            if not key:
                continue
            mf_by[key] = mf_by.get(key, 0.0) + float(r["Output separated (kg/h)"]) * h_y

        for key, mf_qty in mf_by.items():
            ann_qty = float(qty_ann.get(key, 0.0) if key in qty_ann.index else 0.0)
            assert abs(mf_qty - ann_qty) < 0.5, (
                f"{name}: {key} massflow={mf_qty:.4f} annual={ann_qty:.4f}"
            )


def test_annual_process_inputs_includes_reagents_from_step_columns() -> None:
    scen = next(s for s in SCENARIOS if s["name"] == "Mech_10tpy_MIX_unlimited_Co_basis")
    _steps_df, extras, ctx = run_scenario(scen)
    oh = extras.get("Overhead", {}) or {}
    ann = _annual_process_inputs_sheet(oh, ctx, scen["name"])
    reag = ann[ann["category"] == "reagent"]
    items = set(reag["item"].astype(str))
    assert "PVP" in items
    assert float(reag.loc[reag["item"] == "PVP", "Quantity"].sum()) > 0.0
    assert "DMF" in items
    assert "Nitrogen" in items
    naoh_q = float(reag.loc[reag["item"] == "Sodium hydroxide (50%)", "Quantity"].sum())
    assert naoh_q > 2500.0


def test_e2e_excel_export_has_expected_sheet_set() -> None:
    scen = _scenario_by_route("mech")
    steps_df, extras, ctx = run_scenario(scen)

    excel_bytes = export_single_run_to_excel_bytes(scen, steps_df, extras, ctx)
    assert isinstance(excel_bytes, (bytes, bytearray))
    assert len(excel_bytes) > 0

    xls = pd.ExcelFile(BytesIO(excel_bytes))
    expected = {
        "Run_Info",
        "Overview",
        "Massflow",
        "Capex",
        "Material Input – by Variant",
        "Annual process Inputs",
        "Annual process Outputs",
        "Cost structure",
    }
    assert expected.issubset(set(xls.sheet_names))

