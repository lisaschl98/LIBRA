from __future__ import annotations

import pandas as pd

from main import run_scenario
from process_eff_scope import filter_eff_df_for_scenario
from step_utils import PACK_DISMANTLE_STEP, feed_has_pack_from_feed_list, feed_has_pack_level


def test_feed_has_pack_from_feed_list() -> None:
    assert not feed_has_pack_from_feed_list([])
    assert not feed_has_pack_from_feed_list([{"cell_id": "NMC811_Prismatic", "level": "cell", "share": 1.0}])
    assert not feed_has_pack_from_feed_list([{"cell_id": "NMC811_Prismatic", "level": "pack", "share": 0.0}])
    assert feed_has_pack_from_feed_list([{"cell_id": "NMC811_Prismatic", "level": "pack", "share": 0.5}])


def test_filter_eff_df_excludes_pack_dismantle_without_pack() -> None:
    df = pd.DataFrame(
        {
            "__row_id": [0, 1, 2],
            "Area": ["Analytics", "Mechanical", "Mechanical"],
            "Step": ["Analytics & Sorting", PACK_DISMANTLE_STEP, "Shredding"],
            "Value": [1.0, 0.99, 0.98],
        }
    )
    out = filter_eff_df_for_scenario(
        df,
        "mech",
        "nmc",
        feed=[{"cell_id": "NMC811_Prismatic", "level": "cell", "share": 1.0}],
    )
    assert PACK_DISMANTLE_STEP not in out["Step"].astype(str).tolist()
    assert "Shredding" in out["Step"].astype(str).tolist()


def test_run_scenario_cell_only_skips_pack_dismantle() -> None:
    scen = {
        "name": "Cell_only_test",
        "region": "DE",
        "route": "mech",
        "mass_feed_kg_y": 10000.0,
        "pack_energy_kWh": 100.0,
        "pack_energy_by_id": {},
        "feed": [{"cell_id": "NMC811_Prismatic", "level": "cell", "share": 1.0}],
    }
    steps_df, extras, ctx = run_scenario(scen)

    assert not feed_has_pack_level(ctx)
    assert PACK_DISMANTLE_STEP not in steps_df["Step"].astype(str).tolist()
    assert PACK_DISMANTLE_STEP not in extras
