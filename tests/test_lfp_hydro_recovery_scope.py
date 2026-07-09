from __future__ import annotations

from main import SCENARIOS, run_scenario
from recovery_metrics import compute_libra_recovery


def _lfp_only_scenario() -> dict:
    for scen in SCENARIOS:
        if scen.get("name") == "Mech_10tpy_LFP":
            return dict(scen)
    raise AssertionError("LFP scenario not found")


def test_lfp_hydro_scope_fe_skips_li_steps() -> None:
    scen = _lfp_only_scenario()
    scen["lfp_hydro_recovery_scope"] = "fe"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro LFP – Oxalate Drying" in step_names
    assert "Hydro LFP – Wastewater Treatment" in step_names
    assert "Hydro LFP – Ion Exchange" not in step_names
    assert "Hydro LFP – Li Concentration" not in step_names
    assert "Hydro LFP – LiH2PO4 Crystallization" not in step_names


def test_lfp_hydro_scope_all_includes_both_lines() -> None:
    scen = _lfp_only_scenario()
    scen["lfp_hydro_recovery_scope"] = "all"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro LFP – Oxalate Drying" in step_names
    assert "Hydro LFP – LiH2PO4 Crystallization" in step_names


def test_lfp_ferrous_oxalate_counts_as_revenue_product() -> None:
    scen = _lfp_only_scenario()
    scen["lfp_hydro_recovery_scope"] = "fe"

    steps_df, extras, ctx = run_scenario(scen)
    revenue = extras.get("Overhead", {}).get("revenue", {})
    lines = revenue.get("output_lines", []) or []
    ox_lines = [ln for ln in lines if str(ln.get("item", "")).strip() == "Ferrous oxalate"]
    assert len(ox_lines) == 1
    assert ox_lines[0]["economic_type"] == "revenue"
    assert float(ox_lines[0]["qty_kg_y"]) > 0.0
    assert float(ox_lines[0]["amount_per_y"]) > 0.0

    drying = steps_df[steps_df["Step"].astype(str).str.contains("Oxalate Drying", na=False)]
    assert not drying.empty
    assert float(drying.iloc[0].get("Ferrous oxalate (kg/h)", 0.0) or 0.0) > 0.0

    recovery = compute_libra_recovery(ctx, steps_df, {"revenue_raw": revenue})
    fe_row = recovery.recovery_df[recovery.recovery_df["Target"].astype(str) == "Fe"]
    assert not fe_row.empty
    assert "Ferrous oxalate" in str(fe_row.iloc[0]["Products counted"])
    assert float(fe_row.iloc[0]["Recovered mass (kg/y)"]) > 0.0
