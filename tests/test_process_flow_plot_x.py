from __future__ import annotations

from main import SCENARIOS, run_scenario
from app_helpers.process_flow_plot import (
    is_pyro_granulation_alloy_step,
    is_pyro_granulation_slag_step,
    process_flow_plot_x_positions,
)


def _pyro_hydro_branch_keys(step_names: list[str]) -> list[str | None]:
    """Minimal copy of branch-key logic for layout tests."""
    keys: list[str | None] = []
    current: str | None = None
    for name in step_names:
        sl = str(name).strip().lower()
        if not (sl.startswith("hydro pyro") or sl.startswith("hydro-pyro")):
            keys.append(None)
            continue
        name_l = sl
        explicit = None
        if "slag" in name_l or name_l.startswith("hydro pyro – li") or "li wastewater" in name_l:
            explicit = "slag"
        elif "alloy" in name_l or name_l.startswith("hydro-pyro -"):
            explicit = "alloy"
        if "slag digestion" in name_l:
            current = "slag"
            keys.append("slag")
        elif "alloy digestion" in name_l:
            current = "alloy"
            keys.append("alloy")
        elif explicit in {"slag", "alloy"}:
            current = explicit
            keys.append(explicit)
        elif current in {"slag", "alloy"}:
            keys.append(current)
        else:
            keys.append(None)
    return keys


def _first_index(step_names: list[str], pred) -> int | None:
    for i, name in enumerate(step_names):
        if pred(name):
            return i
    return None


def test_pyro_hydro_branches_start_below_granulation_parents() -> None:
    scen = next(s for s in SCENARIOS if str(s.get("route", "")).lower() == "pyro")
    steps_df, _, _ = run_scenario(scen)
    step_names = steps_df["Step"].astype(str).tolist()
    branch_keys = _pyro_hydro_branch_keys(step_names)
    x = process_flow_plot_x_positions(step_names, branch_keys, "pyro")

    alloy_gran = _first_index(step_names, is_pyro_granulation_alloy_step)
    slag_gran = _first_index(step_names, is_pyro_granulation_slag_step)
    alloy_hydro = next(i for i, k in enumerate(branch_keys) if k == "alloy")
    slag_hydro = next(i for i, k in enumerate(branch_keys) if k == "slag")

    assert alloy_gran is not None and slag_gran is not None
    assert x[alloy_hydro] == x[alloy_gran] + 1.0
    assert x[slag_hydro] == x[slag_gran] + 1.0
    assert x[alloy_hydro] < x[slag_hydro] + 5.0
