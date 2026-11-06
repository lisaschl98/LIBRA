from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import General_Parameters as gp
from path import COST_REGION_XLSX, PRICE_INDEX_DIR


def _independent_factor(series_id: str, year: int) -> float:
    path = Path(PRICE_INDEX_DIR) / f"{series_id}.xlsx"
    xl = pd.ExcelFile(path)
    sheet = next(s for s in xl.sheet_names if str(s).strip().casefold() != "readme")
    df = pd.read_excel(path, sheet_name=sheet)
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    df = df.set_index("observation_date")[series_id].sort_index()
    base = float(df[df.index.year == year].mean())
    target = float(df.loc[pd.Timestamp(gp.OPEX_PRICE_TARGET_DATE)])
    return target / base


def _raw_cost(item: str, region: str) -> float:
    df = pd.read_excel(COST_REGION_XLSX, sheet_name="Cost Parameter")
    df.columns = df.columns.astype(str).str.strip()
    row = df.loc[df["item"].astype(str).str.strip() == item].iloc[0]
    return float(row[region])


def test_indexed_prices_use_annual_average_against_target_date() -> None:
    cases = [
        ("Limestone", "WPU03T15M05", 2023),
        ("Water", "WPU03T15M05", 2022),
        ("CH-90 Na resin", "WPU06", 2016),
        ("Cyanex 272", "WPU06", 2022),
        ("Labor", "CIU2013000000000I", 2025),
        ("Building costs", "PCU236211236211", 2024),
    ]
    prices = gp.get_region_opex("DE")
    meta = gp.get_region_opex_meta()
    for item, series_id, year in cases:
        factor = _independent_factor(series_id, year)
        assert prices[item] == pytest.approx(_raw_cost(item, "DE") * factor)
        assert meta[item]["index_factor"] == pytest.approx(factor)
        assert meta[item]["price_index"] == series_id
        assert meta[item]["reference_year"] == year
        assert meta[item]["reference_basis"] == "annual average"
        assert meta[item]["target_date"] == gp.OPEX_PRICE_TARGET_DATE


def test_same_factor_for_every_region_and_plain_prices_stay_raw() -> None:
    de = gp.get_region_opex("DE")
    us = gp.get_region_opex("US")
    assert de["Limestone"] / _raw_cost("Limestone", "DE") == pytest.approx(
        us["Limestone"] / _raw_cost("Limestone", "US")
    )
    assert de["Electricity"] == pytest.approx(_raw_cost("Electricity", "DE"))
    assert de["capex_factor"] == pytest.approx(_raw_cost("capex_factor", "DE"))
    assert de["building_factor"] == pytest.approx(_raw_cost("building_factor", "DE"))

    ctx = gp.apply_region({}, "DE")
    assert ctx["building_cost_m2_base"] == pytest.approx(ctx["prices"]["Building costs"])
    assert ctx["prices"]["Building costs"] == pytest.approx(
        _raw_cost("Building costs", "DE") * ctx["price_meta"]["Building costs"]["index_factor"]
    )
    assert ctx["capex_factor"] == pytest.approx(_raw_cost("capex_factor", "DE"))
    assert ctx["price_meta"]["Electricity"]["index_factor"] == 1.0
    assert "index_factor" not in ctx["gwp_meta"]["Electricity"]


def test_skip_markers_do_not_index() -> None:
    info = gp.opex_index_info(
        pd.Series(
            {
                "item": "Electricity",
                "Price index": "not escalated (2026 price)",
                "Reference period": 2026,
            }
        )
    )
    assert info["index_factor"] == 1.0
    assert info["reference_basis"] == ""


def test_unknown_series_id_raises() -> None:
    with pytest.raises(FileNotFoundError, match="DOES_NOT_EXIST"):
        gp.opex_index_info(
            pd.Series(
                {
                    "item": "Widget",
                    "Price index": "DOES_NOT_EXIST",
                    "Reference period": 2020,
                }
            )
        )


def test_incomplete_reference_year_raises(tmp_path: Path) -> None:
    dates = pd.date_range("2020-01-01", periods=11, freq="MS")
    dates = dates.append(pd.DatetimeIndex(["2026-04-01"]))
    frame = pd.DataFrame({"observation_date": dates, "TESTINDEX": range(1, 13)})
    path = tmp_path / "TESTINDEX.xlsx"
    frame.to_excel(path, sheet_name="Monthly", index=False)
    series, periods = gp.load_price_index_series(str(path), "TESTINDEX")
    with pytest.raises(ValueError, match="reference year 2020"):
        gp.annual_average_index_factor(
            series,
            2020,
            periods_per_year=periods,
            series_id="TESTINDEX",
        )


def test_missing_target_date_raises(tmp_path: Path) -> None:
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    frame = pd.DataFrame({"observation_date": dates, "TESTINDEX": range(1, 13)})
    path = tmp_path / "TESTINDEX_NOTARGET.xlsx"
    frame.to_excel(path, sheet_name="Monthly", index=False)
    series, periods = gp.load_price_index_series(str(path), "TESTINDEX")
    with pytest.raises(KeyError, match="2026-04-01"):
        gp.annual_average_index_factor(
            series,
            2020,
            periods_per_year=periods,
            series_id="TESTINDEX",
        )
