from __future__ import annotations

import copy

import pandas as pd

from infrastructure import (
    LOCATION_COORDINATES,
    compute_infrastructure,
    great_circle_distance_km,
    is_hub_spoke_mode,
    preset_distance_km,
    resolve_hub_region,
    resolve_spoke_region,
    resolve_transport_distance_km,
    size_sites,
    transport_cost_per_y,
)
from main import SCENARIOS, run_scenario
from Save import export_single_run_to_excel_bytes


def _scenario_by_route(route: str) -> dict:
    for scen in SCENARIOS:
        if str(scen.get("route", "")).strip().lower() == route:
            return copy.deepcopy(scen)
    raise AssertionError(f"No scenario for route={route}")


def test_size_sites_ceil_and_utilization() -> None:
    res = size_sites(25000.0, 10000.0)
    assert res["required_sites"] == 3.0
    assert abs(res["throughput_per_site_t_y"] - 25000.0 / 3.0) < 1e-9
    assert abs(res["utilization"] - (25000.0 / 3.0) / 10000.0) < 1e-9


def test_hub_spoke_mode_detection() -> None:
    assert not is_hub_spoke_mode({"infrastructure_mode": "integrated"})
    assert is_hub_spoke_mode({"infrastructure_mode": "hub_spoke"})


def test_location_to_region_mapping() -> None:
    scen = {"region": "DE", "spoke_location": "China", "hub_location": "United States"}
    assert resolve_spoke_region({**scen, "infrastructure_mode": "hub_spoke"}) == "CN"
    assert resolve_hub_region({**scen, "infrastructure_mode": "hub_spoke"}) == "US"


def test_transport_cost_scales_with_distance() -> None:
    low = transport_cost_per_y(1000.0, 0.0)
    high = transport_cost_per_y(1000.0, preset_distance_km("DE", "CN"))
    assert low == 0.0
    assert high > 0.0


def test_germany_china_uses_great_circle_distance_from_coordinates() -> None:
    scen = {
        "infrastructure_mode": "hub_spoke",
        "spoke_location": "Germany",
        "hub_location": "China",
        "region": "DE",
        "custom_transport_distance_km": 0.0,
    }
    distance_km, source = resolve_transport_distance_km(scen)
    de = LOCATION_COORDINATES["Germany"]
    cn = LOCATION_COORDINATES["China"]
    expected = great_circle_distance_km(de[0], de[1], cn[0], cn[1])
    assert source == "coordinates"
    assert distance_km == expected
    assert 7300.0 < distance_km < 7400.0


def test_custom_coordinates_use_great_circle_distance() -> None:
    scen = {
        "infrastructure_mode": "hub_spoke",
        "spoke_location": "Custom",
        "hub_location": "Custom",
        "region": "DE",
        "spoke_latitude": 52.5,
        "spoke_longitude": 13.4,
        "hub_latitude": 31.2,
        "hub_longitude": 121.5,
    }
    distance_km, source = resolve_transport_distance_km(scen)
    assert source == "coordinates"
    assert distance_km == great_circle_distance_km(52.5, 13.4, 31.2, 121.5)
    assert 8300.0 < distance_km < 8500.0


def test_hub_spoke_hydro_steps_have_energy_burden() -> None:
    base = _scenario_by_route("mech")
    dual = copy.deepcopy(base)
    dual.update(
        {
            "infrastructure_mode": "hub_spoke",
            "spoke_location": "Germany",
            "hub_location": "China",
            "pretreatment_capacity_t_y": float(base["mass_feed_kg_y"]) / 1000.0,
            "hydro_capacity_t_bm_y": 5000.0,
            "custom_transport_distance_km": 0.0,
        }
    )
    _steps, extras, _ctx = run_scenario(dual)
    burdens = pd.DataFrame(extras["Overhead"]["environmental"]["burdens"]["step_totals"])
    hydro = burdens[burdens["step_name"].astype(str).str.startswith("Hydro")]
    assert not hydro.empty
    assert float(hydro["emission_energy_kgco2e_per_y"].sum()) > 0.0


def test_hub_spoke_run_germany_china_has_transport_cost() -> None:
    base = _scenario_by_route("mech")
    dual = copy.deepcopy(base)
    dual.update(
        {
            "infrastructure_mode": "hub_spoke",
            "spoke_location": "Germany",
            "hub_location": "China",
            "pretreatment_capacity_t_y": float(base["mass_feed_kg_y"]) / 1000.0,
            "hydro_capacity_t_bm_y": 5000.0,
            "custom_transport_distance_km": 0.0,
        }
    )
    _steps, _extras, ctx = run_scenario(dual)
    infra = ctx["infrastructure"]
    assert 7300.0 < float(infra.get("distance_km", 0.0)) < 7400.0
    assert infra.get("distance_source") == "coordinates"
    assert float(infra.get("transport_cost_per_y", 0.0)) > 0.0
    assert float(infra.get("transport_gwp_kgco2e_per_y", 0.0)) > 0.0


def test_dual_region_mech_run_differs_from_single_region_when_regions_differ() -> None:
    base = None
    for scen in SCENARIOS:
        if str(scen.get("route", "")).lower() == "mech":
            base = copy.deepcopy(scen)
            break
    assert base is not None

    integrated = copy.deepcopy(base)
    integrated["infrastructure_mode"] = "integrated"
    integrated["region"] = "DE"

    dual = copy.deepcopy(base)
    dual["infrastructure_mode"] = "hub_spoke"
    dual["region"] = "DE"
    dual["spoke_location"] = "Germany"
    dual["hub_location"] = "China"
    dual["pretreatment_capacity_t_y"] = float(base["mass_feed_kg_y"]) / 1000.0
    dual["hydro_capacity_t_bm_y"] = 5000.0

    _steps_i, extras_i, ctx_i = run_scenario(integrated)
    _steps_d, extras_d, ctx_d = run_scenario(dual)

    tpc_i = float(extras_i["Overhead"]["summary"].iloc[0]["TPC ($/y)"])
    tpc_d = float(extras_d["Overhead"]["summary"].iloc[0]["TPC ($/y)"])
    assert tpc_d != tpc_i

    infra = ctx_d.get("infrastructure", {})
    assert infra.get("mode") == "hub_spoke"
    assert infra.get("spoke_region") == "DE"
    assert infra.get("hub_region") == "CN"
    assert float(infra.get("transport_cost_per_y", 0.0)) > 0.0

    hydro_regions = set(
        _steps_d.loc[_steps_d["Process site"] == "hub", "Region"].astype(str).tolist()
    )
    spoke_regions = set(
        _steps_d.loc[_steps_d["Process site"] == "spoke", "Region"].astype(str).tolist()
    )
    assert hydro_regions == {"CN"}
    assert spoke_regions == {"DE"}


def test_infrastructure_excel_export_contains_sheet() -> None:
    scen = _scenario_by_route("mech")
    dual = copy.deepcopy(scen)
    dual["infrastructure_mode"] = "hub_spoke"
    dual["spoke_location"] = "Germany"
    dual["hub_location"] = "China"
    dual["pretreatment_capacity_t_y"] = float(scen["mass_feed_kg_y"]) / 1000.0
    dual["hydro_capacity_t_bm_y"] = 5000.0
    steps_df, extras, ctx = run_scenario(dual)
    xlsx = export_single_run_to_excel_bytes(dual, steps_df, extras, ctx)
    import pandas as pd
    from io import BytesIO

    sheets = pd.ExcelFile(BytesIO(xlsx)).sheet_names
    assert "Infrastructure" in sheets
    infra_df = pd.read_excel(BytesIO(xlsx), sheet_name="Infrastructure")
    assert "Transport Cost Factor [$/ (t·km)]" in infra_df.columns
    assert "Infrastructure Configuration" in infra_df.columns
    assert "Pretreatment Site Capacity" in infra_df.columns
    assert "Hydrometallurgical Hub Capacity" in infra_df.columns
    assert float(infra_df.iloc[0]["Required Spokes"]) >= 1.0


def test_compute_infrastructure_returns_transport_per_kg_feed() -> None:
    scen = {
        "infrastructure_mode": "hub_spoke",
        "spoke_location": "Germany",
        "hub_location": "China",
        "pretreatment_capacity_t_y": 10000.0,
        "hydro_capacity_t_bm_y": 5000.0,
    }
    ctx = {"feed_mass_kg_per_year": 1_000_000.0, "hours_per_year": 8400.0}
    infra = compute_infrastructure(
        scen,
        ctx,
        route="mech",
        feed_mass_kg_per_year=1_000_000.0,
        transported_mass_kg_per_year=200_000.0,
    )
    assert infra["transported_mass_t_per_year"] == 200.0
    assert infra["distance_km"] > 0.0
    assert infra["transport_cost_per_kg_feed"] > 0.0
    assert infra["transport_gwp_kgco2e_per_kg_feed"] > 0.0
