from __future__ import annotations

import pandas as pd

import pytest

from main import SCENARIOS, run_scenario
from recovery_config import (
    COMPONENT_BOM_REFERENCE,
    feed_mass_for_keys,
    feed_pool_keys,
    iter_unified_feed_comp_kg_h,
    recovery_input_mass_kg_y,
    recovery_table_targets,
    resolve_recovery_route,
    component_targets,
)
from recovery_metrics import (
    _iter_feed_comp_kg_h,
    _nmc_precursor_feed_contrib_kg_per_kg,
    _product_output_lines_df,
    _product_recovery_contributions_kg_per_kg_product,
    _recovery_pct,
    _saleable_yield_pct,
    build_product_output_table,
    build_recovery_table,
    compute_libra_recovery,
)


def test_recovery_pct_clamps_invalid():
    assert _recovery_pct(50.0, 100.0) == 50.0
    assert _recovery_pct(100.1, 100.0) == 100.1
    assert _recovery_pct(100.09, 100.0) == 100.09
    assert _recovery_pct(100.11, 100.0) is None
    assert _recovery_pct(150.0, 100.0) is None
    assert _recovery_pct(-1.0, 100.0) is None
    assert _recovery_pct(10.0, 0.0) is None


def test_saleable_yield_pct_allows_above_100():
    assert _saleable_yield_pct(150.0, 100.0) == 150.0
    assert _saleable_yield_pct(124.5, 100.0) == 124.5
    assert _saleable_yield_pct(-1.0, 100.0) is None
    assert _recovery_pct(150.0, 100.0) is None


def test_product_output_lines_dedup_same_step_item():
    econ = {
        "revenue_raw": {
            "output_lines": [
                {
                    "item": "Copper scrap",
                    "qty_kg_y": 10.0,
                    "step_name": "Pack Dismantle",
                    "category": "product",
                    "economic_type": "revenue",
                    "amount_per_y": 1.0,
                },
                {
                    "item": "Copper scrap",
                    "qty_kg_y": 20.0,
                    "step_name": "Pack Dismantle",
                    "category": "product",
                    "economic_type": "revenue",
                    "amount_per_y": 2.0,
                },
                {
                    "item": "Copper scrap",
                    "qty_kg_y": 30.0,
                    "step_name": "Hydro Cu",
                    "category": "product",
                    "economic_type": "revenue",
                    "amount_per_y": 3.0,
                },
            ]
        }
    }
    lines = _product_output_lines_df(econ)
    assert len(lines) == 2
    pack_qty = float(lines.loc[lines["step_name"] == "Pack Dismantle", "qty_kg_y"].iloc[0])
    assert pack_qty == 30.0
    podf = build_product_output_table(
        econ,
        {"hours_per_year": 8760.0, "feed_mass_kg_per_year": 100.0, "recovery_route": "pyro"},
    )
    cu = podf[podf["Product"] == "Copper scrap"].iloc[0]
    assert float(cu["Total mass (kg/y)"]) == 60.0


def test_active_feed_pools():
    ctx = {
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Cathode:Li": 2.0,
                    "cell:Cathode:Fe": 3.0,
                    "pack:Steel": 10.0,
                },
            }
        ],
    }
    items = list(_iter_feed_comp_kg_h(ctx))
    assert feed_mass_for_keys(items, feed_pool_keys("nmc", "Li")) == 2.0
    assert feed_mass_for_keys(items, feed_pool_keys("nmc", "Iron")) == 3.0
    assert "Fe" not in recovery_table_targets("nmc")


def test_feed_mass_sums_same_key_across_unified_variants():
    """Several UNIFIED feed rows may share cell:Cathode:Li — all shares must count."""
    ctx = {
        "feed_details": [
            {"units_per_h": 1.0, "comp_abs_kg_per_unit": {"cell:Cathode:Li": 2.0}},
            {"units_per_h": 3.0, "comp_abs_kg_per_unit": {"cell:Cathode:Li": 1.0}},
        ],
    }
    items = list(_iter_feed_comp_kg_h(ctx))
    assert feed_mass_for_keys(items, feed_pool_keys("pyro", "Li")) == 5.0


def test_nmc_graphite_product_counts_toward_recovery():
    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": "nmc",
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Anode:Graphite": 10.0,
                    "cell:Anode:Carbon Black Anode": 1.0,
                    "cell:Cathode:Carbon Black Cathode": 1.0,
                },
            }
        ],
    }
    qty_y = 5000.0
    econ = {
        "revenue_raw": {
            "output_lines": [
                {
                    "item": "Graphite",
                    "qty_kg_y": qty_y,
                    "amount_per_y": 100.0,
                    "economic_type": "revenue",
                    "category": "product",
                },
            ]
        }
    }
    rec = build_recovery_table(
        build_product_output_table(econ, ctx, None), ctx, 8760.0
    )
    g = rec[rec["Target"] == "Graphite"].iloc[0]
    assert abs(float(g["Recovered mass (kg/y)"]) - qty_y) < 1e-6
    assert float(g["Recovery (%)"]) > 0.0


def test_iron_oxalate_fe_fraction_matches_stoichiometry():
    from stoichiometry import MOLAR_MASS

    fr = _product_recovery_contributions_kg_per_kg_product("Ferrous oxalate", {})
    expected = float(MOLAR_MASS["Fe"]) / float(MOLAR_MASS["FeC2O4_2H2O"])
    assert abs(fr["Fe"] - expected) < 1e-9


def test_lih2po4_maps_to_li_and_p():
    fr = _product_recovery_contributions_kg_per_kg_product("Lithium dihydrogenphosphate", {})
    from stoichiometry import MOLAR_MASS

    mm = float(MOLAR_MASS["LiH2PO4"])
    assert abs(fr["Li"] - float(MOLAR_MASS["Li"]) / mm) < 1e-9
    assert abs(fr["P"] - float(MOLAR_MASS["P"]) / mm) < 1e-9


def test_fepo4_c_maps_to_fe_and_p():
    from stoichiometry import FEPO4_C_PRODUCT_RULES, MOLAR_MASS

    fr = _product_recovery_contributions_kg_per_kg_product(
        "Carbon coated Iron Phosphate (FePO4-C)", {}
    )
    solid = 1.0 - float(FEPO4_C_PRODUCT_RULES["carbon_wt_frac_default"])
    mm = float(MOLAR_MASS["FePO4"])
    assert abs(fr["Fe"] - solid * float(MOLAR_MASS["Fe"]) / mm) < 1e-9
    assert abs(fr["P"] - solid * float(MOLAR_MASS["P"]) / mm) < 1e-9


@pytest.mark.parametrize("route_label", ["LFP", "MIX"])
def test_p_recovery_on_lfp_routes(route_label: str) -> None:
    scen = next(s for s in SCENARIOS if route_label in s["name"] and "Mech" in s["name"])
    steps_df, extras, ctx = run_scenario(scen)
    econ = {"revenue_raw": extras.get("Overhead", {}).get("revenue", {})}
    rec_df = compute_libra_recovery(ctx, steps_df, econ).recovery_df
    assert "P" in rec_df["Target"].astype(str).values
    p = rec_df[rec_df["Target"] == "P"].iloc[0]
    assert float(p["Input mass (kg/y)"]) > 0.0
    assert float(p["Recovered mass (kg/y)"]) > 0.0
    assert float(p["Recovery (%)"]) <= 100.0 + 1e-6


def test_li2co3_maps_to_li():
    fr = _product_recovery_contributions_kg_per_kg_product("Lithium carbonate", {})
    assert "Li" in fr
    assert "Fe" not in fr


def test_al_scrap_and_hydroxide_map_to_al():
    fr_scrap = _product_recovery_contributions_kg_per_kg_product("Aluminium scrap", {})
    fr_oh = _product_recovery_contributions_kg_per_kg_product("Aluminium hydroxide", {})
    assert fr_scrap.get("Al") == 1.0
    assert fr_oh.get("Al", 0) > 0.0


def test_pyro_and_nmc_iron_pool_includes_cathode_fe():
    for route in ("pyro", "nmc"):
        keys = feed_pool_keys(route, "Iron")
        assert "cell:Cathode:Fe" in keys
        assert "pack:Fe" in keys
    assert feed_pool_keys("lfp", "Fe") == ("cell:Cathode:Fe",)
    assert "cell:Cathode:Fe" not in feed_pool_keys("lfp", "Iron")


def test_nmc_precursor_recovery_excludes_makeup():
    from stoichiometry import MOLAR_MASS

    niso4_mk = 1.0
    ni_from_mk = niso4_mk * float(MOLAR_MASS["Ni"]) / float(MOLAR_MASS["NiSO4"])
    steps = pd.DataFrame(
        [
            {
                "Step": "Hydro NMC – NMC Precipitation",
                "Ni from battery feed (kg/h)": 4.0,
                "Co from battery feed (kg/h)": 1.0,
                "Mn from battery feed (kg/h)": 1.0,
                "NiSO4 makeup (kg/h)": niso4_mk,
            }
        ]
    )
    ni_battery_h = 4.0 - ni_from_mk
    contrib_feed = _nmc_precursor_feed_contrib_kg_per_kg("NMC 811 Precursor", steps, product_mass_kg_h=20.0)
    assert abs(contrib_feed["Ni"] - ni_battery_h / 20.0) < 1e-9

    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": "nmc",
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Cathode:Ni": 10.0,
                    "cell:Cathode:Co": 5.0,
                    "cell:Cathode:Mn": 5.0,
                },
            }
        ],
    }
    podf = pd.DataFrame([{"Product": "NMC 811 Precursor", "Total mass (kg/y)": 20.0 * 8760.0}])
    rec = build_recovery_table(podf, ctx, 8760.0, steps_df=steps)
    ni_row = rec[rec["Target"] == "Ni"].iloc[0]
    assert abs(float(ni_row["Recovered mass (kg/y)"]) - ni_battery_h * 8760.0) < 1e-6
    assert float(ni_row["Recovery (%)"]) <= 100.0


def test_copper_scrap_maps_to_cu_target():
    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": "pyro",
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "Pack:Cu": 5.0,
                    "module:Cu": 3.0,
                    "cell:Anode:Copper": 2.0,
                },
            }
        ],
    }
    econ = {
        "revenue_raw": {
            "output_lines": [
                {
                    "item": "Copper scrap",
                    "step_name": "Pack Dismantle",
                    "qty_kg_y": 100.0,
                    "amount_per_y": 50.0,
                    "economic_type": "revenue",
                    "category": "product",
                },
                {
                    "item": "Copper scrap",
                    "step_name": "Hydro Pyro – Cu Filtration",
                    "qty_kg_y": 400.0,
                    "amount_per_y": 200.0,
                    "economic_type": "revenue",
                    "category": "product",
                },
            ]
        }
    }
    podf = build_product_output_table(econ, ctx, None)
    assert len(podf) == 1
    assert float(podf.iloc[0]["Total mass (kg/y)"]) == 500.0

    rec = build_recovery_table(podf, ctx, 8760.0)
    cu = rec[rec["Target"] == "Cu"].iloc[0]
    assert abs(float(cu["Recovered mass (kg/y)"]) - 500.0) < 1e-6
    assert float(cu["Input mass (kg/y)"]) == 10.0 * 8760.0


def test_product_output_and_recovery_tables():
    ctx = {
        "hours_per_year": 8760.0,
        "feed_mass_kg_per_year": 876000.0,
        "recovery_route": "pyro",
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {"cell:Cathode:Li": 10.0},
            }
        ],
    }
    econ = {
        "revenue_raw": {
            "output_lines": [
                {
                    "item": "Lithium carbonate",
                    "qty_kg_y": 4380.0,
                    "amount_per_y": 1000.0,
                    "economic_type": "revenue",
                    "category": "product",
                },
            ]
        }
    }
    steps = pd.DataFrame([{"In kg/h": 100.0}])
    res = compute_libra_recovery(ctx, steps, econ)
    assert res.saleable_product_yield is not None
    assert res.element_recovery["Li"] is not None
    assert "Category" in res.recovery_df.columns
    assert "active" in res.recovery_df["Target"].astype(str).values


def test_pyro_saleable_yield_shown_above_100():
    from path import CELL_TECH_XLSX, COST_REGION_XLSX, EFF_XLSX

    scen = dict(next(s for s in SCENARIOS if s.get("name") == "Pyro_10tpy"))
    scen["cost_region_xlsx"] = str(COST_REGION_XLSX)
    scen["cell_tech_xlsx"] = str(CELL_TECH_XLSX)
    scen["eff_xlsx"] = str(EFF_XLSX)
    steps_df, extras, ctx = run_scenario(scen)
    econ = {"revenue_raw": extras.get("Overhead", {}).get("revenue", {})}
    res = compute_libra_recovery(ctx, steps_df, econ)
    assert res.saleable_product_yield is not None
    assert res.saleable_product_yield > 100.0


@pytest.mark.parametrize("route_label", ["NMC", "MIX"])
def test_nmc_precursor_ni_recovery_not_above_input(route_label: str) -> None:
    scen = next(s for s in SCENARIOS if route_label in s["name"] and "Mech" in s["name"])
    steps_df, extras, ctx = run_scenario(scen)
    route = resolve_recovery_route(ctx)
    assert route in ("nmc", "mix")
    econ = {"revenue_raw": extras.get("Overhead", {}).get("revenue", {})}
    rec_df = compute_libra_recovery(ctx, steps_df, econ).recovery_df
    ni = rec_df[rec_df["Target"] == "Ni"].iloc[0]
    inp = float(ni["Input mass (kg/y)"])
    rec = float(ni["Recovered mass (kg/y)"])
    assert rec <= inp + 0.01, f"{scen['name']}: recovered Ni {rec} > input {inp}"
    pct = ni["Recovery (%)"]
    assert pd.isna(pct) or float(pct) <= 100.0


@pytest.mark.parametrize("scen", SCENARIOS, ids=lambda s: s["name"])
def test_recovery_input_mass_matches_unified_feed_all_targets(scen: dict) -> None:
    """Input mass (kg/y) = sum of pool keys over all UNIFIED feed_details rows (active + structural)."""
    steps_df, extras, ctx = run_scenario(scen)
    route = resolve_recovery_route(ctx)
    econ = extras.get("Overhead", {}) or {}
    rec_df = compute_libra_recovery(ctx, steps_df, econ).recovery_df
    targets = [t for t in recovery_table_targets(route) if t != "active"]
    for target in targets:
        expected = recovery_input_mass_kg_y(ctx, route, target, steps_df)
        row = rec_df[rec_df["Target"].astype(str) == target]
        assert not row.empty, f"missing recovery row for {target}"
        actual = float(row.iloc[0]["Input mass (kg/y)"])
        assert abs(actual - expected) < 0.01, (
            f"{scen['name']} {target}: recovery={actual:.4f} unified_feed={expected:.4f}"
        )


def test_graphite_input_includes_carbon_black() -> None:
    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": "nmc",
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Anode:Graphite": 10.0,
                    "cell:Anode:Carbon Black Anode": 1.0,
                    "cell:Cathode:Carbon Black Cathode": 2.0,
                },
            }
        ],
    }
    assert recovery_input_mass_kg_y(ctx, "nmc", "Graphite", None) == 13.0 * 8760.0


def test_fe_input_includes_fe_added_from_steps() -> None:
    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": "lfp",
        "feed_details": [
            {"units_per_h": 1.0, "comp_abs_kg_per_unit": {"cell:Cathode:Fe": 5.0}},
        ],
    }
    steps = pd.DataFrame([{"Fe added (kg/h)": 0.5}, {"Fe added (kg/h)": 0.2}])
    assert recovery_input_mass_kg_y(ctx, "lfp", "Fe", steps) == (5.0 + 0.7) * 8760.0


@pytest.mark.parametrize("route", ["nmc", "pyro"])
def test_cement_fe_counts_toward_structural_iron(route: str) -> None:
    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": route,
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Cathode:Fe": 4.0,
                    "pack:Fe": 1.0,
                },
            }
        ],
    }
    steps = pd.DataFrame([{"Fe added (kg/h)": 0.3}])
    assert recovery_input_mass_kg_y(ctx, route, "Fe", steps) == 0.0
    assert recovery_input_mass_kg_y(ctx, route, "Iron", steps) == (4.0 + 1.0 + 0.3) * 8760.0


def test_pyro_iron_hydroxide_iron_pool_share_only() -> None:
    """Pyro: iron hydroxide credits Iron pool share only; Steel gets no hydroxide mass."""
    from recovery_metrics import _pyro_iron_hydroxide_iron_pool_fe_kg_h
    from stoichiometry import MOLAR_MASS

    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": "pyro",
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Cathode:Fe": 2.0,
                    "pack:Fe": 1.0,
                    "pack:Steel": 10.0,
                },
            }
        ],
    }
    steps = pd.DataFrame([{"Fe added (kg/h)": 0.5}])
    fe_frac = float(MOLAR_MASS["Fe"]) / float(MOLAR_MASS["Fe(OH)3"])
    m_oh_h = 100.0
    fe_iron, _ = _pyro_iron_hydroxide_iron_pool_fe_kg_h(m_oh_h, ctx, "pyro", steps)
    fe_total = m_oh_h * fe_frac
    assert fe_iron < fe_total
    assert fe_iron > 0.0

    podf = pd.DataFrame(
        [
            {"Product": "Iron scrap", "Total mass (kg/y)": 1.0 * 8760.0},
            {"Product": "Steel scrap", "Total mass (kg/y)": 4.0 * 8760.0},
            {"Product": "Iron hydroxide", "Total mass (kg/y)": 100.0 * 8760.0},
        ]
    )
    rec = build_recovery_table(podf, ctx, 8760.0, route="pyro", steps_df=steps)
    iron = rec[rec["Target"] == "Iron"].iloc[0]
    steel = rec[rec["Target"] == "Steel"].iloc[0]
    assert "iron pool share" in str(iron["Notes"]).lower()
    assert float(steel["Recovered mass (kg/y)"]) == pytest.approx(4.0 * 8760.0)
    assert "iron hydroxide" not in str(steel["Products counted"]).lower()


def test_nmc_iron_hydroxide_counts_full_fe_to_iron() -> None:
    """Non-pyro routes: full Fe in iron hydroxide → Iron (no origin split)."""
    from stoichiometry import MOLAR_MASS

    ctx = {
        "hours_per_year": 8760.0,
        "recovery_route": "nmc",
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Cathode:Fe": 5.0,
                    "pack:Fe": 1.0,
                },
            }
        ],
    }
    fe_frac = float(MOLAR_MASS["Fe"]) / float(MOLAR_MASS["Fe(OH)3"])
    m_oh_y = 10.0 * 8760.0
    podf = pd.DataFrame([{"Product": "Iron hydroxide", "Total mass (kg/y)": m_oh_y}])
    rec = build_recovery_table(podf, ctx, 8760.0, route="nmc")
    iron = rec[rec["Target"] == "Iron"].iloc[0]
    expected_rec = 10.0 * fe_frac * 8760.0
    assert float(iron["Recovered mass (kg/y)"]) == pytest.approx(expected_rec, rel=1e-6)


def test_structural_cap_requires_min_excess_fraction() -> None:
    """Cap note only when recovered exceeds input by more than 0.1%."""
    ctx = {"hours_per_year": 8760.0, "recovery_route": "lfp", "feed_details": []}
    podf = pd.DataFrame([{"Product": "Electronic scrap", "Total mass (kg/y)": 1000.5}])
    rec = build_recovery_table(
        podf,
        {
            **ctx,
            "feed_details": [
                {
                    "units_per_h": 1.0,
                    "comp_abs_kg_per_unit": {"module:Electronics": 1000.0 / 8760.0},
                }
            ],
        },
        8760.0,
        route="lfp",
    )
    el = rec[rec["Target"] == "Electronics"].iloc[0]
    assert "capped" not in str(el["Notes"]).lower()
    assert float(el["Recovered mass (kg/y)"]) == pytest.approx(1000.5, rel=1e-9)

    podf2 = pd.DataFrame([{"Product": "Electronic scrap", "Total mass (kg/y)": 1002.0}])
    rec2 = build_recovery_table(
        podf2,
        {
            **ctx,
            "feed_details": [
                {
                    "units_per_h": 1.0,
                    "comp_abs_kg_per_unit": {"module:Electronics": 1000.0 / 8760.0},
                }
            ],
        },
        8760.0,
        route="lfp",
    )
    el2 = rec2[rec2["Target"] == "Electronics"].iloc[0]
    assert "capped" in str(el2["Notes"]).lower()
    assert float(el2["Recovered mass (kg/y)"]) == pytest.approx(1000.0, rel=1e-9)


def test_component_pools_match_bom_reference_keys() -> None:
    for target in component_targets():
        expected = COMPONENT_BOM_REFERENCE[target]
        if target == "Iron":
            expected = expected + ("cell:Cathode:Fe",)
        assert feed_pool_keys("nmc", target) == expected


def test_al_pool_excludes_polyethylene_laminated_foil() -> None:
    ctx = {
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "cell:Cathode:Aluminium": 5.0,
                    "cell:Packing Container:Polyethylene-laminated aluminium foil": 50.0,
                },
            }
        ],
    }
    items = list(iter_unified_feed_comp_kg_h(ctx))
    assert feed_mass_for_keys(items, feed_pool_keys("nmc", "Al")) == 5.0


@pytest.mark.parametrize("route_label", ["LFP", "NMC", "MIX", "pyro"])
def test_structural_recovery_not_above_unified_feed(route_label: str) -> None:
    if route_label == "pyro":
        scen = next(s for s in SCENARIOS if s.get("route") == "pyro")
    else:
        scen = next(s for s in SCENARIOS if route_label in s["name"] and "Mech" in s["name"])
    steps_df, extras, ctx = run_scenario(scen)
    econ = {"revenue_raw": extras.get("Overhead", {}).get("revenue", {})}
    rec_df = compute_libra_recovery(ctx, steps_df, econ).recovery_df
    for target in component_targets():
        row = rec_df[rec_df["Target"] == target].iloc[0]
        inp = float(row["Input mass (kg/y)"])
        rec = float(row["Recovered mass (kg/y)"])
        assert rec <= inp + 0.1, f"{scen['name']} {target}: {rec} > {inp}"
        pct = row["Recovery (%)"]
        assert pd.isna(pct) or float(pct) <= 100.0 + 1e-6


def test_steel_feed_pool_includes_packing_container_nickel_plated_steel() -> None:
    ctx = {
        "hours_per_year": 8760.0,
        "feed_details": [
            {
                "units_per_h": 1.0,
                "comp_abs_kg_per_unit": {
                    "pack:Steel": 10.0,
                    "module:Steel": 2.0,
                    "cell:Packing Container:Nickel-plated steel": 3.0,
                    "cell:Nickel-plated Steel": 99.0,
                },
            }
        ],
    }
    items = list(iter_unified_feed_comp_kg_h(ctx))
    keys = feed_pool_keys("nmc", "Steel")
    assert feed_mass_for_keys(items, keys) == 15.0


def test_structural_input_sums_across_feed_variants() -> None:
    ctx = {
        "hours_per_year": 8760.0,
        "feed_details": [
            {"units_per_h": 1.0, "comp_abs_kg_per_unit": {"pack:Cu": 2.0, "module:Cu": 1.0}},
            {"units_per_h": 2.0, "comp_abs_kg_per_unit": {"cell:Anode:Copper": 0.5}},
        ],
    }
    items = list(iter_unified_feed_comp_kg_h(ctx))
    assert feed_mass_for_keys(items, feed_pool_keys("pyro", "Cu")) == 4.0
    assert recovery_input_mass_kg_y(ctx, "pyro", "Cu", None) == 4.0 * 8760.0
