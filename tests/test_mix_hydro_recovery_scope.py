from __future__ import annotations

from hydro_recovery_scope import resolve_mix_hydro_recovery_scope
from main import SCENARIOS, run_scenario


def test_resolve_mix_hydro_recovery_scope_rejects_legacy_fepo4() -> None:
    assert resolve_mix_hydro_recovery_scope({"mix_hydro_recovery_scope": "fepo4"}) == "all"


def _mix_scenario() -> dict:
    for scen in SCENARIOS:
        if scen.get("name") == "Mech_10tpy_MIX_unlimited_Co_basis":
            return dict(scen)
    raise AssertionError("Mix scenario not found")


def test_mix_hydro_scope_nmc_skips_li_and_fe_steps() -> None:
    scen = _mix_scenario()
    scen["mix_hydro_recovery_scope"] = "nmc"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro Mix – NMC Drying" in step_names
    assert "Hydro Mix – Wastewater Treatment" in step_names
    assert "Hydro Mix – Li Precipitation" not in step_names
    assert "Hydro Mix – Roasting" not in step_names


def test_mix_hydro_scope_nmc_li_skips_fe_steps() -> None:
    scen = _mix_scenario()
    scen["mix_hydro_recovery_scope"] = "nmc_li"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro Mix – Li Drying" in step_names
    assert "Hydro Mix – Fe Concentration" not in step_names
    assert "Hydro Mix – Roasting" not in step_names


def test_mix_hydro_scope_all_includes_full_line() -> None:
    scen = _mix_scenario()
    scen["mix_hydro_recovery_scope"] = "all"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro Mix – NMC Drying" in step_names
    assert "Hydro Mix – Li Drying" in step_names
    assert "Hydro Mix – Roasting" in step_names
