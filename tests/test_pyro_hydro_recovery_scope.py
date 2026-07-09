from __future__ import annotations

from hydro_recovery_scope import resolve_pyro_hydro_recovery_scope
from main import SCENARIOS, run_scenario


def test_resolve_pyro_hydro_recovery_scope_aliases() -> None:
    assert resolve_pyro_hydro_recovery_scope({"pyro_hydro_recovery_scope": "co+ni"}) == "co_ni"
    assert resolve_pyro_hydro_recovery_scope({"pyro_hydro_recovery_scope": "co+ni+mn"}) == "co_ni_mn"


def _pyro_scenario() -> dict:
    for scen in SCENARIOS:
        if scen.get("name") == "Pyro_10tpy":
            return dict(scen)
    raise AssertionError("Pyro scenario not found")


def test_pyro_hydro_scope_all_includes_full_line() -> None:
    scen = _pyro_scenario()
    scen["pyro_hydro_recovery_scope"] = "all"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Pyro Granulation Slag" in step_names
    assert "Hydro Pyro – Slag Digestion" in step_names
    assert "Hydro Pyro – Li Drying" in step_names
    assert "Hydro-Pyro - Ni Crystallization" in step_names


def test_pyro_hydro_scope_co_ni_skips_slag_line() -> None:
    scen = _pyro_scenario()
    scen["pyro_hydro_recovery_scope"] = "co_ni"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Pyro Granulation Alloy" in step_names
    assert "Pyro Granulation Slag" not in step_names
    assert "Hydro Pyro – Slag Digestion" not in step_names
    assert "Hydro-Pyro - Co Crystallization" in step_names
    assert "Hydro-Pyro - Ni Crystallization" in step_names


def test_pyro_hydro_scope_co_skips_ni_crystallization() -> None:
    scen = _pyro_scenario()
    scen["pyro_hydro_recovery_scope"] = "co"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro-Pyro - Co Crystallization" in step_names
    assert "Hydro-Pyro - Ni Crystallization" not in step_names
    assert "Hydro-Pyro - Alloy Wastewater Treatment" in step_names
    assert "Pyro Granulation Slag" not in step_names


def test_pyro_hydro_scope_co_ni_mn_skips_li_line() -> None:
    scen = _pyro_scenario()
    scen["pyro_hydro_recovery_scope"] = "co_ni_mn"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Pyro Granulation Slag" in step_names
    assert "Hydro Pyro – Mn Crystallization" in step_names
    assert "Hydro Pyro – Li Concentration" not in step_names
    assert "Hydro Pyro – Li Drying" not in step_names
    assert "Hydro Pyro – Li Wastewater Treatment" in step_names
    assert "Hydro-Pyro - Ni Crystallization" in step_names


def test_pyro_lfp_only_keeps_zero_mass_hydropyro_steps() -> None:
    scen = _pyro_scenario()
    scen["name"] = "Pyro_LFP_only"
    scen["feed"] = [{"cell_id": "LFP_Pouch", "level": "module", "share": 1.0}]
    scen["pyro_hydro_recovery_scope"] = "all"

    steps_df, _extras, _ctx = run_scenario(scen)
    step_names = set(steps_df["Step"].astype(str).tolist())

    assert "Hydro Pyro – Mn Extraction" in step_names
    assert "Hydro Pyro – Mn Crystallization" in step_names
    assert "Hydro-Pyro - Co Extraction" in step_names
    assert "Hydro-Pyro - Co Crystallization" in step_names
    assert "Hydro-Pyro - Ni Crystallization" in step_names
