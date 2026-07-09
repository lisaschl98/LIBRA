from __future__ import annotations

import pytest

from S02_Discharge.S02_Discharge import (
    cells_per_feed_unit,
    discharge_recovery_from_feed,
)


def test_cells_per_feed_unit_levels() -> None:
    assert cells_per_feed_unit("cell", cells_per_module=12, cells_per_pack=96) == 1
    assert cells_per_feed_unit("module", cells_per_module=12, cells_per_pack=96) == 12
    assert cells_per_feed_unit("pack", cells_per_module=12, cells_per_pack=96) == 96


def test_discharge_recovery_pack_level() -> None:
    ctx = {
        "hours_per_year": 8400.0,
        "feed_details": [
            {
                "cell_id": "NMC_18650",
                "level": "pack",
                "units_per_year": 10.0,
                "cell_energy_Wh": 60.0,
                "cells_per_module": 10,
                "cells_per_pack": 100,
            }
        ],
    }
    rec = discharge_recovery_from_feed(ctx)
    # 10 packs * 100 cells * 0.06 kWh = 60 kWh/y stored
    assert rec["stored_energy_kWh_y"] == pytest.approx(60.0)
    # 60 * 0.3 * 0.9 = 16.2 kWh/y recovered
    assert rec["kWh_y_recovered"] == pytest.approx(16.2)
    assert rec["kWh_h_recovered"] == pytest.approx(16.2 / 8400.0)
    assert rec["cells_discharged_per_y"] == pytest.approx(1000.0)


def test_discharge_recovery_cell_level_matches_pack() -> None:
    ctx_pack = {
        "hours_per_year": 8400.0,
        "feed_details": [
            {
                "cell_id": "LFP_Pouch",
                "level": "pack",
                "units_per_year": 5.0,
                "cell_energy_Wh": 50.0,
                "cells_per_module": 8,
                "cells_per_pack": 200,
            }
        ],
    }
    ctx_cell = {
        "hours_per_year": 8400.0,
        "feed_details": [
            {
                "cell_id": "LFP_Pouch",
                "level": "cell",
                "units_per_year": 5.0 * 200.0,
                "cell_energy_Wh": 50.0,
                "cells_per_module": 8,
                "cells_per_pack": 200,
            }
        ],
    }
    rec_pack = discharge_recovery_from_feed(ctx_pack)
    rec_cell = discharge_recovery_from_feed(ctx_cell)
    assert rec_pack["kWh_y_recovered"] == pytest.approx(rec_cell["kWh_y_recovered"])
    assert rec_pack["stored_energy_kWh_y"] == pytest.approx(rec_cell["stored_energy_kWh_y"])


def test_discharge_recovery_module_level() -> None:
    ctx = {
        "hours_per_year": 8400.0,
        "feed_details": [
            {
                "cell_id": "NMC_2170",
                "level": "module",
                "units_per_year": 20.0,
                "cell_energy_Wh": 20.0,
                "cells_per_module": 24,
                "cells_per_pack": 96,
            }
        ],
    }
    rec = discharge_recovery_from_feed(ctx)
    # 20 modules * 24 cells * 0.02 kWh = 9.6 kWh/y
    assert rec["stored_energy_kWh_y"] == pytest.approx(9.6)
    assert rec["kWh_y_recovered"] == pytest.approx(9.6 * 0.3 * 0.9)
