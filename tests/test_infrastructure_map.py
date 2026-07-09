from __future__ import annotations

import pytest

from infrastructure import (
    LOCATION_COORDINATES,
    resolve_integrated_site_coordinates,
    resolve_location_coordinates,
)
from app_helpers.infrastructure_map import (
    _great_circle_points,
    _transport_hover_text,
    build_infrastructure_world_map_figure,
)


def test_preset_location_coordinates() -> None:
    lat, lon = resolve_location_coordinates("Germany", {}, role="spoke")
    assert lat == LOCATION_COORDINATES["Germany"][0]
    assert lon == LOCATION_COORDINATES["Germany"][1]


def test_custom_location_uses_optional_coordinates() -> None:
    scen = {
        "region": "DE",
        "spoke_latitude": 48.1,
        "spoke_longitude": 11.6,
    }
    lat, lon = resolve_location_coordinates("Custom", scen, role="spoke")
    assert abs(lat - 48.1) < 1e-9
    assert abs(lon - 11.6) < 1e-9


def test_integrated_site_coordinates_from_region() -> None:
    lat, lon = resolve_integrated_site_coordinates({"region": "CN"})
    assert lat == LOCATION_COORDINATES["China"][0]
    assert lon == LOCATION_COORDINATES["China"][1]


def test_great_circle_points_has_multiple_coordinates() -> None:
    lats, lons = _great_circle_points(51.0, 10.0, 35.0, 105.0, n_points=12)
    assert len(lats) == 12
    assert len(lons) == 12
    assert abs(lats[0] - 51.0) < 1e-6
    assert abs(lons[0] - 10.0) < 1e-6


def test_transport_hover_text_from_infra() -> None:
    hover = _transport_hover_text(
        {
            "transport_stream": "Black Mass",
            "transported_mass_t_per_year": 5628.0,
            "distance_km": 7349.0,
            "transport_cost_per_kg_feed": 0.3309,
            "transport_gwp_kgco2e_per_kg_feed": 0.2564,
        }
    )
    assert hover is not None
    assert "Black Mass" in hover
    assert "5,628" in hover


def test_build_hub_spoke_map_figure() -> None:
    pytest.importorskip("plotly")
    scen = {
        "infrastructure_mode": "hub_spoke",
        "spoke_location": "Germany",
        "hub_location": "China",
        "region": "DE",
        "route": "mech",
    }
    infra = {
        "mode": "hub_spoke",
        "spoke_location": "Germany",
        "hub_location": "China",
        "route": "mech",
        "required_spokes": 2.0,
        "required_hubs": 1.0,
        "pretreatment_utilization": 0.8,
        "hydro_utilization": 0.6,
        "transport_stream": "Black Mass",
        "transported_mass_t_per_year": 5254.0,
        "distance_km": 7800.0,
        "transport_cost_per_kg_feed": 0.01,
        "transport_gwp_kgco2e_per_kg_feed": 0.02,
    }
    fig = build_infrastructure_world_map_figure(infra, scen)
    assert fig is not None
    assert len(fig.data) == 4
    legend_names = {str(trace.name) for trace in fig.data}
    assert "Hydrometallurgical Plant" in legend_names
    assert "Transported stream" not in legend_names
    hover_traces = [
        trace
        for trace in fig.data
        if getattr(trace, "mode", "") == "markers" and getattr(trace.marker, "opacity", None) == 0.01
    ]
    assert hover_traces


def test_build_integrated_map_figure_single_marker() -> None:
    pytest.importorskip("plotly")
    scen = {"infrastructure_mode": "integrated", "region": "DE"}
    fig = build_infrastructure_world_map_figure({}, scen)
    assert fig is not None
    assert len(fig.data) == 1
