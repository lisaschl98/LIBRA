"""Lightweight Plotly world-map visualization for LIBRA infrastructure."""
from __future__ import annotations

import math
from typing import Any

from infrastructure import (    hub_process_scope,
    is_hub_spoke_mode,
    resolve_hub_region,
    resolve_integrated_site_coordinates,
    resolve_location_coordinates,
    resolve_spoke_region,
    spoke_process_scope,
)

try:
    import plotly.graph_objects as go
except Exception:  # pragma: no cover
    go = None  # type: ignore[assignment,misc]

MAP_BRAND_BLUE = "#003B75"
MAP_PRETREATMENT = "#C9A004"
MAP_ACCENT = MAP_BRAND_BLUE
MAP_LINE = "#7A8FA6"
MAP_LAND = "#E8EDF3"
MAP_WATER = "#F7FAFD"


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v if v is not None else default)
        if x != x or x in (float("inf"), float("-inf")):
            return default
        return x
    except (TypeError, ValueError):
        return default


def _great_circle_points(
    lat1_deg: float,
    lon1_deg: float,
    lat2_deg: float,
    lon2_deg: float,
    *,
    n_points: int = 28,
) -> tuple[list[float], list[float]]:
    """Interpolate coordinates along a great-circle arc."""
    if n_points < 2:
        n_points = 2
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1_deg, lon1_deg, lat2_deg, lon2_deg])
    delta = 2.0 * math.asin(
        math.sqrt(
            math.sin((lat2 - lat1) / 2.0) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2.0) ** 2
        )
    )
    if delta < 1e-12:
        return [lat1_deg], [lon1_deg]

    lats: list[float] = []
    lons: list[float] = []
    for idx in range(n_points):
        f = idx / (n_points - 1)
        a = math.sin((1.0 - f) * delta) / math.sin(delta)
        b = math.sin(f * delta) / math.sin(delta)
        x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
        y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
        z = a * math.sin(lat1) + b * math.sin(lat2)
        lats.append(math.degrees(math.atan2(z, math.sqrt(x * x + y * y))))
        lons.append(math.degrees(math.atan2(y, x)))
    return lats, lons


def _transport_hover_text(infra_dict: dict[str, Any]) -> str | None:
    stream = str(infra_dict.get("transport_stream", "-"))
    transported_t_y = _safe_float(infra_dict.get("transported_mass_t_per_year"))
    distance_km = _safe_float(infra_dict.get("distance_km"))
    if distance_km <= 0.0:
        return None
    transport_cost_kg = _safe_float(infra_dict.get("transport_cost_per_kg_feed"))
    transport_gwp_kg = _safe_float(infra_dict.get("transport_gwp_kgco2e_per_kg_feed"))
    return (
        f"<b>{stream}</b><br>"
        f"Mass: {transported_t_y:,.0f} t/y<br>"
        f"Distance: {distance_km:,.0f} km<br>"
        f"Transport cost: ${transport_cost_kg:,.4f} / kg feed<br>"
        f"Transport GWP: {transport_gwp_kg:,.4f} kg CO2-eq / kg feed"
    )


def _base_geo_layout(*, title: str) -> dict[str, Any]:
    return dict(
        projection_type="natural earth",
        showland=True,
        landcolor=MAP_LAND,
        showcountries=True,
        countrycolor="white",
        showocean=True,
        oceancolor=MAP_WATER,
        showlakes=False,
        showframe=False,
        bgcolor=MAP_WATER,
        lataxis=dict(showgrid=False),
        lonaxis=dict(showgrid=False),
    )


def _marker_trace(
    *,
    lat: float,
    lon: float,
    name: str,
    color: str,
    symbol: str,
    hover: str,
    showlegend: bool = True,
) -> Any:
    return go.Scattergeo(
        lat=[lat],
        lon=[lon],
        mode="markers",
        name=name,
        marker=dict(size=14, color=color, symbol=symbol, line=dict(width=1.5, color="white")),
        hovertemplate=hover + "<extra></extra>",
        showlegend=showlegend,
    )


def _apply_map_layout(
    fig: Any,
    *,
    compact: bool,
    hub_spoke: bool,
    lons: list[float] | None = None,
    lats: list[float] | None = None,
    compact_height: int = 285,
    legend_below: bool = False,
) -> None:
    if compact:
        fig.update_layout(
            title=None,
            geo=_base_geo_layout(title=""),
            height=int(compact_height),
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=False,
        )
        fig.update_traces(showlegend=False)
        for marker_name in ("Pretreatment Plant", "Hydrometallurgical Plant", "Integrated Recycling Site"):
            fig.update_traces(marker=dict(size=11), selector=dict(name=marker_name))
        if hub_spoke and lons and lats:
            lon_pad = max(12.0, (max(lons) - min(lons)) * 0.45)
            lat_pad = max(8.0, (max(lats) - min(lats)) * 0.45)
            fig.update_geos(
                lonaxis_range=[min(lons) - lon_pad, max(lons) + lon_pad],
                lataxis_range=[max(-60.0, min(lats) - lat_pad), min(80.0, max(lats) + lat_pad)],
            )
        elif not hub_spoke:
            fig.update_geos(lonaxis_range=[-180, 180], lataxis_range=[-60, 80])
        return

    if legend_below:
        fig.update_layout(
            title=None,
            geo=_base_geo_layout(title=""),
            height=int(compact_height or 520),
            margin=dict(l=0, r=0, t=0, b=52),
            legend=dict(orientation="h", yanchor="top", y=-0.08, xanchor="center", x=0.5),
        )
        return

    fig.update_layout(
        title=dict(text="Infrastructure Map", x=0.02, xanchor="left", font=dict(size=14, color=MAP_BRAND_BLUE)),
        geo=_base_geo_layout(title="Infrastructure Map"),
        height=420,
        margin=dict(l=0, r=0, t=42, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
    )


def build_infrastructure_world_map_figure(
    infra: dict | None,
    scen: dict | None,
    *,
    compact: bool = False,
    compact_height: int | None = None,
    legend_below: bool = False,
) -> Any | None:
    """Return a Plotly figure with pretreatment / hydro markers and optional transport line."""
    if go is None:
        return None

    scen_dict = dict(scen or {})
    infra_dict = dict(infra or {})
    hub_spoke = is_hub_spoke_mode(scen_dict)
    show_legend = not compact
    map_height = int(compact_height or 285)
    fig = go.Figure()

    if not hub_spoke:
        lat, lon = resolve_integrated_site_coordinates(scen_dict)
        region = str(scen_dict.get("region", resolve_spoke_region(scen_dict)))
        location_label = region if region != "Custom" else "Custom site"
        hover = (
            f"<b>Integrated Recycling Site</b><br>"
            f"Location: {location_label}<br>"
            f"Region: {region}"
        )
        fig.add_trace(
            _marker_trace(
                lat=lat,
                lon=lon,
                name="Integrated Recycling Site",
                color=MAP_BRAND_BLUE,
                symbol="circle",
                hover=hover,
                showlegend=show_legend,
            )
        )
        _apply_map_layout(fig, compact=compact, hub_spoke=False, compact_height=map_height, legend_below=legend_below)
        if not compact:
            fig.update_geos(lonaxis_range=[-180, 180], lataxis_range=[-60, 80])
        return fig

    spoke_loc = str(infra_dict.get("spoke_location", scen_dict.get("spoke_location", "Germany")))
    hub_loc = str(infra_dict.get("hub_location", scen_dict.get("hub_location", "Germany")))
    spoke_lat, spoke_lon = resolve_location_coordinates(spoke_loc, scen_dict, role="spoke")
    hub_lat, hub_lon = resolve_location_coordinates(hub_loc, scen_dict, role="hub")

    route = str(infra_dict.get("route", scen_dict.get("route", "mech")))
    spoke_label = spoke_process_scope(route)
    hub_label = hub_process_scope(route)
    n_spokes = _safe_float(infra_dict.get("required_spokes"))
    n_hubs = _safe_float(infra_dict.get("required_hubs"))
    spoke_util = _safe_float(infra_dict.get("pretreatment_utilization")) * 100.0
    hub_util = _safe_float(infra_dict.get("hydro_utilization")) * 100.0
    distance_km = _safe_float(infra_dict.get("distance_km"))

    spoke_hover = (
        f"<b>{spoke_label}</b><br>"
        f"Location: {spoke_loc}<br>"
        f"Region: {resolve_spoke_region(scen_dict)}<br>"
        f"Required pretreatment sites: {int(round(n_spokes))}<br>"
        f"Utilization: {spoke_util:.1f}%"
    )
    hub_hover = (
        f"<b>{hub_label}</b><br>"
        f"Location: {hub_loc}<br>"
        f"Region: {resolve_hub_region(scen_dict)}<br>"
        f"Required hydro hubs: {int(round(n_hubs))}<br>"
        f"Utilization: {hub_util:.1f}%"
    )

    fig.add_trace(
        _marker_trace(
            lat=spoke_lat,
            lon=spoke_lon,
            name="Pretreatment Plant",
            color=MAP_PRETREATMENT,
            symbol="circle",
            hover=spoke_hover,
            showlegend=show_legend,
        )
    )
    fig.add_trace(
        _marker_trace(
            lat=hub_lat,
            lon=hub_lon,
            name="Hydrometallurgical Plant",
            color=MAP_BRAND_BLUE,
            symbol="diamond",
            hover=hub_hover,
            showlegend=show_legend,
        )
    )

    if distance_km > 0.0 and (abs(spoke_lat - hub_lat) > 1e-6 or abs(spoke_lon - hub_lon) > 1e-6):
        transport_hover = _transport_hover_text(infra_dict)
        if transport_hover:
            route_lats, route_lons = _great_circle_points(spoke_lat, spoke_lon, hub_lat, hub_lon)
            fig.add_trace(
                go.Scattergeo(
                    lat=route_lats,
                    lon=route_lons,
                    mode="lines",
                    line=dict(width=3.5, color=MAP_LINE),
                    hoverinfo="skip",
                    showlegend=False,
                    name="Transport route",
                )
            )
            fig.add_trace(
                go.Scattergeo(
                    lat=route_lats,
                    lon=route_lons,
                    mode="markers",
                    marker=dict(size=18, color=MAP_LINE, opacity=0.01, line=dict(width=0)),
                    customdata=["transport"] * len(route_lats),
                    hovertemplate=transport_hover + "<extra></extra>",
                    showlegend=False,
                    name="Transport route",
                )
            )

    lons = [spoke_lon, hub_lon]
    lats = [spoke_lat, hub_lat]
    _apply_map_layout(
        fig,
        compact=compact,
        hub_spoke=True,
        lons=lons,
        lats=lats,
        compact_height=map_height,
        legend_below=legend_below,
    )
    if not compact:
        lon_pad = max(12.0, (max(lons) - min(lons)) * 0.35)
        lat_pad = max(8.0, (max(lats) - min(lats)) * 0.35)
        fig.update_geos(
            lonaxis_range=[min(lons) - lon_pad, max(lons) + lon_pad],
            lataxis_range=[max(-60.0, min(lats) - lat_pad), min(80.0, max(lats) + lat_pad)],
        )
    return fig
