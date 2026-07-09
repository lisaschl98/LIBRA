"""Layout helpers for the process-structure dot plot (no Streamlit dependency)."""
from __future__ import annotations

_PROCESS_FLOW_BRANCH_OFFSET = 1.0


def _first_step_index(step_names: list[str], predicate) -> int | None:
    for idx, name in enumerate(step_names):
        if predicate(name):
            return idx
    return None


def is_pyro_granulation_alloy_step(step: str) -> bool:
    sl = str(step or "").lower()
    return "granulation" in sl and "alloy" in sl


def is_pyro_granulation_slag_step(step: str) -> bool:
    sl = str(step or "").lower()
    return "granulation" in sl and "slag" in sl


def process_flow_plot_x_positions(
    step_names: list[str],
    step_branch_keys: list[str | None],
    route: str | None,
) -> list[float]:
    """Assign x by parent-child branch layout (pyro alloy/slag hydro split)."""
    route_key = str(route or "").strip().lower()
    n = len(step_names)
    if route_key != "pyro" or not any(k in {"slag", "alloy"} for k in step_branch_keys):
        return [float(i) for i in range(n)]

    x = [0.0] * n
    main_x = 0.0
    slag_next_x: float | None = None
    alloy_next_x: float | None = None
    alloy_gran_idx = _first_step_index(step_names, is_pyro_granulation_alloy_step)
    slag_gran_idx = _first_step_index(step_names, is_pyro_granulation_slag_step)

    for i in range(n):
        branch = step_branch_keys[i]
        if branch == "slag":
            if slag_next_x is None:
                parent_idx = slag_gran_idx if slag_gran_idx is not None else max(i - 1, 0)
                slag_next_x = x[parent_idx] + _PROCESS_FLOW_BRANCH_OFFSET
            x[i] = slag_next_x
            slag_next_x += 1.0
        elif branch == "alloy":
            if alloy_next_x is None:
                parent_idx = alloy_gran_idx if alloy_gran_idx is not None else max(i - 1, 0)
                alloy_next_x = x[parent_idx] + _PROCESS_FLOW_BRANCH_OFFSET
            x[i] = alloy_next_x
            alloy_next_x += 1.0
        else:
            x[i] = main_x
            main_x += 1.0

    return x
