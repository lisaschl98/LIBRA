"""Hub-spoke infrastructure: dual-region economics and inter-site transport."""
from __future__ import annotations

import math
from typing import Any

import General_Parameters as gp
from Economics.Opex import compute_step_direct_cost
from Economics.Overhead import aggregate_tea
from Economics.Profit import compute_profit
from Economics.Revenue import compute_all_steps_output_economics, compute_step_output_economics
from Environmental.Burdens import compute_step_direct_emissions
from Environmental.Credits import compute_all_steps_output_emission_credits, compute_step_output_emission_credits
from Environmental.net_GWP import aggregate_net_gwp
from step_utils import normalize_row_for_economics

INFRASTRUCTURE_MODES: tuple[str, ...] = ("integrated", "hub_spoke")

LOCATION_OPTIONS: tuple[str, ...] = (
    "Germany",
    "EU",
    "China",
    "United States",
    "Custom",
)

LOCATION_LABELS: dict[str, str] = {
    "Germany": "Germany",
    "EU": "EU",
    "China": "China",
    "United States": "United States",
    "Custom": "Custom",
}

LOCATION_TO_REGION: dict[str, str] = {
    "Germany": "DE",
    "EU": "EU",
    "China": "CN",
    "United States": "US",
}

REGION_SIDEBAR_LABELS: dict[str, str] = {
    **{code: label for label, code in LOCATION_TO_REGION.items()},
    "Custom": "Custom",
}


def region_display_label(region: str) -> str:
    key = str(region or "").strip()
    return REGION_SIDEBAR_LABELS.get(key, key)

# Approximate centroids for lightweight world-map markers (lat, lon).
LOCATION_COORDINATES: dict[str, tuple[float, float]] = {
    "Germany": (51.0, 10.5),
    "EU": (50.1, 14.4),
    "China": (35.0, 105.0),
    "United States": (39.8, -98.5),
}

REGION_COORDINATES: dict[str, tuple[float, float]] = {
    "DE": LOCATION_COORDINATES["Germany"],
    "EU": LOCATION_COORDINATES["EU"],
    "CN": LOCATION_COORDINATES["China"],
    "US": LOCATION_COORDINATES["United States"],
}

DEFAULT_MAP_COORDINATES: tuple[float, float] = LOCATION_COORDINATES["Germany"]

# Symmetric preset distances [km] between region codes.
DISTANCE_KM: dict[tuple[str, str], float] = {
    ("DE", "DE"): 0.0,
    ("DE", "EU"): 600.0,
    ("DE", "CN"): 7800.0,
    ("DE", "US"): 6400.0,
    ("EU", "EU"): 0.0,
    ("EU", "CN"): 8200.0,
    ("EU", "US"): 7000.0,
    ("CN", "CN"): 0.0,
    ("CN", "US"): 11500.0,
    ("US", "US"): 0.0,
}

# Simple tonne-kilometre factors (USD / t·km and kg CO2-eq / t·km).
DEFAULT_TRANSPORT_COST_PER_T_KM = 0.123
DEFAULT_TRANSPORT_GWP_PER_T_KM = 0.1102001688172519

TRANSPORT_STEP_NAME = "Inter-site Transport"


def _safe(v: Any) -> float:
    try:
        x = float(v or 0.0)
        if math.isnan(x) or math.isinf(x):
            return 0.0
        return x
    except Exception:
        return 0.0


def is_hub_spoke_mode(scen: dict | None) -> bool:
    raw = str((scen or {}).get("infrastructure_mode", "integrated") or "integrated").strip().lower()
    return raw in ("hub_spoke", "hub-spoke", "dual")


def _location_key(scen: dict, field: str, fallback: str = "Germany") -> str:
    raw = str((scen or {}).get(field, fallback) or fallback).strip()
    if raw in LOCATION_OPTIONS:
        return raw
    for label, code in LOCATION_TO_REGION.items():
        if raw.upper() == code:
            return label
    return fallback


def location_to_region(location: str, scen: dict | None) -> str:
    loc = str(location or "").strip()
    if loc == "Custom":
        return str((scen or {}).get("region", "DE") or "DE").strip()
    return LOCATION_TO_REGION.get(loc, str((scen or {}).get("region", "DE") or "DE").strip())


def _parse_optional_coordinates(scen: dict | None, lat_key: str, lon_key: str) -> tuple[float, float] | None:
    raw = scen or {}
    try:
        lat = float(raw.get(lat_key))
        lon = float(raw.get(lon_key))
    except (TypeError, ValueError):
        return None
    if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
        return None
    if lat == 0.0 and lon == 0.0:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def resolve_location_coordinates(location: str, scen: dict | None, *, role: str) -> tuple[float, float]:
    """Map coordinates for a named or custom infrastructure location."""
    loc = str(location or "").strip()
    scen_dict = scen or {}
    if loc == "Custom":
        custom = _parse_optional_coordinates(scen_dict, f"{role}_latitude", f"{role}_longitude")
        if custom is not None:
            return custom
        region = location_to_region(loc, scen_dict)
        return REGION_COORDINATES.get(region, DEFAULT_MAP_COORDINATES)
    return LOCATION_COORDINATES.get(loc, DEFAULT_MAP_COORDINATES)


def resolve_integrated_site_coordinates(scen: dict | None) -> tuple[float, float]:
    """Map coordinates for an integrated single-site configuration."""
    scen_dict = scen or {}
    custom = _parse_optional_coordinates(scen_dict, "site_latitude", "site_longitude")
    if custom is not None:
        return custom
    region = str(scen_dict.get("region", "DE") or "DE").strip()
    return REGION_COORDINATES.get(region, DEFAULT_MAP_COORDINATES)


def resolve_spoke_region(scen: dict) -> str:
    if not is_hub_spoke_mode(scen):
        return str(scen.get("region", "DE") or "DE").strip()
    return location_to_region(_location_key(scen, "spoke_location"), scen)


def resolve_hub_region(scen: dict) -> str:
    if not is_hub_spoke_mode(scen):
        return str(scen.get("region", "DE") or "DE").strip()
    return location_to_region(_location_key(scen, "hub_location"), scen)


def is_hydro_step(step_name: str) -> bool:
    s = str(step_name or "").strip()
    sl = s.lower()
    return s.startswith("Hydro") or sl.startswith("hydro ")


def process_site_for_step(step_name: str) -> str:
    return "hub" if is_hydro_step(step_name) else "spoke"


def preset_distance_km(spoke_region: str, hub_region: str) -> float:
    """Legacy region-pair matrix (reference only; transport uses great-circle km)."""
    a = str(spoke_region or "").strip().upper()
    b = str(hub_region or "").strip().upper()
    if not a or not b:
        return 0.0
    if a == b:
        return 0.0
    key = (a, b)
    if key in DISTANCE_KM:
        return float(DISTANCE_KM[key])
    rev = (b, a)
    if rev in DISTANCE_KM:
        return float(DISTANCE_KM[rev])
    return 0.0


def great_circle_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle distance [km] between two WGS84 coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    earth_radius_km = 6371.0
    return round(earth_radius_km * 2.0 * math.asin(math.sqrt(min(1.0, a))), 0)


def _has_explicit_custom_coordinates(scen: dict | None, role: str) -> bool:
    return _parse_optional_coordinates(scen, f"{role}_latitude", f"{role}_longitude") is not None


def resolve_transport_distance_km(scen: dict) -> tuple[float, str]:
    """Return (distance_km, source).

    Source is one of: integrated | coordinates | custom_manual | same_location.
    """
    if not is_hub_spoke_mode(scen):
        return 0.0, "integrated"
    spoke_loc = _location_key(scen, "spoke_location")
    hub_loc = _location_key(scen, "hub_location")
    spoke_lat, spoke_lon = resolve_location_coordinates(spoke_loc, scen, role="spoke")
    hub_lat, hub_lon = resolve_location_coordinates(hub_loc, scen, role="hub")
    coord_distance = great_circle_distance_km(spoke_lat, spoke_lon, hub_lat, hub_lon)

    spoke_custom = spoke_loc == "Custom" and not _has_explicit_custom_coordinates(scen, "spoke")
    hub_custom = hub_loc == "Custom" and not _has_explicit_custom_coordinates(scen, "hub")
    manual_distance = max(0.0, _safe(scen.get("custom_transport_distance_km", 0.0)))
    if (spoke_custom or hub_custom) and manual_distance > 0.0:
        return manual_distance, "custom_manual"

    if coord_distance < 1.0:
        return 0.0, "same_location"
    return coord_distance, "coordinates"


def spoke_process_scope(route: str) -> str:
    route_key = str(route or "mech").strip().lower()
    if route_key == "pyro":
        return "Front-End + Pyro Pretreatment"
    return "Front-End + Pretreatment"


def hub_process_scope(route: str) -> str:
    return "Hydrometallurgical Refining"


def transport_stream_label(route: str) -> str:
    return "Black Mass" if str(route or "mech").strip().lower() == "mech" else "Pyro Hydro Feed (Alloy + Slag)"


def resolve_transport_factors(scen: dict | None) -> dict[str, float]:
    return {
        "transport_cost_per_t_km": _safe(
            (scen or {}).get("transport_cost_per_t_km", DEFAULT_TRANSPORT_COST_PER_T_KM)
        ),
        "transport_gwp_per_t_km": _safe(
            (scen or {}).get("transport_gwp_per_t_km", DEFAULT_TRANSPORT_GWP_PER_T_KM)
        ),
    }


def infrastructure_mode_label(mode: str) -> str:
    return "Hub-Spoke System" if str(mode).strip().lower() in ("hub_spoke", "hub-spoke", "dual") else "Integrated Site"


def size_sites(total_t_per_year: float, capacity_per_site_t_per_year: float) -> dict[str, float]:
    total = max(0.0, _safe(total_t_per_year))
    cap = max(1e-9, _safe(capacity_per_site_t_per_year))
    n = max(1, int(math.ceil(total / cap))) if total > 0.0 else 0
    per_site = (total / n) if n > 0 else 0.0
    utilization = (per_site / cap) if cap > 0.0 else 0.0
    return {
        "required_sites": float(n),
        "throughput_per_site_t_y": per_site,
        "utilization": utilization,
    }


def transport_cost_per_y(
    transported_t_per_year: float,
    distance_km: float,
    scen: dict | None = None,
) -> float:
    factor = _safe((scen or {}).get("transport_cost_per_t_km", DEFAULT_TRANSPORT_COST_PER_T_KM))
    return max(0.0, _safe(transported_t_per_year) * max(0.0, _safe(distance_km)) * factor)


def transport_gwp_per_y(
    transported_t_per_year: float,
    distance_km: float,
    scen: dict | None = None,
) -> float:
    factor = _safe((scen or {}).get("transport_gwp_per_t_km", DEFAULT_TRANSPORT_GWP_PER_T_KM))
    return max(0.0, _safe(transported_t_per_year) * max(0.0, _safe(distance_km)) * factor)


def fork_ctx_region(base_ctx: dict, region: str) -> dict:
    ctx = dict(base_ctx)
    gp.apply_region(ctx, str(region).strip())
    return ctx


def ctx_for_step(step_row: dict[str, Any], base_ctx: dict, scen: dict) -> dict:
    if not is_hub_spoke_mode(scen):
        return fork_ctx_region(base_ctx, str(scen.get("region", "DE") or "DE"))
    site = str(step_row.get("Process site", process_site_for_step(step_row.get("Step", ""))) or "spoke").lower()
    region = resolve_hub_region(scen) if site == "hub" else resolve_spoke_region(scen)
    return fork_ctx_region(base_ctx, region)


def transport_opex_step(cost_per_y: float) -> dict[str, Any]:
    c = max(0.0, _safe(cost_per_y))
    return {
        "step_name": TRANSPORT_STEP_NAME,
        "cost_materials_per_y": c,
        "cost_energy_per_y": 0.0,
        "cost_water_per_y": 0.0,
        "cost_labor_per_y": 0.0,
        "cost_direct_total_per_y": c,
        "maintenance_per_y": 0.0,
        "depreciation_per_y": 0.0,
        "supplies_per_y": 0.0,
        "CAPEX equip ($)": 0.0,
        "CAPEX install ($)": 0.0,
        "CAPEX instr ($)": 0.0,
        "CAPEX piping ($)": 0.0,
        "CAPEX electrical ($)": 0.0,
        "CAPEX building ($)": 0.0,
    }


def transport_emission_step(gwp_per_y: float) -> dict[str, Any]:
    g = max(0.0, _safe(gwp_per_y))
    return {
        "step_name": TRANSPORT_STEP_NAME,
        "emission_materials_kgco2e_per_y": g,
        "emission_energy_kgco2e_per_y": 0.0,
        "emission_water_kgco2e_per_y": 0.0,
        "emission_direct_total_kgco2e_per_y": g,
    }


def compute_infrastructure(
    scen: dict,
    ctx: dict,
    *,
    route: str,
    feed_mass_kg_per_year: float,
    transported_mass_kg_per_year: float,
) -> dict[str, Any]:
    feed_t_y = _safe(feed_mass_kg_per_year) / 1000.0
    transported_t_y = _safe(transported_mass_kg_per_year) / 1000.0
    pretreatment_cap = max(
        1e-9,
        _safe(scen.get("pretreatment_capacity_t_y", scen.get("annual_feed_t_y", feed_t_y)) or feed_t_y),
    )
    hydro_cap = max(
        1e-9,
        _safe(scen.get("hydro_capacity_t_bm_y", scen.get("hydro_capacity_t_y", transported_t_y)) or transported_t_y),
    )

    hub_spoke = is_hub_spoke_mode(scen)
    spoke_sizing = size_sites(feed_t_y, pretreatment_cap)
    hub_sizing = size_sites(transported_t_y, hydro_cap)

    spoke_region = resolve_spoke_region(scen)
    hub_region = resolve_hub_region(scen)
    spoke_loc = _location_key(scen, "spoke_location")
    hub_loc = _location_key(scen, "hub_location")
    distance_km, distance_source = resolve_transport_distance_km(scen)
    transport_factors = resolve_transport_factors(scen)

    transport_cost_y = 0.0
    transport_gwp_y = 0.0
    if hub_spoke and transported_t_y > 0.0 and distance_km > 0.0:
        transport_cost_y = transport_cost_per_y(transported_t_y, distance_km, scen)
        transport_gwp_y = transport_gwp_per_y(transported_t_y, distance_km, scen)

    denom_kg_y = _safe(ctx.get("feed_mass_kg_per_year") or feed_mass_kg_per_year)
    perkg_cost = (transport_cost_y / denom_kg_y) if denom_kg_y > 0.0 else 0.0
    perkg_gwp = (transport_gwp_y / denom_kg_y) if denom_kg_y > 0.0 else 0.0

    stream_label = transport_stream_label(route)
    mode_key = "hub_spoke" if hub_spoke else "integrated"

    return {
        "mode": mode_key,
        "mode_label": infrastructure_mode_label(mode_key),
        "route": str(route),
        "spoke_location": spoke_loc,
        "hub_location": hub_loc,
        "spoke_region": spoke_region,
        "hub_region": hub_region,
        "spoke_process_scope": spoke_process_scope(route),
        "hub_process_scope": hub_process_scope(route),
        "transport_stream": stream_label,
        "transported_mass_kg_per_year": transported_t_y * 1000.0,
        "transported_mass_t_per_year": transported_t_y,
        "distance_km": distance_km,
        "distance_source": distance_source,
        "preset_distance_km": preset_distance_km(spoke_region, hub_region),
        "great_circle_distance_km": great_circle_distance_km(
            *resolve_location_coordinates(spoke_loc, scen, role="spoke"),
            *resolve_location_coordinates(hub_loc, scen, role="hub"),
        ),
        "transport_cost_per_t_km": transport_factors["transport_cost_per_t_km"],
        "transport_gwp_per_t_km": transport_factors["transport_gwp_per_t_km"],
        "pretreatment_capacity_t_y": pretreatment_cap,
        "hydro_capacity_t_y": hydro_cap,
        "required_spokes": spoke_sizing["required_sites"],
        "pretreatment_utilization": spoke_sizing["utilization"],
        "feed_per_spoke_t_y": spoke_sizing["throughput_per_site_t_y"],
        "required_hubs": hub_sizing["required_sites"],
        "hydro_utilization": hub_sizing["utilization"],
        "black_mass_per_hub_t_y": hub_sizing["throughput_per_site_t_y"],
        "transport_cost_per_y": transport_cost_y,
        "transport_gwp_kgco2e_per_y": transport_gwp_y,
        "transport_cost_per_kg_feed": perkg_cost,
        "transport_gwp_kgco2e_per_kg_feed": perkg_gwp,
    }


def infrastructure_export_row(scen: dict, ctx: dict, scen_name: str | None = None) -> dict[str, Any]:
    """One Excel-ready row for the Infrastructure sheet."""
    infra = dict((ctx or {}).get("infrastructure") or {})
    if not infra:
        infra = compute_infrastructure(
            scen,
            ctx,
            route=str(scen.get("route", "mech")),
            feed_mass_kg_per_year=_safe(ctx.get("feed_mass_kg_per_year")),
            transported_mass_kg_per_year=_safe(ctx.get("black_mass_kg_per_year")),
        )

    integrated = str(infra.get("mode", "integrated")) == "integrated"
    return {
        "Scenario": str(scen_name or scen.get("name", "") or ""),
        "Infrastructure Configuration": infra.get("mode_label", infrastructure_mode_label(infra.get("mode", "integrated"))),
        "Spoke Location": "-" if integrated else infra.get("spoke_location", "-"),
        "Hub Location": "-" if integrated else infra.get("hub_location", "-"),
        "Spoke Region": str(scen.get("region", infra.get("spoke_region", "-"))) if integrated else infra.get("spoke_region", "-"),
        "Hub Region": "-" if integrated else infra.get("hub_region", "-"),
        "Transported Stream": "none (integrated site)" if integrated else infra.get("transport_stream", "-"),
        "Transported Mass [t/y]": _safe(infra.get("transported_mass_t_per_year")),
        "Distance [km]": _safe(infra.get("distance_km")),
        "Transport Cost Factor [$/ (t·km)]": _safe(infra.get("transport_cost_per_t_km")),
        "Transport GWP Factor [kg CO2-eq/(t·km)]": _safe(infra.get("transport_gwp_per_t_km")),
        "Transport Cost [$/y]": _safe(infra.get("transport_cost_per_y")),
        "Transport Cost [$/kg feed]": _safe(infra.get("transport_cost_per_kg_feed")),
        "Transport GWP [kg CO2-eq/y]": _safe(infra.get("transport_gwp_kgco2e_per_y")),
        "Transport GWP [kg CO2-eq/kg feed]": _safe(infra.get("transport_gwp_kgco2e_per_kg_feed")),
        "Required Spokes": _safe(infra.get("required_spokes")),
        "Required Hubs": _safe(infra.get("required_hubs")),
        "Pretreatment Site Capacity": _safe(infra.get("pretreatment_capacity_t_y")),
        "Hydrometallurgical Hub Capacity": _safe(infra.get("hydro_capacity_t_y")),
        "Spoke Utilization [%]": _safe(infra.get("pretreatment_utilization")) * 100.0,
        "Hub Utilization [%]": _safe(infra.get("hydro_utilization")) * 100.0,
    }


def run_info_infrastructure_fields(scen: dict, ctx: dict) -> dict[str, Any]:
    """Compact infrastructure fields for Run_Info / scenario summaries."""
    row = infrastructure_export_row(scen, ctx)
    mode = str((ctx.get("infrastructure") or {}).get("mode", scen.get("infrastructure_mode", "integrated")))
    compact = {
        "infrastructure_configuration": row["Infrastructure Configuration"],
        "spoke_location": row["Spoke Location"],
        "hub_location": row["Hub Location"],
        "spoke_region": row["Spoke Region"],
        "hub_region": row["Hub Region"],
        "transported_stream": row["Transported Stream"],
        "transported_mass_t_y": row["Transported Mass [t/y]"],
        "transport_distance_km": row["Distance [km]"],
        "transport_cost_per_kg_feed": row["Transport Cost [$/kg feed]"],
        "transport_gwp_per_kg_feed": row["Transport GWP [kg CO2-eq/kg feed]"],
    }
    if mode == "integrated":
        compact["spoke_location"] = "-"
        compact["hub_location"] = "-"
        compact["transported_stream"] = "none (integrated site)"
    return compact


def _compute_multi_ctx_opex(step_dicts: list[dict[str, Any]], base_ctx: dict, scen: dict) -> dict[str, Any]:
    all_material_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for row in step_dicts:
        row_ctx = ctx_for_step(row, base_ctx, scen)
        step_res = compute_step_direct_cost(row, row_ctx)
        all_material_lines.extend(step_res.pop("material_lines"))
        step_totals.append(step_res)

    direct_opex_total_per_y = sum(_safe(s.get("cost_direct_total_per_y")) for s in step_totals)

    grouped_cost: dict[tuple[str, str], float] = {}
    grouped_qty_h: dict[tuple[str, str], float] = {}
    grouped_qty_y: dict[tuple[str, str], float] = {}
    for ln in all_material_lines:
        k = (ln["step_name"], ln["item"])
        grouped_cost[k] = grouped_cost.get(k, 0.0) + _safe(ln.get("cost_per_y"))
        grouped_qty_h[k] = grouped_qty_h.get(k, 0.0) + _safe(ln.get("qty_kg_h"))
        grouped_qty_y[k] = grouped_qty_y.get(k, 0.0) + _safe(ln.get("qty_kg_y"))

    material_cost_by_step_item = [
        {
            "step_name": k[0],
            "item": k[1],
            "qty_kg_h": grouped_qty_h[k],
            "qty_kg_y": grouped_qty_y[k],
            "cost_per_y": v,
        }
        for k, v in grouped_cost.items()
    ]

    return {
        "material_lines": all_material_lines,
        "material_cost_by_step_item": material_cost_by_step_item,
        "step_totals": step_totals,
        "direct_opex_total_per_y": direct_opex_total_per_y,
    }


def _compute_multi_ctx_burdens(step_dicts: list[dict[str, Any]], base_ctx: dict, scen: dict) -> dict[str, Any]:
    all_material_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for row in step_dicts:
        row_ctx = ctx_for_step(row, base_ctx, scen)
        step_res = compute_step_direct_emissions(row, row_ctx)
        all_material_lines.extend(step_res.pop("material_lines"))
        step_totals.append(step_res)

    direct_emissions_total_kgco2e_per_y = sum(
        _safe(s.get("emission_direct_total_kgco2e_per_y")) for s in step_totals
    )

    grouped_emissions: dict[tuple[str, str], float] = {}
    grouped_qty_h: dict[tuple[str, str], float] = {}
    grouped_qty_y: dict[tuple[str, str], float] = {}
    for ln in all_material_lines:
        k = (ln["step_name"], ln["item"])
        grouped_emissions[k] = grouped_emissions.get(k, 0.0) + _safe(ln.get("emission_kgco2e_per_y"))
        grouped_qty_h[k] = grouped_qty_h.get(k, 0.0) + _safe(ln.get("qty_kg_h"))
        grouped_qty_y[k] = grouped_qty_y.get(k, 0.0) + _safe(ln.get("qty_kg_y"))

    material_emission_by_step_item = [
        {
            "step_name": k[0],
            "item": k[1],
            "qty_kg_h": grouped_qty_h[k],
            "qty_kg_y": grouped_qty_y[k],
            "emission_kgco2e_per_y": v,
        }
        for k, v in grouped_emissions.items()
    ]

    return {
        "material_lines": all_material_lines,
        "material_emission_by_step_item": material_emission_by_step_item,
        "step_totals": step_totals,
        "direct_emissions_total_kgco2e_per_y": direct_emissions_total_kgco2e_per_y,
    }


def _compute_multi_ctx_revenue(step_dicts: list[dict[str, Any]], base_ctx: dict, scen: dict) -> dict[str, Any]:
    from collections import defaultdict

    all_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for row in step_dicts:
        row_ctx = ctx_for_step(row, base_ctx, scen)
        step_res = compute_step_output_economics(row, row_ctx)
        all_lines.extend(step_res.pop("output_lines", []) or [])
        step_totals.append(step_res)

    revenue_total_per_y = sum(_safe(x.get("revenue_per_y")) for x in step_totals)
    output_cost_total_per_y = sum(_safe(x.get("output_cost_per_y")) for x in step_totals)
    net_output_value_total_per_y = revenue_total_per_y - output_cost_total_per_y

    by_step_item = defaultdict(float)
    for ln in all_lines:
        by_step_item[(ln["step_name"], ln["item"], ln["economic_type"], ln["category"])] += _safe(
            ln.get("amount_per_y")
        )

    by_step_item_rows = [
        {
            "step_name": k[0],
            "item": k[1],
            "economic_type": k[2],
            "category": k[3],
            "amount_per_y": v,
        }
        for k, v in by_step_item.items()
    ]

    return {
        "output_lines": all_lines,
        "by_step_item": by_step_item_rows,
        "step_totals": step_totals,
        "revenue_total_per_y": revenue_total_per_y,
        "output_cost_total_per_y": output_cost_total_per_y,
        "net_output_value_total_per_y": net_output_value_total_per_y,
    }


def _compute_multi_ctx_credits(step_dicts: list[dict[str, Any]], base_ctx: dict, scen: dict) -> dict[str, Any]:
    from collections import defaultdict

    all_lines: list[dict[str, Any]] = []
    step_totals: list[dict[str, Any]] = []

    for row in step_dicts:
        row_ctx = ctx_for_step(row, base_ctx, scen)
        step_res = compute_step_output_emission_credits(row, row_ctx)
        all_lines.extend(step_res.pop("output_lines", []) or [])
        step_totals.append(step_res)

    credit_total_kgco2e_per_y = sum(_safe(x.get("credit_kgco2e_per_y")) for x in step_totals)
    burden_total_kgco2e_per_y = sum(_safe(x.get("burden_kgco2e_per_y")) for x in step_totals)
    net_output_effect_total_kgco2e_per_y = burden_total_kgco2e_per_y - credit_total_kgco2e_per_y

    by_step_item = defaultdict(float)
    for ln in all_lines:
        by_step_item[(ln["step_name"], ln["item"], ln["environmental_type"], ln["category"])] += _safe(
            ln.get("amount_kgco2e_per_y")
        )

    by_step_item_rows = [
        {
            "step_name": k[0],
            "item": k[1],
            "environmental_type": k[2],
            "category": k[3],
            "amount_kgco2e_per_y": v,
        }
        for k, v in by_step_item.items()
    ]

    return {
        "output_lines": all_lines,
        "by_step_item": by_step_item_rows,
        "step_totals": step_totals,
        "credit_total_kgco2e_per_y": credit_total_kgco2e_per_y,
        "burden_total_kgco2e_per_y": burden_total_kgco2e_per_y,
        "net_output_effect_total_kgco2e_per_y": net_output_effect_total_kgco2e_per_y,
    }


def aggregate_dual_region_overhead(
    base_ctx: dict,
    flows: dict,
    step_rows: list,
    scen: dict,
    infra: dict | None = None,
) -> dict:
    """Build economics/environmental payload with per-step regional parameters."""
    import pandas as pd

    overhead_payload: dict = {}
    try:
        if not _safe(base_ctx.get("feed_mass_kg_per_year")):
            base_ctx["feed_mass_kg_per_year"] = (
                _safe(getattr(flows.get("total"), "mass_kg_per_h", 0.0))
                * _safe(base_ctx.get("hours_per_year"))
            )

        normalized_rows = []
        for r in step_rows:
            if r is None or getattr(r, "empty", True):
                continue
            preview = r.iloc[0].to_dict()
            row_ctx = ctx_for_step(preview, base_ctx, scen)
            normalized_rows.append(normalize_row_for_economics(r, row_ctx))

        step_dicts = [r.iloc[0].to_dict() for r in normalized_rows if r is not None and not r.empty]

        if is_hub_spoke_mode(scen):
            opex_res = _compute_multi_ctx_opex(step_dicts, base_ctx, scen)
            burdens_res = _compute_multi_ctx_burdens(step_dicts, base_ctx, scen)
            revenue_res = _compute_multi_ctx_revenue(step_dicts, base_ctx, scen)
            credits_res = _compute_multi_ctx_credits(step_dicts, base_ctx, scen)
        else:
            ctx_single = fork_ctx_region(base_ctx, str(scen.get("region", "DE") or "DE"))
            from Economics.Opex import compute_all_steps_direct_opex
            from Environmental.Burdens import compute_all_steps_direct_emissions

            opex_res = compute_all_steps_direct_opex(step_dicts, ctx_single)
            burdens_res = compute_all_steps_direct_emissions(step_dicts, ctx_single)
            revenue_res = compute_all_steps_output_economics(step_dicts, ctx_single)
            credits_res = compute_all_steps_output_emission_credits(step_dicts, ctx_single)

        if infra and _safe(infra.get("transport_cost_per_y")) > 0.0:
            opex_res["step_totals"].append(transport_opex_step(_safe(infra.get("transport_cost_per_y"))))
            opex_res["direct_opex_total_per_y"] = sum(
                _safe(s.get("cost_direct_total_per_y")) for s in opex_res.get("step_totals", [])
            )

        if infra and _safe(infra.get("transport_gwp_kgco2e_per_y")) > 0.0:
            burdens_res["step_totals"].append(
                transport_emission_step(_safe(infra.get("transport_gwp_kgco2e_per_y")))
            )
            burdens_res["direct_emissions_total_kgco2e_per_y"] = sum(
                _safe(s.get("emission_direct_total_kgco2e_per_y")) for s in burdens_res.get("step_totals", [])
            )

        oh_res = aggregate_tea(base_ctx, opex_res.get("step_totals", []))
        oh_summary_raw = oh_res.get("summary", {}) if isinstance(oh_res, dict) else {}
        oh_for_profit = {
            "summary": {
                "total_product_costs_per_y": float((oh_summary_raw or {}).get("TPC ($/y)", 0.0) or 0.0),
                "overhead_total_per_y": float((oh_summary_raw or {}).get("Overhead total ($/y)", 0.0) or 0.0),
            }
        }
        profit_res = compute_profit(opex_res, oh_for_profit, revenue_res)
        net_gwp_res = aggregate_net_gwp(base_ctx, burdens_res, credits_res)

        summary_df = pd.DataFrame([oh_res.get("summary", {})])
        capex_df = pd.DataFrame([oh_res.get("capex", {})])
        manufact_df = pd.DataFrame([oh_res.get("manufacturing", {})])

        overhead_payload = {
            "summary": summary_df,
            "capex": capex_df,
            "manufacturing": manufact_df,
            "opex": opex_res,
            "revenue": revenue_res,
            "profit": profit_res,
            "environmental": {
                "burdens": burdens_res,
                "credits": credits_res,
                "net_gwp": net_gwp_res,
            },
            "infrastructure": infra or {},
        }
    except Exception as e:
        print(f"[WARN] Economics aggregation failed: {e}")
    return overhead_payload
