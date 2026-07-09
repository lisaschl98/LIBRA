from __future__ import annotations

from hydro_recovery_scope import resolve_nmc_hydro_recovery_scope
from main import SCENARIOS, run_scenario


def _nmc_only_scenario() -> dict:
    for scen in SCENARIOS:
        if scen.get("name") == "Mech_10tpy_NMC_unlimited_Co_basis":
            return dict(scen)
    raise AssertionError("NMC scenario not found")


def test_resolve_nmc_hydro_recovery_scope_rejects_legacy_li() -> None:
    assert resolve_nmc_hydro_recovery_scope({"nmc_hydro_recovery_scope": "li"}) == "all"
    assert resolve_nmc_hydro_recovery_scope({"nmc_hydro_recovery_scope": "nmc"}) == "nmc"


def test_nmc_hydro_scope_nmc_skips_li_steps() -> None:
    scen = _nmc_only_scenario()
    scen["nmc_hydro_recovery_scope"] = "nmc"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro NMC – NMC Drying" in step_names
    assert "Hydro NMC – Wastewater Treatment" in step_names
    assert "Hydro NMC – Li Precipitation" not in step_names
    assert "Hydro NMC – Li Filtration" not in step_names
    assert "Hydro NMC – Li Washing" not in step_names
    assert "Hydro NMC – Li Drying" not in step_names


def test_nmc_hydro_scope_all_includes_both_lines() -> None:
    scen = _nmc_only_scenario()
    scen["nmc_hydro_recovery_scope"] = "all"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro NMC – NMC Drying" in step_names
    assert "Hydro NMC – Li Drying" in step_names
