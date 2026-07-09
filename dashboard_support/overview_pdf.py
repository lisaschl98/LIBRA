"""HTML/CSS based Executive Summary PDF entry points."""
from __future__ import annotations

from dataclasses import dataclass, field
import html as html_module
import io
from typing import Any

BRAND_BLUE = "#003B75"
OVERVIEW_LABEL_GRAY = "#5F6C7B"
LIBRA_VERSION = "1.0"

LAST_PDF_EXPORTER = ""
LAST_PDF_EXPORT_ERROR = ""


@dataclass
class OverviewPdfPayload:
    scenario_name: str
    generated_at: str
    region: str
    route_label: str
    refining_route: str
    feed_t_y: str
    op_hours_y: str
    unit_per_kg: str
    profit_display: str
    profit_color: str
    trc_display: str
    revenue_display: str
    profit_status: str
    profit_status_color: str
    cf_display: str
    cf_color: str
    gwp_burden_display: str
    gwp_credit_display: str
    env_status: str
    env_status_color: str
    product_sections: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)
    revenue_sunburst_png: bytes | None = None
    revenue_hierarchy: dict[str, Any] | None = None
    revenue_center_kg: float = 0.0
    recovery_summary: list[tuple[str, str]] = field(default_factory=list)
    recovery_detail: list[tuple[str, list[tuple[str, float | None]]]] = field(default_factory=list)
    process_flow_model: dict[str, Any] | None = None
    economic_breakdown: dict[str, Any] = field(default_factory=dict)
    cost_driver_data: list[dict[str, Any]] = field(default_factory=list)
    gwp_burden_data: list[dict[str, Any]] = field(default_factory=list)
    gwp_credit_data: list[dict[str, Any]] = field(default_factory=list)
    product_outputs: dict[str, Any] = field(default_factory=dict)
    site_layout: dict[str, Any] = field(default_factory=dict)
    economic_insight: str = ""
    gwp_insight: str = ""
    output_note: str = ""
    site_layout_note: str = ""
    feedstock_display: str = "-"
    plant_concept: str = "-"
    map_markers: list[dict[str, Any]] = field(default_factory=list)
    infrastructure_map_png: bytes | None = None


def pdf_export_available() -> bool:
    """True when the HTML/Playwright PDF backend is importable."""
    try:
        import jinja2  # noqa: F401
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _clean_pdf_label(text: Any) -> str:
    raw = html_module.unescape(str(text or ""))
    for token in ("<br>", "<br/>", "<br />"):
        raw = raw.replace(token, "\n")
    for token in ("<b>", "</b>", "<span>", "</span>"):
        raw = raw.replace(token, "")
    return " ".join(part.strip() for part in raw.replace("\n", " | ").split("|") if part.strip())


def _wrap_label(text: Any, *, width: int = 18, max_lines: int = 3) -> str:
    import textwrap

    cleaned = _clean_pdf_label(text)
    lines: list[str] = []
    for chunk in cleaned.split(" | "):
        lines.extend(textwrap.wrap(chunk, width=width) or [chunk])
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [lines[max_lines - 1][: max(4, width - 1)].rstrip() + "..."]
    return "\n".join(lines)


def _pdf_t_y_label(kg_h: float, hours_y: float) -> str:
    t_y = float(kg_h or 0.0) * float(hours_y or 0.0) / 1000.0
    return f"({t_y:,.0f} t/y)"


def _split_stream_label(title: Any, label: Any) -> tuple[str, str]:
    import re

    name = _clean_pdf_label(title)
    raw_label = _clean_pdf_label(label)
    match = re.search(r"\(([^)]*t/y[^)]*)\)", str(label or ""))
    amount = f"({match.group(1)})" if match else ""
    if not name and raw_label:
        name = re.sub(r"\s*\([^)]*t/y[^)]*\)", "", raw_label).strip()
    return name or "Stream", amount


def _process_flow_png(model: dict[str, Any] | None, *, width_px: int = 1500, height_px: int = 420) -> bytes | None:
    """Render the process flow model as a PNG for the HTML template."""
    if not model or not model.get("nodes"):
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch
    except ImportError:
        return None

    nodes = list(model.get("nodes") or [])
    side_by_node = dict(model.get("side_streams_by_node") or {})
    hours_y = float(model.get("hours_y") or 0.0)
    n = max(1, len(nodes))

    fig_w = width_px / 180.0
    fig_h = height_px / 180.0
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=180)
    ax.set_axis_off()
    ax.set_xlim(-0.04, 1.04)
    ax.set_ylim(0, 1)

    x_min, x_max = 0.035, 0.965
    xs = [0.5] if n == 1 else [x_min + i * (x_max - x_min) / (n - 1) for i in range(n)]
    y_main = 0.55
    node_w = min(0.155, max(0.092, 0.82 / max(1, n)))
    node_h = 0.23
    stream_node_w = node_w * 0.78
    stream_node_h = node_h * 0.58
    arrow_color = "#35566f"
    reagent_color = "#1a7f37"

    def _node_dims(node: dict[str, Any]) -> tuple[float, float]:
        if str(node.get("kind", "")) == "process":
            return node_w, node_h
        return stream_node_w, stream_node_h

    for i in range(n - 1):
        src_w, _src_h = _node_dims(nodes[i])
        tgt_w, _tgt_h = _node_dims(nodes[i + 1])
        x0 = xs[i] + src_w / 2 + 0.006
        x1 = xs[i + 1] - tgt_w / 2 - 0.006
        if x1 <= x0:
            continue
        ax.add_patch(
            FancyArrowPatch(
                (x0, y_main),
                (x1, y_main),
                arrowstyle="-|>",
                mutation_scale=11,
                linewidth=1.7,
                color=arrow_color,
                shrinkA=0,
                shrinkB=0,
            )
        )

    for i, node in enumerate(nodes):
        x = xs[i]
        kind = str(node.get("kind", ""))
        color = str(node.get("color") or ("#003B75" if kind == "process" else "#f7fbff"))
        border = str(node.get("border") or "#b8c6d6")
        text_color = "white" if kind == "process" else BRAND_BLUE
        this_w = node_w if kind == "process" else stream_node_w
        this_h = node_h if kind == "process" else stream_node_h
        rounding = 0.012 if kind == "process" else stream_node_h / 2.0
        if kind == "process":
            box = FancyBboxPatch(
                (x - this_w / 2, y_main - this_h / 2),
                this_w,
                this_h,
                boxstyle=f"round,pad=0.008,rounding_size={rounding}",
                linewidth=0.8,
                edgecolor=border,
                facecolor=color,
            )
        else:
            box = Ellipse((x, y_main), width=this_w, height=this_h, linewidth=0.8, edgecolor=border, facecolor=color)
        ax.add_patch(box)
        ax.text(
            x,
            y_main,
            _wrap_label(node.get("display_label", ""), width=16 if kind == "process" else 13, max_lines=3),
            ha="center",
            va="center",
            fontsize=6.4,
            color=text_color,
            fontweight="bold" if kind == "process" else "normal",
            linespacing=1.15,
        )

        reagent = float(node.get("reagents_kg_h") or 0.0)
        if reagent > 1e-12:
            amount_label = _pdf_t_y_label(reagent, hours_y)
            ax.add_patch(
                FancyArrowPatch(
                    (x, 0.84),
                    (x, y_main + this_h / 2 + 0.004),
                    arrowstyle="-|>",
                    mutation_scale=8,
                    linewidth=1.1,
                    color=reagent_color,
                    shrinkA=0,
                    shrinkB=0,
                )
            )
            ax.text(x, 0.895, "+ Reagents", ha="center", va="center", fontsize=5.3, color=reagent_color, fontweight="bold")
            ax.text(x, 0.858, amount_label, ha="center", va="center", fontsize=4.9, color=BRAND_BLUE)

        side_items = list(side_by_node.get(str(node.get("id", "")), []) or [])
        if side_items:
            shown_side_items = side_items[:3]
            offsets = [0.0] if len(shown_side_items) == 1 else [-node_w * 0.28, node_w * 0.28]
            if len(shown_side_items) > 2:
                offsets = [-node_w * 0.34, 0.0, node_w * 0.34]
            for side_idx, (item, offset) in enumerate(zip(shown_side_items, offsets)):
                sx = x + offset
                side_name, side_amount = _split_stream_label(item.get("title", ""), item.get("label", ""))
                label = _wrap_label(side_name, width=18, max_lines=2)
                if side_amount:
                    label += f"\n{side_amount}"
                if side_idx == len(shown_side_items) - 1 and len(side_items) > len(shown_side_items):
                    label += "\n..."
                ax.plot([sx, sx], [y_main - this_h / 2, 0.255], color="#9aa7b7", linewidth=0.85, linestyle=(0, (2, 2)))
                ax.text(sx, 0.215, label, ha="center", va="top", fontsize=4.9, color=OVERVIEW_LABEL_GRAY, linespacing=1.18)

    fig.subplots_adjust(left=0.01, right=0.99, top=0.98, bottom=0.08)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, facecolor="white", pad_inches=0)
    plt.close(fig)
    return buf.getvalue()


def _build_overview_pdf_html_playwright(payload: OverviewPdfPayload) -> bytes:
    from .pdf_export_html import export_executive_summary_pdf_html

    return export_executive_summary_pdf_html(payload, None)


def get_last_pdf_exporter() -> tuple[str, str]:
    return LAST_PDF_EXPORTER, LAST_PDF_EXPORT_ERROR


def build_overview_pdf_bytes(payload: OverviewPdfPayload) -> bytes:
    """Build the executive summary PDF via HTML/Playwright only."""
    global LAST_PDF_EXPORTER, LAST_PDF_EXPORT_ERROR
    try:
        pdf = _build_overview_pdf_html_playwright(payload)
        LAST_PDF_EXPORTER = "HTML/Playwright"
        LAST_PDF_EXPORT_ERROR = ""
        return pdf
    except Exception as exc:
        LAST_PDF_EXPORTER = "HTML/Playwright"
        LAST_PDF_EXPORT_ERROR = f"{type(exc).__name__}: {exc}"
        raise
