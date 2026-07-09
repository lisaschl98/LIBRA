from __future__ import annotations

import pandas as pd

from process_eff_scope import (
    filter_eff_df_for_scenario,
    process_eff_areas_for_scenario,
)


def test_process_eff_areas_pyro() -> None:
    areas = process_eff_areas_for_scenario("pyro", "mix")
    assert "Pyro" in areas
    assert "Hydro Pyro Slag" in areas
    assert "Hydro NMC" not in areas


def test_process_eff_areas_mech_nmc() -> None:
    areas = process_eff_areas_for_scenario("mech", "nmc")
    assert areas == ("Analytics", "Mechanical", "Hydro NMC")


def test_filter_eff_df_for_scenario() -> None:
    df = pd.DataFrame(
        {
            "__row_id": [0, 1, 2],
            "Area": ["Analytics", "Hydro NMC", "Hydro LFP"],
            "Step": ["Analytics & Sorting", "Hydro NMC – Digestion", "Hydro LFP – Digestion"],
            "Value": [1.0, 2.0, 3.0],
        }
    )
    out = filter_eff_df_for_scenario(df, "mech", "nmc")
    assert list(out["Area"]) == ["Analytics", "Hydro NMC"]
