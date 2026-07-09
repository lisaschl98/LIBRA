"""HTML/CSS based Executive Summary PDF export."""
from __future__ import annotations

import base64
import asyncio
from dataclasses import asdict, is_dataclass
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"
ASSETS_DIR = ROOT_DIR.parent / "assets"
TEMPLATE_NAME = "executive_summary.html"
CSS_NAME = "report.css"
SCENARIO_ICON_PATH = ASSETS_DIR / "pdf_scenario_icon.png"
GENERATED_ICON_PATH = ASSETS_DIR / "pdf_generated_icon.png"
FOOTER_ICON_PATH = ASSETS_DIR / "about_libra_battery.png"
PRODUCT_ICON_PATH = ASSETS_DIR / "pdf_recycling_products_icon.png"
LIBRA_VERSION = "1.0"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        raw = str(value).replace(",", "").strip()
        parsed = float(raw)
        if parsed != parsed or parsed in (float("inf"), float("-inf")):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


def _data_uri(data: bytes | None, mime_type: str = "image/png") -> str:
    if not data:
        return ""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _file_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return _data_uri(path.read_bytes(), mime_type)


def _payload_value(payload: Any, name: str, default: Any = "") -> Any:
    if isinstance(payload, dict):
        return payload.get(name, default)
    return getattr(payload, name, default)


def _payload_dict(payload: Any) -> dict[str, Any]:
    if is_dataclass(payload):
        return asdict(payload)
    if isinstance(payload, dict):
        return dict(payload)
    return dict(getattr(payload, "__dict__", {}))


def _display_region(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    lookup = {
        "de": "Germany",
        "germany": "Germany",
        "us": "United States",
        "usa": "United States",
        "united states": "United States",
        "cn": "China",
        "china": "China",
        "eu": "Europe",
        "europe": "Europe",
    }
    return lookup.get(raw.lower(), raw)


def _normalise_recovery_summary(payload: Any) -> list[dict[str, str]]:
    raw_items = list(_payload_value(payload, "recovery_summary", []) or [])
    items: list[dict[str, str]] = []
    for item in raw_items[:3]:
        if isinstance(item, dict):
            label = str(item.get("label", "Recovery"))
            value = str(item.get("value", "n/a"))
        else:
            try:
                label, value = item
            except (TypeError, ValueError):
                label, value = "Recovery", item
            label = str(label)
            value = str(value)
        if value not in {"n/a", "-"} and "%" not in value:
            value = f"{value}%"
        items.append({"label": label, "value": value})
    fallback = [
        {"label": "Overall metal recovery", "value": "n/a"},
        {"label": "Active material recovery", "value": "n/a"},
        {"label": "Component recovery", "value": "n/a"},
    ]
    return (items + fallback)[:3]


def _normalise_map_markers(payload: Any) -> list[dict[str, str]]:
    raw_items = list(_payload_value(payload, "map_markers", []) or [])
    markers: list[dict[str, str]] = []
    for item in raw_items[:2]:
        if not isinstance(item, dict):
            continue
        x = str(item.get("x", "")).strip()
        y = str(item.get("y", "")).strip()
        if not x or not y:
            continue
        svg_x = x[:-1] if x.endswith("%") else x
        svg_y = y[:-1] if y.endswith("%") else y
        markers.append(
            {
                "x": x,
                "y": y,
                "svg_x": svg_x,
                "svg_y": svg_y,
                "lat": str(item.get("lat", "")).strip(),
                "lon": str(item.get("lon", "")).strip(),
                "label": str(item.get("label", "Site")),
                "role": str(item.get("role", "site")),
            }
        )
    if markers:
        return markers
    region = str(_payload_value(payload, "region", "")).strip().lower()
    fallback = {
        "de": ("54%", "28%"),
        "germany": ("54%", "28%"),
        "eu": ("55%", "28%"),
        "europe": ("55%", "28%"),
        "cn": ("78%", "38%"),
        "china": ("78%", "38%"),
        "us": ("25%", "38%"),
        "usa": ("25%", "38%"),
        "united states": ("25%", "38%"),
    }
    x, y = fallback.get(region, ("54%", "28%"))
    return [{"x": x, "y": y, "svg_x": x[:-1], "svg_y": y[:-1], "lat": "", "lon": "", "label": "Site", "role": "site"}]


def _map_route(markers: list[dict[str, str]]) -> dict[str, str] | None:
    if len(markers) < 2:
        return None
    return {
        "x1": markers[0]["svg_x"],
        "y1": markers[0]["svg_y"],
        "x2": markers[1]["svg_x"],
        "y2": markers[1]["svg_y"],
    }


def _marker_lat_lon(marker: dict[str, str]) -> tuple[float, float]:
    lat_raw = str(marker.get("lat", "")).strip()
    lon_raw = str(marker.get("lon", "")).strip()
    if lat_raw and lon_raw:
        return _as_float(lat_raw), _as_float(lon_raw)
    x = _as_float(marker.get("svg_x"), 50.0)
    y = _as_float(marker.get("svg_y"), 50.0)
    lon = x / 100.0 * 360.0 - 180.0
    lat = 90.0 - y / 100.0 * 180.0
    return lat, lon


def _cartopy_world_map_data_uri(markers: list[dict[str, str]]) -> str:
    if not markers:
        return ""
    try:
        import io

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
    except Exception:
        return ""

    try:
        coords = [_marker_lat_lon(marker) for marker in markers]
        fig = plt.figure(figsize=(5.2, 1.55), dpi=180)
        ax = plt.axes(projection=ccrs.PlateCarree())
        ax.set_facecolor("#F5F8FB")
        if len(coords) > 1:
            lats = [lat for lat, _lon in coords]
            lons = [lon for _lat, lon in coords]
            lon_span = max(lons) - min(lons)
            lat_span = max(lats) - min(lats)
            if lon_span > 155.0:
                ax.set_extent([-180.0, 180.0, -58.0, 78.0], crs=ccrs.PlateCarree())
            else:
                lon_pad = max(7.0, lon_span * 0.08)
                lat_pad = max(6.0, lat_span * 0.45)
                ax.set_extent(
                    [
                        max(-180.0, min(lons) - lon_pad),
                        min(180.0, max(lons) + lon_pad),
                        max(-60.0, min(lats) - lat_pad),
                        min(82.0, max(lats) + lat_pad),
                    ],
                    crs=ccrs.PlateCarree(),
                )
        else:
            lat, lon = coords[0]
            ax.set_extent(
                [
                    max(-180.0, lon - 10.0),
                    min(180.0, lon + 10.0),
                    max(-60.0, lat - 7.0),
                    min(82.0, lat + 7.0),
                ],
                crs=ccrs.PlateCarree(),
            )
        ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#DFE7EF", edgecolor="#5F6C7B", linewidth=0.32)
        ax.add_feature(cfeature.BORDERS.with_scale("50m"), edgecolor="#9AA7B7", linewidth=0.24)
        ax.add_feature(cfeature.COASTLINE.with_scale("50m"), edgecolor="#5F6C7B", linewidth=0.30)
        if len(coords) > 1:
            ax.plot(
                [coords[0][1], coords[1][1]],
                [coords[0][0], coords[1][0]],
                color="#7A8FA6",
                linewidth=1.0,
                linestyle=(0, (3, 2)),
                transform=ccrs.Geodetic(),
                zorder=6,
            )
        for marker, (lat, lon) in zip(markers, coords):
            color = "#C9A004" if marker.get("role") == "spoke" else "#003B75"
            ax.scatter(
                [lon],
                [lat],
                s=32,
                color=color,
                edgecolor="white",
                linewidth=1.0,
                transform=ccrs.PlateCarree(),
                zorder=7,
            )
        ax.set_axis_off()
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=180, facecolor="#F5F8FB", pad_inches=0)
        plt.close(fig)
        return _data_uri(buf.getvalue(), "image/png")
    except Exception:
        try:
            plt.close("all")
        except Exception:
            pass
        return ""


def _process_flow_data_uri(payload: Any) -> str:
    model = _payload_value(payload, "process_flow_model", None)
    if not model:
        return ""
    try:
        from .overview_pdf import _process_flow_png

        png = _process_flow_png(model, width_px=1800, height_px=520)
    except Exception:
        return ""
    return _data_uri(png, "image/png")


def _infrastructure_map_data_uri(payload: Any) -> str:
    image_bytes = _payload_value(payload, "infrastructure_map_png", None)
    if isinstance(image_bytes, (bytes, bytearray)):
        return _data_uri(bytes(image_bytes), "image/png")
    return ""


def _short_label(value: Any, max_chars: int = 16) -> str:
    text = str(value or "").strip()
    return text if len(text) <= max_chars else f"{text[: max_chars - 1]}."


def _fig_data_uri(fig: Any) -> str:
    import io

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=190, facecolor="white", bbox_inches=None, pad_inches=0)
    return _data_uri(buf.getvalue(), "image/png")


def _set_balance_ylim(ax: Any, values: list[float], *, zero_fraction: float = 0.55) -> float:
    """Set y-limits so the zero line sits at a consistent relative height."""
    max_positive = max([0.0, *[float(value) for value in values if float(value) > 0.0]])
    max_negative = max([0.0, *[abs(float(value)) for value in values if float(value) < 0.0]])
    if max_positive <= 1e-12 and max_negative <= 1e-12:
        ax.set_ylim(-1.0, 1.0)
        return 1.0

    zero_fraction = min(0.80, max(0.20, zero_fraction))
    lower = max_negative / zero_fraction if max_negative > 0 else max_positive * 0.45
    upper = max_positive / (1.0 - zero_fraction) if max_positive > 0 else max_negative * 0.45
    span = max(lower, upper, 1.0)
    ax.set_ylim(-span * zero_fraction, span * (1.0 - zero_fraction))
    return max(max_positive, max_negative, 1.0)


def _common_balance_ylim(econ_values: list[float], env_values: list[float], *, zero_fraction: float = 0.55) -> tuple[float, float]:
    all_values = [float(value) for value in [*econ_values, *env_values]]
    max_positive = max([0.0, *[value for value in all_values if value > 0.0]])
    max_negative = max([0.0, *[abs(value) for value in all_values if value < 0.0]])
    if max_positive <= 1e-12 and max_negative <= 1e-12:
        return -1.0, 1.0

    zero_fraction = min(0.80, max(0.20, zero_fraction))
    lower_span = max_negative / zero_fraction if max_negative > 0.0 else max_positive * 0.45
    upper_span = max_positive / (1.0 - zero_fraction) if max_positive > 0.0 else max_negative * 0.45
    span = max(lower_span, upper_span, 1.0)
    return -span * zero_fraction, span * (1.0 - zero_fraction)


def _page2_rows(rows: Any, *, limit: int = 5, abs_values: bool = False) -> list[dict[str, float | str]]:
    clean: list[dict[str, float | str]] = []
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        value = _as_float(row.get("value"), 0.0)
        if abs_values:
            value = abs(value)
        if abs(value) <= 1e-12:
            continue
        clean.append({"label": str(row.get("label", "") or "-"), "value": value})
    clean.sort(key=lambda item: abs(float(item["value"])), reverse=True)
    return clean[:limit]


def _economic_balance_chart_parts(payload: Any) -> tuple[list[str], list[float], list[str]]:
    rows = list((_payload_value(payload, "economic_breakdown", {}) or {}).get("waterfall") or [])
    if not rows:
        return [], [], []

    def _display_row(row: dict[str, Any]) -> dict[str, Any]:
        label = str(row.get("label", "") or "")
        if label.strip().lower() == "revenue":
            label = "Product revenue"
        return {**row, "label": label}

    display_rows = [_display_row(row) for row in rows if isinstance(row, dict)]

    labels = [str(row.get("label", "") or "") for row in display_rows]
    values = [_as_float(row.get("value"), 0.0) for row in display_rows]
    colors = []
    for label, value in zip(labels, values):
        low = label.lower()
        if "product revenue" in low or low == "revenue":
            colors.append("#003B75")
        elif "profit" in low:
            colors.append("#1A7F37" if value >= 0 else "#C62828")
        elif low == "trc":
            colors.append("#4B5563")
        else:
            colors.append("#6B7280")
    return labels, values, colors


def _economic_balance_chart_data_uri(payload: Any, y_limits: tuple[float, float] | None = None) -> str:
    labels, values, colors = _economic_balance_chart_parts(payload)
    if not labels or not any(abs(v) > 1e-12 for v in values):
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FormatStrFormatter, MaxNLocator
    except Exception:
        return ""

    fig, ax = plt.subplots(figsize=(4.2, 2.05))
    x_pos = list(range(len(values)))
    ax.bar(x_pos, values, color=colors, width=0.58)
    ax.axhline(0, color="#9AA7B7", linewidth=0.7, linestyle=(0, (2, 2)))
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels, rotation=28, ha="right", fontsize=5.6)
    ax.tick_params(axis="y", labelsize=5.6, length=0, colors="#5F6C7B")
    ax.tick_params(axis="x", length=0, colors="#003B75")
    ax.grid(False)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.0f"))
    if y_limits:
        ax.set_ylim(*y_limits)
        span = max(abs(limit) for limit in y_limits) or 1.0
    else:
        span = _set_balance_ylim(ax, values)
    for idx, value in enumerate(values):
        ax.text(
            idx,
            value + (span * 0.035 if value >= 0 else -span * 0.035),
            f"{value:.2f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=5.4,
            color="#1F2A37",
        )
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.94, bottom=0.36)
    try:
        return _fig_data_uri(fig)
    finally:
        plt.close(fig)


def _normalise_product_output_rows(payload: Any) -> dict[str, Any]:
    data = _payload_value(payload, "product_outputs", {}) or {}
    raw_rows = list(data.get("rows") or [])
    raw_groups = list(data.get("groups") or [])
    rows: list[dict[str, str]] = []
    for row in raw_rows[:7]:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "product": str(row.get("product", "-") or "-"),
                "flow": str(row.get("flow_display", "") or f"{_as_float(row.get('flow_t_y'), 0.0):,.0f}"),
                "revenue": str(row.get("revenue_display", "") or f"{_as_float(row.get('revenue_per_y'), 0.0):,.0f}"),
            }
        )
    total = _as_float(data.get("total_flow_t_y"), 0.0)
    total_revenue = _as_float(data.get("total_revenue_per_y"), 0.0)
    default_groups = [
        {"key": "Front-End", "title": "Front-End Processing", "rows": []},
        {"key": "Mechanical", "title": "Mechanical/Pyro Treatment", "rows": []},
        {"key": "Hydro", "title": "Hydrometallurgy", "rows": []},
    ]
    groups: list[dict[str, Any]] = []
    source_groups = raw_groups if raw_groups else default_groups
    for group in source_groups[:3]:
        if not isinstance(group, dict):
            continue
        group_rows: list[dict[str, str]] = []
        for row in list(group.get("rows") or []):
            if not isinstance(row, dict):
                continue
            group_rows.append(
                {
                    "product": str(row.get("product", "-") or "-"),
                    "flow": str(row.get("flow_display", "") or f"{_as_float(row.get('flow_t_y'), 0.0):,.0f}"),
                    "output": str(row.get("output_display", "") or f"{_as_float(row.get('output_kg_per_kg'), 0.0):.3f}"),
                    "revenue": str(row.get("revenue_display", "") or f"{_as_float(row.get('revenue_kg'), 0.0):.2f}"),
                }
            )
        groups.append(
            {
                "key": str(group.get("key", "") or ""),
                "title": str(group.get("title", "Products") or "Products"),
                "rows": group_rows,
            }
        )
    return {
        "rows": rows,
        "groups": groups,
        "total": f"{total:,.0f}" if total else "-",
        "total_revenue": f"{total_revenue:,.0f}" if total_revenue else "-",
    }


def _page2_economic_insight(payload: Any) -> str:
    econ = _payload_value(payload, "economic_breakdown", {}) or {}
    rows = list(econ.get("waterfall") or [])
    cost_rows: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label", "") or "").strip()
        label_lower = label.lower()
        if not label or label_lower == "trc" or "revenue" in label_lower or "profit" in label_lower:
            continue
        value = abs(_as_float(row.get("value"), 0.0))
        if value > 1e-12:
            cost_rows.append((label, value))

    trc = _as_float(econ.get("total_costs"), _as_float(_payload_value(payload, "trc_display", 0.0)))
    revenue = _as_float(econ.get("revenue"), _as_float(_payload_value(payload, "revenue_display", 0.0)))
    profit = _as_float(econ.get("profit"), _as_float(_payload_value(payload, "profit_display", 0.0)))
    if not cost_rows or trc <= 0:
        return str(_payload_value(payload, "economic_insight", "Economic performance is driven by the main recycling cost categories."))

    driver_label, driver_value = max(cost_rows, key=lambda item: item[1])
    share = 100.0 * driver_value / trc
    first = (
        f"Economics are driven by {driver_label}, "
        f"which account for {share:.0f}% of total recycling costs."
    )
    if trc > revenue:
        second = (
            "Because TRC exceed product revenue, the scenario results in a "
            f"negative profit of {profit:.2f} $/kg feed processed."
        )
    else:
        second = (
            "Because product revenue exceeds TRC, the scenario results in a "
            f"positive profit of {profit:.2f} $/kg feed processed."
        )
    return f"{first} {second}"


def _normalise_gwp_burden_rows(rows: Any) -> list[dict[str, float | str]]:
    grouped = {"Materials": 0.0, "Energy": 0.0, "Residual treatment": 0.0}
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        label = str(row.get("label", "") or "").strip()
        value = abs(_as_float(row.get("value"), 0.0))
        if value <= 1e-12:
            continue
        label_lower = label.lower()
        if any(token in label_lower for token in ("electric", "heat", "thermal", "energy", "power", "steam", "gas")):
            grouped["Energy"] += value
        elif any(token in label_lower for token in ("residual", "waste", "treatment", "disposal")):
            grouped["Residual treatment"] += value
        else:
            grouped["Materials"] += value
    return [{"label": label, "value": value} for label, value in grouped.items()]


def _page2_gwp_insight(payload: Any, burden_rows: list[dict[str, float | str]], credit_rows: Any) -> str:
    burden_clean = _page2_rows(burden_rows, limit=3, abs_values=True)
    credit_clean = _page2_rows(credit_rows, limit=999, abs_values=True)
    if not burden_clean and not credit_clean:
        return str(_payload_value(payload, "gwp_insight", "GWP contributions are determined by burdens and product credits."))

    burden_label = str(burden_clean[0]["label"]) if burden_clean else "available burdens"
    credit_label = str(credit_clean[0]["label"]) if credit_clean else "available credits"
    burden_total = _as_float(_payload_value(payload, "gwp_burden_display", 0.0), sum(float(row["value"]) for row in burden_clean))
    credit_total = _as_float(_payload_value(payload, "gwp_credit_display", 0.0), sum(float(row["value"]) for row in credit_clean))
    net_gwp = _as_float(_payload_value(payload, "cf_display", 0.0), burden_total - credit_total)
    if credit_total > burden_total:
        overall = (
            "Overall, credits exceed burdens, resulting in a "
            f"net GWP benefit of {abs(net_gwp):.2f} kg CO₂-eq/kg feed processed."
        )
    elif burden_total > credit_total:
        overall = (
            "Overall, burdens exceed credits, resulting in a "
            f"net GWP burden of {net_gwp:.2f} kg CO₂-eq/kg feed processed."
        )
    else:
        overall = "Overall, burdens and credits are balanced."
    return (
        f"The GWP burden is mainly driven by {burden_label}, "
        f"while credits are dominated by {credit_label}. {overall}"
    )


def _environmental_balance_chart_parts(
    payload: Any,
    burden_rows: list[dict[str, float | str]],
    credit_rows: Any,
) -> tuple[list[str], list[float], list[str], list[str]]:
    burden_clean = [
        {"label": str(row.get("label", "") or "-"), "value": abs(_as_float(row.get("value"), 0.0))}
        for row in list(burden_rows or [])
        if isinstance(row, dict)
    ]
    credit_clean = _page2_rows(credit_rows, limit=999, abs_values=True)
    if not burden_clean and not credit_clean:
        return [], [], [], []

    burden_component_total = sum(float(row["value"]) for row in burden_clean)
    burden_total = _as_float(_payload_value(payload, "gwp_burden_display", 0.0), burden_component_total)
    labels = [str(row["label"]) for row in burden_clean]
    values = [float(row["value"]) for row in burden_clean]
    colors = ["#C62828"] * len(values)
    hatches = [""] * len(values)

    if burden_total > 1e-12:
        labels.append("GWP burden")
        values.append(burden_total)
        colors.append("#9F1F1F")
        hatches.append("")

    credit_component_total = sum(float(row["value"]) for row in _page2_rows(credit_rows, limit=999, abs_values=True))
    credit_total = _as_float(_payload_value(payload, "gwp_credit_display", 0.0), credit_component_total)
    for row in credit_clean:
        labels.append(str(row["label"]))
        values.append(-float(row["value"]))
        colors.append("#1A7F37")
        hatches.append("")

    if credit_total > 1e-12:
        labels.append("GWP credits")
        values.append(-credit_total)
        colors.append("#0F6B2B")
        hatches.append("")

    net_gwp = _as_float(_payload_value(payload, "cf_display", 0.0), burden_total - credit_total)
    labels.append("Net GWP")
    values.append(net_gwp)
    colors.append("#1A7F37" if net_gwp <= 0 else "#C62828")
    hatches.append("////")
    return labels, values, colors, hatches


def _environmental_balance_chart_data_uri(
    payload: Any,
    burden_rows: list[dict[str, float | str]],
    credit_rows: Any,
    y_limits: tuple[float, float] | None = None,
) -> str:
    labels, values, colors, hatches = _environmental_balance_chart_parts(payload, burden_rows, credit_rows)
    if not any(abs(value) > 1e-12 for value in values):
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FormatStrFormatter, MaxNLocator
    except Exception:
        return ""

    fig, ax = plt.subplots(figsize=(4.2, 2.05))
    x_pos = list(range(len(values)))
    bars = ax.bar(x_pos, values, color=colors, width=0.56, edgecolor=colors, linewidth=0.4)
    for bar, hatch in zip(bars, hatches):
        if hatch:
            bar.set_hatch(hatch)
            bar.set_edgecolor("#003B75")
    ax.axhline(0, color="#9AA7B7", linewidth=0.7, linestyle=(0, (2, 2)))
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels, rotation=28, ha="right", fontsize=5.6)
    ax.tick_params(axis="y", labelsize=5.6, length=0, colors="#5F6C7B")
    ax.tick_params(axis="x", length=0, colors="#003B75")
    ax.grid(False)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.0f"))
    if y_limits:
        ax.set_ylim(*y_limits)
        span = max(abs(limit) for limit in y_limits) or 1.0
    else:
        span = _set_balance_ylim(ax, values)
    for idx, value in enumerate(values):
        ax.text(
            idx,
            value + (span * 0.035 if value >= 0 else -span * 0.035),
            f"{abs(value):.2f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=5.4,
            color="#1F2A37",
        )
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.94, bottom=0.36)
    try:
        return _fig_data_uri(fig)
    finally:
        plt.close(fig)


def _page2_context(payload: Any) -> dict[str, Any]:
    burden_rows = _normalise_gwp_burden_rows(_payload_value(payload, "gwp_burden_data", []))
    credit_rows = _payload_value(payload, "gwp_credit_data", [])
    _econ_labels, econ_values, _econ_colors = _economic_balance_chart_parts(payload)
    _env_labels, env_values, _env_colors, _env_hatches = _environmental_balance_chart_parts(payload, burden_rows, credit_rows)
    balance_y_limits = _common_balance_ylim(econ_values, env_values)
    return {
        "economic_balance_chart_data_uri": _economic_balance_chart_data_uri(payload, balance_y_limits),
        "environmental_balance_chart_data_uri": _environmental_balance_chart_data_uri(payload, burden_rows, credit_rows, balance_y_limits),
        "product_output_table": _normalise_product_output_rows(payload),
        "economic_insight": _page2_economic_insight(payload),
        "gwp_insight": _page2_gwp_insight(payload, burden_rows, credit_rows),
    }


def build_executive_summary_html(payload: Any) -> str:
    """Render the one-page executive summary HTML from the PDF payload."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    css = (STATIC_DIR / CSS_NAME).read_text(encoding="utf-8")
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(TEMPLATE_NAME)

    context = _payload_dict(payload)
    profit = _as_float(_payload_value(payload, "profit_display", 0.0))
    net_gwp = _as_float(_payload_value(payload, "cf_display", 0.0))
    logo_path = ASSETS_DIR / "businesschemistry_logo.png"
    map_markers = _normalise_map_markers(payload)
    context.update(
        {
            "css": css,
            "version": LIBRA_VERSION,
            "region": _display_region(_payload_value(payload, "region", "")),
            "logo_data_uri": _file_data_uri(logo_path),
            "scenario_icon_data_uri": _file_data_uri(SCENARIO_ICON_PATH),
            "generated_icon_data_uri": _file_data_uri(GENERATED_ICON_PATH),
            "footer_icon_data_uri": _file_data_uri(FOOTER_ICON_PATH),
            "product_icon_data_uri": _file_data_uri(PRODUCT_ICON_PATH),
            "process_flow_data_uri": _process_flow_data_uri(payload),
            "infrastructure_map_data_uri": _infrastructure_map_data_uri(payload) or _cartopy_world_map_data_uri(map_markers),
            "recovery_summary": _normalise_recovery_summary(payload),
            "map_markers": map_markers,
            "map_route": _map_route(map_markers),
            "profit_class": "negative" if profit < 0 else "positive",
            "gwp_class": "positive" if net_gwp < 0 else "negative",
            "profit_status": _payload_value(payload, "profit_status", "Economic deficit"),
            "env_status": _payload_value(payload, "env_status", "Environmentally beneficial"),
            **_page2_context(payload),
        }
    )
    return template.render(**context)


def _playwright_browser_missing(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "executable doesn't exist" in message or "playwright install" in message


def _install_playwright_chromium() -> None:
    """Install the Playwright Chromium browser on hosts such as Streamlit Cloud."""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
            timeout=240,
        )
    except subprocess.CalledProcessError as exc:
        details = "\n".join(part for part in (exc.stdout, exc.stderr) if part)
        raise RuntimeError(f"Playwright Chromium installation failed.\n{details}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Playwright Chromium installation timed out.") from exc
    if completed.stderr:
        # Keep successful installs quiet in the app, but retain a hook for debuggers.
        os.environ.setdefault("LIBRA_PLAYWRIGHT_INSTALL_LOG", completed.stderr[-1000:])


def export_executive_summary_pdf_html(payload: Any, output_path: str | Path | None) -> bytes:
    """Render HTML with Jinja2 and export A4 PDF via Playwright/Chromium."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    html = build_executive_summary_html(payload)
    out_path = Path(output_path) if output_path else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if os.environ.get("LIBRA_PDF_DEBUG_HTML"):
            out_path.with_suffix(".html").write_text(html, encoding="utf-8")

    if sys.platform.startswith("win") and hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(args=["--no-sandbox"])
        except PlaywrightError as exc:
            if not _playwright_browser_missing(exc):
                raise
            _install_playwright_chromium()
            browser = playwright.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=1)
            page.set_content(html, wait_until="networkidle")
            pdf_bytes = page.pdf(
                path=str(out_path) if out_path else None,
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            browser.close()
    return pdf_bytes
