"""Route / feedstock filters for process-efficiency editing."""
from __future__ import annotations

import pandas as pd

from hydro_recovery_scope import resolve_pyro_hydro_recovery_scope
from step_utils import PACK_DISMANTLE_STEP, feed_has_pack_from_feed_list, feed_has_pack_level

FEEDSTOCK_TYPE_LABELS: dict[str, str] = {
    "nmc": "NMC Feedstock",
    "lfp": "LFP Feedstock",
    "mix": "Mixed NMC/LFP Feedstock",
}


def process_eff_area(step: str) -> str:
    s = str(step or "").strip()
    sl = s.lower()
    mechanical_steps = {
        "discharge",
        "pack dismantle",
        "shredding",
        "drying",
        "magnetic separation",
        "air-classification 1",
        "air-classification 2",
        "crushing",
        "sieving",
    }
    if s == "Analytics & Sorting":
        return "Analytics"
    if sl in mechanical_steps:
        return "Mechanical"
    if sl.startswith("pyro ") or s in {"Gas Scrubbing"}:
        return "Pyro"
    if s.startswith("Hydro NMC"):
        return "Hydro NMC"
    if s.startswith("Hydro LFP"):
        return "Hydro LFP"
    if s.startswith("Hydro Mix"):
        return "Hydro Mix"
    if s.startswith("Hydro-Pyro") or "Alloy" in s:
        return "Hydro Pyro Alloy"
    if s.startswith("Hydro Pyro"):
        return "Hydro Pyro Slag"
    return "Other"


def process_eff_areas_for_scenario(
    route: str,
    feedstock_type: str,
    *,
    pyro_hydro_recovery_scope: str = "all",
) -> tuple[str, ...]:
    """Process-efficiency areas that apply to the current route / feedstock selection."""
    route_key = str(route or "mech").strip().lower()
    ft = str(feedstock_type or "mix").strip().lower()
    common = ("Analytics", "Mechanical")
    if route_key == "pyro":
        scope = resolve_pyro_hydro_recovery_scope({"pyro_hydro_recovery_scope": pyro_hydro_recovery_scope})
        areas: list[str] = list(common + ("Pyro",))
        if scope in ("all", "co_ni_mn"):
            areas.append("Hydro Pyro Slag")
        areas.append("Hydro Pyro Alloy")
        return tuple(areas)
    if ft == "nmc":
        return common + ("Hydro NMC",)
    if ft == "lfp":
        return common + ("Hydro LFP",)
    return common + ("Hydro Mix",)


def process_eff_scenario_filter_label(route: str, feedstock_type: str) -> str:
    route_key = str(route or "mech").strip().lower()
    if route_key == "pyro":
        return "Pyrometallurgical → Hydrometallurgical"
    ft = str(feedstock_type or "mix").strip().lower()
    return f"Mechanical → Hydrometallurgical ({FEEDSTOCK_TYPE_LABELS.get(ft, ft)})"


def filter_eff_df_for_scenario(
    df: pd.DataFrame,
    route: str,
    feedstock_type: str,
    *,
    pyro_hydro_recovery_scope: str = "all",
    ctx: dict | None = None,
    feed: list | None = None,
) -> pd.DataFrame:
    if df is None or df.empty or "Area" not in df.columns:
        return df
    allowed = set(
        process_eff_areas_for_scenario(
            route, feedstock_type, pyro_hydro_recovery_scope=pyro_hydro_recovery_scope
        )
    )
    out = df[df["Area"].astype(str).isin(allowed)].copy()
    if ctx is not None:
        has_pack = feed_has_pack_level(ctx)
    elif feed is not None:
        has_pack = feed_has_pack_from_feed_list(feed)
    else:
        has_pack = True
    if not has_pack and "Step" in out.columns:
        out = out[out["Step"].astype(str) != PACK_DISMANTLE_STEP].copy()
    return out
