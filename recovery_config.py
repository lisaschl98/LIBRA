"""
Recovery configuration (single source of truth).

Formula (per target):
  Recovery % = 100 * recovered_target_mass_in_products / target_mass_in_feed

Recovery input basis (``Input mass (kg/y)``):
  1. **Battery feed:** sum over all ``ctx["feed_details"]`` rows (UNIFIED pack composition).
  2. **Process additions** (where configured): e.g. ``Fe added`` from Cu-cementation steps.

  Not taken from intermediate massflow steps — only initial feed + explicit process inputs.

Categories:
  - active: cell:Cathode (Li, Ni, Co, Mn, Fe) + cell:Anode:Graphite
  - component: Al, Cu, Fe, Steel, Electronics (remaining pack/module/cell materials)

Edit pools and ROUTE_PRODUCT_RULES here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

import pandas as pd

RecoveryCategory = Literal["active", "component"]

ROUTE_KEYS: tuple[str, ...] = ("pyro", "lfp", "nmc", "mix")

# --- Feed input pools (comp_abs keys) -----------------------------------------

ACTIVE_POOLS: dict[str, tuple[str, ...]] = {
    "Li": ("cell:Cathode:Li",),
    "P": ("cell:Cathode:P",),
    "Ni": ("cell:Cathode:Ni",),
    "Co": ("cell:Cathode:Co",),
    "Mn": ("cell:Cathode:Mn",),
    "Fe": ("cell:Cathode:Fe",),
    # Graphite filtration separates all carbonaceous anode/cathode solids into one stream.
    "Graphite": (
        "cell:Anode:Graphite",
        "cell:Anode:Carbon Black Anode",
        "cell:Cathode:Carbon Black Cathode",
    ),
}

# Extra input from process steps (column in steps_df → targets), not in UNIFIED feed_details.
STEP_INPUT_ADDITIONS: dict[str, tuple[str, ...]] = {
    "Fe": ("Fe added (kg/h)",),
}

# Active Fe input includes cementation Fe (→ iron oxalate / FePO4-C products).
ROUTES_WITH_FE_CEMENT_INPUT: frozenset[str] = frozenset({"lfp", "mix"})
# Pyro / NMC: cement Fe + cathode Fe → iron hydroxide / scrap (structural Iron), not active Fe.
ROUTES_FE_CEMENT_TO_IRON: frozenset[str] = frozenset({"pyro", "nmc"})

# Reference keys from UNIFIED ``feed_details`` / CellDB (for tests and docs).
# Not in pool: ``cell:Packing Container:Polyethylene-laminated aluminium foil`` (laminate, not structural Al basis).
COMPONENT_BOM_REFERENCE: dict[str, tuple[str, ...]] = {
    "Al": (
        "cell:Cathode:Aluminium",
        "cell:Packing Container:Aluminium",
        "module:Al",
        "pack:Al",
    ),
    "Cu": ("cell:Anode:Copper", "module:Cu", "pack:Cu"),
    "Iron": ("pack:Fe",),
    "Steel": (
        "cell:Packing Container:Nickel-plated steel",
        "module:Steel",
        "pack:Steel",
    ),
    "Electronics": ("module:Electronics", "pack:Electronics"),
}

COMPONENT_POOLS: dict[str, tuple[str, ...]] = {
    target: keys for target, keys in COMPONENT_BOM_REFERENCE.items()
}

# Pyro / NMC: cathode Fe is recovered as structural iron (hydroxide / scrap), not active Fe.
ROUTES_IRON_INCLUDES_CATHODE_FE: frozenset[str] = frozenset({"pyro", "nmc"})
IRON_EXTRA_POOL_KEYS: tuple[str, ...] = ("cell:Cathode:Fe",)
# Pyro: only the Iron-pool share of Fe in iron hydroxide counts toward Iron (steel share excluded).
ROUTES_IRON_HYDROXIDE_SPLIT_BY_ORIGIN: frozenset[str] = frozenset({"pyro"})
# Fe mass fraction in structural steel BOM keys (denominator for pyro hydroxide split only).
STEEL_FE_MASS_FRAC: float = 0.98

ACTIVE_TARGET_ORDER: tuple[str, ...] = ("Li", "P", "Ni", "Co", "Mn", "Fe", "Graphite")

# Routes with LFP cathode chemistry (LiFePO4 / LiH2PO4 / FePO4-C products).
ROUTES_WITH_P_RECOVERY: frozenset[str] = frozenset({"lfp", "mix"})
COMPONENT_TARGET_ORDER: tuple[str, ...] = ("Al", "Cu", "Iron", "Steel", "Electronics")


@dataclass(frozen=True)
class ProductRule:
    """Match saleable product name (normalized substring) → recovery targets."""

    product_match: str
    category: RecoveryCategory
    nmc_precursor_feed_only: bool = False


def _rules(*items: ProductRule) -> tuple[ProductRule, ...]:
    return items


# Shared component / scrap products (all routes that use hydrometallurgy + dismantling)
_COMPONENT_PRODUCTS: tuple[ProductRule, ...] = (
    ProductRule("aluminium scrap", "component"),
    ProductRule("copper scrap", "component"),
    ProductRule("electronic scrap", "component"),
    ProductRule("iron scrap", "component"),
    ProductRule("steel scrap", "component"),
    ProductRule("aluminium hydroxide", "component"),
    ProductRule("iron hydroxide", "component"),
)

ROUTE_PRODUCT_RULES: dict[str, tuple[ProductRule, ...]] = {
    "pyro": _COMPONENT_PRODUCTS
    + (
        ProductRule("manganese sulfate", "active"),
        ProductRule("lithium carbonate", "active"),
        ProductRule("cobalt sulfate", "active"),
        ProductRule("nickel sulfate", "active"),
    ),
    "lfp": _COMPONENT_PRODUCTS
    + (
        ProductRule("lithium carbonate", "active"),
        ProductRule("iron oxalate", "active"),
        ProductRule("ferrous oxalate", "active"),
        ProductRule("lithium dihydrogenphosphate", "active"),
        ProductRule("graphite", "active"),
    ),
    "nmc": _COMPONENT_PRODUCTS
    + (
        ProductRule("lithium carbonate", "active"),
        ProductRule("manganese sulfate", "active"),
        ProductRule("nickel sulfate", "active"),
        ProductRule("cobalt sulfate", "active"),
        ProductRule("graphite", "active"),
        ProductRule("nmc precursor", "active", nmc_precursor_feed_only=True),
    ),
    "mix": _COMPONENT_PRODUCTS
    + (
        ProductRule("lithium carbonate", "active"),
        ProductRule("iron oxalate", "active"),
        ProductRule("ferrous oxalate", "active"),
        ProductRule("lithium dihydrogenphosphate", "active"),
        ProductRule("graphite", "active"),
        ProductRule("manganese sulfate", "active"),
        ProductRule("nickel sulfate", "active"),
        ProductRule("cobalt sulfate", "active"),
        ProductRule("carbon coated iron phosphate", "active"),
        ProductRule("nmc precursor", "active", nmc_precursor_feed_only=True),
    ),
}


def resolve_recovery_route(ctx: dict | None) -> str:
    ctx = ctx or {}
    explicit = str(ctx.get("recovery_route") or "").strip().lower()
    if explicit in ROUTE_KEYS:
        return explicit
    route = str(ctx.get("route") or "").strip().lower()
    if route == "pyro":
        return "pyro"
    flags = ctx.get("recovery_flags") or {}
    if flags.get("mix_lfp_nmc"):
        return "mix"
    if flags.get("lfp_only"):
        return "lfp"
    if flags.get("nmc_only"):
        return "nmc"
    return "mech"


def active_targets_for_route(recovery_route: str) -> tuple[str, ...]:
    """Route-specific active detail rows (pyro/nmc Fe → structural; P only on LFP/mix)."""
    targets = list(ACTIVE_TARGET_ORDER)
    if recovery_route in ("pyro", "nmc"):
        targets = [t for t in targets if t != "Fe"]
    if recovery_route not in ROUTES_WITH_P_RECOVERY:
        targets = [t for t in targets if t != "P"]
    return tuple(targets)


def component_targets() -> tuple[str, ...]:
    return COMPONENT_TARGET_ORDER


def feed_pool_keys(recovery_route: str, target: str) -> tuple[str, ...]:
    if target in ACTIVE_POOLS:
        return ACTIVE_POOLS[target]
    if target in COMPONENT_POOLS:
        keys = COMPONENT_POOLS[target]
        if recovery_route in ROUTES_IRON_INCLUDES_CATHODE_FE and target == "Iron":
            return keys + IRON_EXTRA_POOL_KEYS
        return keys
    return ()


def target_category(target: str) -> RecoveryCategory | None:
    if target in ACTIVE_POOLS:
        return "active"
    if target in COMPONENT_POOLS:
        return "component"
    return None


def get_product_rules(recovery_route: str | None) -> tuple[ProductRule, ...]:
    return ROUTE_PRODUCT_RULES.get(str(recovery_route or "").strip().lower(), ())


def find_product_rule(product: str, rules: tuple[ProductRule, ...]) -> ProductRule | None:
    from recovery_metrics import _norm_lower

    def _compact(s: str) -> str:
        return _norm_lower(s).replace(" ", "")

    nl = _compact(product)
    exact = [r for r in rules if _compact(r.product_match) == nl]
    if exact:
        return exact[-1]

    def _tokens_match(rule_match: str) -> bool:
        parts = [p for p in _norm_lower(rule_match).split() if p]
        if not parts:
            return False
        return all(_compact(p) in nl for p in parts)

    partial = [r for r in rules if _compact(r.product_match) in nl or _tokens_match(r.product_match)]
    return partial[-1] if partial else None


def recovery_table_targets(recovery_route: str) -> tuple[str, ...]:
    """Detail rows: active rollup + active elements + structural (route-specific active set)."""
    return ("active",) + active_targets_for_route(recovery_route) + component_targets()


def active_rollup_targets(recovery_route: str) -> tuple[str, ...]:
    return active_targets_for_route(recovery_route)


def iter_unified_feed_comp_kg_h(ctx: dict | None) -> Iterable[tuple[str, float]]:
    """Yield (comp_abs_key, kg/h) for each component in every UNIFIED ``feed_details`` row."""
    for row in (ctx or {}).get("feed_details") or []:
        if not isinstance(row, dict):
            continue
        try:
            units_per_h = float(row.get("units_per_h") or 0.0)
        except (TypeError, ValueError):
            continue
        if units_per_h <= 0.0:
            continue
        comp = row.get("comp_abs_kg_per_unit") or {}
        if not isinstance(comp, dict):
            continue
        for comp_key, per_unit_kg in comp.items():
            try:
                m = float(per_unit_kg) * units_per_h
            except (TypeError, ValueError):
                continue
            if m > 0.0:
                yield str(comp_key), m


def battery_feed_input_mass_kg_h(ctx: dict | None, recovery_route: str, target: str) -> float:
    """Target mass [kg/h] from UNIFIED ``feed_details`` only (route-specific pool)."""
    keys = feed_pool_keys(recovery_route, target)
    if not keys:
        return 0.0
    exclude_cathode_fe = target == "Iron" and recovery_route not in ROUTES_IRON_INCLUDES_CATHODE_FE
    return feed_mass_for_keys(
        iter_unified_feed_comp_kg_h(ctx),
        keys,
        exclude_cathode_fe=exclude_cathode_fe,
    )


def unified_feed_input_mass_kg_h(ctx: dict | None, recovery_route: str, target: str) -> float:
    """Alias for :func:`battery_feed_input_mass_kg_h` (battery-only, no process additions)."""
    return battery_feed_input_mass_kg_h(ctx, recovery_route, target)


def process_addition_input_mass_kg_h(
    steps_df: pd.DataFrame | None,
    recovery_route: str,
    target: str,
) -> float:
    """Process-side input [kg/h] added on-route (e.g. Fe powder for Cu cementation)."""
    if target == "Fe" and recovery_route not in ROUTES_WITH_FE_CEMENT_INPUT:
        return 0.0
    if target == "Fe" and recovery_route in ROUTES_FE_CEMENT_TO_IRON:
        return 0.0
    if target == "Iron" and recovery_route in ROUTES_FE_CEMENT_TO_IRON:
        cols = STEP_INPUT_ADDITIONS.get("Fe")
    else:
        cols = STEP_INPUT_ADDITIONS.get(target)
    if not cols or steps_df is None or steps_df.empty:
        return 0.0
    total = 0.0
    for col in cols:
        if col not in steps_df.columns:
            continue
        total += float(pd.to_numeric(steps_df[col], errors="coerce").fillna(0.0).sum())
    return total


def recovery_input_mass_kg_h(
    ctx: dict | None,
    recovery_route: str,
    target: str,
    steps_df: pd.DataFrame | None = None,
) -> float:
    """Full recovery input basis [kg/h]: UNIFIED battery feed + configured process additions."""
    if target == "Fe" and recovery_route in ROUTES_IRON_INCLUDES_CATHODE_FE:
        return 0.0
    return battery_feed_input_mass_kg_h(ctx, recovery_route, target) + process_addition_input_mass_kg_h(
        steps_df, recovery_route, target
    )


def recovery_input_mass_kg_y(
    ctx: dict | None,
    recovery_route: str,
    target: str,
    steps_df: pd.DataFrame | None = None,
) -> float:
    """Recovery table ``Input mass (kg/y)`` basis."""
    try:
        hours_y = float((ctx or {}).get("hours_per_year") or 8760.0)
    except (TypeError, ValueError):
        hours_y = 8760.0
    return recovery_input_mass_kg_h(ctx, recovery_route, target, steps_df) * hours_y


def unified_feed_input_mass_kg_y(ctx: dict | None, recovery_route: str, target: str) -> float:
    """Battery feed only [kg/y] — prefer :func:`recovery_input_mass_kg_y` for recovery tables."""
    try:
        hours_y = float((ctx or {}).get("hours_per_year") or 8760.0)
    except (TypeError, ValueError):
        hours_y = 8760.0
    return unified_feed_input_mass_kg_h(ctx, recovery_route, target) * hours_y


def feed_mass_for_keys(
    comp_items,
    feed_keys: tuple[str, ...],
    *,
    exclude_cathode_fe: bool = False,
) -> float:
    """
    Sum feed mass for comp_abs keys (exact match per pattern).

    UNIFIED feed_details may list several cell variants that share the same key
    (e.g. cell:Cathode:Li); each row is a separate feed share and must be summed.
    """
    if not feed_keys:
        return 0.0
    total = 0.0
    for ck, m in comp_items:
        ck_l = str(ck).lower()
        if exclude_cathode_fe and ck_l.startswith("cell:cathode:") and ck_l.endswith(":fe"):
            continue
        if any(_key_matches(ck, fk) for fk in feed_keys):
            total += float(m)
    return total


def _key_matches(comp_key: str, pattern: str) -> bool:
    """Exact comp_abs key match (case-insensitive) — avoids e.g. cell:Fe matching Cathode:Fe."""
    return str(comp_key).strip().lower() == str(pattern).strip().lower()
