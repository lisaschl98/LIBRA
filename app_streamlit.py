# app_streamlit.py
from __future__ import annotations

import base64
import hashlib
import html as html_module
from pathlib import Path
import tempfile
import uuid
from typing import Any
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import altair as alt
try:
    import plotly.graph_objects as go
except Exception:  # pragma: no cover - optional dependency fallback for local installs
    go = None

from cell_db import CellDB
from machine import TARGET_DATE as MACHINE_CAPEX_TARGET_DATE
from path import CELL_TECH_XLSX, COST_REGION_XLSX, EFF_XLSX
from stoichiometry import NMC_PRECURSOR_RULES
from step_utils import MASSFLOW_SEPARATED_TO_OUTPUT_ITEM, feed_has_pack_level, resolve_output_item_key
from hydro_recovery_scope import (
    LFP_HYDRO_RECOVERY_SCOPE_OPTIONS,
    LFP_HYDRO_RECOVERY_SCOPE_LABELS,
    MIX_HYDRO_RECOVERY_SCOPE_OPTIONS,
    MIX_HYDRO_RECOVERY_SCOPE_LABELS,
    NMC_HYDRO_RECOVERY_SCOPE_OPTIONS,
    NMC_HYDRO_RECOVERY_SCOPE_LABELS,
    PYRO_HYDRO_RECOVERY_SCOPE_OPTIONS,
    PYRO_HYDRO_RECOVERY_SCOPE_LABELS,
    resolve_lfp_hydro_recovery_scope,
    resolve_mix_hydro_recovery_scope,
    resolve_nmc_hydro_recovery_scope,
    resolve_pyro_hydro_recovery_scope,
    lfp_hydro_recovery_scope_summary,
    mix_hydro_recovery_scope_summary,
    nmc_hydro_recovery_scope_summary,
    pyro_hydro_recovery_scope_summary,
)
from infrastructure import (
    DEFAULT_TRANSPORT_COST_PER_T_KM,
    DEFAULT_TRANSPORT_GWP_PER_T_KM,
    LOCATION_COORDINATES,
    LOCATION_OPTIONS,
    REGION_COORDINATES,
    TRANSPORT_STEP_NAME,
    is_hub_spoke_mode,
    preset_distance_km,
    region_display_label,
    resolve_integrated_site_coordinates,
    resolve_hub_region,
    resolve_location_coordinates,
    resolve_spoke_region,
    resolve_transport_distance_km,
)
from main import (
    run_scenario,
    NMC_PRECURSOR_CODES,
    resolve_nmc_code,
    NMC_TARGET_BASIS_OPTIONS,
    resolve_nmc_target_basis,
    NMC_MAKEUP_POLICY_OPTIONS,
    NMC_MAKEUP_POLICY_LABELS,
    resolve_nmc_makeup_policy,
    resolve_nmc_makeup_fill_fraction,
    nmc_makeup_policy_summary,
)
from process_eff_scope import (
    filter_eff_df_for_scenario,
    process_eff_area,
    process_eff_scenario_filter_label,
)
from app_helpers.process_flow_plot import process_flow_plot_x_positions
from recovery_metrics import (
    LibraRecoveryResult,
    _product_output_lines_df,
    _recovery_pct,
    build_product_output_table,
    compute_libra_recovery,
)
from dashboard_support.overview_pdf import OverviewPdfPayload
from app_helpers.chemistry_labels import format_chemistry_html, format_chemistry_unicode, format_dataframe_chemistry
from dashboard_support import analytics as ac


# -------------------------------------------------------------------
# Page setup
# -------------------------------------------------------------------
st.set_page_config(page_title="LIBRA Dashboard", layout="wide")
ac.render_tracker_snippet()
ac.log_pageview_once()
BRAND_BLUE = "#003B75"
BRAND_YELLOW = "#E3B505"
INFRA_PRETREATMENT_COLOR = "#C9A004"
INFRA_HYDROMET_COLOR = BRAND_BLUE
PLOTLY_CHART_CONFIG = {
    "displayModeBar": "hover",
    "displaylogo": False,
    "scrollZoom": True,
    "toImageButtonOptions": {
        "format": "svg",
        "filename": "libra_chart",
        "scale": 1,
    },
}
PLANT_INFRA_INVESTMENT_VIEW_LABEL = "Infrastructure & Investment"
PROCESS_ECON_ENV_VIEW_LABEL = "Economics & Environmental Performance"
PLANT_INFRA_MAP_HEIGHT_BASE_PX = 520
PLANT_INFRA_CONFIG_PANEL_HEIGHT_BASE_PX = 178
PLANT_INFRA_PANEL_HEIGHT_SCALE = 1.1
PLANT_INFRA_PANEL_GAP_PX = 14
PLANT_INFRA_MAP_CAPTION_PX = 30
PLANT_INFRA_BORDER_CHROME_PX = 34
PLANT_INFRA_RIGHT_COLUMN_TRIM_PX = 2
PLANT_INFRA_MAP_HEIGHT_PX = int(round(PLANT_INFRA_MAP_HEIGHT_BASE_PX * PLANT_INFRA_PANEL_HEIGHT_SCALE))
PLANT_CAPEX_COMPOSITION_CHART_HEIGHT_PX = 360
PLANT_CAPEX_COMPOSITION_PANEL_HEADING_CHROME_PX = int(round(32 * PLANT_INFRA_PANEL_HEIGHT_SCALE))
OVERVIEW_CARD_BORDER = "#d4dce8"
OVERVIEW_LABEL_GRAY = "#5f6c7b"
SIDEBAR_WIDTH_INPUT_PX = 580  # wide: input mode / after "Clear results"
SIDEBAR_WIDTH_RESULTS_PX = 400  # narrow: after "Run Model" (more dashboard space)
LANDING_DIAGRAM_WIDTH_PX = 1302  # width of libra_process_overview.svg on the landing page

# ---------------------------------------------------------------------------
# Overview KPI tiles (Scenario | Economics | Environmental)
# ---------------------------------------------------------------------------
OVERVIEW_REVENUE_SUNBURST_HEIGHT_PX = 540  # Plotly height for the Revenue Explorer sunburst
OVERVIEW_TILE_HEIGHT_PX = 320  # shared height for the three KPI cards
OVERVIEW_DECISION_DASHBOARD_TILE_HEIGHT_PX = 400  # KPI cards in the Decision Dashboard
OVERVIEW_SECTION_HEADING_CHROME_PX = 36  # heading plus spacing below
# Reserved space inside the Scenario card without the map; too small would introduce scrolling.
OVERVIEW_TILE_CONTAINER_CHROME_PX = 32  # Streamlit card border plus inner padding
OVERVIEW_TILE_SCENARIO_HEADER_PX = OVERVIEW_SECTION_HEADING_CHROME_PX
OVERVIEW_TILE_SCENARIO_METRIC_ROW_PX = 44  # one KPI row with two columns
OVERVIEW_TILE_SCENARIO_BLOCK_GAP_PX = 4  # spacing between heading, rows, and card content
OVERVIEW_TILE_STATUS_MIN_PX = 80  # minimum height for Economics / Environmental status banners
OVERVIEW_TILE_STATUS_PADDING_Y_PX = 11  # vertical padding inside status boxes
OVERVIEW_TILE_STATUS_PADDING_X_PX = 14  # horizontal padding inside status boxes
OVERVIEW_TILE_HEADING_PADDING_TOP_PX = 0  # minimal distance from card edge to heading
OVERVIEW_TILE_HEADING_SIZE_REM = "1.75rem"  # matches st.subheader / Revenue Explorer
# Recovery summary card with three cards; also defines the Process Flow card height below.
OVERVIEW_RECOVERY_SUMMARY_CARD_PX = 92  # value + label + padding + margin for each card
OVERVIEW_BOTTOM_TILE_HEIGHT_PX = (
    OVERVIEW_TILE_CONTAINER_CHROME_PX
    + OVERVIEW_SECTION_HEADING_CHROME_PX
    + 3 * OVERVIEW_RECOVERY_SUMMARY_CARD_PX
    + 4
)
OVERVIEW_PFD_COMPACT_SCALE = 0.80  # process-flow diagram scale in the Overview card, without horizontal scroll

OVERVIEW_TILE_METRIC_LABEL_REM = "0.88rem"  # metric labels (Route, Feed, Costs, ...)
OVERVIEW_TILE_METRIC_VALUE_REM = "1.55rem"  # small KPI values in all three cards
OVERVIEW_TILE_PRIMARY_LABEL_REM = "0.95rem"  # Profit / Net GWP label
OVERVIEW_TILE_PRIMARY_VALUE_REM = "2.35rem"  # Profit / Net GWP value
OVERVIEW_TILE_STATUS_FONT_REM = "1.0rem"  # status banner text (Profitable, ...)


def _overview_scenario_map_slot_px() -> int:
    """Map height that fits inside OVERVIEW_TILE_HEIGHT_PX without tile scrolling."""
    reserved = (
        OVERVIEW_TILE_CONTAINER_CHROME_PX
        + OVERVIEW_TILE_SCENARIO_HEADER_PX
        + 2 * OVERVIEW_TILE_SCENARIO_METRIC_ROW_PX
        + 3 * OVERVIEW_TILE_SCENARIO_BLOCK_GAP_PX
    )
    return max(90, OVERVIEW_TILE_HEIGHT_PX - reserved)


# -------------------------------------------------------------------
# Data / helpers
# -------------------------------------------------------------------
def _path_exists_safe(p: Path | None) -> bool:
    if p is None:
        return False
    try:
        return p.exists()
    except (OSError, ValueError):
        return False


def _st_image(img, *, caption: str | None = None, use_container_width: bool = True, **kwargs) -> None:
    """``st.image`` wrapper with Streamlit width API compatibility."""
    import inspect

    opts = dict(kwargs)
    if caption is not None:
        opts["caption"] = caption
    params = inspect.signature(st.image).parameters
    if "width" in params:
        opts["width"] = "stretch" if use_container_width else "content"
    elif "use_container_width" in params:
        opts["use_container_width"] = use_container_width
    elif use_container_width and "use_column_width" in params:
        opts["use_column_width"] = True
    st.image(img, **opts)


def _render_svg_inline(path: Path, *, caption: str | None = None) -> None:
    """Render an SVG file inline (``st.image`` does not reliably display SVG)."""
    if caption:
        st.caption(caption)
    svg = path.read_text(encoding="utf-8")
    st.markdown(
        f'<div style="width:100%;max-width:100%;overflow-x:auto;">{svg}</div>',
        unsafe_allow_html=True,
    )


def _inject_sidebar_width(*, results_visible: bool) -> None:
    """Wide sidebar for scenario input; narrower after a model run."""
    width_px = SIDEBAR_WIDTH_RESULTS_PX if results_visible else SIDEBAR_WIDTH_INPUT_PX
    st.markdown(
        f"""
        <style>
            [data-testid="stSidebar"] {{
                min-width: {width_px}px !important;
                max-width: {width_px}px !important;
            }}
            [data-testid="stSidebar"][aria-expanded="true"] > div:first-child {{
                width: {width_px}px !important;
                min-width: {width_px}px !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _apply_brand_styles() -> None:
    st.markdown(
        f"""
        <style>
            :root {{
                --primary-color: {BRAND_YELLOW};
            }}
            .stApp a {{
                color: {BRAND_BLUE};
            }}
            .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
            .stApp p, .stApp li,
            .stApp [data-testid="stWidgetLabel"],
            .stApp [data-testid="stMarkdownContainer"] {{
                color: {BRAND_BLUE};
            }}
            [data-testid="stSidebar"],
            [data-testid="stSidebar"] [data-testid="stWidgetLabel"],
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
            [data-testid="stSidebar"] p,
            [data-testid="stSidebar"] li {{
                color: {BRAND_BLUE};
            }}
            /* Sidebar boxes/chips should not be fully blue */
            [data-testid="stSidebar"] [data-baseweb="tag"] {{
                background: transparent !important;
                border: 1px solid {BRAND_BLUE} !important;
                color: {BRAND_BLUE} !important;
            }}
            [data-testid="stSidebar"] [data-baseweb="tag"] * {{
                color: {BRAND_BLUE} !important;
                fill: {BRAND_BLUE} !important;
            }}
            /* Sidebar select fields must stay readable/clickable */
            [data-testid="stSidebar"] [data-baseweb="select"] > div {{
                background: #ffffff !important;
                border-color: {BRAND_YELLOW} !important;
            }}
            [data-testid="stSidebar"] [data-baseweb="select"] > div * {{
                color: {BRAND_BLUE} !important;
            }}
            [data-testid="stSidebar"] [role="listbox"] {{
                background: #ffffff !important;
            }}
            [data-testid="stSidebar"] [role="option"] {{
                background: #ffffff !important;
                color: {BRAND_BLUE} !important;
            }}
            [data-testid="stSidebar"] [role="option"][aria-selected="true"] {{
                background: rgba(0, 59, 117, 0.10) !important;
            }}
            .stButton > button, .stDownloadButton > button {{
                border-color: {BRAND_YELLOW};
                color: {BRAND_BLUE};
            }}
            .stButton > button[kind="primary"] {{
                background-color: {BRAND_YELLOW};
                color: {BRAND_BLUE};
            }}
            /* Keep tabs readable: no solid fills */
            [data-baseweb="tab-list"] {{
                background: transparent !important;
            }}
            [data-baseweb="tab"], [data-baseweb="tab"][aria-selected="true"] {{
                background: transparent !important;
                color: {BRAND_BLUE} !important;
                border-color: {BRAND_BLUE} !important;
            }}
            /* Inputs/selects readable with brand focus */
            [data-baseweb="input"] > div,
            [data-baseweb="textarea"] > div,
            [data-baseweb="select"] > div {{
                border-color: {BRAND_YELLOW} !important;
                box-shadow: none !important;
            }}
            [data-baseweb="input"] > div:focus-within,
            [data-baseweb="textarea"] > div:focus-within,
            [data-baseweb="select"] > div:focus-within {{
                border-color: {BRAND_YELLOW} !important;
                box-shadow: 0 0 0 1px {BRAND_YELLOW} !important;
            }}
            [data-baseweb="select"] * {{
                color: {BRAND_BLUE} !important;
            }}
            [data-baseweb="select"] svg {{
                color: {BRAND_BLUE} !important;
            }}
            /* Dropdown popup readable */
            [role="listbox"] {{
                background: #ffffff !important;
            }}
            [role="option"] {{
                background: #ffffff !important;
            }}
            [role="option"][aria-selected="true"] {{
                background: rgba(0, 59, 117, 0.10) !important;
            }}
            [role="listbox"] *,
            [role="option"] * {{
                color: {BRAND_BLUE} !important;
            }}
            /* Native control accents */
            [data-testid="stCheckbox"] input[type="checkbox"],
            [data-testid="stRadio"] input[type="radio"],
            [data-testid="stToggle"] input[type="checkbox"] {{
                accent-color: {BRAND_YELLOW} !important;
            }}
            /* Slider: keep readable labels; style only handle/accent */
            [data-baseweb="slider"] [role="slider"] {{
                background-color: {BRAND_YELLOW} !important;
                border-color: {BRAND_YELLOW} !important;
            }}
            [data-baseweb="slider"] [role="slider"] ~ div {{
                background-color: transparent !important;
            }}
            [data-baseweb="progress-bar"] > div {{
                background-color: {BRAND_YELLOW};
            }}
            [data-testid="stNumberInput"] button {{
                color: {BRAND_BLUE} !important;
            }}
            [data-testid="stSelectbox"] svg,
            [data-testid="stMultiSelect"] svg,
            [data-testid="stDateInput"] svg {{
                color: {BRAND_BLUE} !important;
            }}
            /* Sharper +/- icons for number inputs */
            [data-testid="stNumberInput"] button svg,
            [data-testid="stNumberInput"] button svg * {{
                color: {BRAND_BLUE} !important;
                fill: {BRAND_BLUE} !important;
                stroke: none !important;
                filter: none !important;
                shape-rendering: geometricPrecision;
            }}
            /* Plotly modebar: show on chart hover, keep it light like the native toolbar */
            .modebar {{
                background: transparent !important;
                box-shadow: none !important;
            }}
            .modebar-group {{
                background: transparent !important;
                box-shadow: none !important;
            }}
            .modebar-btn {{
                background: transparent !important;
                border-radius: 3px !important;
                opacity: 0.72 !important;
            }}
            .modebar-btn:hover,
            .modebar-btn.active {{
                background: rgba(0, 59, 117, 0.08) !important;
                box-shadow: none !important;
                opacity: 1 !important;
            }}
            .modebar-btn svg,
            .modebar-btn svg path {{
                fill: #9aa3ad !important;
            }}
            .modebar-btn:hover svg,
            .modebar-btn:hover svg path {{
                fill: {BRAND_BLUE} !important;
            }}
            /* HTML tables: blue text only (no SVG fill override) */
            [data-testid="stTable"] th,
            [data-testid="stTable"] td {{
                color: {BRAND_BLUE} !important;
            }}
            /* Data editor: only grid cell colors via CSS vars — toolbar/icons stay Streamlit default */
            /* Data editor/dataframe selection contrast (readable when clicked) */
            [data-testid="stDataFrame"],
            [data-testid="stDataEditor"] {{
                --gdg-accent-color: {BRAND_YELLOW} !important;
                --gdg-accent-fg: {BRAND_BLUE} !important;
                --gdg-text-dark: {BRAND_BLUE} !important;
                --gdg-text-header: {BRAND_BLUE} !important;
                --gdg-bg-header: #ffffff !important;
                --gdg-bg-cell: #ffffff !important;
                --gdg-bg-cell-medium: rgba(0, 59, 117, 0.10) !important;
                --gdg-bg-cell-selected: rgba(0, 59, 117, 0.16) !important;
            }}
            [data-testid="stDataFrame"] [class*="gdg"],
            [data-testid="stDataEditor"] [class*="gdg"] {{
                color: {BRAND_BLUE} !important;
            }}
            [data-testid="stDataFrame"] canvas,
            [data-testid="stDataEditor"] canvas {{
                filter: none !important;
            }}
            /* Help icons (question marks) */
            [data-testid="stWidgetLabel"] [data-testid="stTooltipIcon"],
            [data-testid="stWidgetLabel"] [data-testid="stTooltipIcon"] > div {{
                background: transparent !important;
                color: {BRAND_BLUE} !important;
            }}
            [data-testid="stTooltipIcon"] svg {{
                color: {BRAND_BLUE} !important;
                fill: none !important;
                background: transparent !important;
            }}
            [data-testid="stTooltipIcon"] svg * {{
                color: {BRAND_BLUE} !important;
                stroke: currentColor !important;
                fill: none !important;
            }}
            [data-testid="stWidgetLabel"] [data-testid="stTooltipIcon"] svg,
            [data-testid="stWidgetLabel"] [data-testid="stTooltipIcon"] svg * {{
                fill: none !important;
                stroke: {BRAND_BLUE} !important;
            }}
            /* Help tooltip/popover text */
            [role="tooltip"], [role="tooltip"] *,
            [data-baseweb="popover"], [data-baseweb="popover"] * {{
                color: {BRAND_BLUE} !important;
            }}
            input:focus, textarea:focus, select:focus {{
                border-color: {BRAND_YELLOW} !important;
                box-shadow: 0 0 0 1px {BRAND_YELLOW} !important;
            }}
            /* Main-area selects (e.g. overview revenue) – match overview card borders */
            section[data-testid="stMain"] [data-baseweb="select"] > div {{
                border-color: {OVERVIEW_CARD_BORDER} !important;
                background: #fafbfd !important;
                box-shadow: none !important;
            }}
            section[data-testid="stMain"] [data-baseweb="select"] > div:focus-within {{
                border-color: {OVERVIEW_CARD_BORDER} !important;
                box-shadow: none !important;
            }}
            section[data-testid="stMain"] [data-testid="stAlert"],
            section[data-testid="stMain"] [data-testid="stAlert"] * {{
                font-weight: 700 !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _resolve_scenario_name(raw_name: str) -> str:
    """Use a custom name when provided; otherwise assign Scenario 1, 2, 3, … per run."""
    cleaned = str(raw_name or "").strip()
    if cleaned:
        return cleaned
    st.session_state["auto_scenario_seq"] = int(st.session_state.get("auto_scenario_seq", 0)) + 1
    return f"Scenario {st.session_state['auto_scenario_seq']}"


def _landing_logo_img_html(*, width_px: int = 180) -> str:
    logo_path = Path(__file__).resolve().parent / "assets" / "businesschemistry_logo.png"
    if not _path_exists_safe(logo_path):
        return ""
    encoded = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    return (
        f'<img src="data:image/png;base64,{encoded}" width="{width_px}" '
        f'alt="Institute of Business Chemistry, University of Münster" '
        f'style="display:block; max-width:100%; height:auto;" />'
    )


def _inject_landing_layout_styles() -> None:
    st.markdown(
        f"""
        <style>
            section[data-testid="stMain"] .libra-landing-shell {{
                max-width: {LANDING_DIAGRAM_WIDTH_PX}px;
                width: 100%;
                margin: 0 0 0.75rem 0;
            }}
            section[data-testid="stMain"] .libra-landing-header {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 1rem;
                margin: 0 0 0.35rem 0;
            }}
            section[data-testid="stMain"] .libra-landing-logo-wrap {{
                flex: 0 0 auto;
                margin-left: auto;
            }}
            section[data-testid="stMain"] .libra-landing-banner {{
                border-radius: 0.5rem;
                padding: 0.75rem 1rem;
                font-weight: 600;
                margin: 0.2rem 0 0.8rem 0;
            }}
            section[data-testid="stMain"] .libra-landing-banner-yellow {{
                background-color: {BRAND_YELLOW};
                color: {BRAND_BLUE};
            }}
            section[data-testid="stMain"] .libra-landing-banner-cleared {{
                background-color: #d4edda;
                color: #1a7f37;
                font-weight: 700;
            }}
            section[data-testid="stMain"] .libra-landing-get-started {{
                color: {BRAND_BLUE};
                margin: 0.25rem 0 0.35rem 0;
                font-size: 1.1rem;
            }}
            section[data-testid="stMain"] .libra-landing-steps {{
                color: {BRAND_BLUE};
                margin: 0 0 0.8rem 1.1rem;
                padding: 0;
            }}
            section[data-testid="stMain"] .libra-landing-steps > div {{
                margin: 0.2rem 0;
            }}
            section[data-testid="stMain"] .libra-landing-diagram {{
                width: 100%;
                overflow-x: auto;
            }}
            section[data-testid="stMain"] .libra-landing-diagram svg {{
                width: 100%;
                height: auto;
                display: block;
            }}
            section[data-testid="stMain"] .libra-landing-footer {{
                color: {OVERVIEW_LABEL_GRAY};
                font-size: 0.85rem;
                margin: 0.5rem 0 0 0;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_landing_welcome_page(*, show_cleared: bool) -> None:
    """Start page: header, banners, and diagram share the SVG width."""
    _inject_landing_layout_styles()
    base_dir = Path(__file__).resolve().parent
    process_path = base_dir / "assets" / "libra_process_overview.svg"
    logo_html = _landing_logo_img_html()
    logo_block = (
        f'<div class="libra-landing-logo-wrap">{logo_html}</div>' if logo_html else ""
    )
    # Small HTML chunks — Streamlit escapes <ol> and large nested blocks.
    st.markdown(
        f"""
        <div class="libra-landing-shell">
            <div class="libra-landing-header">
                <div class="libra-landing-title">
                    <h1 style="margin:0; padding:0; color:{BRAND_BLUE}; font-size:3.15rem; font-weight:700; line-height:1.05;">
                        LIBRA
                    </h1>
                    <p style="margin:0.15rem 0 0 0; padding:0; color:{BRAND_BLUE}; font-size:1.5rem; font-weight:600; line-height:1.2;">
                        Lithium-Ion Battery Recycling Assessment
                    </p>
                </div>
                {logo_block}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if show_cleared:
        st.markdown(
            """
            <div class="libra-landing-shell">
                <div class="libra-landing-banner libra-landing-banner-cleared">Cleared.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown(
        f"""
        <div class="libra-landing-shell">
            <div class="libra-landing-banner libra-landing-banner-yellow">
                Configure inputs in the sidebar and click <b>Run Model</b>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="libra-landing-shell">
            <h4 class="libra-landing-get-started">Get Started</h4>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="libra-landing-shell">
            <div class="libra-landing-steps">
                <div>1. Select the recycling route and infrastructure setup.</div>
                <div>2. Define the region and annual recycling feed.</div>
                <div>3. Configure the battery feedstock, including chemistry, cell format, input level, and feedstock shares.</div>
                <div>4. Choose product and recovery settings.</div>
                <div>5. Optionally adjust process efficiencies and advanced assumptions.</div>
                <div>6. Click Run Model to calculate the scenario.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if _path_exists_safe(process_path):
        svg = process_path.read_text(encoding="utf-8")
        st.markdown(
            f"""
            <div class="libra-landing-shell">
                <div class="libra-landing-diagram">
                    <div style="width:100%;max-width:100%;overflow-x:auto;">{svg}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown(
        f"""
        <div class="libra-landing-shell">
            <p class="libra-landing-footer">© 2026 University Münster. All rights reserved.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_header_with_logo() -> None:
    base_dir = Path(__file__).resolve().parent
    logo_html = _landing_logo_img_html(width_px=180)
    logo_block = (
        f'<div style="margin-left:auto; display:flex; justify-content:flex-end;">{logo_html}</div>'
        if logo_html
        else ""
    )
    st.markdown(
        f"""
        <div style="display:flex; align-items:flex-start; justify-content:space-between; width:100%; gap:1rem; margin:0 0 0.35rem 0;">
            <div>
                <h1 style="margin:0; padding:0; color:{BRAND_BLUE}; font-size:3.15rem; font-weight:700; line-height:1.05;">
                    LIBRA
                </h1>
                <p style="margin:0.15rem 0 0 0; padding:0; color:{BRAND_BLUE}; font-size:1.5rem; font-weight:600; line-height:1.2;">
                    Lithium-Ion Battery Recycling Assessment
                </p>
            </div>
            {logo_block}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_default_graphics_block() -> None:
    base_dir = Path(__file__).resolve().parent
    process_path = base_dir / "assets" / "libra_process_overview.svg"
    if _path_exists_safe(process_path):
        _render_svg_inline(process_path, caption="LIBRA Process Overview")


def _render_custom_graphics_block() -> None:
    st.markdown("### Additional Graphics")
    st.caption("Upload your own logos, diagrams, or process graphics and show them directly on the page.")
    uploaded_images = st.file_uploader(
        "Upload graphics",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="custom_graphics_upload",
        help="You can upload multiple image files.",
    )
    if uploaded_images:
        img_cols = st.columns(min(3, len(uploaded_images)))
        for idx, img in enumerate(uploaded_images):
            with img_cols[idx % len(img_cols)]:
                _st_image(
                    img,
                    caption=img.name,
                )


_apply_brand_styles()


def _safe_df(x) -> pd.DataFrame:
    return x if isinstance(x, pd.DataFrame) else pd.DataFrame()


def _safe_float(v, default=0.0) -> float:
    try:
        x = float(v)
        if pd.isna(x):
            return default
        return x
    except Exception:
        return default


def _ensure_select_option(key: str, options: list, *, default_index: int = 0) -> None:
    """Keep session_state[key] valid when option lists change after a new run."""
    if not options:
        return
    idx = min(max(int(default_index), 0), len(options) - 1)
    cur = st.session_state.get(key)
    if cur is None or cur not in options:
        st.session_state[key] = options[idx]


def _nmc_precursor_label(code: str) -> str:
    r = NMC_PRECURSOR_RULES.get(str(code), {})
    ni = r.get("ni", "?")
    co = r.get("co", "?")
    mn = r.get("mn", "?")
    return f"NMC{code}  (Ni:Co:Mn = {ni}:{co}:{mn})"

def _custom_workbook_path(prefix: str, payload: bytes) -> Path:
    digest = hashlib.sha256(payload).hexdigest()[:12]
    target_dir = Path(tempfile.gettempdir()) / "libra_streamlit_inputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{prefix}_{digest}.xlsx"


def _norm_col_name(col: str) -> str:
    return str(col).strip().lower()


def _region_columns_from_df(df: pd.DataFrame) -> list[str]:
    meta_cols = {
        "item",
        "material",
        "role",
        "economic type",
        "environmental type",
        "category",
        "unit",
    }
    out: list[str] = []
    for c in df.columns:
        name = str(c).strip()
        norm = _norm_col_name(name)
        if not name or name.lower().startswith("unnamed"):
            continue
        if norm in meta_cols:
            continue
        out.append(str(c))
    return out


def _region_options_from_workbook(xlsx_path: str) -> list[str]:
    try:
        cost = pd.read_excel(str(xlsx_path), sheet_name="Cost Parameter")
        gwp = pd.read_excel(str(xlsx_path), sheet_name="GWP Parameter")
    except Exception:
        return ["DE", "EU", "US", "CN"]
    cols = []
    for c in _region_columns_from_df(cost):
        if c in _region_columns_from_df(gwp) and c not in cols:
            cols.append(c)
    return cols or ["DE", "EU", "US", "CN"]


def _custom_region_editor_df(df: pd.DataFrame, base_region: str, key_prefix: str) -> pd.DataFrame:
    view = df.copy()
    view.columns = [str(c).strip() for c in view.columns]
    if "item" not in view.columns or base_region not in view.columns:
        return pd.DataFrame(columns=["item", base_region, "Custom"])

    display_cols = [c for c in ["item", "role", "category", "unit", base_region] if c in view.columns]
    out = view[display_cols].copy()
    out["Custom"] = pd.to_numeric(view[base_region], errors="coerce").fillna(0.0)
    st.caption("Edit only the `Custom` column. Click a cell, type a value, and press Enter.")

    return st.data_editor(
        out,
        key=key_prefix,
        hide_index=True,
        width="stretch",
        disabled=[c for c in out.columns if c != "Custom"],
        column_config={
            "Custom": st.column_config.NumberColumn("Custom", format="%.6g"),
        },
    )


def _write_custom_region_workbook(
    source_path: str,
    base_region: str,
    cost_edit: pd.DataFrame,
    gwp_edit: pd.DataFrame,
) -> str:
    sheets = pd.read_excel(str(source_path), sheet_name=None)

    def _apply(sheet_name: str, edit_df: pd.DataFrame) -> None:
        if sheet_name not in sheets:
            return
        df = sheets[sheet_name].copy()
        df.columns = [str(c).strip() for c in df.columns]
        if "item" not in df.columns or "Custom" not in edit_df.columns:
            return
        values = {
            str(r.get("item", "")).strip(): _safe_float(r.get("Custom"), 0.0)
            for _, r in edit_df.iterrows()
            if str(r.get("item", "")).strip()
        }
        df["Custom"] = df["item"].astype(str).str.strip().map(values)
        if df["Custom"].isna().any() and base_region in df.columns:
            df["Custom"] = df["Custom"].fillna(pd.to_numeric(df[base_region], errors="coerce").fillna(0.0))
        sheets[sheet_name] = df

    _apply("Cost Parameter", cost_edit)
    _apply("GWP Parameter", gwp_edit)

    payload = (
        str(Path(source_path).resolve())
        + "|"
        + base_region
        + "|"
        + cost_edit.to_csv(index=False)
        + "|"
        + gwp_edit.to_csv(index=False)
    ).encode("utf-8", errors="ignore")
    target = _custom_workbook_path("custom_region", payload)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return str(target)


def _chem_family_for_label(chemistry: str) -> str:
    c = str(chemistry or "").strip().upper()
    if c.startswith("NMC"):
        return "NMC"
    if c.startswith("LFP"):
        return "LFP"
    return c


def _format_cell_display_label(cell_id: str) -> str:
    """User-facing battery label; underlying cell_id key stays unchanged."""
    cid = str(cell_id or "").strip()
    if not cid or "_" not in cid:
        return cid
    chem, *fmt_parts = cid.split("_")
    fmt = " ".join(fmt_parts)
    return f"{chem} – {fmt}"


FEEDSTOCK_TYPE_OPTIONS: tuple[str, ...] = ("nmc", "lfp", "mix")

FEEDSTOCK_TYPE_LABELS: dict[str, str] = {
    "nmc": "NMC Feedstock",
    "lfp": "LFP Feedstock",
    "mix": "Mixed NMC/LFP Feedstock",
}

FEEDSTOCK_TYPE_SHORT_LABELS: dict[str, str] = {
    "nmc": "NMC",
    "lfp": "LFP",
    "mix": "NMC/LFP Mixed",
}

_LFP_RECOVERY_SCOPE_CAPTIONS: dict[str, str] = {
    "all": "Recover iron and lithium products.",
    "fe": "Recover iron only. Lithium remains unrecovered.",
}

_MIX_RECOVERY_SCOPE_CAPTIONS: dict[str, str] = {
    "all": "Recover NMC, lithium, and iron products.",
    "nmc": "Recover NMC only.",
    "nmc_li": "Recover NMC and lithium products.",
}

_PYRO_RECOVERY_SCOPE_CAPTIONS: dict[str, str] = {
    "all": "Recover cobalt, nickel, manganese, and lithium products.",
    "co_ni": "Recover cobalt and nickel products.",
    "co": "Recover cobalt products.",
    "co_ni_mn": "Recover cobalt, nickel, and manganese products.",
}

ROUTE_DISPLAY_LABELS: dict[str, str] = {
    "mech": "Mech → Hydro",
    "pyro": "Pyro → Hydro",
}

ROUTE_SIDEBAR_LABELS: dict[str, str] = {
    "mech": "Mechanical-Hydrometallurgical",
    "pyro": "Pyrometallurgical-Hydrometallurgical",
}

_EXTERNAL_METAL_SUPPLY_OPTIONS: tuple[str, ...] = ("none", "limited", "flexible")
_EXTERNAL_METAL_SUPPLY_LABELS: dict[str, str] = {
    "none": "None",
    "limited": "Limited",
    "flexible": "Flexible",
}
_EXTERNAL_METAL_SUPPLY_CAPTIONS: dict[str, str] = {
    "none": "Use only recovered metals.",
    "limited": "External metal sulfates may be added up to a user-defined limit.",
    "flexible": (
        "External metal sulfates may be added without restriction to achieve the target composition."
    ),
}

# Sidebar labels for nmc_target_basis (internal keys unchanged: min | ni | co | mn).
_NMC_PRODUCTION_CONSTRAINT_LABELS: dict[str, str] = {
    "min": "Limiting Metal Availability",
    "ni": "Nickel Availability",
    "co": "Cobalt Availability",
    "mn": "Manganese Availability",
}

_METAL_RECOVERY_SCOPE_HELP = (
    "If fewer recovery targets are selected, the process steps for additional "
    "production outside that scope are omitted from the model."
)


def _external_metal_supply_from_scenario(source: dict | None) -> str:
    """Map internal makeup policy to user-facing External Metal Supply option."""
    policy = resolve_nmc_makeup_policy(source, default="capped")
    if policy == "none":
        return "none"
    if policy == "unlimited":
        return "flexible"
    return "limited"

_CELL_FORMAT_DISPLAY: dict[str, str] = {
    "pouch": "Pouch",
    "prismatic": "Prismatic",
    "cylindrical21700": "Cylindrical 21700",
    "cylindrical4680": "Cylindrical 4680",
}


def _inject_sidebar_section_styles() -> None:
    st.markdown(
        f"""
        <style>
            section[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
                font-weight: 600;
            }}
            section[data-testid="stSidebar"] .libra-feedstock-row-label {{
                font-size: 0.82rem;
                font-weight: 700;
                color: {BRAND_BLUE};
                margin: 0.35rem 0 0.15rem 0;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _sidebar_section(title: str) -> None:
    st.sidebar.divider()
    st.sidebar.subheader(title)


def _format_display_label(fmt: str) -> str:
    key = str(fmt or "").strip()
    if not key:
        return ""
    return _CELL_FORMAT_DISPLAY.get(key, key.replace("_", " ").title())


def _chemistry_for_cell_id(cell_id: str, cell_meta: dict[str, dict[str, str]]) -> str:
    cid = str(cell_id or "").strip()
    meta = cell_meta.get(cid, {})
    chem = str(meta.get("chemistry") or "").strip()
    if chem:
        return chem
    return cid.split("_")[0] if "_" in cid else cid


def _format_for_cell_id(cell_id: str, cell_meta: dict[str, dict[str, str]]) -> str:
    cid = str(cell_id or "").strip()
    meta = cell_meta.get(cid, {})
    fmt = str(meta.get("format") or "").strip()
    if fmt:
        return fmt
    return cid.split("_", 1)[1] if "_" in cid else ""


def _chemistry_options_for_cells(
    cell_ids: list[str],
    cell_meta: dict[str, dict[str, str]],
) -> list[str]:
    chems = {_chemistry_for_cell_id(cid, cell_meta) for cid in cell_ids if str(cid).strip()}
    return sorted(c for c in chems if c)


def _format_options_for_chemistry(
    cell_ids: list[str],
    cell_meta: dict[str, dict[str, str]],
    chemistry: str,
) -> list[str]:
    chem = str(chemistry or "").strip()
    formats = {
        _format_for_cell_id(cid, cell_meta)
        for cid in cell_ids
        if str(cid).strip() and _chemistry_for_cell_id(cid, cell_meta) == chem
    }
    return sorted(f for f in formats if f)


def _resolve_cell_id_from_parts(
    cell_ids: list[str],
    cell_meta: dict[str, dict[str, str]],
    chemistry: str,
    format_key: str,
) -> str:
    chem = str(chemistry or "").strip()
    fmt = str(format_key or "").strip()
    for cid in cell_ids:
        if _chemistry_for_cell_id(cid, cell_meta) == chem and _format_for_cell_id(cid, cell_meta) == fmt:
            return cid
    return cell_ids[0] if cell_ids else ""


def _cell_chem_family(cell_id: str, cell_meta: dict[str, dict[str, str]] | None = None) -> str:
    cid = str(cell_id or "").strip()
    meta = (cell_meta or {}).get(cid, {})
    chem = str(meta.get("chemistry") or "").strip()
    if chem:
        return _chem_family_for_label(chem)
    return _chem_family_for_label(cid)


def _cell_matches_feedstock_type(
    cell_id: str,
    feedstock_type: str,
    cell_meta: dict[str, dict[str, str]] | None = None,
) -> bool:
    ft = str(feedstock_type or "mix").strip().lower()
    family = _cell_chem_family(cell_id, cell_meta)
    if ft == "nmc":
        return family == "NMC"
    if ft == "lfp":
        return family == "LFP"
    if ft == "mix":
        return family in ("NMC", "LFP")
    return True


def _filter_cell_options_for_feedstock_type(
    cell_options: list[str],
    cell_meta: dict[str, dict[str, str]],
    feedstock_type: str,
) -> list[str]:
    return [cid for cid in cell_options if _cell_matches_feedstock_type(cid, feedstock_type, cell_meta)]


def _sanitize_feed_rows_for_feedstock_type(
    feed_rows: list[dict],
    filtered_options: list[str],
) -> list[dict]:
    if not filtered_options:
        return feed_rows
    fallback = filtered_options[0]
    out: list[dict] = []
    for row in feed_rows:
        r = dict(row)
        cid = str(r.get("cell_id", "")).strip()
        if cid not in filtered_options:
            r["cell_id"] = fallback
        out.append(r)
    return out


def _infer_feedstock_type_from_feed(feed: list[dict], cell_meta: dict[str, dict[str, str]] | None = None) -> str:
    families = {
        _cell_chem_family(str(row.get("cell_id", "")), cell_meta)
        for row in (feed or [])
        if isinstance(row, dict) and str(row.get("cell_id", "")).strip()
    }
    families.discard("")
    has_nmc = "NMC" in families
    has_lfp = "LFP" in families
    if has_nmc and has_lfp:
        return "mix"
    if has_nmc:
        return "nmc"
    if has_lfp:
        return "lfp"
    return "mix"


def _resolve_feedstock_type(source: dict | None, cell_meta: dict[str, dict[str, str]] | None = None) -> str:
    raw = str((source or {}).get("feedstock_type", "") or "").strip().lower()
    if raw in FEEDSTOCK_TYPE_OPTIONS:
        return raw
    return _infer_feedstock_type_from_feed((source or {}).get("feed") or [], cell_meta)


def _material_editor(df: pd.DataFrame, value_col: str, key: str) -> pd.DataFrame:
    view = df.copy()
    view.columns = [str(c).strip() for c in view.columns]
    keep = [c for c in ["component", "material", value_col] if c in view.columns]
    out = view[keep].copy()
    out[f"Custom {value_col}"] = pd.to_numeric(view[value_col], errors="coerce").fillna(0.0)
    st.caption(f"Edit only `Custom {value_col}`. All other columns are read-only.")
    return st.data_editor(
        out,
        key=key,
        hide_index=True,
        width="stretch",
        disabled=[c for c in out.columns if not str(c).startswith("Custom ")],
        column_config={
            f"Custom {value_col}": st.column_config.NumberColumn(f"Custom {value_col}", format="%.8g"),
        },
    )


def _write_custom_cell_tech_workbook(
    source_path: str,
    *,
    base_cell_id: str,
    custom_cell_id: str,
    custom_chemistry: str,
    custom_format: str,
    cell_weight_kg: float,
    cell_energy_Wh: float,
    cells_per_module: int,
    cell_edit: pd.DataFrame,
    module_edit: pd.DataFrame,
    pack_edit: pd.DataFrame,
) -> str:
    db = CellDB(str(source_path))
    sheets = pd.read_excel(str(source_path), sheet_name=None)

    ct = db.cell_types.copy()
    base_ct = ct.loc[ct["cell_id"].astype(str).str.strip() == base_cell_id].iloc[0].to_dict()
    chemistry = str(custom_chemistry or base_ct.get("chemistry", "")).strip()
    chem_family = _chem_family_for_label(chemistry)
    base_format = str(base_ct.get("format", "")).strip()

    ct = ct[ct["cell_id"].astype(str).str.strip() != custom_cell_id].copy()
    base_ct.update(
        {
            "cell_id": custom_cell_id,
            "chemistry": chemistry,
            "format": custom_format,
            "cell_weight_kg": float(cell_weight_kg),
            "cell_energy_Wh": float(cell_energy_Wh),
        }
    )
    ct = pd.concat([ct, pd.DataFrame([base_ct])], ignore_index=True)

    cm = db.cell_mats.copy()
    cm = cm[cm["cell_id"].astype(str).str.strip() != custom_cell_id].copy()
    cm_rows = []
    custom_cell_col = "Custom kg_per_cell"
    for _, r in cell_edit.iterrows():
        mat = str(r.get("material", "")).strip()
        comp = str(r.get("component", "")).strip()
        if not mat:
            continue
        cm_rows.append(
            {
                "cell_id": custom_cell_id,
                "component": comp,
                "material": mat,
                "kg_per_cell": _safe_float(r.get(custom_cell_col), 0.0),
            }
        )
    cm = pd.concat([cm, pd.DataFrame(cm_rows)], ignore_index=True)

    mm = db.mod_mats.copy()
    mm = mm[mm["format"].astype(str).str.strip() != custom_format].copy()
    mm_rows = []
    custom_module_col = "Custom kg_per_module"
    for _, r in module_edit.iterrows():
        mat = str(r.get("material", "")).strip()
        if not mat:
            continue
        mm_rows.append(
            {
                "module_template_id": f"mod_{custom_format}_{chem_family}_custom",
                "chemistry": chem_family,
                "format": custom_format,
                "material": mat,
                "kg_per_module": _safe_float(r.get(custom_module_col), 0.0),
            }
        )
    mm = pd.concat([mm, pd.DataFrame(mm_rows)], ignore_index=True)

    pm = db.pack_mats.copy()
    pm = pm[pm["format"].astype(str).str.strip() != custom_format].copy()
    pm_rows = []
    custom_pack_col = "Custom kg_per_100kWhpack"
    for _, r in pack_edit.iterrows():
        mat = str(r.get("material", "")).strip()
        if not mat:
            continue
        pm_rows.append(
            {
                "pack_id": f"pack_{custom_format}_{chem_family}_custom",
                "chemistry": chem_family,
                "format": custom_format,
                "material": mat,
                "kg_per_100kWhpack": _safe_float(r.get(custom_pack_col), 0.0),
            }
        )
    pm = pd.concat([pm, pd.DataFrame(pm_rows)], ignore_index=True)

    fr = db.format_rules.copy()
    base_fr = fr.loc[fr["format"].astype(str).str.strip() == base_format]
    fr = fr[fr["format"].astype(str).str.strip() != custom_format].copy()
    fr_row = base_fr.iloc[0].to_dict() if not base_fr.empty else {"format": custom_format}
    fr_row.update({"format": custom_format, "cells_per_module": int(cells_per_module)})
    fr = pd.concat([fr, pd.DataFrame([fr_row])], ignore_index=True)

    replacements = {
        db._sheet_map.get("cell_types", "Cell_Types"): ct,
        db._sheet_map.get("cell_materials", "Cell_Materials"): cm,
        db._sheet_map.get("module_materials", "Module_Materials"): mm,
        db._sheet_map.get("pack_materials", "Pack_Materials"): pm,
        db._sheet_map.get("format_rules", "Modules_format_rules"): fr,
    }
    sheets.update(replacements)

    payload = (
        str(Path(source_path).resolve())
        + "|"
        + base_cell_id
        + "|"
        + custom_cell_id
        + "|"
        + str(custom_chemistry)
        + "|"
        + str(cell_weight_kg)
        + "|"
        + str(cell_energy_Wh)
        + "|"
        + str(cells_per_module)
        + "|"
        + cell_edit.to_csv(index=False)
        + "|"
        + module_edit.to_csv(index=False)
        + "|"
        + pack_edit.to_csv(index=False)
    ).encode("utf-8", errors="ignore")
    target = _custom_workbook_path("custom_cell_tech", payload)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return str(target)


def _load_cell_meta(xlsx_path: str) -> tuple[dict[str, dict[str, str]], list[str], str | None]:
    try:
        db = CellDB(str(xlsx_path))
        ct = db.cell_types
        meta: dict[str, dict[str, str]] = {}
        if isinstance(ct, pd.DataFrame) and not ct.empty:
            for _, r in ct.iterrows():
                cid = str(r.get("cell_id") or "").strip()
                if not cid:
                    continue
                meta[cid] = {
                    "chemistry": str(r.get("chemistry") or "").strip(),
                    "format": str(r.get("format") or "").strip(),
                }
        return meta, sorted(meta.keys()), None
    except Exception as exc:
        return {}, [], f"{type(exc).__name__}: {exc}"


def _process_eff_editor_df(xlsx_path: str) -> pd.DataFrame:
    sheets = pd.read_excel(str(xlsx_path), sheet_name=None)
    frames = []
    for _, df in sheets.items():
        if df is None or df.empty:
            continue
        tmp = df.copy()
        tmp.columns = [str(c).strip() for c in tmp.columns]
        frames.append(tmp)
    if not frames:
        return pd.DataFrame(columns=["Step", "Type", "Key", "Value", "default_stream", "loss_sink"])

    out = pd.concat(frames, ignore_index=True)
    required = ["Step", "Type", "Key", "Value", "default_stream", "loss_sink"]
    for col in required:
        if col not in out.columns:
            out[col] = "" if col != "Value" else 0.0
    out = out[required].copy()
    out["Value"] = pd.to_numeric(out["Value"], errors="coerce").fillna(0.0)
    out.insert(0, "__row_id", range(len(out)))
    out.insert(1, "Area", out["Step"].map(process_eff_area))
    return out


def _write_custom_eff_workbook(edit_df: pd.DataFrame, source_path: str) -> str:
    required = ["Step", "Type", "Key", "Value", "default_stream", "loss_sink"]
    out = edit_df.copy()
    for col in required:
        if col not in out.columns:
            out[col] = "" if col != "Value" else 0.0
    out = out[required].copy()
    out["Value"] = pd.to_numeric(out["Value"], errors="coerce").fillna(0.0)

    payload = (
        str(Path(source_path).resolve())
        + "|"
        + out.to_csv(index=False)
    ).encode("utf-8", errors="ignore")
    target = _custom_workbook_path("custom_eff", payload)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="Custom", index=False)
    return str(target)


_MACHINE_EDITOR_EDITABLE: tuple[str, ...] = (
    "invest_cost",
    "lifetime_y",
    "capacity",
    "labor_person_h_per_day",
    "area_per_machine_m2",
    "electrical_power_design_kW",
    "scale_exponent",
    "install_factor",
    "instr_factor",
    "piping_factor",
    "electr_factor",
    "maint_pct_installed",
    "supplies_pct_of_maint",
)

_MACHINE_EDITOR_COLUMN_LABELS: dict[str, str] = {
    "name": "Machine",
    "capacity_unit": "Capacity unit",
    "invest_cost": "Invest cost ($)",
    "lifetime_y": "Lifetime (y)",
    "capacity": "Design capacity",
    "labor_person_h_per_day": "Labor (person h/day)",
    "area_per_machine_m2": "Area per machine (m²)",
    "electrical_power_design_kW": "Electrical power (kW)",
    "scale_exponent": "Scale exponent",
    "install_factor": "Install factor",
    "instr_factor": "Instr. factor",
    "piping_factor": "Piping factor",
    "electr_factor": "Electrical factor",
    "maint_pct_installed": "Maint. % installed (/y)",
    "supplies_pct_of_maint": "Supplies % of maint.",
}


def _machine_editor_raw_df(xlsx_path: str) -> pd.DataFrame:
    raw = pd.read_excel(str(xlsx_path), sheet_name="Machines")
    raw.columns = [str(c).strip() for c in raw.columns]
    return raw


def _machine_editor_view_df(raw: pd.DataFrame) -> pd.DataFrame:
    display_cols = ["name", "capacity_unit"] + [
        c for c in _MACHINE_EDITOR_EDITABLE if c in raw.columns
    ]
    out = raw[display_cols].copy()
    for col in _MACHINE_EDITOR_EDITABLE:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _apply_stored_machine_values(view_df: pd.DataFrame, stored: dict) -> pd.DataFrame:
    out = view_df.copy()
    for idx, row in out.iterrows():
        name = str(row.get("name", "")).strip()
        overrides = stored.get(name)
        if not isinstance(overrides, dict):
            continue
        for col in _MACHINE_EDITOR_EDITABLE:
            if col in overrides and col in out.columns:
                out.at[idx, col] = _safe_float(overrides[col], _safe_float(row.get(col), 0.0))
    return out


def _machine_editor_column_config() -> dict:
    cfg: dict = {}
    for col, label in _MACHINE_EDITOR_COLUMN_LABELS.items():
        if col in ("name", "capacity_unit"):
            cfg[col] = st.column_config.TextColumn(label, disabled=True)
        elif col in _MACHINE_EDITOR_EDITABLE:
            cfg[col] = st.column_config.NumberColumn(label, format="%.6g")
    return cfg


def _machine_baseline_lookup(xlsx_path: str) -> dict[str, dict[str, float | str]]:
    raw = _machine_editor_raw_df(xlsx_path)
    return {
        str(r.get("name", "")).strip(): {
            "invest_cost": _safe_float(r.get("invest_cost"), 0.0),
            "capex_ref_date": str(r.get("capex_ref_date", "")).strip(),
        }
        for _, r in raw.iterrows()
        if str(r.get("name", "")).strip()
    }


def _invest_cost_changed(new_value: float, baseline_value: float) -> bool:
    return abs(float(new_value) - float(baseline_value)) > max(abs(baseline_value), 1.0) * 1e-9


def _write_custom_machines_workbook(
    edit_view_df: pd.DataFrame,
    source_path: str,
    baseline: dict[str, dict[str, float | str]] | None = None,
) -> str:
    sheets = pd.read_excel(str(source_path), sheet_name=None)
    if "Machines" not in sheets:
        raise KeyError("Machines sheet missing from workbook.")

    raw = sheets["Machines"].copy()
    raw.columns = [str(c).strip() for c in raw.columns]
    updates = {
        str(r.get("name", "")).strip(): r
        for _, r in edit_view_df.iterrows()
        if str(r.get("name", "")).strip()
    }
    for idx, row in raw.iterrows():
        name = str(row.get("name", "")).strip()
        if name not in updates:
            continue
        upd = updates[name]
        for col in _MACHINE_EDITOR_EDITABLE:
            if col in raw.columns and col in upd.index:
                raw.at[idx, col] = upd[col]
        if "capex_ref_date" in raw.columns and "invest_cost" in raw.columns:
            base = (baseline or {}).get(name, {})
            new_invest = _safe_float(upd.get("invest_cost"), _safe_float(row.get("invest_cost"), 0.0))
            if _invest_cost_changed(new_invest, _safe_float(base.get("invest_cost"), new_invest)):
                raw.at[idx, "capex_ref_date"] = MACHINE_CAPEX_TARGET_DATE
            elif base.get("capex_ref_date"):
                raw.at[idx, "capex_ref_date"] = str(base["capex_ref_date"])

    sheets["Machines"] = raw
    payload = (
        str(Path(source_path).resolve())
        + "|"
        + edit_view_df.to_csv(index=False)
    ).encode("utf-8", errors="ignore")
    target = _custom_workbook_path("custom_machines", payload)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return str(target)


def _normalize_shares(feed_rows: list[dict]) -> list[dict]:
    cleaned = []
    for r in feed_rows:
        if not isinstance(r, dict):
            continue
        cell_id = str(r.get("cell_id") or "").strip()
        level = str(r.get("level") or "").strip().lower()
        share = _safe_float(r.get("share"), 0.0)
        if not cell_id:
            continue
        if level not in {"pack", "module", "cell"}:
            continue
        if share < 0:
            share = 0.0
        cleaned.append({"cell_id": cell_id, "level": level, "share": share})

    s = sum(x["share"] for x in cleaned)
    if s <= 0:
        n = len(cleaned)
        if n == 0:
            return []
        for x in cleaned:
            x["share"] = 1.0 / n
        return cleaned

    for x in cleaned:
        x["share"] = x["share"] / s
    return cleaned


def _extract_econ(extras_all: dict) -> dict:
    oh = extras_all.get("Overhead", {}) if isinstance(extras_all, dict) else {}
    summary_df = _safe_df(oh.get("summary"))
    capex_df = _safe_df(oh.get("capex"))
    manuf_df = _safe_df(oh.get("manufacturing"))
    opex = oh.get("opex", {}) if isinstance(oh.get("opex", {}), dict) else {}
    revenue = oh.get("revenue", {}) if isinstance(oh.get("revenue", {}), dict) else {}
    profit = oh.get("profit", {}) if isinstance(oh.get("profit", {}), dict) else {}
    environmental = oh.get("environmental", {}) if isinstance(oh.get("environmental", {}), dict) else {}

    opex_step_df = pd.DataFrame(opex.get("step_totals", []) or [])
    opex_material_df = pd.DataFrame(opex.get("material_cost_by_step_item", []) or [])
    revenue_item_df = pd.DataFrame(revenue.get("by_step_item", []) or [])
    profit_summary = profit.get("summary", {}) if isinstance(profit.get("summary", {}), dict) else {}
    burdens = environmental.get("burdens", {}) if isinstance(environmental.get("burdens", {}), dict) else {}
    credits = environmental.get("credits", {}) if isinstance(environmental.get("credits", {}), dict) else {}
    net_gwp = environmental.get("net_gwp", {}) if isinstance(environmental.get("net_gwp", {}), dict) else {}
    burdens_step_df = pd.DataFrame(burdens.get("step_totals", []) or [])
    burdens_material_df = pd.DataFrame(burdens.get("material_emission_by_step_item", []) or [])
    credits_step_df = pd.DataFrame(credits.get("step_totals", []) or [])
    credits_item_df = pd.DataFrame(credits.get("by_step_item", []) or [])
    net_gwp_summary = net_gwp.get("summary", {}) if isinstance(net_gwp.get("summary", {}), dict) else {}

    return {
        "summary_df": summary_df,
        "capex_df": capex_df,
        "manuf_df": manuf_df,
        "opex_step_df": opex_step_df,
        "opex_material_df": opex_material_df,
        "revenue_item_df": revenue_item_df,
        "profit_summary": profit_summary,
        "revenue_raw": revenue,
        "credits_raw": credits,
        "burdens_step_df": burdens_step_df,
        "burdens_material_df": burdens_material_df,
        "credits_step_df": credits_step_df,
        "credits_item_df": credits_item_df,
        "net_gwp_summary": net_gwp_summary,
    }


def _transport_step_cost_y(econ: dict, ctx: dict) -> float:
    infra = ctx.get("infrastructure", {}) if isinstance(ctx.get("infrastructure"), dict) else {}
    transport_y = _safe_float(infra.get("transport_cost_per_y"), 0.0)
    if transport_y > 0.0:
        return transport_y
    opex_step_df = _safe_df(econ.get("opex_step_df"))
    if opex_step_df.empty or "step_name" not in opex_step_df.columns:
        return 0.0
    mask = opex_step_df["step_name"].astype(str) == TRANSPORT_STEP_NAME
    if not mask.any():
        return 0.0
    return float(
        pd.to_numeric(opex_step_df.loc[mask, "cost_materials_per_y"], errors="coerce").fillna(0.0).sum()
    )


def _transport_step_gwp_y(econ: dict, ctx: dict) -> float:
    infra = ctx.get("infrastructure", {}) if isinstance(ctx.get("infrastructure"), dict) else {}
    transport_y = _safe_float(infra.get("transport_gwp_kgco2e_per_y"), 0.0)
    if transport_y > 0.0:
        return transport_y
    burdens_step_df = _safe_df(econ.get("burdens_step_df"))
    if burdens_step_df.empty or "step_name" not in burdens_step_df.columns:
        return 0.0
    mask = burdens_step_df["step_name"].astype(str) == TRANSPORT_STEP_NAME
    if not mask.any():
        return 0.0
    return float(
        pd.to_numeric(
            burdens_step_df.loc[mask, "emission_direct_total_kgco2e_per_y"], errors="coerce"
        )
        .fillna(0.0)
        .sum()
    )


def _kpi_block(ctx: dict, econ: dict) -> dict:
    summary_df = econ["summary_df"]
    revenue_raw = econ["revenue_raw"]
    profit_summary = econ["profit_summary"]
    net_gwp_summary = econ["net_gwp_summary"]

    mass_y = _safe_float(ctx.get("feed_mass_kg_per_year"), 0.0)

    trc_y = 0.0
    if not summary_df.empty:
        r0 = summary_df.iloc[0].to_dict()
        trc_y = _safe_float(r0.get("TPC ($/y)", r0.get("total_product_costs_per_y", 0.0)), 0.0)

    rev_y = _safe_float(revenue_raw.get("net_output_value_total_per_y", 0.0), 0.0)
    profit_y = _safe_float(profit_summary.get("profit_per_y", 0.0), 0.0)
    gwp_burden_y = _safe_float(net_gwp_summary.get("direct_inputs_total_kgco2e_per_y", 0.0), 0.0) + _safe_float(
        net_gwp_summary.get("output_burdens_total_kgco2e_per_y", 0.0), 0.0
    )
    gwp_credit_y = _safe_float(net_gwp_summary.get("output_credits_total_kgco2e_per_y", 0.0), 0.0)
    cf_y = gwp_burden_y - gwp_credit_y
    transport_cost_y = _transport_step_cost_y(econ, ctx)
    transport_gwp_y = _transport_step_gwp_y(econ, ctx)

    return {
        "mass_y": mass_y,
        "trc_y": trc_y,
        "revenue_y": rev_y,
        "profit_y": profit_y,
        "gwp_burden_y": gwp_burden_y,
        "gwp_credit_y": gwp_credit_y,
        "cf_y": cf_y,
        "transport_cost_y": transport_cost_y,
        "transport_gwp_y": transport_gwp_y,
        "trc_kg": (trc_y / mass_y) if mass_y > 0 else 0.0,
        "revenue_kg": (rev_y / mass_y) if mass_y > 0 else 0.0,
        "profit_kg": (profit_y / mass_y) if mass_y > 0 else 0.0,
        "gwp_burden_kg": (gwp_burden_y / mass_y) if mass_y > 0 else 0.0,
        "gwp_credit_kg": (gwp_credit_y / mass_y) if mass_y > 0 else 0.0,
        "cf_kg": (cf_y / mass_y) if mass_y > 0 else 0.0,
        "transport_cost_kg": (transport_cost_y / mass_y) if mass_y > 0 else 0.0,
        "transport_gwp_kg": (transport_gwp_y / mass_y) if mass_y > 0 else 0.0,
    }


def _per_kg_feed(v_per_y: float, annual_feed_kg: float) -> float:
    return float(v_per_y) / float(annual_feed_kg) if annual_feed_kg > 0 else 0.0


def _fmt_metric(v: float, ndigits: int = 4) -> str:
    return f"{float(v):,.{int(ndigits)}f}"


def _fmt_recovery_pct(value: float | None, ndigits: int = 2) -> str:
    if value is None:
        return "n/a"
    return _fmt_metric(value, ndigits)


def _fmt_dashboard_num(v: float, ndigits: int = 2) -> str:
    return f"{float(v):,.{int(ndigits)}f}"


def _kg_h_to_t_h(kg_h: float) -> float:
    return float(kg_h) / 1000.0


def _kg_h_to_t_y(kg_h: float, hours_y: float) -> float:
    if hours_y <= 0.0:
        return 0.0
    return float(kg_h) * float(hours_y) / 1000.0


def _kwh_h_to_mw(kwh_h: float) -> float:
    return float(kwh_h) / 1000.0


def _hours_per_year(ctx: dict | None) -> float:
    h = _safe_float((ctx or {}).get("hours_per_year"), 8760.0)
    return h if h > 0.0 else 8760.0


def _rollup_recovery_category(recovery_df: pd.DataFrame, category: str) -> float | None:
    if recovery_df is None or recovery_df.empty or "Category" not in recovery_df.columns:
        return None
    sub = recovery_df[recovery_df["Category"].astype(str).str.lower() == str(category).lower()].copy()
    sub = sub[sub["Target"].astype(str) != "active"]
    if sub.empty:
        return None
    inp_y = float(pd.to_numeric(sub.get("Input mass (kg/y)", 0.0), errors="coerce").fillna(0.0).sum())
    rec_y = float(pd.to_numeric(sub.get("Recovered mass (kg/y)", 0.0), errors="coerce").fillna(0.0).sum())
    return _recovery_pct(rec_y, inp_y)


def _round_df_numeric(df: pd.DataFrame, ndigits: int = 2) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = pd.to_numeric(out[col], errors="coerce").round(ndigits)
    return out


_STEP_MASSFLOW_VALUE_COL_ORDER = [
    "Input (t/h)",
    "Input (t/y)",
    "Input (kg/h)",
    "Materials added (t/h)",
    "Materials added (t/y)",
    "Materials added (kg/h)",
    "Name Material added",
    "Main output (t/h)",
    "Output forwarded (t/h)",
    "Output forwarded (t/y)",
    "Output forwarded (kg/h)",
    "Main output stream",
    "Name Output forwarded ",
    "Output separated (t/h)",
    "Output separated (t/y)",
    "Output separated (kg/h)",
    "Name Output Separated",
]


def _order_massflow_detail_columns(df: pd.DataFrame, *, leading_cols: list[str] | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    leading = [c for c in (leading_cols or []) if c in df.columns]
    ordered = leading + [c for c in _STEP_MASSFLOW_VALUE_COL_ORDER if c in df.columns and c not in leading]
    extra = [c for c in df.columns if c not in ordered and c != "_step_context"]
    return df[ordered + extra]


def _format_massflow_detail_t_y(mf_long: pd.DataFrame, hours_y: float, route_key: str) -> pd.DataFrame:
    if mf_long is None or mf_long.empty:
        return mf_long
    mf_display = mf_long.copy()
    if "_step_context" in mf_display.columns:
        mf_display.insert(
            2,
            "Route section",
            mf_display["_step_context"].astype(str).map(lambda s: _process_stage(s, route_key)),
        )
    rate_cols = {
        "Input (kg/h)": "Input (t/y)",
        "Materials added (kg/h)": "Materials added (t/y)",
        "Output forwarded (kg/h)": "Output forwarded (t/y)",
        "Output separated (kg/h)": "Output separated (t/y)",
    }
    for src, dst in rate_cols.items():
        if src in mf_display.columns:
            mf_display[dst] = pd.to_numeric(mf_display[src], errors="coerce").fillna(0.0).map(
                lambda v: _kg_h_to_t_y(v, hours_y)
            )
    drop_cols = [c for c in rate_cols if c in mf_display.columns]
    mf_display = mf_display.drop(columns=drop_cols, errors="ignore")
    return _round_df_numeric(
        _order_massflow_detail_columns(
            mf_display,
            leading_cols=["Scenario", "Route section", "Step"],
        ),
        2,
    )


def _format_stage_items_t_y(stage_items_df: pd.DataFrame, hours_y: float) -> pd.DataFrame:
    if stage_items_df is None or stage_items_df.empty:
        return stage_items_df
    out = stage_items_df.copy()
    if "kg/h" in out.columns:
        out["t/y"] = pd.to_numeric(out["kg/h"], errors="coerce").fillna(0.0).map(lambda v: _kg_h_to_t_y(v, hours_y))
        out = out.drop(columns=["kg/h"])
    return _round_df_numeric(out, 2)


_RECOVERY_CATEGORY_LABELS = {
    "active": "active material",
    "component": "component material",
}


def _recovery_detail_by_material_df(recovery_df: pd.DataFrame) -> pd.DataFrame:
    if recovery_df is None or recovery_df.empty:
        return pd.DataFrame()
    detail = recovery_df[recovery_df["Target"].astype(str) != "active"].copy()
    if "Category" in detail.columns:
        detail["Category"] = (
            detail["Category"]
            .astype(str)
            .str.strip()
            .str.lower()
            .map(lambda c: _RECOVERY_CATEGORY_LABELS.get(c, c))
        )
    if "Input mass (kg/y)" in detail.columns:
        detail["Feed mass (t/y)"] = (
            pd.to_numeric(detail["Input mass (kg/y)"], errors="coerce").fillna(0.0) / 1000.0
        )
    if "Recovered mass (kg/y)" in detail.columns:
        detail["Recovered target material mass (t/y)"] = (
            pd.to_numeric(detail["Recovered mass (kg/y)"], errors="coerce").fillna(0.0) / 1000.0
        )
    detail = detail.drop(
        columns=[c for c in ("Input mass (kg/y)", "Recovered mass (kg/y)") if c in detail.columns],
        errors="ignore",
    )
    rename = {"Target": "Target material"}
    detail = detail.rename(columns={k: v for k, v in rename.items() if k in detail.columns})
    col_order = [
        "Target material",
        "Category",
        "Recovery (%)",
        "Products counted",
        "Feed mass (t/y)",
        "Recovered target material mass (t/y)",
    ]
    detail = detail[[c for c in col_order if c in detail.columns]]
    return _round_df_numeric(detail, 2)


def _render_mass_dashboard_recovery(libra: LibraRecoveryResult) -> None:
    st.markdown("**Recovery**")
    active_pct = libra.element_recovery.get("active")
    if active_pct is None and not libra.recovery_df.empty:
        active_rows = libra.recovery_df[libra.recovery_df["Target"].astype(str) == "active"]
        if not active_rows.empty:
            raw = active_rows.iloc[0].get("Recovery (%)")
            active_pct = None if pd.isna(raw) else float(raw)

    r1, r2 = st.columns(2)
    r1.metric("Component recovery (%)", _fmt_recovery_pct(_rollup_recovery_category(libra.recovery_df, "component")))
    r2.metric("Active material recovery (%)", _fmt_recovery_pct(active_pct))

    with st.expander("Detailed recovery by material", expanded=False):
        detail_df = _recovery_detail_by_material_df(libra.recovery_df)
        if detail_df.empty:
            st.caption("No recovery data.")
        else:
            st.dataframe(_clean_display_df(detail_df), width="stretch", hide_index=True)


_COMPONENT_RECOVERY_LABELS: dict[str, str] = {
    "Al": "Aluminium",
    "Cu": "Copper",
    "Iron": "Iron",
    "Steel": "Steel",
    "Electronics": "Electronics",
}

_ACTIVE_RECOVERY_DISPLAY_ORDER: tuple[str, ...] = ("Li", "Ni", "Mn", "Co", "Fe", "P", "Graphite")

_ACTIVE_RECOVERY_LABELS: dict[str, str] = {
    "Li": "Lithium",
    "Ni": "Nickel",
    "Mn": "Manganese",
    "Co": "Cobalt",
    "Fe": "Iron",
    "P": "Phosphor",
    "Graphite": "Graphite",
}

_RECOVERY_UI_FONT = (
    "Source Sans Pro, Source Sans, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"
)


def _render_libra_recovery(
    steps_df: pd.DataFrame,
    ctx: dict,
    econ: dict,
    *,
    libra: LibraRecoveryResult | None = None,
    show_product_table: bool = False,
) -> LibraRecoveryResult:
    """Recovery UI (same logic as Excel Recovery sheet via compute_libra_recovery)."""
    if libra is None:
        libra = compute_libra_recovery(ctx, steps_df, econ)

    st.markdown("**Recovery**")
    p1, p2 = st.columns(2)
    p1.metric("Overall Metal Recovery (%)", _fmt_recovery_pct(libra.overall_metal_recovery))
    active_val = libra.element_recovery.get("active")
    p2.metric("Active material recovery (%)", _fmt_recovery_pct(active_val))

    from recovery_config import active_targets_for_route, component_targets, resolve_recovery_route

    rec_rt = resolve_recovery_route(ctx)
    active_keys = [t for t in active_targets_for_route(rec_rt) if t != "Graphite"] + ["Graphite"]
    st.markdown(
        "<div style='font-size:0.8rem; color:#5f6c7b; font-weight:600; margin:10px 0 4px 0;'>"
        "Active materials</div>",
        unsafe_allow_html=True,
    )
    e_cols = st.columns(3)
    shown = 0
    for key in active_keys:
        val = libra.element_recovery.get(key)
        if not _recovery_target_visible(libra.recovery_df, key, val):
            continue
        e_cols[shown % 3].metric(f"{key} recovery (%)", _fmt_recovery_pct(val))
        shown += 1

    st.markdown(
        "<div style='font-size:0.8rem; color:#5f6c7b; font-weight:600; margin:10px 0 4px 0;'>"
        "Component materials</div>",
        unsafe_allow_html=True,
    )
    s_cols = st.columns(3)
    shown = 0
    for key in component_targets():
        label = _COMPONENT_RECOVERY_LABELS.get(key, key)
        val = libra.element_recovery.get(key)
        if not _recovery_target_visible(libra.recovery_df, key, val):
            continue
        s_cols[shown % 3].metric(f"{label} (%)", _fmt_recovery_pct(val))
        shown += 1

    st.markdown(
        "<div style='font-size:0.8rem; color:#5f6c7b; font-weight:600; margin:10px 0 4px 0;'>"
        "Recovery table</div>",
        unsafe_allow_html=True,
    )
    if libra.recovery_df.empty:
        st.caption("No recovery data.")
    else:
        st.dataframe(_clean_display_df(libra.recovery_df), width="stretch", hide_index=True)

    if show_product_table:
        podf = libra.product_output_df.copy() if libra.product_output_df is not None else pd.DataFrame()
        with st.expander("Product output (saleable products)", expanded=False):
            if podf.empty:
                st.caption("No product output lines.")
            else:
                st.dataframe(_clean_display_df(podf), width="stretch", hide_index=True)

    return libra


def _recovery_target_visible(recovery_df: pd.DataFrame, target: str, pct: float | None) -> bool:
    if pct is not None:
        return True
    if recovery_df is None or recovery_df.empty:
        return False
    sub = recovery_df[recovery_df["Target"].astype(str) == target]
    if sub.empty:
        return False
    return float(sub.iloc[0].get("Input mass (kg/y)", 0.0) or 0.0) > 0.0


_UNIT_PER_KG_FEED_PROCESSED = "/kg feed processed"


def _recovery_ring_svg_html(
    label: str,
    pct: float | None,
    *,
    color: str = BRAND_BLUE,
    size: int = 108,
) -> str:
    """Donut ring: filled arc = recovery %, value centered."""
    cx = cy = size / 2
    r = size * (40 / 108)
    stroke = max(8.0, size * (9 / 108))
    font_size = max(14.0, size * (15 / 108))
    label_font = f"{0.78 + (size - 108) * 0.002:.2f}rem"
    label_max = int(size + 20)
    circumference = 2 * 3.14159265 * r
    label_esc = html_module.escape(label)
    if pct is None:
        display = "n/a"
        fill_pct = 0.0
        arc_color = "#c5cdd8"
    else:
        fill_pct = min(100.0, max(0.0, float(pct)))
        display = f"{_fmt_recovery_pct(fill_pct, 1 if fill_pct >= 10 else 2)}%"
        arc_color = color
    dash_offset = circumference * (1.0 - fill_pct / 100.0)
    return (
        f'<div style="display:flex;flex-direction:column;align-items:center;width:100%;max-width:{label_max}px;'
        f'margin:0 auto;padding:4px 6px 10px 6px;box-sizing:border-box;">'
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" aria-label="{label_esc}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e8ecf1" stroke-width="{stroke}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{arc_color}" stroke-width="{stroke}" '
        f'stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{dash_offset:.2f}" '
        f'stroke-linecap="round" transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy + font_size * 0.35}" text-anchor="middle" font-size="{font_size:.1f}" '
        f'font-weight="700" font-family="{_RECOVERY_UI_FONT}" fill="#003B75">{display}</text>'
        f"</svg>"
        f'<div style="font-family:{_RECOVERY_UI_FONT};font-size:{label_font};color:#5f6c7b;font-weight:600;'
        f'text-align:center;line-height:1.25;max-width:{label_max}px;">'
        f"{label_esc}</div></div>"
    )


def _recovery_rings_row_html(
    items: list[tuple[str, float | None]],
    *,
    ring_size: int = 108,
    full_width: bool = False,
) -> str:
    if not items:
        return ""
    rings = "".join(_recovery_ring_svg_html(label, pct, size=ring_size) for label, pct in items)
    if full_width:
        cols = len(items)
        return (
            f'<div style="display:grid;grid-template-columns:repeat({cols},minmax(0,1fr));'
            f'width:100%;gap:10px 16px;align-items:start;margin:0 0 6px 0;">{rings}</div>'
        )
    return (
        f'<div style="display:flex;flex-wrap:wrap;justify-content:flex-start;margin:0;">{rings}</div>'
    )


def _overview_recovery_summary_items(libra: LibraRecoveryResult) -> list[tuple[str, float | None, str]]:
    return [
        (
            "Overall metal recovery",
            libra.overall_metal_recovery,
            "Weighted recovery of battery metals (Li, Ni, Co, Mn, Fe, Cu, Al) in saleable products.",
        ),
        (
            "Active material recovery",
            libra.element_recovery.get("active"),
            "Roll-up recovery of cathode and anode active materials in the cell.",
        ),
        (
            "Component recovery",
            _rollup_recovery_category(libra.recovery_df, "component"),
            "Roll-up recovery of structural component materials (Al, Cu, iron, steel, electronics).",
        ),
    ]


def _overview_recovery_summary_card_html(label: str, pct: float | None, tooltip: str = "") -> str:
    label_esc = html_module.escape(label)
    tip_attr = f' title="{html_module.escape(tooltip)}"' if tooltip else ""
    if pct is None:
        display = "n/a"
        color = "#5f6c7b"
    else:
        display = f"{_fmt_recovery_pct(pct, 1 if float(pct) >= 10 else 2)}%"
        color = BRAND_BLUE
    return f"""
    <div{tip_attr} style="border:1px solid {OVERVIEW_CARD_BORDER};border-radius:10px;padding:12px 10px;margin:0 0 10px 0;
        background:#fafbfd;text-align:center;cursor:help;">
        <div style="font-family:{_RECOVERY_UI_FONT};font-size:1.75rem;color:{color};
            font-weight:700;line-height:1.1;">{display}</div>
        <div style="font-family:{_RECOVERY_UI_FONT};font-size:0.88rem;color:{OVERVIEW_LABEL_GRAY};
            font-weight:600;line-height:1.25;margin-top:6px;">{label_esc}</div>
    </div>
    """


def _render_overview_recovery_summary_column(items: list[tuple[str, float | None, str]]) -> None:
    if not items:
        return
    _overview_section_heading("Recovery")
    for label, pct, help_text in items:
        st.markdown(_overview_recovery_summary_card_html(label, pct, help_text), unsafe_allow_html=True)


def _render_recovery_rings_grid(
    items: list[tuple[str, float | None]],
    *,
    section_title: str | None = None,
    ring_size: int = 108,
    full_width: bool = False,
) -> None:
    if not items:
        return
    title_html = ""
    if section_title:
        title_esc = html_module.escape(section_title)
        title_html = (
            f'<div style="font-family:{_RECOVERY_UI_FONT};font-size:0.9rem;color:#5f6c7b;'
            f'font-weight:600;margin:14px 0 8px 0;">{title_esc}</div>'
        )
    row_html = _recovery_rings_row_html(items, ring_size=ring_size, full_width=full_width)
    if full_width:
        row_height = ring_size + 52
        iframe_height = row_height + (34 if section_title else 8)
    else:
        rows = max(1, (len(items) + 5) // 6)
        iframe_height = rows * (ring_size + 42) + (28 if section_title else 12)
    components.html(
        f'<div style="font-family:{_RECOVERY_UI_FONT};margin:0;width:100%;">{title_html}{row_html}</div>',
        height=iframe_height,
        scrolling=False,
    )


def _libra_recovery_detail_sections(
    libra: LibraRecoveryResult,
    ctx: dict,
) -> list[tuple[str, float | None, list[tuple[str, float | None]]]]:
    from recovery_config import active_targets_for_route, component_targets, resolve_recovery_route

    rec_rt = resolve_recovery_route(ctx)
    route_active_keys = set(active_targets_for_route(rec_rt))
    active_items: list[tuple[str, float | None]] = []
    for key in _ACTIVE_RECOVERY_DISPLAY_ORDER:
        if key not in route_active_keys:
            continue
        val = libra.element_recovery.get(key)
        if not _recovery_target_visible(libra.recovery_df, key, val):
            continue
        label = _ACTIVE_RECOVERY_LABELS.get(key, key)
        active_items.append((label, val))

    component_items: list[tuple[str, float | None]] = []
    for key in component_targets():
        label = _COMPONENT_RECOVERY_LABELS.get(key, key)
        val = libra.element_recovery.get(key)
        if not _recovery_target_visible(libra.recovery_df, key, val):
            continue
        component_items.append((label, val))

    active_rollup = libra.element_recovery.get("active")
    component_rollup = _rollup_recovery_category(libra.recovery_df, "component")
    if component_rollup is None:
        component_rollup = libra.element_recovery.get("component")

    return [
        ("Active materials", active_rollup, active_items),
        ("Component materials", component_rollup, component_items),
    ]


def _recovery_performance_bar_rows_html(
    items: list[tuple[str, float | None]],
    *,
    bar_width_pct: float = 0.6,
) -> str:
    if not items:
        return (
            f'<div style="font-family:{_RECOVERY_UI_FONT};font-size:0.88rem;color:#5f6c7b;'
            f'font-weight:600;">No recovery data.</div>'
        )
    rows: list[str] = []
    for label, pct in items:
        label_esc = html_module.escape(str(label))
        if pct is None:
            display = "n/a"
            fill_pct = 0.0
            bar_html = (
                f'<div style="height:18px;background:#e8ecf1;border-radius:3px;overflow:hidden;'
                f'display:flex;align-items:center;justify-content:center;padding:0 8px;box-sizing:border-box;">'
                f'<span style="font-family:{_RECOVERY_UI_FONT};font-size:0.78rem;font-weight:600;'
                f'color:#5f6c7b;line-height:1;">{display}</span>'
                f"</div>"
            )
        else:
            fill_pct = min(100.0, max(0.0, float(pct)))
            display = f"{_fmt_recovery_pct(fill_pct, 1 if fill_pct >= 10 else 2)}%"
            bar_html = (
                f'<div style="height:18px;background:#e8ecf1;border-radius:3px;overflow:hidden;position:relative;">'
                f'<div style="height:100%;width:{fill_pct:.2f}%;background:{BRAND_BLUE};border-radius:3px;"></div>'
                f'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
                f'pointer-events:none;">'
                f'<span style="font-family:{_RECOVERY_UI_FONT};font-size:0.78rem;font-weight:600;'
                f'color:#ffffff;line-height:1;white-space:nowrap;">{display}</span>'
                f"</div></div>"
            )
        rows.append(
            f'<div style="display:grid;grid-template-columns:minmax(72px,108px) minmax(0,1fr);'
            f'gap:10px;align-items:center;margin:0 0 10px 0;">'
            f'<div style="font-family:{_RECOVERY_UI_FONT};font-size:0.92rem;font-weight:600;color:#1f2937;">'
            f"{label_esc}</div>"
            f'<div style="width:{bar_width_pct * 100:.0f}%;max-width:{bar_width_pct * 100:.0f}%;">'
            f"{bar_html}</div>"
            f"</div>"
        )
    return "".join(rows)


_RECOVERY_PERF_BAR_ROW_PX = 28  # 18px bar + 10px row gap
_RECOVERY_PERF_BARS_TOP_PX = 4
_RECOVERY_PERF_RING_SIZE = 162


def _recovery_performance_ring_center_y(*, ring_size: int = _RECOVERY_PERF_RING_SIZE) -> float:
    return 4.0 + ring_size / 2.0


def _recovery_performance_bars_block_height(item_count: int) -> int:
    return max(0, item_count) * _RECOVERY_PERF_BAR_ROW_PX


def _recovery_performance_bars_padding_top(
    item_count: int,
    *,
    reference_item_count: int | None = None,
    ring_size: int = _RECOVERY_PERF_RING_SIZE,
) -> int:
    """Match the left card's circle-to-list vertical relationship on shorter lists."""
    if item_count <= 0:
        return _RECOVERY_PERF_BARS_TOP_PX
    if reference_item_count is None or reference_item_count <= 0:
        return _RECOVERY_PERF_BARS_TOP_PX

    ring_center = _recovery_performance_ring_center_y(ring_size=ring_size)
    ref_top = float(_RECOVERY_PERF_BARS_TOP_PX)
    ref_height = float(_recovery_performance_bars_block_height(reference_item_count))
    block_height = float(_recovery_performance_bars_block_height(item_count))
    if ref_height <= 0.0 or block_height <= 0.0:
        return _RECOVERY_PERF_BARS_TOP_PX

    center_ratio = (ring_center - ref_top) / ref_height
    padding = ring_center - center_ratio * block_height
    return max(_RECOVERY_PERF_BARS_TOP_PX, int(round(padding)))


def _recovery_performance_panel_html(
    section_title: str,
    rollup_pct: float | None,
    rollup_ring_label: str,
    items: list[tuple[str, float | None]],
    *,
    ring_size: int = _RECOVERY_PERF_RING_SIZE,
    bars_padding_top: int = _RECOVERY_PERF_BARS_TOP_PX,
) -> str:
    title_esc = html_module.escape(section_title)
    ring_html = _recovery_ring_svg_html(rollup_ring_label, rollup_pct, size=ring_size)
    bars_html = _recovery_performance_bar_rows_html(items)
    return (
        f'<div style="font-family:{_RECOVERY_UI_FONT};border:1px solid {OVERVIEW_CARD_BORDER};'
        f'border-radius:10px;padding:16px 1cm 12px 16px;background:#fafbfd;box-sizing:border-box;'
        f'height:100%;display:flex;flex-direction:column;align-self:stretch;">'
        f'<div style="font-size:0.95rem;font-weight:600;color:#1f2937;margin:0 0 14px 0;">{title_esc}</div>'
        f'<div style="display:grid;grid-template-columns:minmax({ring_size}px,48%) minmax(0,1fr);'
        f'gap:8px;align-items:flex-start;width:100%;flex:1 1 auto;">'
        f'<div style="min-width:0;align-self:start;">{ring_html}</div>'
        f'<div style="min-width:0;padding-top:{bars_padding_top}px;align-self:start;">{bars_html}</div>'
        f"</div></div>"
    )


def _recovery_performance_dual_panel_html(
    panels: list[tuple],
) -> str:
    cells: list[str] = []
    for panel in panels:
        if len(panel) >= 5:
            title, rollup, ring_label, items, bars_padding_top = panel[:5]
        elif len(panel) == 4:
            title, rollup, ring_label, items = panel
            bars_padding_top = _RECOVERY_PERF_BARS_TOP_PX
        else:
            continue
        cells.append(
            _recovery_performance_panel_html(
                str(title),
                rollup,
                str(ring_label),
                items,
                bars_padding_top=int(bars_padding_top),
            )
        )
    return (
        f'<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));'
        f'gap:16px;align-items:stretch;width:100%;">'
        f'{"".join(cells)}</div>'
    )


def _render_recovery_performance(
    steps_df: pd.DataFrame,
    ctx: dict,
    econ: dict,
    *,
    libra: LibraRecoveryResult | None = None,
    heading: str = "Recovery Performance",
    section_heading=None,
) -> None:
    if libra is None:
        libra = compute_libra_recovery(ctx, steps_df, econ)

    sections = _libra_recovery_detail_sections(libra, ctx)
    if not any(items for _title, _rollup, items in sections if items):
        st.caption("No recovery data.")
        return

    render_heading = section_heading if section_heading is not None else _overview_section_heading
    render_heading(heading)
    section_map = {title: (rollup, items) for title, rollup, items in sections}
    ring_labels = {
        "Active materials": "Active material recovery",
        "Component materials": "Component recovery",
    }
    section_titles = ["Active materials", "Component materials"]
    active_items = section_map.get("Active materials", (None, []))[1]
    active_item_count = len(active_items)
    panels = [
        (
            title,
            section_map.get(title, (None, []))[0],
            ring_labels.get(title, title),
            section_map.get(title, (None, []))[1],
            _recovery_performance_bars_padding_top(
                len(section_map.get(title, (None, []))[1]),
                reference_item_count=active_item_count if title == "Component materials" else None,
            ),
        )
        for title in section_titles
    ]
    st.markdown(_recovery_performance_dual_panel_html(panels), unsafe_allow_html=True)


def _render_overview_recovery(
    steps_df: pd.DataFrame,
    ctx: dict,
    econ: dict,
    *,
    libra: LibraRecoveryResult | None = None,
    heading: str = "Recovery Details",
) -> None:
    """Overview recovery: full-width detail rings (active + component; no table / product output)."""
    if libra is None:
        libra = compute_libra_recovery(ctx, steps_df, econ)
    ring_size = 148

    sections = _libra_recovery_detail_sections(libra, ctx)
    ring_layout: list[tuple[str | None, list[tuple[str, float | None]]]] = []
    for title, _rollup, items in sections:
        if not items:
            continue
        ring_layout.append((title, [(f"{label} recovery", pct) for label, pct in items]))
    sections = ring_layout
    if not any(items for _, items in sections):
        st.caption("No recovery data.")
        return

    _overview_section_heading(heading)

    row_height = ring_size + 52
    title_extra = 34
    iframe_height = 12
    body_parts: list[str] = []
    for title, items in sections:
        if not items:
            continue
        if title:
            title_esc = html_module.escape(title)
            body_parts.append(
                f'<div style="font-family:{_RECOVERY_UI_FONT};font-size:0.9rem;color:#5f6c7b;'
                f'font-weight:600;margin:14px 0 8px 0;">{title_esc}</div>'
            )
            iframe_height += title_extra
        body_parts.append(_recovery_rings_row_html(items, ring_size=ring_size, full_width=True))
        iframe_height += row_height + 6

    if not body_parts:
        st.caption("No recovery data.")
        return

    components.html(
        f'<div style="font-family:{_RECOVERY_UI_FONT};margin:0;width:100%;">{"".join(body_parts)}</div>',
        height=iframe_height,
        scrolling=False,
    )


_OVERVIEW_STAGE_SHORT = {
    "Front-End Processing": "Front-End",
    "Mechanical Processing": "Mechanical",
    "Hydrometallurgical Processing": "Hydro",
    "Front-end processing": "Front-End",
    "Mechanical treatment": "Mechanical",
    "Pyro treatment": "Mechanical",
    "Hydrometallurgy": "Hydro",
    "Other processing": "Hydro",
}

_OVERVIEW_STAGE_SECTIONS = [
    ("Hydro", "Hydrometallurgical Products"),
    ("Mechanical", "Mechanical Products"),
    ("Front-End", "Front-End Products"),
]


def _overview_stage_short(stage_long: str) -> str:
    stage = _OVERVIEW_STAGE_SHORT.get(str(stage_long), str(stage_long))
    if stage in {"Hydro", "Mechanical", "Front-End"}:
        return stage
    return "Hydro"


def _product_stage_map_from_output_lines(econ: dict, route_key: str) -> dict[str, str]:
    """Map product → stage from revenue output lines (category == product), by largest mass."""
    lines = _product_output_lines_df(econ)
    if lines.empty:
        return {}
    lines = lines.copy()
    lines["stage_short"] = lines["step_name"].astype(str).map(
        lambda s: _overview_stage_short(_process_stage(s, route_key))
    )
    top = (
        lines.sort_values("qty_kg_y", ascending=False)
        .groupby("item", as_index=False)
        .first()[["item", "stage_short"]]
    )
    return dict(zip(top["item"].astype(str), top["stage_short"].astype(str)))


_OVERVIEW_REVENUE_STAGE_LONG_MAP = {
    "Front-end processing": "Front-End Processing",
    "Mechanical treatment": "Mechanical Processing",
    "Pyro treatment": "Mechanical Processing",
    "Hydrometallurgy": "Hydrometallurgical Processing",
    "Other processing": "Hydrometallurgical Processing",
}


def _overview_revenue_lines_df(econ: dict, route_key: str) -> pd.DataFrame:
    """Output lines with positive revenue and quantity, plus overview stage_short."""
    out_df = _build_output_value_emission_df(econ)
    if out_df.empty:
        return pd.DataFrame()
    rev_df = out_df.copy()
    rev_df["revenue_per_y"] = pd.to_numeric(rev_df.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
    rev_df["Quantity"] = pd.to_numeric(rev_df.get("Quantity", 0.0), errors="coerce").fillna(0.0)
    rev_df = rev_df[(rev_df["revenue_per_y"] > 0) & (rev_df["Quantity"] > 0)].copy()
    if rev_df.empty:
        return pd.DataFrame()
    rev_df["stage_long"] = rev_df["step_name"].astype(str).map(lambda s: _process_stage(s, route_key))
    rev_df["stage"] = rev_df["stage_long"].map(
        lambda x: _OVERVIEW_REVENUE_STAGE_LONG_MAP.get(str(x), "Hydrometallurgical Processing")
    )
    rev_df["stage_short"] = rev_df["stage"].map(_overview_stage_short)
    return rev_df


def _overview_mass_by_stage_item(econ: dict, route_key: str) -> pd.DataFrame:
    """Saleable product mass (kg/y) per overview stage and item."""
    lines = _product_output_lines_df(econ)
    if lines.empty:
        return pd.DataFrame(columns=["stage_short", "item", "mass_kg_y"])
    lines = lines.copy()
    lines["stage_short"] = lines["step_name"].astype(str).map(
        lambda s: _overview_stage_short(_process_stage(s, route_key))
    )
    return (
        lines.groupby(["stage_short", "item"], as_index=False)["qty_kg_y"]
        .sum()
        .rename(columns={"qty_kg_y": "mass_kg_y"})
    )


def _overview_output_products_df(econ: dict, annual_feed_kg: float) -> pd.DataFrame:
    out_df = _build_output_value_emission_df(econ)
    if out_df.empty:
        return pd.DataFrame(columns=["Product", "Output (kg/kg feed)", "Revenue share (%)", "_revenue"])

    df = out_df.copy()
    if "Quantity unit" in df.columns:
        df = df[df["Quantity unit"].astype(str).str.lower().str.strip() == "kg/y"]
    df["Quantity"] = pd.to_numeric(df.get("Quantity", 0.0), errors="coerce").fillna(0.0)
    df["revenue_per_y"] = pd.to_numeric(df.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
    if "category" in df.columns:
        df = df[df["category"].astype(str).str.lower().str.strip() == "product"]

    grp = (
        df.groupby("item", as_index=False)
        .agg({"Quantity": "sum", "revenue_per_y": "sum"})
        .rename(columns={"item": "Product"})
    )
    grp = grp[grp["Quantity"] > 0.0].copy()
    if grp.empty:
        return pd.DataFrame(columns=["Product", "Output (kg/kg feed)", "Revenue share (%)", "_revenue"])

    total_revenue = float(grp.loc[grp["revenue_per_y"] > 0.0, "revenue_per_y"].sum())
    grp["_revenue"] = grp["revenue_per_y"].clip(lower=0.0)
    grp["Output (kg/kg feed)"] = grp["Quantity"].apply(lambda v: _per_kg_feed(v, annual_feed_kg))
    grp["Revenue share (%)"] = grp["_revenue"].apply(lambda v: (100.0 * v / total_revenue) if total_revenue > 0 else 0.0)
    grp = grp.sort_values("_revenue", ascending=False)
    return grp[["Product", "Output (kg/kg feed)", "Revenue share (%)", "_revenue"]].reset_index(drop=True)


def _overview_products_grouped_by_stage(
    econ: dict,
    annual_feed_kg: float,
    route_key: str,
    *,
    ctx: dict | None = None,
    steps_df: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Group revenue-bearing outputs by stage (same rows as the Revenue sunburst)."""
    del ctx, steps_df  # kept for call-site compatibility
    empty = {
        title: pd.DataFrame(columns=["Product", "Output (kg/kg feed)"])
        for _, title in _OVERVIEW_STAGE_SECTIONS
    }

    hierarchy = _build_overview_revenue_hierarchy(econ, route_key)
    if hierarchy is None:
        return empty

    mass_df = _overview_mass_by_stage_item(econ, route_key)
    mass_lookup = {
        (str(r["stage_short"]), str(r["item"])): float(r["mass_kg_y"])
        for _, r in mass_df.iterrows()
    }
    qty_lookup: dict[tuple[str, str], float] = {}
    rev_lines = _overview_revenue_lines_df(econ, route_key)
    if not rev_lines.empty:
        qty_grp = rev_lines.groupby(["stage_short", "item"], as_index=False)["Quantity"].sum()
        qty_lookup = {
            (str(r["stage_short"]), str(r["item"])): float(r["Quantity"])
            for _, r in qty_grp.iterrows()
        }

    rows: list[dict[str, object]] = []
    for entry in hierarchy["products"]:
        stage_short = str(entry["stage_short"])
        product = str(entry["product"])
        mass_kg_y = mass_lookup.get((stage_short, product))
        if mass_kg_y is None:
            mass_kg_y = qty_lookup.get((stage_short, product), 0.0)
        rows.append(
            {
                "stage_short": stage_short,
                "Product": product,
                "Output (kg/kg feed)": _per_kg_feed(float(mass_kg_y), annual_feed_kg),
            }
        )
    if not rows:
        return empty

    products = pd.DataFrame(rows)
    grouped: dict[str, pd.DataFrame] = {}
    for stage_key, section_title in _OVERVIEW_STAGE_SECTIONS:
        sub = products[products["stage_short"].astype(str) == stage_key].copy()
        sub = sub.sort_values("Output (kg/kg feed)", ascending=False)
        grouped[section_title] = sub[["Product", "Output (kg/kg feed)"]].reset_index(drop=True)
    return grouped


_OVERVIEW_REVENUE_RING_ORDER = ("Front-End", "Mechanical", "Hydro")
_OVERVIEW_REVENUE_LABEL_SHARE_PCT = 2.1
_OVERVIEW_OUTPUT_MASS_LABEL_SHARE_PCT = 2.0
_OVERVIEW_OUTPUT_MASS_SUNBURST_TEXT_SIZE = 14
_OVERVIEW_REVENUE_SMALL_STAGE_SHARE_PCT = 10.0
_OVERVIEW_REVENUE_SUNBURST_TEXT_SIZE = 14
_OVERVIEW_REVENUE_SUNBURST_TEXT_MIN = 12
_OVERVIEW_REVENUE_SUNBURST_CENTER_TEXT_SIZE = 14
_OVERVIEW_REVENUE_STAGE_DISPLAY: dict[str, str] = {
    "Hydro": "Hydro",
    "Mechanical": "Mechanical",
    "Front-End": "Front-End",
    "Residual treatment": "Residual treatment",
}
_OVERVIEW_REVENUE_STAGE_STYLE: dict[str, dict[str, object]] = {
    "Hydro": {
        "fill": BRAND_BLUE,
        "light": ("#003B75", "#1a528f", "#3369a9", "#4d80c3", "#6697dd", "#80aef0", "#a3c4f5"),
        "text_on_fill": "#ffffff",
        "text_on_light": "#ffffff",
    },
    "Mechanical": {
        "fill": "#C9A004",
        "light": ("#a68504", "#b89304", "#c9a004", "#d4ad1a", "#dfbc33", "#eacc5c", "#f0db85"),
        "text_on_fill": BRAND_BLUE,
        "text_on_light": BRAND_BLUE,
    },
    "Front-End": {
        "fill": "#6b7280",
        "light": ("#4b5563", "#6b7280", "#9ca3af", "#b0b7c3", "#c5cad3", "#d8dce3", "#eceef2"),
        "text_on_fill": "#ffffff",
        "text_on_light": "#374151",
    },
}
_OVERVIEW_PRODUCT_SHORT_LABELS: tuple[tuple[str, str], ...] = (
    ("nmc 532 precursor", "NMC 532"),
    ("532 precursor", "NMC 532"),
    ("wastewater treated", "Wastewater"),
    ("carbon coated iron phosphate", "FePO4-C"),
    ("lithium dihydrogenphosphate", "LiH2PO4"),
    ("lithium carbonate", "Li2CO3"),
    ("nickel sulfate", "NiSO4"),
    ("sodium sulfate", "Na2SO4"),
    ("calcium sulfate", "CaSO4"),
    ("cobalt sulfate", "CoSO4"),
    ("manganese sulfate", "MnSO4"),
    ("iron oxalate", "FeC2O4"),
    ("ferrous oxalate", "FeC2O4"),
    ("aluminium hydroxide", "Al(OH)3"),
    ("aluminum hydroxide", "Al(OH)3"),
    ("iron hydroxide", "Fe(OH)3"),
    ("electronic scrap", "Electr."),
    ("electronics", "Electr."),
    ("aluminium scrap", "Al"),
    ("aluminum scrap", "Al"),
    ("copper scrap", "Cu"),
    ("iron scrap", "Fe"),
    ("steel scrap", "Steel"),
    ("nmc precursor", "NMC-Prec."),
    ("nmc 811 precursor", "NMC-Prec."),
    ("graphite", "Graphite"),
    ("copper", "Cu"),
    ("steel", "Steel"),
)


def _fmt_revenue_y_hover(value_y: float) -> str:
    v = float(value_y)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f} M$"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f} k$"
    return f"{v:,.0f} $"


def _fmt_revenue_per_kg_tooltip(value_kg: float) -> str:
    return f"{float(value_kg):,.2f} $/kg feed"


def _overview_residual_ring_label(share_pct: float) -> str:
    return _overview_sunburst_label(f"Residual<br>{share_pct:.0f}%")


def _overview_revenue_stage_display(stage_short: str) -> str:
    return _OVERVIEW_REVENUE_STAGE_DISPLAY.get(str(stage_short), str(stage_short))


def _overview_revenue_bold_label(text: str) -> str:
    if not str(text).strip():
        return ""
    return "<br>".join(f"<b>{part}</b>" for part in str(text).split("<br>"))


def _overview_sunburst_label(text: str) -> str:
    """Plotly sunburst label: Unicode subscripts center more reliably than HTML <sub>."""
    if not str(text).strip():
        return ""
    return _overview_revenue_bold_label(format_chemistry_unicode(text))


def _add_sunburst_center_annotation(fig, center_label: str) -> None:
    """Render sunburst center text horizontally via layout annotation."""
    if not str(center_label).strip():
        return
    fig.add_annotation(
        text=center_label,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        xanchor="center",
        yanchor="middle",
        showarrow=False,
        align="center",
        font=dict(size=_OVERVIEW_REVENUE_SUNBURST_CENTER_TEXT_SIZE, color=BRAND_BLUE),
    )


def _overview_product_short_name(product: str) -> str:
    nl = str(product).strip().lower()
    for needle, short in _OVERVIEW_PRODUCT_SHORT_LABELS:
        if needle in nl:
            return short
    if len(product) <= 14:
        return str(product)
    return str(product)[:12] + "…"


def _is_output_wastewater_product(product: str) -> bool:
    nl = str(product).strip().lower()
    if "mother liquor" in nl:
        return False
    if nl in {"wastewater", "wastewater treated", "treated wastewater"}:
        return True
    return (
        "wastewater treated" in nl
        or "treated wastewater" in nl
        or "waste water" in nl
        or (nl.startswith("wastewater") and "mother liquor" not in nl)
    )


def _overview_output_mass_product_short_name(product: str) -> str:
    if _is_output_wastewater_product(product):
        return "Wastewater"
    nl = str(product).strip().lower()
    if "precursor" in nl and ("nmc" in nl or "532" in nl):
        return "NMC 532"
    return _overview_product_short_name(product)


def _overview_output_mass_product_label(product: str) -> str:
    return _overview_sunburst_label(_overview_output_mass_product_short_name(product))


def _overview_output_mass_show_product_label(product_share_pct: float) -> bool:
    return float(product_share_pct) >= _OVERVIEW_OUTPUT_MASS_LABEL_SHARE_PCT


def _overview_revenue_root_center_label(*, revenue_kg: float, title: str = "Revenue") -> str:
    return _overview_sunburst_label(f"{title}<br>{_fmt_metric(revenue_kg, 2)} $/kg feed")


def _overview_revenue_stage_ring_label(stage_display: str, share_pct: float) -> str:
    return _overview_sunburst_label(f"{stage_display}<br>{float(share_pct):.0f}%")


def _overview_revenue_show_product_label(
    product_share_pct: float,
    stage_share_pct: float,
) -> bool:
    """Show product labels from total share, within-stage share, or all in small stages."""
    if product_share_pct <= 0.0:
        return False
    if product_share_pct >= _OVERVIEW_REVENUE_LABEL_SHARE_PCT:
        return True
    if stage_share_pct <= 0.0:
        return False
    if stage_share_pct < _OVERVIEW_REVENUE_SMALL_STAGE_SHARE_PCT:
        return True
    within_stage_pct = 100.0 * product_share_pct / stage_share_pct
    return within_stage_pct >= _OVERVIEW_REVENUE_LABEL_SHARE_PCT


def _overview_revenue_stage_palette(stage_short: str, index: int) -> str:
    style = _OVERVIEW_REVENUE_STAGE_STYLE.get(stage_short, _OVERVIEW_REVENUE_STAGE_STYLE["Hydro"])
    shades = style["light"]
    return str(shades[index % len(shades)])


def _build_overview_revenue_hierarchy(econ: dict, route_key: str) -> dict | None:
    """Display-only aggregation: process group -> individual products."""
    rev_df = _overview_revenue_lines_df(econ, route_key)
    if rev_df.empty:
        return None

    by_stage_item = (
        rev_df.groupby(["stage_short", "item"], as_index=False)["revenue_per_y"]
        .sum()
        .sort_values(["stage_short", "revenue_per_y"], ascending=[True, False])
    )
    by_stage = by_stage_item.groupby("stage_short", as_index=False)["revenue_per_y"].sum()
    total_rev_y = float(by_stage["revenue_per_y"].sum())
    if total_rev_y <= 0:
        return None

    products: list[dict[str, object]] = []
    stages: list[dict[str, object]] = []
    for stage_short in _OVERVIEW_REVENUE_RING_ORDER:
        stage_rows = by_stage_item[by_stage_item["stage_short"].astype(str) == stage_short].copy()
        stage_rows = stage_rows.sort_values("revenue_per_y", ascending=False)
        if stage_rows.empty:
            continue
        stage_rev_y = float(stage_rows["revenue_per_y"].sum())
        stages.append(
            {
                "stage_short": stage_short,
                "revenue_y": stage_rev_y,
                "share_pct": 100.0 * stage_rev_y / total_rev_y,
            }
        )
        shade_idx = 0
        for _, pr in stage_rows.iterrows():
            p_name = str(pr["item"])
            p_rev_y = float(pr["revenue_per_y"])
            share_pct = 100.0 * p_rev_y / total_rev_y
            products.append(
                {
                    "stage_short": stage_short,
                    "product": p_name,
                    "revenue_y": p_rev_y,
                    "share_pct": share_pct,
                    "shade_idx": shade_idx,
                }
            )
            shade_idx += 1

    return {"total_rev_y": total_rev_y, "stages": stages, "products": products}


def _overview_residue_mass_lines_df(
    mf_long: pd.DataFrame,
    ctx: dict | None,
    route_key: str,
    hours_y: float,
) -> pd.DataFrame:
    sep = _separated_outputs_df(mf_long, ctx, route_key)
    if sep.empty:
        return pd.DataFrame(columns=["item", "mass_kg_y"])
    work = sep[sep["Category"].astype(str).str.lower() == "residue"].copy()
    if work.empty:
        return pd.DataFrame(columns=["item", "mass_kg_y"])
    grp = work.groupby("Name", as_index=False)["kg/h"].sum()
    grp["mass_kg_y"] = pd.to_numeric(grp["kg/h"], errors="coerce").fillna(0.0) * float(hours_y)
    return grp.rename(columns={"Name": "item"})[["item", "mass_kg_y"]]


def _build_overview_output_mass_hierarchy(
    econ: dict,
    route_key: str,
    ctx: dict | None,
    mf_long: pd.DataFrame,
    hours_y: float,
) -> dict | None:
    """Process group -> product/residue items; slice sizes from output mass (kg/y)."""
    mass_df = _overview_mass_by_stage_item(econ, route_key)
    if mass_df.empty:
        rev_df = _overview_revenue_lines_df(econ, route_key)
        if not rev_df.empty and "Quantity" in rev_df.columns:
            mass_df = (
                rev_df.groupby(["stage_short", "item"], as_index=False)["Quantity"]
                .sum()
                .rename(columns={"Quantity": "mass_kg_y"})
            )
    if mass_df.empty and _overview_residue_mass_lines_df(mf_long, ctx, route_key, hours_y).empty:
        return None

    by_stage_item = (
        mass_df.groupby(["stage_short", "item"], as_index=False)["mass_kg_y"]
        .sum()
        .sort_values(["stage_short", "mass_kg_y"], ascending=[True, False])
        if not mass_df.empty
        else pd.DataFrame(columns=["stage_short", "item", "mass_kg_y"])
    )

    stages: list[dict[str, object]] = []
    products: list[dict[str, object]] = []
    total_product_y = 0.0
    for stage_short in _OVERVIEW_REVENUE_RING_ORDER:
        stage_rows = by_stage_item[by_stage_item["stage_short"].astype(str) == stage_short].copy()
        if stage_rows.empty:
            continue
        stage_mass_y = float(stage_rows["mass_kg_y"].sum())
        total_product_y += stage_mass_y
        stages.append(
            {
                "stage_short": stage_short,
                "mass_y": stage_mass_y,
                "share_pct": 0.0,
            }
        )
        shade_idx = 0
        for _, pr in stage_rows.iterrows():
            p_mass_y = float(pr["mass_kg_y"])
            products.append(
                {
                    "stage_short": stage_short,
                    "product": str(pr["item"]),
                    "mass_y": p_mass_y,
                    "share_pct": 0.0,
                    "shade_idx": shade_idx,
                }
            )
            shade_idx += 1

    residue_df = _overview_residue_mass_lines_df(mf_long, ctx, route_key, hours_y)
    if not residue_df.empty:
        residue_df = residue_df.copy()
        residue_df["_display_item"] = residue_df["item"].astype(str).map(
            lambda name: "Wastewater" if _is_output_wastewater_product(name) else str(name).strip()
        )
        residue_df = (
            residue_df.groupby("_display_item", as_index=False)["mass_kg_y"]
            .sum()
            .rename(columns={"_display_item": "item"})
        )
    total_residual_y = float(residue_df["mass_kg_y"].sum()) if not residue_df.empty else 0.0
    total_y = total_product_y + total_residual_y
    if total_y <= 0:
        return None

    for stage in stages:
        stage["share_pct"] = 100.0 * float(stage["mass_y"]) / total_y
    for prod in products:
        prod["share_pct"] = 100.0 * float(prod["mass_y"]) / total_y

    if total_residual_y > 1e-12:
        stages.append(
            {
                "stage_short": _PROCESS_ECON_RESIDUAL_STAGE_SHORT,
                "mass_y": total_residual_y,
                "share_pct": 100.0 * total_residual_y / total_y,
                "is_residual": True,
            }
        )
        for shade_idx, (_, row) in enumerate(residue_df.iterrows()):
            val_y = float(row["mass_kg_y"])
            products.append(
                {
                    "stage_short": _PROCESS_ECON_RESIDUAL_STAGE_SHORT,
                    "product": str(row["item"]),
                    "mass_y": val_y,
                    "share_pct": 100.0 * val_y / total_y,
                    "shade_idx": shade_idx,
                    "is_residual": True,
                }
            )

    return {"total_mass_y": total_y, "stages": stages, "products": products}


def _overview_output_mass_hover_row(
    title: str,
    stage_display: str,
    *,
    mass_kg: float,
    mass_y: float,
    share_pct: float,
) -> tuple[str, str, str, str, str]:
    return (
        format_chemistry_unicode(title),
        stage_display,
        f"{_fmt_metric(mass_kg, 2)} kg/kg feed",
        f"{_fmt_metric(mass_y / 1000.0, 1)} t/y",
        f"{float(share_pct):.1f}%",
    )


def _overview_output_mass_sunburst_figure(
    hierarchy: dict,
    *,
    annual_feed_kg: float,
    total_mass_kg: float,
    total_mass_y: float,
    center_title: str = "Outputs",
    chart_height_px: int = OVERVIEW_REVENUE_SUNBURST_HEIGHT_PX,
) -> "go.Figure | None":
    """Sunburst: process groups (inner) -> products/residues (outer); slice sizes from mass share."""
    if go is None:
        return None

    total_mass_y_h = float(hierarchy["total_mass_y"])
    stages: list[dict[str, object]] = hierarchy["stages"]
    products: list[dict[str, object]] = hierarchy["products"]
    if total_mass_y_h <= 0 or not stages:
        return None

    root_id = "root"
    center_mass_kg = total_mass_kg if total_mass_kg > 0 else _per_kg_feed(total_mass_y_h, annual_feed_kg)
    center_mass_t_y = total_mass_y if total_mass_y > 0 else total_mass_y_h / 1000.0
    ids = [root_id]
    labels = [""]
    parents = [""]
    values = [100.0]
    colors = ["#ffffff"]
    text_colors = ["#ffffff"]
    hover_rows: list[tuple[str, str, str, str, str]] = [
        _overview_output_mass_hover_row(
            "Total outputs",
            "All",
            mass_kg=center_mass_kg,
            mass_y=center_mass_t_y * 1000.0,
            share_pct=100.0,
        )
    ]

    stage_share_by_short: dict[str, float] = {
        str(stage["stage_short"]): float(stage["share_pct"]) for stage in stages
    }

    for stage in stages:
        stage_short = str(stage["stage_short"])
        stage_display = _overview_revenue_stage_display(stage_short)
        stage_mass_y = float(stage["mass_y"])
        stage_share = float(stage["share_pct"])
        stage_mass_kg = _per_kg_feed(stage_mass_y, annual_feed_kg)
        stage_id = f"stage::{stage_short}"
        is_residual_stage = bool(stage.get("is_residual")) or stage_short == _PROCESS_ECON_RESIDUAL_STAGE_SHORT
        ids.append(stage_id)
        if is_residual_stage:
            stage_ring_label = _overview_residual_ring_label(stage_share)
        else:
            stage_ring_label = _overview_revenue_stage_ring_label(stage_display, stage_share)
        labels.append(
            stage_ring_label
            if is_residual_stage or stage_share >= _OVERVIEW_REVENUE_LABEL_SHARE_PCT
            else ""
        )
        parents.append(root_id)
        values.append(stage_share)
        if is_residual_stage:
            colors.append(_PROCESS_ECON_RESIDUAL_FILL)
            text_colors.append(_PROCESS_ECON_RESIDUAL_TEXT)
        else:
            style = _OVERVIEW_REVENUE_STAGE_STYLE.get(stage_short, _OVERVIEW_REVENUE_STAGE_STYLE["Hydro"])
            colors.append(str(style["fill"]))
            text_colors.append(str(style["text_on_fill"]))
        if is_residual_stage:
            hover_rows.append(
                (
                    "Residual",
                    "Residual",
                    f"{_fmt_metric(stage_mass_kg, 2)} kg/kg feed",
                    f"{_fmt_metric(stage_mass_y / 1000.0, 1)} t/y",
                    f"{stage_share:.1f}%",
                )
            )
        else:
            hover_rows.append(
                _overview_output_mass_hover_row(
                    stage_display,
                    stage_display,
                    mass_kg=stage_mass_kg,
                    mass_y=stage_mass_y,
                    share_pct=stage_share,
                )
            )

    for prod in products:
        stage_short = str(prod["stage_short"])
        stage_display = _overview_revenue_stage_display(stage_short)
        p_name = str(prod["product"])
        p_mass_y = float(prod["mass_y"])
        p_share = float(prod["share_pct"])
        p_mass_kg = _per_kg_feed(p_mass_y, annual_feed_kg)
        shade_idx = int(prod.get("shade_idx", 0))
        stage_id = f"stage::{stage_short}"
        p_id = f"prod::{stage_short}::{p_name}"
        is_residual = bool(prod.get("is_residual"))
        ids.append(p_id)
        stage_share = stage_share_by_short.get(stage_short, 0.0)
        product_ring_label = _overview_output_mass_product_label(p_name)
        labels.append(
            product_ring_label
            if _overview_output_mass_show_product_label(p_share)
            else ""
        )
        parents.append(stage_id)
        values.append(p_share)
        if is_residual:
            colors.append(_process_econ_residual_palette(shade_idx))
            text_colors.append(_PROCESS_ECON_RESIDUAL_TEXT)
        else:
            style = _OVERVIEW_REVENUE_STAGE_STYLE.get(stage_short, _OVERVIEW_REVENUE_STAGE_STYLE["Hydro"])
            colors.append(_overview_revenue_stage_palette(stage_short, shade_idx))
            text_colors.append(str(style["text_on_light"]))
        hover_rows.append(
            _overview_output_mass_hover_row(
                p_name,
                "Residual" if is_residual else stage_display,
                mass_kg=p_mass_kg,
                mass_y=p_mass_y,
                share_pct=p_share,
            )
        )

    text_sizes = [
        _OVERVIEW_REVENUE_SUNBURST_TEXT_SIZE
        if node_id == root_id or node_id.startswith("stage::")
        else _OVERVIEW_OUTPUT_MASS_SUNBURST_TEXT_SIZE
        for node_id in ids
    ]

    fig = go.Figure(
        go.Sunburst(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
            customdata=hover_rows,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Process group: %{customdata[1]}<br>"
                "Mass: %{customdata[2]}<br>"
                "Annual mass: %{customdata[3]}<br>"
                "Share of total output mass: %{customdata[4]}<extra></extra>"
            ),
            textinfo="label",
            maxdepth=3,
            insidetextorientation="auto",
            insidetextfont=dict(size=text_sizes, color=text_colors),
        )
    )
    fig.update_layout(
        margin=dict(t=8, l=8, r=8, b=8),
        height=int(chart_height_px),
        paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=OVERVIEW_CARD_BORDER,
            font=dict(size=13, color=BRAND_BLUE),
        ),
    )
    fig.update_traces(textinfo="label", insidetextorientation="auto")
    return fig


def _render_mass_dashboard_output_distribution(
    econ: dict,
    route_key: str,
    annual_feed_kg: float,
    ctx: dict,
    mf_long: pd.DataFrame,
    hours_y: float,
    *,
    chart_height_px: int = OVERVIEW_REVENUE_SUNBURST_HEIGHT_PX,
) -> None:
    hierarchy = _build_overview_output_mass_hierarchy(econ, route_key, ctx, mf_long, hours_y)
    if hierarchy is None:
        st.info("No product or residue output mass available for distribution view.")
        return
    total_mass_y = float(hierarchy["total_mass_y"])
    total_mass_kg = _per_kg_feed(total_mass_y, annual_feed_kg) if annual_feed_kg > 0 else 0.0
    fig = _overview_output_mass_sunburst_figure(
        hierarchy,
        annual_feed_kg=annual_feed_kg,
        total_mass_kg=total_mass_kg,
        total_mass_y=total_mass_y / 1000.0,
        chart_height_px=chart_height_px,
    )
    if fig is None:
        st.info("No product or residue output mass available for distribution view.")
    else:
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CHART_CONFIG)


def _overview_revenue_hover_row(
    title: str,
    stage_display: str,
    *,
    revenue_kg: float,
    revenue_y: float,
    share_pct: float,
) -> tuple[str, str, str, str, str]:
    return (
        format_chemistry_unicode(title),
        stage_display,
        _fmt_revenue_per_kg_tooltip(revenue_kg),
        _fmt_revenue_y_hover(revenue_y),
        f"{float(share_pct):.1f}%",
    )


def _overview_revenue_sunburst_figure(
    hierarchy: dict,
    *,
    annual_feed_kg: float,
    revenue_kg: float,
    revenue_y: float,
    center_title: str = "Revenue",
) -> "go.Figure | None":
    """Sunburst: process groups (inner) -> products (outer); slice sizes from revenue share."""
    if go is None:
        return None

    total_rev_y = float(hierarchy["total_rev_y"])
    stages: list[dict[str, object]] = hierarchy["stages"]
    products: list[dict[str, object]] = hierarchy["products"]
    if total_rev_y <= 0 or not stages:
        return None

    root_id = "root"
    center_revenue_kg = revenue_kg if revenue_kg > 0 else _per_kg_feed(total_rev_y, annual_feed_kg)
    ids = [root_id]
    labels = [_overview_revenue_root_center_label(revenue_kg=center_revenue_kg, title=center_title)]
    parents = [""]
    values = [100.0]
    colors = ["#ffffff"]
    text_colors = [BRAND_BLUE]
    hover_rows: list[tuple[str, str, str, str, str]] = [
        _overview_revenue_hover_row(
            "Total Revenue",
            "All",
            revenue_kg=revenue_kg if revenue_kg > 0 else _per_kg_feed(total_rev_y, annual_feed_kg),
            revenue_y=revenue_y if revenue_y > 0 else total_rev_y,
            share_pct=100.0,
        )
    ]

    stage_share_by_short: dict[str, float] = {
        str(stage["stage_short"]): float(stage["share_pct"]) for stage in stages
    }

    for stage in stages:
        stage_short = str(stage["stage_short"])
        stage_display = _overview_revenue_stage_display(stage_short)
        stage_rev_y = float(stage["revenue_y"])
        stage_share = float(stage["share_pct"])
        stage_rev_kg = _per_kg_feed(stage_rev_y, annual_feed_kg)
        stage_id = f"stage::{stage_short}"
        is_residual_stage = bool(stage.get("is_residual")) or stage_short == _PROCESS_ECON_RESIDUAL_STAGE_SHORT
        ids.append(stage_id)
        if is_residual_stage:
            stage_ring_label = _overview_residual_ring_label(stage_share)
        else:
            stage_ring_label = _overview_revenue_stage_ring_label(stage_display, stage_share)
        labels.append(
            stage_ring_label
            if is_residual_stage or stage_share >= _OVERVIEW_REVENUE_LABEL_SHARE_PCT
            else ""
        )
        parents.append(root_id)
        values.append(stage_share)
        if is_residual_stage:
            colors.append(_PROCESS_ECON_RESIDUAL_FILL)
            text_colors.append(_PROCESS_ECON_RESIDUAL_TEXT)
        else:
            style = _OVERVIEW_REVENUE_STAGE_STYLE.get(stage_short, _OVERVIEW_REVENUE_STAGE_STYLE["Hydro"])
            colors.append(str(style["fill"]))
            text_colors.append(str(style["text_on_fill"]))
        if is_residual_stage:
            hover_rows.append(
                (
                    "Residual",
                    "Residual",
                    f"-{_fmt_metric(stage_rev_kg, 2)} $/kg feed",
                    f"-{_fmt_revenue_y_hover(stage_rev_y)}",
                    f"{stage_share:.1f}%",
                )
            )
        else:
            hover_rows.append(
                _overview_revenue_hover_row(
                    stage_display,
                    stage_display,
                    revenue_kg=stage_rev_kg,
                    revenue_y=stage_rev_y,
                    share_pct=stage_share,
                )
            )

    for prod in products:
        stage_short = str(prod["stage_short"])
        stage_display = _overview_revenue_stage_display(stage_short)
        p_name = str(prod["product"])
        p_rev_y = float(prod["revenue_y"])
        p_share = float(prod["share_pct"])
        p_rev_kg = _per_kg_feed(p_rev_y, annual_feed_kg)
        shade_idx = int(prod.get("shade_idx", 0))
        stage_id = f"stage::{stage_short}"
        p_id = f"prod::{stage_short}::{p_name}"
        is_residual = bool(prod.get("is_residual"))
        ids.append(p_id)
        stage_share = stage_share_by_short.get(stage_short, 0.0)
        product_ring_label = _overview_sunburst_label(_overview_product_short_name(p_name))
        labels.append(
            product_ring_label
            if is_residual or _overview_revenue_show_product_label(p_share, stage_share)
            else ""
        )
        parents.append(stage_id)
        values.append(p_share)
        if is_residual:
            colors.append(_process_econ_residual_palette(shade_idx))
            text_colors.append(_PROCESS_ECON_RESIDUAL_TEXT)
        else:
            style = _OVERVIEW_REVENUE_STAGE_STYLE.get(stage_short, _OVERVIEW_REVENUE_STAGE_STYLE["Hydro"])
            colors.append(_overview_revenue_stage_palette(stage_short, shade_idx))
            text_colors.append(str(style["text_on_light"]))
        if is_residual:
            hover_rows.append(
                (
                    format_chemistry_unicode(p_name),
                    "Residual",
                    f"-{_fmt_metric(p_rev_kg, 2)} $/kg feed",
                    f"-{_fmt_revenue_y_hover(p_rev_y)}",
                    f"{p_share:.1f}%",
                )
            )
        else:
            hover_rows.append(
                _overview_revenue_hover_row(
                    p_name,
                    stage_display,
                    revenue_kg=p_rev_kg,
                    revenue_y=p_rev_y,
                    share_pct=p_share,
                )
            )

    text_sizes = [_OVERVIEW_REVENUE_SUNBURST_TEXT_SIZE] * len(ids)
    center_label = labels[0]
    labels[0] = ""

    fig = go.Figure(
        go.Sunburst(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
            customdata=hover_rows,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Process group: %{customdata[1]}<br>"
                "Revenue: %{customdata[2]}<br>"
                "Annual revenue: %{customdata[3]}<br>"
                "Share of total revenue: %{customdata[4]}<extra></extra>"
            ),
            textinfo="label",
            maxdepth=3,
            insidetextorientation="auto",
            insidetextfont=dict(size=text_sizes, color=text_colors),
        )
    )
    fig.update_layout(
        margin=dict(t=8, l=8, r=8, b=8),
        height=OVERVIEW_REVENUE_SUNBURST_HEIGHT_PX,
        paper_bgcolor="rgba(0,0,0,0)",
        uniformtext=dict(minsize=_OVERVIEW_REVENUE_SUNBURST_TEXT_MIN, mode="hide"),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=OVERVIEW_CARD_BORDER,
            font=dict(size=13, color=BRAND_BLUE),
        ),
    )
    fig.update_traces(textinfo="label", insidetextorientation="auto")
    _add_sunburst_center_annotation(fig, center_label)
    return fig


def _render_overview_revenue_block(
    econ: dict,
    route_key: str,
    annual_feed_kg: float,
    kpi: dict,
) -> None:
    hierarchy = _build_overview_revenue_hierarchy(econ, route_key)
    if hierarchy is None:
        out_df = _build_output_value_emission_df(econ)
        rev_df = out_df.copy()
        if not rev_df.empty:
            rev_df["revenue_per_y"] = pd.to_numeric(rev_df.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
            rev_df = rev_df[rev_df["revenue_per_y"] > 0]
        if rev_df.empty:
            st.info("No positive output revenues available for hierarchy view.")
        else:
            st.bar_chart(
                rev_df.groupby("item", as_index=False)["revenue_per_y"]
                .sum()
                .sort_values("revenue_per_y", ascending=False)
                .set_index("item")
            )
        return

    sunburst_fig = _overview_revenue_sunburst_figure(
        hierarchy,
        annual_feed_kg=annual_feed_kg,
        revenue_kg=_safe_float(kpi.get("revenue_kg"), 0.0),
        revenue_y=_safe_float(kpi.get("revenue_y"), float(hierarchy["total_rev_y"])),
    )
    if sunburst_fig is None:
        st.info("No positive output revenues available for hierarchy view.")
    else:
        st.plotly_chart(sunburst_fig, width="stretch", config=PLOTLY_CHART_CONFIG)


def _overview_credits_lines_from_item_df(econ: dict, route_key: str) -> pd.DataFrame:
    credits_item_df = _safe_df(econ.get("credits_item_df"))
    if credits_item_df.empty:
        return pd.DataFrame()
    df = credits_item_df.copy()
    amount_col = "amount_kgco2e_per_y" if "amount_kgco2e_per_y" in df.columns else None
    if amount_col is None:
        return pd.DataFrame()
    df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
    if "environmental_type" in df.columns:
        df = df[df["environmental_type"].astype(str).str.lower().str.strip() == "credit"]
    df = df[df[amount_col] > 0].copy()
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={amount_col: "credit_per_y"})
    if "step_name" not in df.columns:
        df["step_name"] = ""
    if "item" not in df.columns:
        df["item"] = ""
    df["Quantity"] = 1.0
    df["stage_long"] = df["step_name"].astype(str).map(lambda s: _process_stage(s, route_key))
    df["stage"] = df["stage_long"].map(
        lambda x: _OVERVIEW_REVENUE_STAGE_LONG_MAP.get(str(x), "Hydrometallurgical Processing")
    )
    df["stage_short"] = df["stage"].map(_overview_stage_short)
    return df


def _overview_credits_lines_df(econ: dict, route_key: str) -> pd.DataFrame:
    """Output lines with positive environmental credits and overview stage_short."""
    out_df = _build_output_value_emission_df(econ)
    if not out_df.empty:
        cred_df = out_df.copy()
        cred_df["credit_per_y"] = pd.to_numeric(cred_df.get("credit_kgco2eq_per_y", 0.0), errors="coerce").fillna(0.0)
        cred_df["Quantity"] = pd.to_numeric(cred_df.get("Quantity", 0.0), errors="coerce").fillna(0.0)
        cred_df = cred_df[(cred_df["credit_per_y"] > 0) & (cred_df["Quantity"] > 0)].copy()
        if not cred_df.empty:
            cred_df["stage_long"] = cred_df["step_name"].astype(str).map(lambda s: _process_stage(s, route_key))
            cred_df["stage"] = cred_df["stage_long"].map(
                lambda x: _OVERVIEW_REVENUE_STAGE_LONG_MAP.get(str(x), "Hydrometallurgical Processing")
            )
            cred_df["stage_short"] = cred_df["stage"].map(_overview_stage_short)
            return cred_df
    return _overview_credits_lines_from_item_df(econ, route_key)


def _build_overview_credits_hierarchy(econ: dict, route_key: str) -> dict | None:
    """Display-only aggregation: process group -> individual credited products."""
    cred_df = _overview_credits_lines_df(econ, route_key)
    if cred_df.empty:
        return None

    by_stage_item = (
        cred_df.groupby(["stage_short", "item"], as_index=False)["credit_per_y"]
        .sum()
        .sort_values(["stage_short", "credit_per_y"], ascending=[True, False])
    )
    by_stage = by_stage_item.groupby("stage_short", as_index=False)["credit_per_y"].sum()
    total_credit_y = float(by_stage["credit_per_y"].sum())
    if total_credit_y <= 0:
        return None

    products: list[dict[str, object]] = []
    stages: list[dict[str, object]] = []
    for stage_short in _OVERVIEW_REVENUE_RING_ORDER:
        stage_rows = by_stage_item[by_stage_item["stage_short"].astype(str) == stage_short].copy()
        stage_rows = stage_rows.sort_values("credit_per_y", ascending=False)
        if stage_rows.empty:
            continue
        stage_credit_y = float(stage_rows["credit_per_y"].sum())
        stages.append(
            {
                "stage_short": stage_short,
                "credit_y": stage_credit_y,
                "share_pct": 100.0 * stage_credit_y / total_credit_y,
            }
        )
        shade_idx = 0
        for _, pr in stage_rows.iterrows():
            p_name = str(pr["item"])
            p_credit_y = float(pr["credit_per_y"])
            share_pct = 100.0 * p_credit_y / total_credit_y
            products.append(
                {
                    "stage_short": stage_short,
                    "product": p_name,
                    "credit_y": p_credit_y,
                    "share_pct": share_pct,
                    "shade_idx": shade_idx,
                }
            )
            shade_idx += 1

    return {"total_credit_y": total_credit_y, "stages": stages, "products": products}


def _fmt_credits_y_hover(value_y: float) -> str:
    v = float(value_y)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f} M kg CO2-eq"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f} k kg CO2-eq"
    return f"{v:,.0f} kg CO2-eq"


def _fmt_credits_per_kg_tooltip(value_kg: float) -> str:
    return f"{float(value_kg):,.2f} kg CO2-eq/kg feed"


def _overview_credits_root_center_label(*, credits_kg: float) -> str:
    return _overview_sunburst_label(f"Environmental credits<br>{_fmt_metric(credits_kg, 2)} kg CO2-eq/kg feed")


def _overview_credits_hover_row(
    title: str,
    stage_display: str,
    *,
    credits_kg: float,
    credits_y: float,
    share_pct: float,
) -> tuple[str, str, str, str, str]:
    return (
        format_chemistry_unicode(title),
        stage_display,
        f"Environmental credit: {_fmt_credits_per_kg_tooltip(credits_kg)}",
        f"Annual credit: {_fmt_credits_y_hover(credits_y)}",
        f"{float(share_pct):.1f}%",
    )


def _overview_credits_sunburst_figure(
    hierarchy: dict,
    *,
    annual_feed_kg: float,
    credits_kg: float,
    credits_y: float,
) -> "go.Figure | None":
    """Sunburst: process groups (inner) -> products (outer); slice sizes from credit share."""
    if go is None:
        return None

    total_credit_y = float(hierarchy["total_credit_y"])
    stages: list[dict[str, object]] = hierarchy["stages"]
    products: list[dict[str, object]] = hierarchy["products"]
    if total_credit_y <= 0 or not stages:
        return None

    root_id = "root"
    center_credits_kg = credits_kg if credits_kg > 0 else _per_kg_feed(total_credit_y, annual_feed_kg)
    ids = [root_id]
    labels = [_overview_credits_root_center_label(credits_kg=center_credits_kg)]
    parents = [""]
    values = [100.0]
    colors = ["#ffffff"]
    text_colors = [BRAND_BLUE]
    hover_rows: list[tuple[str, str, str, str, str]] = [
        _overview_credits_hover_row(
            "Total Environmental Credits",
            "All",
            credits_kg=credits_kg if credits_kg > 0 else _per_kg_feed(total_credit_y, annual_feed_kg),
            credits_y=credits_y if credits_y > 0 else total_credit_y,
            share_pct=100.0,
        )
    ]

    stage_share_by_short: dict[str, float] = {
        str(stage["stage_short"]): float(stage["share_pct"]) for stage in stages
    }

    for stage in stages:
        stage_short = str(stage["stage_short"])
        stage_display = _overview_revenue_stage_display(stage_short)
        stage_credit_y = float(stage["credit_y"])
        stage_share = float(stage["share_pct"])
        stage_credit_kg = _per_kg_feed(stage_credit_y, annual_feed_kg)
        stage_id = f"stage::{stage_short}"
        is_residual_stage = bool(stage.get("is_residual")) or stage_short == _PROCESS_ECON_RESIDUAL_STAGE_SHORT
        ids.append(stage_id)
        if is_residual_stage:
            stage_ring_label = _overview_residual_ring_label(stage_share)
        else:
            stage_ring_label = _overview_revenue_stage_ring_label(stage_display, stage_share)
        labels.append(
            stage_ring_label
            if is_residual_stage or stage_share >= _OVERVIEW_REVENUE_LABEL_SHARE_PCT
            else ""
        )
        parents.append(root_id)
        values.append(stage_share)
        if is_residual_stage:
            colors.append(_PROCESS_ECON_RESIDUAL_FILL)
            text_colors.append(_PROCESS_ECON_RESIDUAL_TEXT)
        else:
            style = _OVERVIEW_REVENUE_STAGE_STYLE.get(stage_short, _OVERVIEW_REVENUE_STAGE_STYLE["Hydro"])
            colors.append(str(style["fill"]))
            text_colors.append(str(style["text_on_fill"]))
        if is_residual_stage:
            hover_rows.append(
                (
                    "Residual treatment (burden)",
                    "Residual",
                    f"Environmental burden: +{_fmt_metric(stage_credit_kg, 2)} kg CO2-eq/kg",
                    f"Annual burden: {_fmt_credits_y_hover(stage_credit_y)}",
                    f"{stage_share:.1f}%",
                )
            )
        else:
            hover_rows.append(
                _overview_credits_hover_row(
                    stage_display,
                    stage_display,
                    credits_kg=stage_credit_kg,
                    credits_y=stage_credit_y,
                    share_pct=stage_share,
                )
            )

    for prod in products:
        stage_short = str(prod["stage_short"])
        stage_display = _overview_revenue_stage_display(stage_short)
        p_name = str(prod["product"])
        p_credit_y = float(prod["credit_y"])
        p_share = float(prod["share_pct"])
        p_credit_kg = _per_kg_feed(p_credit_y, annual_feed_kg)
        shade_idx = int(prod.get("shade_idx", 0))
        stage_id = f"stage::{stage_short}"
        p_id = f"prod::{stage_short}::{p_name}"
        is_residual = bool(prod.get("is_residual"))
        ids.append(p_id)
        stage_share = stage_share_by_short.get(stage_short, 0.0)
        product_ring_label = _overview_sunburst_label(_overview_product_short_name(p_name))
        labels.append(
            product_ring_label
            if is_residual or _overview_revenue_show_product_label(p_share, stage_share)
            else ""
        )
        parents.append(stage_id)
        values.append(p_share)
        if is_residual:
            colors.append(_process_econ_residual_palette(shade_idx))
            text_colors.append(_PROCESS_ECON_RESIDUAL_TEXT)
        else:
            style = _OVERVIEW_REVENUE_STAGE_STYLE.get(stage_short, _OVERVIEW_REVENUE_STAGE_STYLE["Hydro"])
            colors.append(_overview_revenue_stage_palette(stage_short, shade_idx))
            text_colors.append(str(style["text_on_light"]))
        if is_residual:
            hover_rows.append(
                (
                    format_chemistry_unicode(p_name),
                    "Residual",
                    f"Environmental burden: +{_fmt_metric(p_credit_kg, 2)} kg CO2-eq/kg",
                    f"Annual burden: {_fmt_credits_y_hover(p_credit_y)}",
                    f"{p_share:.1f}%",
                )
            )
        else:
            hover_rows.append(
                _overview_credits_hover_row(
                    p_name,
                    stage_display,
                    credits_kg=p_credit_kg,
                    credits_y=p_credit_y,
                    share_pct=p_share,
                )
            )

    text_sizes = [_OVERVIEW_REVENUE_SUNBURST_TEXT_SIZE] * len(ids)
    center_label = labels[0]
    labels[0] = ""

    fig = go.Figure(
        go.Sunburst(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
            customdata=hover_rows,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Process group: %{customdata[1]}<br>"
                "%{customdata[2]}<br>"
                "%{customdata[3]}<br>"
                "Share of total credits: %{customdata[4]}<extra></extra>"
            ),
            textinfo="label",
            maxdepth=3,
            insidetextorientation="auto",
            insidetextfont=dict(size=text_sizes, color=text_colors),
        )
    )
    fig.update_layout(
        margin=dict(t=8, l=8, r=8, b=8),
        height=OVERVIEW_REVENUE_SUNBURST_HEIGHT_PX,
        paper_bgcolor="rgba(0,0,0,0)",
        uniformtext=dict(minsize=_OVERVIEW_REVENUE_SUNBURST_TEXT_MIN, mode="hide"),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=OVERVIEW_CARD_BORDER,
            font=dict(size=13, color=BRAND_BLUE),
        ),
    )
    fig.update_traces(textinfo="label", insidetextorientation="auto")
    _add_sunburst_center_annotation(fig, center_label)
    return fig


def _render_overview_credits_block(
    econ: dict,
    route_key: str,
    annual_feed_kg: float,
    kpi: dict,
) -> None:
    hierarchy = _build_overview_credits_hierarchy(econ, route_key)
    if hierarchy is None:
        out_df = _build_output_value_emission_df(econ)
        cred_df = out_df.copy()
        if not cred_df.empty:
            cred_df["credit_per_y"] = pd.to_numeric(cred_df.get("credit_kgco2eq_per_y", 0.0), errors="coerce").fillna(0.0)
            cred_df = cred_df[cred_df["credit_per_y"] > 0]
        if cred_df.empty:
            fallback = _process_econ_gwp_credits_by_product_df(econ, annual_feed_kg)
            if fallback.empty:
                st.info("No positive environmental credits available for hierarchy view.")
            else:
                st.bar_chart(
                    fallback.set_index("Product")["value_per_kg"].sort_values(ascending=False)
                )
        else:
            st.bar_chart(
                cred_df.groupby("item", as_index=False)["credit_per_y"]
                .sum()
                .sort_values("credit_per_y", ascending=False)
                .set_index("item")
            )
        return

    sunburst_fig = _overview_credits_sunburst_figure(
        hierarchy,
        annual_feed_kg=annual_feed_kg,
        credits_kg=_safe_float(kpi.get("gwp_credit_kg"), 0.0),
        credits_y=_safe_float(kpi.get("gwp_credit_y"), float(hierarchy["total_credit_y"])),
    )
    if sunburst_fig is None:
        st.info("No positive environmental credits available for hierarchy view.")
    else:
        st.plotly_chart(sunburst_fig, width="stretch", config=PLOTLY_CHART_CONFIG)


def _inject_overview_tab_styles() -> None:
    """Overview-only typography: gray labels, blue key values."""
    overview_kpi_inner_row = (
        'section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div.libra-overview-left-block) '
        '> div[data-testid="column"]:first-child > div > [data-testid="stVerticalBlock"] '
        '> div[data-testid="stHorizontalBlock"]:first-of-type'
    )
    overview_env_tile = (
        'section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div.libra-overview-right-block) '
        '> div[data-testid="column"]:last-child > div > [data-testid="stVerticalBlock"] '
        '> [data-testid="stVerticalBlockBorderWrapper"]:first-of-type'
    )
    st.markdown(
        f"""
        <style>
            section[data-testid="stMain"] [data-testid="stMetricLabel"] {{
                color: {OVERVIEW_LABEL_GRAY} !important;
                font-weight: 600 !important;
            }}
            section[data-testid="stMain"] [data-testid="stMetricValue"] {{
                color: {BRAND_BLUE} !important;
                font-weight: 400 !important;
            }}
            section[data-testid="stMain"] [data-baseweb="select"] > div,
            section[data-testid="stMain"] [data-baseweb="select"] > div * {{
                color: {OVERVIEW_LABEL_GRAY} !important;
            }}
            section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div.libra-overview-left-block) {{
                align-items: stretch !important;
            }}
            section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div.libra-overview-left-block) > div[data-testid="column"] {{
                display: flex !important;
                flex-direction: column !important;
            }}
            {overview_kpi_inner_row} {{
                align-items: stretch !important;
            }}
            {overview_kpi_inner_row} > div[data-testid="column"] {{
                display: flex !important;
                flex-direction: column !important;
            }}
            {overview_kpi_inner_row} [data-testid="stVerticalBlockBorderWrapper"],
            {overview_env_tile} {{
                flex: 1 1 auto !important;
                width: 100% !important;
                display: flex !important;
                flex-direction: column !important;
                overflow: hidden !important;
                padding-top: {OVERVIEW_TILE_HEADING_PADDING_TOP_PX}px !important;
                padding-block-start: {OVERVIEW_TILE_HEADING_PADDING_TOP_PX}px !important;
            }}
            section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div.libra-overview-left-block) .libra-overview-tile-heading {{
                font-size: {OVERVIEW_TILE_HEADING_SIZE_REM} !important;
                font-weight: 600 !important;
                color: {BRAND_BLUE} !important;
                margin: 0 0 0.2rem 0 !important;
                padding: 0 !important;
                line-height: 1.1 !important;
            }}
            {overview_kpi_inner_row} [data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"],
            {overview_env_tile} > div[data-testid="stVerticalBlock"] {{
                display: flex !important;
                flex-direction: column !important;
                flex: 1 1 auto !important;
                height: 100% !important;
                overflow: hidden !important;
                padding-top: 0 !important;
                gap: 0 !important;
            }}
            {overview_kpi_inner_row} [data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] > div:first-child,
            {overview_kpi_inner_row} [data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] > div:first-child [data-testid="stElementContainer"],
            {overview_kpi_inner_row} [data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] > div:first-child [data-testid="stMarkdownContainer"],
            {overview_env_tile} > div[data-testid="stVerticalBlock"] > div:first-child,
            {overview_env_tile} > div[data-testid="stVerticalBlock"] > div:first-child [data-testid="stElementContainer"],
            {overview_env_tile} > div[data-testid="stVerticalBlock"] > div:first-child [data-testid="stMarkdownContainer"] {{
                margin-top: 0 !important;
                padding-top: 0 !important;
            }}
            {overview_kpi_inner_row} [data-testid="stHeading"],
            {overview_env_tile} [data-testid="stHeading"] {{
                margin-top: 0 !important;
                margin-bottom: 0.2rem !important;
                padding-top: 0 !important;
                padding-bottom: 0 !important;
            }}
            {overview_kpi_inner_row} [data-testid="stHeading"] h3,
            {overview_kpi_inner_row} [data-testid="stMarkdownContainer"] h3,
            {overview_env_tile} [data-testid="stHeading"] h3,
            {overview_env_tile} [data-testid="stMarkdownContainer"] h3 {{
                margin-top: 0 !important;
                padding-top: 0 !important;
            }}
            {overview_kpi_inner_row} > div[data-testid="column"]:first-child [data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] > div:last-child {{
                flex: 1 1 auto !important;
                min-height: 0 !important;
                overflow: hidden !important;
            }}
            {overview_kpi_inner_row} [data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] > div:last-child,
            {overview_env_tile} > div[data-testid="stVerticalBlock"] > div:last-child {{
                margin-top: auto !important;
                flex-shrink: 0 !important;
            }}
            {overview_kpi_inner_row} > div[data-testid="column"]:first-child [data-testid="stPlotlyChart"] {{
                margin-top: 0 !important;
            }}
            {overview_kpi_inner_row} > div[data-testid="column"]:first-child [data-testid="stPlotlyChart"] > div {{
                overflow: hidden !important;
            }}
            section[data-testid="stMain"] .libra-overview-tile-primary-kpi-fill {{
                flex: 1 1 auto !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important;
                min-height: 0 !important;
            }}
            section[data-testid="stMain"] .libra-overview-tile-primary-kpi-fill > div {{
                flex: 1 1 auto !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important;
            }}
            section[data-testid="stMain"] .libra-overview-tile-status-compact {{
                margin: 6px 0 0 0 !important;
                min-height: {OVERVIEW_TILE_STATUS_MIN_PX}px !important;
                padding: {OVERVIEW_TILE_STATUS_PADDING_Y_PX}px {OVERVIEW_TILE_STATUS_PADDING_X_PX}px !important;
                border-radius: 8px !important;
                font-size: {OVERVIEW_TILE_STATUS_FONT_REM} !important;
                font-weight: 600 !important;
                line-height: 1.2 !important;
                text-align: center !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                box-sizing: border-box !important;
            }}
            section[data-testid="stMain"] .libra-overview-tile-status-large {{
                min-height: 96px !important;
                padding: 14px 16px !important;
                font-size: 1.12rem !important;
            }}
            section[data-testid="stMain"] div.libra-overview-left-block,
            section[data-testid="stMain"] div.libra-overview-right-block {{
                display: block !important;
                height: 0 !important;
                margin: 0 !important;
                padding: 0 !important;
                overflow: hidden !important;
                line-height: 0 !important;
            }}
            section[data-testid="stMain"] [data-testid="stElementContainer"]:has(div.libra-overview-left-block),
            section[data-testid="stMain"] [data-testid="stElementContainer"]:has(div.libra-overview-right-block) {{
                margin: 0 !important;
                padding: 0 !important;
                min-height: 0 !important;
            }}
            {overview_kpi_inner_row},
            {overview_env_tile} {{
                margin-top: 0 !important;
            }}
            section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(div.libra-overview-left-block) > [data-testid="stVerticalBlock"] {{
                gap: 0 !important;
            }}
            section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(div.libra-overview-left-block) > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:first-child {{
                margin-bottom: 0 !important;
                padding-bottom: 0 !important;
            }}
            section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div.libra-overview-left-block) > div[data-testid="column"] > div > [data-testid="stVerticalBlock"] {{
                gap: 0 !important;
            }}
            section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div.libra-overview-right-block) > div[data-testid="column"]:last-child > div > [data-testid="stVerticalBlock"] {{
                gap: 0 !important;
            }}
            section[data-testid="stMain"] table.libra-overview-metric-table,
            section[data-testid="stMain"] table.libra-overview-metric-table tr,
            section[data-testid="stMain"] table.libra-overview-metric-table td,
            section[data-testid="stMain"] table.libra-overview-metric-table th {{
                border: 1px solid #ffffff !important;
                border-color: #ffffff !important;
            }}
            section[data-testid="stMain"] div.libra-overview-process-flow-marker + div[data-testid="stVerticalBlockBorderWrapper"] {{
                width: 100% !important;
                margin-top: 0.75rem !important;
                padding-top: {OVERVIEW_TILE_HEADING_PADDING_TOP_PX}px !important;
                padding-block-start: {OVERVIEW_TILE_HEADING_PADDING_TOP_PX}px !important;
                overflow: hidden !important;
            }}
            section[data-testid="stMain"] div.libra-overview-process-flow-marker + div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {{
                display: flex !important;
                flex-direction: column !important;
                height: 100% !important;
                overflow: hidden !important;
            }}
            section[data-testid="stMain"] div.libra-overview-process-flow-marker + div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHeading"] {{
                margin-top: 0 !important;
                margin-bottom: 0.2rem !important;
                padding-top: 0 !important;
                padding-bottom: 0 !important;
                flex-shrink: 0 !important;
            }}
            section[data-testid="stMain"] div.libra-overview-process-flow-marker + div[data-testid="stVerticalBlockBorderWrapper"] .mass-pfd-wrap {{
                flex: 1 1 auto !important;
                overflow-x: auto !important;
                overflow-y: hidden !important;
                max-width: 100% !important;
                min-height: 0 !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: flex-start !important;
            }}
            section[data-testid="stMain"] div.libra-overview-process-flow-marker + div[data-testid="stVerticalBlockBorderWrapper"] .mass-pfd-scroll {{
                overflow-x: auto !important;
                overflow-y: hidden !important;
                -webkit-overflow-scrolling: touch !important;
            }}
            section[data-testid="stMain"] div.libra-overview-recovery-marker + div[data-testid="stVerticalBlockBorderWrapper"] {{
                width: 100% !important;
                margin-top: 0.75rem !important;
                padding-top: {OVERVIEW_TILE_HEADING_PADDING_TOP_PX}px !important;
                padding-block-start: {OVERVIEW_TILE_HEADING_PADDING_TOP_PX}px !important;
                overflow: hidden !important;
            }}
            section[data-testid="stMain"] div.libra-overview-recovery-marker + div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {{
                display: flex !important;
                flex-direction: column !important;
                height: 100% !important;
                overflow: hidden !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _overview_tile_heading(title: str) -> None:
    """Match Revenue Explorer heading size without Streamlit stHeading top spacing."""
    title_esc = html_module.escape(title)
    st.markdown(
        f'<h3 class="libra-overview-tile-heading">{title_esc}</h3>',
        unsafe_allow_html=True,
    )


def _overview_tile_bottom_status_block(text: str, *, positive: bool, large: bool = False) -> str:
    """Compact status banner at the bottom of Economics / Environmental tiles."""
    text_esc = html_module.escape(text)
    if positive:
        bg, border, color = "#d4edda", "#b7dfc5", "#1a7f37"
    else:
        bg, border, color = "#f8d7da", "#f1c2c7", "#c0392b"
    status_class = "libra-overview-tile-status-compact"
    if large:
        status_class += " libra-overview-tile-status-large"
    return (
        f'<div class="{status_class}" '
        f'style="background:{bg}; border:1px solid {border}; color:{color};">'
        f"{text_esc}</div>"
    )


def _overview_metric_row_html(
    left: tuple[str, str],
    right: tuple[str, str] | None = None,
    *,
    compact: bool = False,
    large: bool = False,
) -> str:
    """Two metrics side by side without ``st.columns`` (Streamlit nesting limit)."""
    return _overview_metrics_grid_html(left, *((right,) if right is not None else ()), compact=compact, large=large)


def _overview_metrics_grid_html(
    *pairs: tuple[str, str],
    compact: bool = False,
    large: bool = False,
) -> str:
    """Metric grid as a single table; borders white so Streamlit table lines stay invisible."""
    rows: list[str] = []
    for i in range(0, len(pairs), 2):
        left = _overview_metric_html(pairs[i][0], pairs[i][1], compact=compact, large=large)
        right = (
            _overview_metric_html(pairs[i + 1][0], pairs[i + 1][1], compact=compact, large=large)
            if i + 1 < len(pairs)
            else ""
        )
        rows.append(
            "<tr>"
            f'<td style="width:50%;border:1px solid #ffffff;padding:0;vertical-align:top;">{left}</td>'
            f'<td style="width:50%;border:1px solid #ffffff;padding:0;vertical-align:top;">{right}</td>'
            "</tr>"
        )
    return (
        '<table class="libra-overview-metric-table" '
        'style="width:100%;border-collapse:collapse;border:1px solid #ffffff;margin:0;padding:0;">'
        f'{"".join(rows)}'
        "</table>"
    )


def _overview_metric_html(label: str, value: str, *, compact: bool = False, large: bool = False) -> str:
    label_esc = html_module.escape(label)
    value_esc = html_module.escape(value)
    if compact:
        if large:
            pad, label_size, value_size = "4px 0 6px 0", "0.98rem", "1.9rem"
        else:
            pad, label_size, value_size = "0 0 2px 0", OVERVIEW_TILE_METRIC_LABEL_REM, OVERVIEW_TILE_METRIC_VALUE_REM
    elif large:
        pad, label_size, value_size = "4px 0 8px 0", "1.0rem", "2.0rem"
    else:
        pad, label_size, value_size = "2px 0 4px 0", "0.875rem", "1.75rem"
    return f"""
    <div style="padding:{pad};">
        <div style="font-size:{label_size}; color:{OVERVIEW_LABEL_GRAY}; font-weight:600; line-height:1.2;">{label_esc}</div>
        <div style="font-size:{value_size}; color:{BRAND_BLUE}; font-weight:400; line-height:1.15;">{value_esc}</div>
    </div>
    """


def _infrastructure_site_count_label(count: int, singular: str, plural: str) -> str:
    n = max(0, int(count))
    return f"{n} {singular}" if n == 1 else f"{n} {plural}"


def _infrastructure_executive_card_html(infra: dict) -> str:
    """Compact vertical hub-spoke flow card for Overview / Plant Economics."""
    spoke = html_module.escape(str(infra.get("spoke_location", "-")))
    hub = html_module.escape(str(infra.get("hub_location", "-")))
    spoke_scope = html_module.escape(str(infra.get("spoke_process_scope", "Front-End + Pretreatment")))
    hub_scope = html_module.escape(str(infra.get("hub_process_scope", "Hydrometallurgical Refining")))
    stream = html_module.escape(str(infra.get("transport_stream", "-")))
    n_spokes = int(_safe_float(infra.get("required_spokes"), 0.0))
    n_hubs = int(_safe_float(infra.get("required_hubs"), 0.0))
    transported_t_y = _safe_float(infra.get("transported_mass_t_per_year"), 0.0)
    distance_km = _safe_float(infra.get("distance_km"), 0.0)
    spokes_label = html_module.escape(_infrastructure_site_count_label(n_spokes, "Spoke", "Spokes"))
    hubs_label = html_module.escape(_infrastructure_site_count_label(n_hubs, "Hub", "Hubs"))

    return f"""
    <div style="border:1px solid {OVERVIEW_CARD_BORDER}; border-radius:10px; padding:10px 14px; margin:0 0 8px 0; background:#fafbfd;">
        <div style="display:grid; grid-template-columns:1fr auto 1fr auto 1fr; gap:8px; align-items:center; text-align:center;">
            <div>
                <div style="font-size:1.05rem; color:{BRAND_BLUE}; font-weight:700;">{spoke}</div>
                <div style="font-size:0.78rem; color:{OVERVIEW_LABEL_GRAY}; line-height:1.25;">{spoke_scope}</div>
                <div style="font-size:0.82rem; color:{BRAND_BLUE}; font-weight:600; margin-top:4px;">{spokes_label}</div>
            </div>
            <div style="color:{OVERVIEW_LABEL_GRAY}; font-size:1.1rem; font-weight:600;">↓</div>
            <div>
                <div style="font-size:0.9rem; color:{OVERVIEW_LABEL_GRAY}; font-weight:600;">{stream}</div>
                <div style="font-size:1.0rem; color:{BRAND_BLUE}; font-weight:700; margin-top:4px;">{transported_t_y:,.0f} t/y</div>
                <div style="font-size:0.9rem; color:{BRAND_BLUE}; font-weight:600;">{distance_km:,.0f} km</div>
            </div>
            <div style="color:{OVERVIEW_LABEL_GRAY}; font-size:1.1rem; font-weight:600;">↓</div>
            <div>
                <div style="font-size:1.05rem; color:{BRAND_BLUE}; font-weight:700;">{hub}</div>
                <div style="font-size:0.78rem; color:{OVERVIEW_LABEL_GRAY}; line-height:1.25;">{hub_scope}</div>
                <div style="font-size:0.82rem; color:{BRAND_BLUE}; font-weight:600; margin-top:4px;">{hubs_label}</div>
            </div>
        </div>
    </div>
    """


def _render_infrastructure_hub_spoke_metrics(infra: dict) -> None:
    """KPI grid below the infrastructure flow card."""
    transported_t_y = _safe_float(infra.get("transported_mass_t_per_year"), 0.0)
    distance_km = _safe_float(infra.get("distance_km"), 0.0)
    transport_cost_kg = _safe_float(infra.get("transport_cost_per_kg_feed"), 0.0)
    transport_gwp_kg = _safe_float(infra.get("transport_gwp_kgco2e_per_kg_feed"), 0.0)
    n_spokes = int(_safe_float(infra.get("required_spokes"), 0.0))
    n_hubs = int(_safe_float(infra.get("required_hubs"), 0.0))
    spoke_util = _safe_float(infra.get("pretreatment_utilization"), 0.0) * 100.0
    hub_util = _safe_float(infra.get("hydro_utilization"), 0.0) * 100.0
    stream = str(infra.get("transport_stream", "-"))

    r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns(5)
    r1c1.markdown(_overview_metric_html("Spoke location", str(infra.get("spoke_location", "-"))), unsafe_allow_html=True)
    r1c2.markdown(_overview_metric_html("Hub location", str(infra.get("hub_location", "-"))), unsafe_allow_html=True)
    r1c3.markdown(_overview_metric_html("Transported stream", stream), unsafe_allow_html=True)
    r1c4.markdown(_overview_metric_html("Transported mass [t/y]", f"{transported_t_y:,.0f}"), unsafe_allow_html=True)
    r1c5.markdown(_overview_metric_html("Distance [km]", f"{distance_km:,.0f}"), unsafe_allow_html=True)

    r2c1, r2c2, r2c3, r2c4, r2c5, r2c6 = st.columns(6)
    r2c1.markdown(_overview_metric_html("Transport cost [$/kg feed]", f"${transport_cost_kg:,.4f}"), unsafe_allow_html=True)
    r2c2.markdown(_overview_metric_html("Transport GWP [kg CO2-eq/kg feed]", f"{transport_gwp_kg:,.4f}"), unsafe_allow_html=True)
    r2c3.markdown(_overview_metric_html("Required spokes", str(n_spokes)), unsafe_allow_html=True)
    r2c4.markdown(_overview_metric_html("Required hubs", str(n_hubs)), unsafe_allow_html=True)
    r2c5.markdown(_overview_metric_html("Spoke utilization [%]", f"{spoke_util:.1f}"), unsafe_allow_html=True)
    r2c6.markdown(_overview_metric_html("Hub utilization [%]", f"{hub_util:.1f}"), unsafe_allow_html=True)


def _plant_capex_heading(title: str) -> None:
    st.subheader(title)


def _plant_capex_white_divider() -> None:
    st.markdown(
        '<hr style="border:0; border-top:1px solid #ffffff; margin:0.85rem 0;" />',
        unsafe_allow_html=True,
    )


_PLANT_CAPEX_STRUCTURE_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("Purchased Equipment", "I.A.1 Purchased equip ($)"),
    ("Installation", "I.A.2 Installation ($)"),
    ("Buildings", "I.B Building ($)"),
    ("Service Facilities", "I.C Service facilities ($)"),
    ("Engineering", "II.A Engineering ($)"),
    ("Construction", "II.B Construction ($)"),
    ("Contingency", "II.C Contingency ($)"),
    ("Working Capital", "IV Working Capital ($)"),
)


def _fmt_usd_compact(v: float) -> str:
    x = float(v)
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:,.1f}M"
    if abs(x) >= 1_000:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def _fmt_usd_compact_k(v: float) -> str:
    x = float(v)
    if abs(x) >= 1_000:
        return f"${x / 1_000:,.1f}k"
    return f"${x:,.0f}"


def _fmt_t_y(v: float) -> str:
    return f"{_fmt_metric(v, 0)} t/y"


def _fmt_t_h(v: float) -> str:
    return f"{_fmt_metric(v, 2)} t/h"


def _fmt_pct(v: float, ndigits: int = 1) -> str:
    return f"{_fmt_metric(v, ndigits)}%"


def _plant_type_label(scen_sel: dict, ctx: dict) -> str:
    if is_hub_spoke_mode(scen_sel):
        return "Hub-Spoke System"
    return "Integrated Recycling Site"


def _plant_process_stage_display_label(stage: str) -> str:
    labels = {
        "Front-end processing": "Front-end processing",
        "Mechanical treatment": "Mechanical treatment",
        "Pyro treatment": "Pyrometallurgy",
        "Hydrometallurgy": "Hydrometallurgy",
        "Other processing": "Refining / product recovery",
        "Transport / Infrastructure": "Transport / infrastructure",
    }
    return labels.get(str(stage), str(stage))


def _plant_capex_process_stage_short_label(stage: str) -> str:
    labels = {
        "Front-end processing": "Front-End",
        "Mechanical treatment": "Mech",
        "Pyrometallurgy": "Pyro",
        "Pyro treatment": "Pyro",
        "Hydrometallurgy": "Hydro",
        "Other processing": "Other",
        "Refining / product recovery": "Other",
        "Transport / infrastructure": "Transport",
    }
    return labels.get(str(stage), str(stage))


_PLANT_CAPEX_PROCESS_STAGE_COLORS: dict[str, str] = {
    "Hydro": BRAND_BLUE,
    "Mech": INFRA_PRETREATMENT_COLOR,
    "Pyro": INFRA_PRETREATMENT_COLOR,
    "Front-End": "#6b7280",
    "Other": "#5f6c7b",
    "Transport": "#7A8FA6",
}


def _plant_capex_process_stage_text_color(stage_short: str) -> str:
    if str(stage_short) == "Hydro":
        return "#ffffff"
    if str(stage_short) in {"Mech", "Pyro"}:
        return BRAND_BLUE
    return "#ffffff"


def _plant_capex_process_stage_color(stage_short: str) -> str:
    return _PLANT_CAPEX_PROCESS_STAGE_COLORS.get(str(stage_short), "#5f6c7b")


def _plant_capex_process_stage_ring_label(stage: str, share_pct: float) -> str:
    if float(share_pct) < _OVERVIEW_REVENUE_LABEL_SHARE_PCT:
        return ""
    return _overview_sunburst_label(f"{stage}<br>{float(share_pct):.0f}%")


def _build_plant_capex_process_stage_donut_figure(stage_df: pd.DataFrame) -> "go.Figure | None":
    if go is None or stage_df is None or stage_df.empty:
        return None
    plot_df = stage_df.copy()
    plot_df["capex_equip_step"] = pd.to_numeric(plot_df["capex_equip_step"], errors="coerce").fillna(0.0)
    plot_df = plot_df[plot_df["capex_equip_step"] > 0]
    if plot_df.empty:
        return None
    total = float(plot_df["capex_equip_step"].sum())
    if total <= 0:
        return None
    plot_df = plot_df.sort_values("capex_equip_step", ascending=False)
    plot_df["share_pct"] = plot_df["capex_equip_step"] / total * 100.0

    short_labels = [
        _plant_capex_process_stage_short_label(str(row["process_stage"]))
        for _, row in plot_df.iterrows()
    ]
    color_range = [_plant_capex_process_stage_color(label) for label in short_labels]
    text_colors = [_plant_capex_process_stage_text_color(label) for label in short_labels]
    display_labels = [
        _plant_capex_process_stage_ring_label(short_label, float(row["share_pct"]))
        for short_label, (_, row) in zip(short_labels, plot_df.iterrows())
    ]
    hover_rows = [
        (
            f"<b>{html_module.escape(str(row['process_stage']))}</b><br>"
            f"Purchased Equipment CAPEX: {_fmt_usd_compact(float(row['capex_equip_step']))}<br>"
            f"Share: {float(row['share_pct']):.1f}%"
        )
        for _, row in plot_df.iterrows()
    ]

    fig = go.Figure(
        go.Pie(
            labels=short_labels,
            values=plot_df["capex_equip_step"].astype(float).tolist(),
            hole=0.5,
            text=display_labels,
            textinfo="text",
            textposition="inside",
            insidetextorientation="auto",
            insidetextfont=dict(size=14, color=text_colors),
            marker=dict(colors=color_range, line=dict(color="#ffffff", width=2)),
            customdata=hover_rows,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        showlegend=False,
        height=PLANT_CAPEX_COMPOSITION_CHART_HEIGHT_PX,
        margin=dict(t=8, l=8, r=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        uniformtext=dict(minsize=12, mode="hide"),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=OVERVIEW_CARD_BORDER,
            font=dict(size=13, color=BRAND_BLUE),
        ),
    )
    fig.update_traces(domain=dict(x=[0.02, 0.98], y=[0.02, 0.98]))
    return fig


def _build_plant_capex_waterfall_figure(econ: dict):
    struct_df = _plant_capex_structure_df(econ.get("capex_df"))
    cap = _capex_summary_row(econ.get("capex_df"))
    tci = cap.get("tci", 0.0)
    if go is None or struct_df.empty or tci <= 0:
        return None
    waterfall_rows = struct_df[struct_df["value_usd"] > 0].copy()
    if waterfall_rows.empty:
        return None
    labels = waterfall_rows["component"].astype(str).tolist() + ["Total Capital Investment (TCI)"]
    values = waterfall_rows["value_usd"].astype(float).tolist()
    measures = ["relative"] * len(values) + ["total"]
    y_max = max(values + [tci])
    y_range_max = y_max * 1.22
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=measures,
            x=labels,
            y=values + [tci],
            connector={"line": {"color": OVERVIEW_CARD_BORDER}},
            increasing={"marker": {"color": BRAND_BLUE}},
            totals={"marker": {"color": "#4b5563"}},
            text=[_fmt_usd_compact(v) for v in values] + [_fmt_usd_compact(tci)],
            textposition="outside",
        )
    )
    fig.update_traces(cliponaxis=False)
    fig.update_layout(
        height=PLANT_CAPEX_COMPOSITION_CHART_HEIGHT_PX,
        margin=dict(l=52, r=20, t=56, b=104),
        showlegend=False,
        xaxis_tickangle=-25,
        font=dict(size=11),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        title="$M",
        tickprefix="$",
        tickformat=".0s",
        range=[0, y_range_max],
    )
    return fig


def _capex_summary_row(capex_df: pd.DataFrame) -> dict:
    if capex_df is None or capex_df.empty:
        return {}
    row = capex_df.iloc[0]
    return {
        "tci": _safe_float(row.get("V Total Capital ($)", row.get("TCI ($)", 0.0)), 0.0),
        "fci": _safe_float(row.get("III Fixed Capital ($)", row.get("FCI ($)", 0.0)), 0.0),
        "working_capital": _safe_float(row.get("IV Working Capital ($)", row.get("II Working capital ($)", 0.0)), 0.0),
        "purchased_equipment": _safe_float(row.get("I.A.1 Purchased equip ($)", 0.0), 0.0),
    }


def _collect_plant_equipment_capex(steps_df: pd.DataFrame, extras_all: dict, scen_name: str) -> pd.DataFrame:
    from Save import _capex_collect

    return _capex_collect(_safe_df(steps_df), str(scen_name or ""), extras_all or {})


def _plant_step_capex_table(equip_df: pd.DataFrame) -> pd.DataFrame:
    if equip_df is None or equip_df.empty or "Step" not in equip_df.columns:
        return pd.DataFrame()
    cap_col = "CAPEX equip per step ($)"
    if cap_col not in equip_df.columns:
        return pd.DataFrame()
    df = equip_df.copy()
    df[cap_col] = pd.to_numeric(df[cap_col], errors="coerce").fillna(0.0)
    if "Machines" in df.columns:
        df["Machines"] = pd.to_numeric(df["Machines"], errors="coerce").fillna(0.0)
    else:
        df["Machines"] = 0.0
    step_df = (
        df.groupby("Step", as_index=False)
        .agg({cap_col: "max", "Machines": "sum"})
        .rename(columns={cap_col: "capex_equip_step"})
    )
    return step_df[step_df["capex_equip_step"] > 0].copy()


def _plant_equipment_driver_label(row: pd.Series) -> str:
    machine = str(row.get("Machine name(s)", "")).strip()
    if machine and machine not in {"-", "nan", "None"}:
        return machine
    return _compact_step_label(str(row.get("Step", "")))


def _plant_process_stage(step: str, route: str | None = None) -> str:
    if str(step or "").strip() == "Inter-site Transport":
        return "Transport / Infrastructure"
    return _process_stage(step, route)


def _plant_capex_structure_df(capex_df: pd.DataFrame) -> pd.DataFrame:
    if capex_df is None or capex_df.empty:
        return pd.DataFrame()
    row = capex_df.iloc[0]
    rows = [
        {"component": label, "value_usd": _safe_float(row.get(col, 0.0), 0.0)}
        for label, col in _PLANT_CAPEX_STRUCTURE_COMPONENTS
    ]
    return pd.DataFrame(rows)


def _plant_purchased_equipment_usd(row: pd.Series) -> float:
    per_machine = _safe_float(row.get("CAPEX equip per machine($)"), 0.0)
    machines = _safe_float(row.get("Machines"), 0.0)
    step_capex = _safe_float(row.get("CAPEX equip per step ($)"), 0.0)
    if per_machine > 0.0 and machines > 0.0:
        return per_machine * machines
    return step_capex


def _plant_equipment_capex_drivers_df(
    steps_df: pd.DataFrame,
    extras_all: dict,
    scen_sel: dict,
    *,
    top_n: int | None = None,
) -> pd.DataFrame:
    equip_df = _collect_plant_equipment_capex(steps_df, extras_all, str(scen_sel.get("name", "")))
    if equip_df.empty:
        return pd.DataFrame()
    route_key = str(scen_sel.get("route", "") or "")
    drivers = equip_df.copy()
    drivers["driver"] = drivers.apply(_plant_equipment_driver_label, axis=1)
    drivers["purchased_usd"] = drivers.apply(_plant_purchased_equipment_usd, axis=1)
    drivers["process_stage"] = drivers["Step"].astype(str).map(
        lambda s: _plant_process_stage_display_label(_plant_process_stage(s, route_key))
    )
    drivers["process_stage_short"] = drivers["process_stage"].map(_plant_capex_process_stage_short_label)
    drivers = drivers[drivers["purchased_usd"] > 0].copy()
    if drivers.empty:
        return pd.DataFrame()
    dominant_idx = drivers.groupby("driver")["purchased_usd"].idxmax()
    stage_by_driver = drivers.loc[dominant_idx].set_index("driver")["process_stage_short"]
    grouped = drivers.groupby("driver", as_index=False)["purchased_usd"].sum()
    grouped["process_stage_short"] = grouped["driver"].map(stage_by_driver).fillna("Other")
    total_purchased = float(grouped["purchased_usd"].sum())
    if grouped.empty or total_purchased <= 0:
        return pd.DataFrame()
    grouped["share_pct"] = grouped["purchased_usd"] / total_purchased * 100.0
    grouped["value_musd"] = grouped["purchased_usd"] / 1_000_000.0
    grouped = grouped.sort_values("purchased_usd", ascending=False)
    if top_n is not None:
        grouped = grouped.head(int(top_n)).copy()
    return grouped


def _build_plant_equipment_investment_breakdown_figure(drivers_df: pd.DataFrame) -> "go.Figure | None":
    if go is None or drivers_df is None or drivers_df.empty:
        return None
    plot_df = drivers_df.copy()
    plot_df["value_musd"] = pd.to_numeric(plot_df["value_musd"], errors="coerce").fillna(0.0)
    plot_df = plot_df[plot_df["value_musd"] > 0]
    if plot_df.empty:
        return None
    plot_df = plot_df.sort_values("value_musd", ascending=True)
    bar_colors = [
        _plant_capex_process_stage_color(str(stage))
        for stage in plot_df["process_stage_short"].astype(str)
    ]
    hover_rows = [
        (
            f"<b>{html_module.escape(str(row['driver']))}</b><br>"
            f"Process stage: {html_module.escape(str(row['process_stage_short']))}<br>"
            f"Purchased Equipment CAPEX: {_fmt_usd_compact(float(row['purchased_usd']))}<br>"
            f"Share: {float(row['share_pct']):.1f}%"
        )
        for _, row in plot_df.iterrows()
    ]
    fig = go.Figure(
        go.Bar(
            y=plot_df["driver"].astype(str).tolist(),
            x=plot_df["value_musd"].astype(float).tolist(),
            orientation="h",
            marker=dict(color=bar_colors, line=dict(color="#ffffff", width=1)),
            customdata=hover_rows,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )
    fig_height = max(360, 30 * len(plot_df))
    fig.update_layout(
        height=fig_height,
        margin=dict(l=16, r=24, t=12, b=48),
        showlegend=False,
        hovermode="y",
        hoverdistance=80,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=OVERVIEW_CARD_BORDER,
            font=dict(size=13, color=BRAND_BLUE),
        ),
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        title=None,
        tickprefix="$",
        tickformat=".0f",
        ticksuffix="M",
        automargin=True,
    )
    fig.update_yaxes(showgrid=False, zeroline=False, title=None, automargin=True)
    return fig


def _plant_largest_investment_drivers_card_html(drivers_df: pd.DataFrame, *, top_n: int = 5) -> str:
    if drivers_df is None or drivers_df.empty:
        return ""
    rows = drivers_df.head(top_n)
    body_rows = []
    for idx, row in rows.iterrows():
        bg = "#ffffff" if len(body_rows) % 2 == 0 else "#fafbfd"
        equipment = html_module.escape(str(row["driver"]))
        capex = html_module.escape(_fmt_usd_compact(float(row["purchased_usd"])))
        share = html_module.escape(f"{float(row['share_pct']):.0f}%")
        body_rows.append(
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px 12px; color:#3d4f63; font-weight:600; font-size:0.84rem;">{equipment}</td>'
            f'<td style="padding:8px 12px; text-align:right; color:{BRAND_BLUE}; font-weight:700; font-size:0.84rem;">{capex}</td>'
            f'<td style="padding:8px 12px; text-align:right; color:{OVERVIEW_LABEL_GRAY}; font-weight:700; font-size:0.84rem;">{share}</td>'
            f"</tr>"
        )
    return (
        f'<div style="margin-top:12px; border:1px solid {OVERVIEW_CARD_BORDER}; border-radius:10px; overflow:hidden;">'
        f'<div style="padding:9px 12px; background:#f8fafc; border-bottom:1px solid #e8edf3;">'
        f'<span style="font-size:0.92rem; color:{BRAND_BLUE}; font-weight:700;">Largest Investment Drivers</span>'
        f"</div>"
        f'<table style="width:100%; border-collapse:collapse;">'
        f"<thead>"
        f'<tr style="background:#fafbfd; border-bottom:1px solid #e8edf3;">'
        f'<th style="padding:8px 12px; text-align:left; font-size:0.76rem; color:{OVERVIEW_LABEL_GRAY}; font-weight:600;">Equipment</th>'
        f'<th style="padding:8px 12px; text-align:right; font-size:0.76rem; color:{OVERVIEW_LABEL_GRAY}; font-weight:600;">CAPEX</th>'
        f'<th style="padding:8px 12px; text-align:right; font-size:0.76rem; color:{OVERVIEW_LABEL_GRAY}; font-weight:600;">Share</th>'
        f"</tr>"
        f"</thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        f"</table>"
        f"</div>"
    )


def _plant_capex_bar_chart(
    df: pd.DataFrame,
    *,
    category_col: str,
    value_col: str,
    value_title: str,
    height: int = 300,
    tooltip_extra: list | None = None,
    bar_color: str | None = None,
) -> alt.Chart | None:
    if df is None or df.empty or value_col not in df.columns:
        return None
    plot_df = df.copy()
    plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce").fillna(0.0)
    plot_df = plot_df[plot_df[value_col] > 0]
    if plot_df.empty:
        return None
    tooltips = [
        alt.Tooltip(f"{category_col}:N", title="Item"),
        alt.Tooltip(f"{value_col}:Q", title=value_title, format=",.2f"),
    ]
    if tooltip_extra:
        tooltips.extend(tooltip_extra)
    return (
        alt.Chart(plot_df)
        .mark_bar(color=bar_color or BRAND_BLUE, cornerRadiusEnd=3)
        .encode(
            y=alt.Y(f"{category_col}:N", sort="-x", title=None),
            x=alt.X(f"{value_col}:Q", title=value_title),
            tooltip=tooltips,
        )
        .properties(height=height)
    )


def _plant_network_capacity_context(scen_sel: dict, ctx: dict) -> dict[str, float | int]:
    infra = ctx.get("infrastructure", {}) if isinstance(ctx.get("infrastructure"), dict) else {}
    annual_feed_t_y = _safe_float(ctx.get("feed_mass_kg_per_year"), 0.0) / 1000.0
    spoke_cap_site = max(0.0, _safe_float(infra.get("pretreatment_capacity_t_y"), annual_feed_t_y))
    hub_cap_site = max(0.0, _safe_float(infra.get("hydro_capacity_t_y"), 0.0))
    hydro_tp = max(0.0, _safe_float(infra.get("transported_mass_t_per_year"), 0.0))

    if is_hub_spoke_mode(scen_sel):
        n_pretreatment = int(_safe_float(infra.get("required_spokes"), 0.0))
        n_hydromet = int(_safe_float(infra.get("required_hubs"), 0.0))
        hydromet_throughput = hydro_tp
    else:
        n_pretreatment = 1
        n_hydromet = 1
        hydromet_throughput = hydro_tp if hydro_tp > 0.0 else annual_feed_t_y

    pretreatment_installed = n_pretreatment * spoke_cap_site
    hydromet_installed = n_hydromet * hub_cap_site
    pretreatment_throughput = annual_feed_t_y

    pretreatment_util = (
        100.0 * pretreatment_throughput / pretreatment_installed if pretreatment_installed > 0.0 else 0.0
    )
    hydromet_util = (
        100.0 * hydromet_throughput / hydromet_installed if hydromet_installed > 0.0 else 0.0
    )
    if _safe_float(infra.get("pretreatment_utilization"), 0.0) > 0.0:
        pretreatment_util = _safe_float(infra.get("pretreatment_utilization"), 0.0) * 100.0
    if _safe_float(infra.get("hydro_utilization"), 0.0) > 0.0:
        hydromet_util = _safe_float(infra.get("hydro_utilization"), 0.0) * 100.0

    return {
        "is_hub_spoke": is_hub_spoke_mode(scen_sel),
        "pretreatment_sites": n_pretreatment,
        "hydromet_hubs": n_hydromet,
        "pretreatment_capacity_per_spoke_t_y": spoke_cap_site,
        "hydromet_capacity_per_hub_t_y": hub_cap_site,
        "pretreatment_util_pct": pretreatment_util,
        "hydromet_util_pct": hydromet_util,
        "pretreatment_installed_t_y": pretreatment_installed,
        "pretreatment_throughput_t_y": pretreatment_throughput,
        "hydromet_installed_t_y": hydromet_installed,
        "hydromet_throughput_t_y": hydromet_throughput,
        "hydromet_throughput_config_t_y": hydromet_throughput,
        "integrated_installed_t_y": pretreatment_installed,
        "integrated_throughput_t_y": pretreatment_throughput,
        "integrated_util_pct": pretreatment_util,
    }


def _plant_configuration_region_label(scen_sel: dict, ctx: dict) -> str:
    if is_hub_spoke_mode(scen_sel):
        infra = ctx.get("infrastructure", {}) if isinstance(ctx.get("infrastructure"), dict) else {}
        spoke_loc = str(infra.get("spoke_location", scen_sel.get("spoke_location", "-")))
        hub_loc = str(infra.get("hub_location", scen_sel.get("hub_location", "-")))
        spoke_label = region_display_label(spoke_loc)
        hub_label = region_display_label(hub_loc)
        if spoke_label == hub_label:
            return spoke_label
        return f"{spoke_label} · {hub_label}"
    return region_display_label(str(scen_sel.get("region", ctx.get("region", "-"))))


def _plant_configuration_lines(scen_sel: dict, ctx: dict) -> list[tuple[str, str]]:
    annual_feed_t_y = _safe_float(ctx.get("feed_mass_kg_per_year"), 0.0) / 1000.0
    hours_y = _safe_float(ctx.get("hours_per_year"), 0.0)
    region_v = _plant_configuration_region_label(scen_sel, ctx)

    return [
        ("Plant type", _plant_type_label(scen_sel, ctx)),
        ("Region", region_v),
        ("Annual recycling feed [t/y]", _fmt_metric(annual_feed_t_y, 0) if annual_feed_t_y > 0 else "—"),
        ("Operating hours [h/y]", _fmt_metric(hours_y, 0) if hours_y > 0 else "—"),
    ]


def _plant_infra_scaled_rem(rem: float) -> str:
    return f"{rem * PLANT_INFRA_PANEL_HEIGHT_SCALE:.3f}rem"


def _plant_infra_scaled_px(px: float) -> int:
    return int(round(px * PLANT_INFRA_PANEL_HEIGHT_SCALE))


def _plant_infra_panel_heading_html(title: str) -> str:
    title_esc = html_module.escape(title)
    return (
        f'<div style="font-size:{_plant_infra_scaled_rem(1.1)}; color:{BRAND_BLUE}; font-weight:700; '
        f'margin-bottom:{_plant_infra_scaled_px(10)}px;">'
        f"{title_esc}</div>"
    )


def _plant_configuration_fact_sheet_html(lines: list[tuple[str, str]]) -> str:
    rows = []
    for idx, (label, value) in enumerate(lines):
        border = "" if idx == len(lines) - 1 else f"border-bottom:1px solid #e8edf3;"
        rows.append(
            f'<div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px; '
            f'padding:{_plant_infra_scaled_px(4)}px 0; {border}">'
            f'<span style="font-size:{_plant_infra_scaled_rem(0.76)}; color:{OVERVIEW_LABEL_GRAY}; '
            f'font-weight:500; line-height:1.3;">'
            f"{html_module.escape(label)}</span>"
            f'<span style="font-size:{_plant_infra_scaled_rem(0.82)}; color:#3d4f63; font-weight:600; '
            f'text-align:right; line-height:1.3;">'
            f"{html_module.escape(value)}</span>"
            f"</div>"
        )
    body = "".join(rows)
    pad = _plant_infra_scaled_px(6)
    pad_x = _plant_infra_scaled_px(10)
    return (
        f'<div class="libra-infra-fact-sheet" style="background:#f8fafc; border-radius:8px; '
        f'padding:{pad}px {pad_x}px;">{body}</div>'
    )


def _plant_infra_overview_column_height_px() -> int:
    base = PLANT_INFRA_MAP_HEIGHT_BASE_PX + PLANT_INFRA_MAP_CAPTION_PX + PLANT_INFRA_BORDER_CHROME_PX
    return int(round(base * PLANT_INFRA_PANEL_HEIGHT_SCALE))


def _plant_infra_config_panel_height_px() -> int:
    return int(round(PLANT_INFRA_CONFIG_PANEL_HEIGHT_BASE_PX * PLANT_INFRA_PANEL_HEIGHT_SCALE))


def _plant_infra_capacity_panel_height_px() -> int:
    total = _plant_infra_overview_column_height_px()
    raw = total - _plant_infra_config_panel_height_px() - PLANT_INFRA_PANEL_GAP_PX
    return max(260, raw - PLANT_INFRA_RIGHT_COLUMN_TRIM_PX)


def _plant_capex_composition_panel_height_px() -> int:
    return (
        PLANT_INFRA_BORDER_CHROME_PX
        + PLANT_CAPEX_COMPOSITION_PANEL_HEADING_CHROME_PX
        + PLANT_CAPEX_COMPOSITION_CHART_HEIGHT_PX
        + 12
    )


def _plant_capex_composition_layout_css() -> None:
    st.markdown(
        """
        <style>
            section[data-testid="stMain"] div.libra-capex-composition-row + div[data-testid="stHorizontalBlock"] {
                align-items: stretch !important;
            }
            section[data-testid="stMain"] div.libra-capex-composition-row + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                display: flex !important;
                flex-direction: column !important;
            }
            section[data-testid="stMain"] div.libra-capex-composition-row + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div {
                flex: 1 1 auto !important;
                width: 100% !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _plant_network_level_card_html(
    *,
    title: str,
    color: str,
    metrics: list[tuple[str, str]],
    utilization_pct: float,
) -> str:
    title_esc = html_module.escape(title)
    metric_blocks = []
    for label, value in metrics:
        if str(label).strip().lower() in {"utilization", "capacity utilization"}:
            continue
        metric_blocks.append(
            f'<div style="margin-bottom:{_plant_infra_scaled_px(8)}px;">'
            f'<div style="font-size:{_plant_infra_scaled_rem(0.76)}; color:{OVERVIEW_LABEL_GRAY}; '
            f'font-weight:600; line-height:1.2;">'
            f"{html_module.escape(label)}</div>"
            f'<div style="font-size:{_plant_infra_scaled_rem(0.98)}; color:{color}; font-weight:700; '
            f'line-height:1.25; margin-top:2px;">'
            f"{html_module.escape(value)}</div>"
            f"</div>"
        )
    pct_clamped = max(0.0, min(100.0, float(utilization_pct)))
    card_pad = _plant_infra_scaled_px(11)
    card_pad_x = _plant_infra_scaled_px(12)
    return (
        f'<div class="libra-infra-network-card" style="border:1px solid {OVERVIEW_CARD_BORDER}; border-radius:10px; '
        f'border-top:3px solid {color}; padding:{card_pad}px {card_pad_x}px; background:#fafbfd;">'
        f'<div style="font-size:{_plant_infra_scaled_rem(0.9)}; color:{color}; font-weight:700; '
        f'margin-bottom:{_plant_infra_scaled_px(10)}px;">{title_esc}</div>'
        f"{''.join(metric_blocks)}"
        f'<div style="margin-bottom:0;">'
        f'<div style="font-size:{_plant_infra_scaled_rem(0.76)}; color:{OVERVIEW_LABEL_GRAY}; '
        f'font-weight:600; line-height:1.2;">Capacity utilization</div>'
        f'<div style="font-size:{_plant_infra_scaled_rem(0.98)}; color:{color}; font-weight:700; '
        f'line-height:1.25; margin-top:2px;">'
        f"{_fmt_pct(pct_clamped)}</div>"
        f'<div style="height:{_plant_infra_scaled_px(8)}px; background:#e8edf3; border-radius:999px; '
        f'overflow:hidden; margin-top:{_plant_infra_scaled_px(6)}px;">'
        f'<div style="width:{pct_clamped:.1f}%; height:100%; background:{color}; border-radius:999px;"></div>'
        f"</div>"
        f"</div>"
        f"</div>"
    )


def _plant_infra_overview_layout_css() -> None:
    st.markdown(
        """
        <style>
            section[data-testid="stMain"] div.libra-infra-overview-row + div[data-testid="stHorizontalBlock"] {
                align-items: stretch !important;
            }
            section[data-testid="stMain"] div.libra-infra-overview-row + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                display: flex !important;
                flex-direction: column !important;
            }
            section[data-testid="stMain"] div.libra-infra-overview-row + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div {
                flex: 1 1 auto !important;
                width: 100% !important;
            }
            section[data-testid="stMain"] div.libra-infra-overview-row + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child [data-testid="stVerticalBlock"] {
                gap: 14px !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_plant_configuration_card(scen_sel: dict, ctx: dict, *, container_height: int | None = None) -> None:
    lines = _plant_configuration_lines(scen_sel, ctx)
    container_kwargs: dict = {"border": True}
    if container_height is not None:
        container_kwargs["height"] = int(container_height)
    with st.container(**container_kwargs):
        st.markdown(_plant_infra_panel_heading_html("Plant Configuration"), unsafe_allow_html=True)
        st.markdown(_plant_configuration_fact_sheet_html(lines), unsafe_allow_html=True)


def _render_plant_capacity_utilization_card(
    scen_sel: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
    *,
    container_height: int | None = None,
) -> None:
    network = _plant_network_capacity_context(scen_sel, ctx)
    container_kwargs: dict = {"border": True}
    if container_height is not None:
        container_kwargs["height"] = int(container_height)
    with st.container(**container_kwargs):
        st.markdown(_plant_infra_panel_heading_html("Capacity & Utilization"), unsafe_allow_html=True)
        if network["is_hub_spoke"]:
            pre_col, hyd_col = st.columns(2, gap="small")
            pretreatment_card = _plant_network_level_card_html(
                title="Pretreatment",
                color=INFRA_PRETREATMENT_COLOR,
                metrics=[
                    ("Spokes", str(int(network["pretreatment_sites"]))),
                    (
                        "Installed capacity per spoke",
                        _fmt_t_y(float(network["pretreatment_capacity_per_spoke_t_y"])),
                    ),
                    ("Annual throughput", _fmt_t_y(float(network["pretreatment_throughput_t_y"]))),
                ],
                utilization_pct=float(network["pretreatment_util_pct"]),
            )
            hydromet_card = _plant_network_level_card_html(
                title="Hydrometallurgical Refining",
                color=INFRA_HYDROMET_COLOR,
                metrics=[
                    ("Hubs", str(int(network["hydromet_hubs"]))),
                    (
                        "Installed capacity per hub",
                        _fmt_t_y(float(network["hydromet_capacity_per_hub_t_y"])),
                    ),
                    ("Annual throughput", _fmt_t_y(float(network["hydromet_throughput_t_y"]))),
                ],
                utilization_pct=float(network["hydromet_util_pct"]),
            )
            pre_col.markdown(pretreatment_card, unsafe_allow_html=True)
            hyd_col.markdown(hydromet_card, unsafe_allow_html=True)
            return

        st.markdown(
            _plant_network_level_card_html(
                title="Integrated Recycling Site",
                color=BRAND_BLUE,
                metrics=[
                    ("Installed capacity", _fmt_t_y(float(network["integrated_installed_t_y"]))),
                    ("Annual throughput", _fmt_t_y(float(network["integrated_throughput_t_y"]))),
                ],
                utilization_pct=float(network["integrated_util_pct"]),
            ),
            unsafe_allow_html=True,
        )


def _render_plant_capex_infrastructure_overview(
    scen_sel: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
) -> None:
    with st.container(border=True):
        _plant_capex_heading("Infrastructure Configuration")
        _plant_infra_overview_layout_css()
        st.markdown('<div class="libra-infra-overview-row"></div>', unsafe_allow_html=True)
        column_height = _plant_infra_overview_column_height_px()
        config_height = _plant_infra_config_panel_height_px()
        capacity_height = _plant_infra_capacity_panel_height_px()
        map_col, cfg_col = st.columns([1.75, 1.0], gap="medium")
        with map_col:
            with st.container(height=column_height, border=True):
                _render_infrastructure_world_map(
                    scen_sel,
                    ctx,
                    legend_below=True,
                    compact_height=PLANT_INFRA_MAP_HEIGHT_PX,
                )
        with cfg_col:
            _render_plant_configuration_card(scen_sel, ctx, container_height=config_height)
            _render_plant_capacity_utilization_card(
                scen_sel,
                ctx,
                steps_df,
                extras_all,
                container_height=capacity_height,
            )


def _render_plant_capex_executive_summary(
    econ: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
    scen_sel: dict,
) -> None:
    _plant_capex_heading("Capital Investment")
    cap = _capex_summary_row(econ.get("capex_df"))
    tci = cap.get("tci", 0.0)
    annual_feed_t_y = _safe_float(ctx.get("feed_mass_kg_per_year"), 0.0) / 1000.0
    investment_intensity = (tci / annual_feed_t_y) if annual_feed_t_y > 0 else 0.0

    kpis_investment = [
        ("Total Capital Investment (TCI)", _fmt_usd_compact(tci) if tci > 0 else "—", None),
        (
            "Investment Intensity",
            _fmt_usd_compact_k(investment_intensity) if investment_intensity > 0 else "—",
            "per t/y capacity",
        ),
        ("Working Capital", _fmt_usd_compact(cap.get("working_capital", 0.0)) if cap.get("working_capital", 0.0) > 0 else "—", None),
    ]
    inv_cols = st.columns(3)
    for col, (label, value, subtitle) in zip(inv_cols, kpis_investment):
        with col:
            st.markdown(
                _overview_primary_kpi_html(label, value, BRAND_BLUE, compact=True, subtitle=subtitle),
                unsafe_allow_html=True,
            )


def _render_plant_capex_composition(
    econ: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
    scen_sel: dict,
) -> None:
    _plant_capex_composition_layout_css()
    st.markdown('<div class="libra-capex-composition-row"></div>', unsafe_allow_html=True)
    panel_height = _plant_capex_composition_panel_height_px()
    left_col, right_col = st.columns(2, gap="medium")

    with left_col:
        with st.container(border=True, height=panel_height):
            st.markdown(_plant_infra_panel_heading_html("Investment Breakdown"), unsafe_allow_html=True)
            waterfall_fig = _build_plant_capex_waterfall_figure(econ)
            if waterfall_fig is not None:
                st.plotly_chart(waterfall_fig, width="stretch", config=PLOTLY_CHART_CONFIG)
            else:
                st.caption("No waterfall data available for this run.")

    with right_col:
        with st.container(border=True, height=panel_height):
            st.markdown(_plant_infra_panel_heading_html("Investment by Process Stage"), unsafe_allow_html=True)
            route_key = str(scen_sel.get("route", "") or "")
            equip_df = _collect_plant_equipment_capex(steps_df, extras_all, str(scen_sel.get("name", "")))
            step_capex = _plant_step_capex_table(equip_df)
            if step_capex.empty:
                st.caption("No process-stage CAPEX data available.")
            else:
                step_capex["process_stage"] = step_capex["Step"].astype(str).map(
                    lambda s: _plant_process_stage_display_label(_plant_process_stage(s, route_key))
                )
                stage_df = (
                    step_capex.groupby("process_stage", as_index=False)["capex_equip_step"]
                    .sum()
                    .sort_values("capex_equip_step", ascending=False)
                )
                total = float(stage_df["capex_equip_step"].sum())
                if total <= 0:
                    st.caption("No process-stage CAPEX data available.")
                else:
                    donut_fig = _build_plant_capex_process_stage_donut_figure(stage_df)
                    if donut_fig is not None:
                        st.plotly_chart(donut_fig, width="stretch", config=PLOTLY_CHART_CONFIG)
                    else:
                        st.caption("No process-stage CAPEX data available.")


def _render_plant_capex_equipment_drivers(
    steps_df: pd.DataFrame,
    extras_all: dict,
    scen_sel: dict,
) -> None:
    _plant_capex_heading("Purchased Equipment Breakdown")
    drivers = _plant_equipment_capex_drivers_df(steps_df, extras_all, scen_sel)
    if drivers.empty:
        st.caption("No equipment-level CAPEX detail available for this run.")
        return

    with st.container(border=True):
        fig = _build_plant_equipment_investment_breakdown_figure(drivers)
        if fig is not None:
            st.plotly_chart(fig, width="stretch", config=PLOTLY_CHART_CONFIG)
        else:
            st.caption("No equipment-level CAPEX detail available for this run.")


def _render_plant_capex_lower_section(
    econ: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
    scen_sel: dict,
) -> None:
    with st.container(border=True):
        _render_plant_capex_executive_summary(econ, ctx, steps_df, extras_all, scen_sel)
        st.divider()
        _render_plant_capex_composition(econ, steps_df, extras_all, scen_sel)
        st.divider()
        _render_plant_capex_equipment_drivers(steps_df, extras_all, scen_sel)


def _render_plant_capex_dashboard(
    scen_sel: dict,
    ctx: dict,
    econ: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
) -> None:
    _inject_overview_tab_styles()
    _render_plant_capex_infrastructure_overview(scen_sel, ctx, steps_df, extras_all)
    _render_plant_capex_lower_section(econ, ctx, steps_df, extras_all, scen_sel)


def _plotly_chart_selection_points(plot_event: Any) -> list[Any]:
    if plot_event is None:
        return []
    selection = getattr(plot_event, "selection", None)
    if selection is not None:
        return getattr(selection, "points", []) or (
            selection.get("points", []) if isinstance(selection, dict) else []
        )
    if isinstance(plot_event, dict):
        return plot_event.get("selection", {}).get("points", [])
    return []


def _plotly_point_customdata(point: Any) -> Any:
    if hasattr(point, "get"):
        return point.get("customdata")
    return getattr(point, "customdata", None)


def _infrastructure_transport_details_html(infra: dict) -> str | None:
    stream = str(infra.get("transport_stream", "-"))
    transported_t_y = float(infra.get("transported_mass_t_per_year") or 0.0)
    distance_km = float(infra.get("distance_km") or 0.0)
    if distance_km <= 0.0:
        return None
    transport_cost_kg = float(infra.get("transport_cost_per_kg_feed") or 0.0)
    transport_gwp_kg = float(infra.get("transport_gwp_kgco2e_per_kg_feed") or 0.0)
    return (
        f'<div style="margin-top:10px; padding:12px 14px; border:1px solid #D7E3F0; border-radius:10px; background:#F7FAFD;">'
        f'<div style="font-size:1rem; color:#003B75; font-weight:700; margin-bottom:6px;">{stream}</div>'
        f'<div style="font-size:0.92rem; color:#334155; line-height:1.55;">'
        f"Mass: {transported_t_y:,.0f} t/y<br>"
        f"Distance: {distance_km:,.0f} km<br>"
        f"Transport cost: ${transport_cost_kg:,.4f} / kg feed<br>"
        f"Transport GWP: {transport_gwp_kg:,.4f} kg CO2-eq / kg feed"
        f"</div></div>"
    )


def _render_infrastructure_world_map(
    scen_sel: dict,
    ctx: dict,
    *,
    compact: bool = False,
    compact_height: int | None = None,
    legend_below: bool = False,
) -> None:
    """Lightweight world-map view of pretreatment / hydro sites and transport."""
    if go is None:
        st.caption("Infrastructure map requires Plotly (see requirements.txt).")
        return
    try:
        from app_helpers.infrastructure_map import build_infrastructure_world_map_figure

        infra = ctx.get("infrastructure", {}) if isinstance(ctx.get("infrastructure"), dict) else {}
        fig = build_infrastructure_world_map_figure(
            infra,
            scen_sel,
            compact=compact,
            compact_height=compact_height,
            legend_below=legend_below,
        )
        if fig is not None:
            chart_key = "plant_infra_world_map" if legend_below else "infra_world_map_compact"
            plot_event = None
            try:
                plot_event = st.plotly_chart(
                    fig,
                    width="stretch",
                    config=PLOTLY_CHART_CONFIG,
                    key=chart_key,
                    on_select="rerun",
                    selection_mode="points",
                )
            except TypeError:
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CHART_CONFIG)

            if legend_below:
                transport_selected = False
                for point in _plotly_chart_selection_points(plot_event):
                    customdata = _plotly_point_customdata(point)
                    if customdata == "transport" or (
                        isinstance(customdata, (list, tuple)) and customdata and str(customdata[0]) == "transport"
                    ):
                        transport_selected = True
                        break
                transport_html = _infrastructure_transport_details_html(infra)
                if transport_selected and transport_html:
                    st.markdown(transport_html, unsafe_allow_html=True)
                elif transport_html:
                    st.caption("Click the transport route on the map to view stream details.")
    except Exception as exc:
        st.caption(f"Map preview unavailable: {type(exc).__name__}: {exc}")


def _render_overview_scenario_configuration_tile(
    scen_sel: dict,
    ctx: dict,
    *,
    route_label: str,
    refining_route_v: str,
    feed_t_y: float,
    op_hours_y: float,
) -> None:
    """Scenario configuration KPIs and compact hub-spoke location map."""
    _overview_tile_heading("Scenario Configuration")
    st.markdown(
        _overview_metrics_grid_html(
            ("Recycling Route", route_label),
            ("Refining Route", refining_route_v),
            ("Annual feed (t/y)", f"{feed_t_y:,.0f}"),
            ("Operating Hours (h/y)", f"{op_hours_y:,.0f}"),
            compact=True,
        ),
        unsafe_allow_html=True,
    )
    map_slot_px = _overview_scenario_map_slot_px()
    with st.container(height=map_slot_px, border=False):
        _render_infrastructure_world_map(
            scen_sel,
            ctx,
            compact=True,
            compact_height=map_slot_px,
        )


def _render_overview_economics_tile(kpi: dict, *, large: bool = False) -> None:
    """Economics summary tile for the Overview dashboard."""
    profit_color = "#1a7f37" if kpi["profit_kg"] > 0 else "#c0392b"
    _overview_tile_heading("Economics")
    st.markdown(
        _overview_primary_kpi_html(
            f"Profit (${_UNIT_PER_KG_FEED_PROCESSED})",
            _fmt_metric(kpi["profit_kg"], 2),
            profit_color,
            fill_tile=True,
            large=large,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        _overview_metric_row_html(
            (
                f"Total Recycling Costs (${_UNIT_PER_KG_FEED_PROCESSED})",
                _fmt_metric(kpi["trc_kg"], 2),
            ),
            (
                f"Revenue (${_UNIT_PER_KG_FEED_PROCESSED})",
                _fmt_metric(kpi["revenue_kg"], 2),
            ),
            compact=True,
            large=large,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        _overview_tile_bottom_status_block(
            "Profitable" if kpi["profit_y"] > 0 else "Economic deficit",
            positive=kpi["profit_y"] > 0,
            large=large,
        ),
        unsafe_allow_html=True,
    )


def _render_overview_environmental_tile(kpi: dict, *, large: bool = False) -> None:
    """Environmental summary tile for the Overview dashboard."""
    cf_color = "#1a7f37" if kpi["cf_kg"] < 0 else "#c0392b"
    _overview_tile_heading("Environmental")
    st.markdown(
        _overview_primary_kpi_html(
            f"GWP net (kg CO2-eq{_UNIT_PER_KG_FEED_PROCESSED})",
            _fmt_metric(kpi["cf_kg"], 2),
            cf_color,
            fill_tile=True,
            large=large,
        ),
        unsafe_allow_html=True,
    )
    g_mid1, g_mid2 = st.columns(2, gap="small")
    g_mid1.markdown(
        _overview_metric_html(
            f"GWP burden (kg CO2-eq{_UNIT_PER_KG_FEED_PROCESSED})",
            _fmt_metric(kpi["gwp_burden_kg"], 2),
            compact=True,
            large=large,
        ),
        unsafe_allow_html=True,
    )
    g_mid2.markdown(
        _overview_metric_html(
            f"GWP credit (kg CO2-eq{_UNIT_PER_KG_FEED_PROCESSED})",
            _fmt_metric(kpi["gwp_credit_kg"], 2),
            compact=True,
            large=large,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        _overview_tile_bottom_status_block(
            "Environmentally beneficial" if kpi["cf_y"] < 0 else "Environmental burden",
            positive=kpi["cf_y"] < 0,
            large=large,
        ),
        unsafe_allow_html=True,
    )


def _overview_product_chip_html(product: str, output_kg_per_kg: float) -> str:
    product_esc = format_chemistry_html(product)
    return f"""
    <div style="border:1px solid {OVERVIEW_CARD_BORDER}; border-radius:8px; padding:8px 10px; margin-bottom:6px; background:#fafbfd;">
        <div style="font-size:0.82rem; color:{OVERVIEW_LABEL_GRAY}; font-weight:600; line-height:1.2;">{product_esc}</div>
        <div style="font-size:1.05rem; color:{BRAND_BLUE}; line-height:1.2;">
            <span style="font-weight:700;">{_fmt_metric(output_kg_per_kg, 3)}</span>
            <span style="font-weight:400;"> kg{_UNIT_PER_KG_FEED_PROCESSED}</span>
        </div>
    </div>
    """


def _build_overview_pdf_payload(
    scen_sel: dict,
    ctx: dict,
    kpi: dict,
    econ: dict,
    steps_df: pd.DataFrame,
    *,
    libra: LibraRecoveryResult | None = None,
    generated_at: str,
) -> OverviewPdfPayload:
    def _pdf_map_marker(label: str, lat: float, lon: float, role: str) -> dict[str, str]:
        x_pct = max(2.0, min(98.0, (float(lon) + 180.0) / 360.0 * 100.0))
        y_pct = max(4.0, min(96.0, (90.0 - float(lat)) / 180.0 * 100.0))
        return {
            "label": label,
            "x": f"{x_pct:.2f}%",
            "y": f"{y_pct:.2f}%",
            "lat": f"{float(lat):.6f}",
            "lon": f"{float(lon):.6f}",
            "role": role,
        }

    def _pdf_map_markers(scen: dict) -> list[dict[str, str]]:
        if is_hub_spoke_mode(scen):
            spoke_loc = str(scen.get("spoke_location", "Germany") or "Germany")
            hub_loc = str(scen.get("hub_location", "Germany") or "Germany")
            spoke_lat, spoke_lon = resolve_location_coordinates(spoke_loc, scen, role="spoke")
            hub_lat, hub_lon = resolve_location_coordinates(hub_loc, scen, role="hub")
            markers = [_pdf_map_marker("Spoke", spoke_lat, spoke_lon, "spoke")]
            if abs(spoke_lat - hub_lat) > 1e-9 or abs(spoke_lon - hub_lon) > 1e-9:
                markers.append(_pdf_map_marker("Hub", hub_lat, hub_lon, "hub"))
            return markers
        lat, lon = resolve_integrated_site_coordinates(scen)
        return [_pdf_map_marker("Site", lat, lon, "site")]

    route_key = str(scen_sel.get("route", "") or "")
    route_label = ROUTE_DISPLAY_LABELS.get(route_key, route_key or "-")
    refining_route = (
        _black_mass_type_label(scen_sel, short=True) if scen_sel.get("route") == "mech" else "-"
    )
    feedstock_display = _black_mass_type_label(scen_sel, short=False)
    plant_concept = "Hub-spoke" if is_hub_spoke_mode(scen_sel) else "Integrated site"
    annual_feed_kg = _safe_float(kpi.get("mass_y", 0.0), 0.0)
    if libra is None:
        libra = compute_libra_recovery(ctx, steps_df, econ)

    process_flow_model = None
    try:
        hours_y = _hours_per_year(ctx)
        mf_long = _massflow_long_safe(steps_df, str(scen_sel.get("name", "scenario")))
        stage_card_df = _stage_cards_df(steps_df, mf_long, ctx, route=route_key)
        feed_input_kg_h = _safe_float(steps_df.iloc[0].get("In kg/h"), 0.0) if not steps_df.empty else 0.0
        process_flow_model = _build_mass_dashboard_pfd_model(
            stage_card_df,
            steps_df,
            mf_long,
            ctx,
            route_key,
            hours_y,
            feed_input_kg_h,
            float(libra.saleable_product_mass_kg_h or 0.0),
            econ=econ,
        )
    except Exception:
        process_flow_model = None

    grouped_products = _overview_products_grouped_by_stage(
        econ, annual_feed_kg, route_key, ctx=ctx, steps_df=steps_df
    )
    product_sections: list[tuple[str, list[tuple[str, str]]]] = []
    for section_title, stage_df in grouped_products.items():
        if stage_df.empty:
            continue
        items = [
            (
                str(row["Product"]),
                f"{_fmt_metric(float(row['Output (kg/kg feed)']), 3)} kg{_UNIT_PER_KG_FEED_PROCESSED}",
            )
            for _, row in stage_df.iterrows()
        ]
        product_sections.append((section_title, items))

    hierarchy = _build_overview_revenue_hierarchy(econ, route_key)
    sunburst_png = None

    recovery_summary = [
        (label, _fmt_recovery_pct(pct))
        for label, pct, _tip in _overview_recovery_summary_items(libra)
    ]

    from recovery_config import active_targets_for_route, component_targets, resolve_recovery_route

    rec_rt = resolve_recovery_route(ctx)
    active_keys = [t for t in active_targets_for_route(rec_rt) if t != "Graphite"] + ["Graphite"]
    active_items: list[tuple[str, float | None]] = []
    for key in active_keys:
        val = libra.element_recovery.get(key)
        if _recovery_target_visible(libra.recovery_df, key, val):
            active_items.append((f"{key} recovery", val))

    component_items: list[tuple[str, float | None]] = []
    for key in component_targets():
        label = _COMPONENT_RECOVERY_LABELS.get(key, key)
        val = libra.element_recovery.get(key)
        if _recovery_target_visible(libra.recovery_df, key, val):
            component_items.append((label, val))

    recovery_detail = [
        ("Active materials", active_items),
        ("Component materials", component_items),
    ]

    profit_color = "#1a7f37" if kpi["profit_kg"] > 0 else "#c0392b"
    cf_color = "#1a7f37" if kpi["cf_kg"] < 0 else "#c0392b"
    pdf_scenario_results = {"econ": econ, "kpi": kpi, "ctx": ctx, "steps_df": steps_df, "route_key": route_key}
    economic_breakdown = prepare_economic_breakdown(pdf_scenario_results)
    cost_driver_data = prepare_cost_driver_data(pdf_scenario_results)
    gwp_data = prepare_gwp_burden_credit_data(pdf_scenario_results)
    product_outputs = prepare_product_outputs(pdf_scenario_results)
    site_layout = prepare_site_layout_data(scen_sel, pdf_scenario_results)
    economic_insight = generate_economic_insight(
        cost_driver_data,
        _safe_float(economic_breakdown.get("total_costs"), 0.0),
        _safe_float(economic_breakdown.get("revenue"), 0.0),
        _safe_float(economic_breakdown.get("profit"), 0.0),
    )
    gwp_insight = generate_gwp_insight(
        list(gwp_data.get("burdens") or []),
        list(gwp_data.get("credits") or []),
        _safe_float(kpi.get("gwp_burden_kg"), 0.0),
        _safe_float(kpi.get("gwp_credit_kg"), 0.0),
        _safe_float(kpi.get("cf_kg"), 0.0),
    )
    output_note = generate_product_output_note()
    site_layout_note = generate_site_layout_note(str(site_layout.get("layout_type", "integrated")))
    pdf_region_label = _plant_configuration_region_label(scen_sel, ctx)

    return OverviewPdfPayload(
        scenario_name=str(scen_sel.get("name", "scenario")),
        generated_at=generated_at,
        region=pdf_region_label,
        route_label=route_label,
        refining_route=refining_route,
        feed_t_y=f"{_safe_float(ctx.get('feed_mass_kg_per_year'), 0.0) / 1000.0:,.0f}",
        op_hours_y=f"{_safe_float(ctx.get('hours_per_year'), 0.0):,.0f}",
        feedstock_display=feedstock_display,
        plant_concept=plant_concept,
        unit_per_kg=_UNIT_PER_KG_FEED_PROCESSED,
        profit_display=_fmt_metric(kpi["profit_kg"], 2),
        profit_color=profit_color,
        trc_display=_fmt_metric(kpi["trc_kg"], 2),
        revenue_display=_fmt_metric(kpi["revenue_kg"], 2),
        profit_status="Profitable" if kpi["profit_y"] > 0 else "Economic deficit",
        profit_status_color=profit_color,
        cf_display=_fmt_metric(kpi["cf_kg"], 2),
        cf_color=cf_color,
        gwp_burden_display=_fmt_metric(kpi["gwp_burden_kg"], 2),
        gwp_credit_display=_fmt_metric(kpi["gwp_credit_kg"], 2),
        env_status="Environmentally beneficial" if kpi["cf_y"] < 0 else "Environmental burden",
        env_status_color=cf_color,
        product_sections=product_sections,
        revenue_sunburst_png=sunburst_png,
        revenue_hierarchy=hierarchy,
        revenue_center_kg=_safe_float(kpi.get("revenue_kg"), 0.0),
        recovery_summary=recovery_summary,
        recovery_detail=recovery_detail,
        process_flow_model=process_flow_model,
        economic_breakdown=economic_breakdown,
        cost_driver_data=cost_driver_data,
        gwp_burden_data=list(gwp_data.get("burdens") or []),
        gwp_credit_data=list(gwp_data.get("credits") or []),
        product_outputs=product_outputs,
        site_layout=site_layout,
        economic_insight=economic_insight,
        gwp_insight=gwp_insight,
        output_note=output_note,
        site_layout_note=site_layout_note,
        map_markers=_pdf_map_markers(scen_sel),
    )


def _export_center_run_signature(pick_idx: int, scen_sel: dict) -> str:
    return f"{pick_idx}:{str(scen_sel.get('name', 'scenario'))}"


def _export_center_zip_signature(run_history: list) -> str:
    names = tuple(str((run.get("scen") or {}).get("name", "")) for run in run_history)
    return f"{len(run_history)}:{hash(names)}"


def _build_export_center_excel(
    scen_sel: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
    *,
    generated_at: str,
) -> tuple[bytes | None, str | None]:
    try:
        from Save import export_single_run_to_excel_bytes

        return export_single_run_to_excel_bytes(scen_sel, steps_df, extras_all, ctx), None
    except Exception as e:
        return None, f"Excel export failed: {type(e).__name__}: {e}"


def _build_export_center_pdf(
    scen_sel: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    econ: dict,
    kpi: dict,
    *,
    generated_at: str,
) -> tuple[bytes | None, str | None]:
    import importlib

    import dashboard_support.overview_pdf as overview_pdf_module
    import dashboard_support.pdf_export_html as pdf_export_html_module

    pdf_export_html_module = importlib.reload(pdf_export_html_module)
    overview_pdf_module = importlib.reload(overview_pdf_module)
    globals()["OverviewPdfPayload"] = overview_pdf_module.OverviewPdfPayload
    build_overview_pdf_bytes = overview_pdf_module.build_overview_pdf_bytes
    get_last_pdf_exporter = overview_pdf_module.get_last_pdf_exporter
    pdf_export_available = overview_pdf_module.pdf_export_available

    if not pdf_export_available():
        return None, (
            "PDF export requires `jinja2` and `playwright` for the HTML exporter. "
            "Install dependencies and restart Streamlit."
        )

    try:
        pdf_payload = _build_overview_pdf_payload(
            scen_sel,
            ctx,
            kpi,
            econ,
            steps_df,
            generated_at=generated_at,
        )
        pdf_bytes = build_overview_pdf_bytes(pdf_payload)
        return pdf_bytes, None
    except Exception as e:
        return None, f"PDF export failed: {type(e).__name__}: {e}"


def _render_export_center_tab(
    scen_sel: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    extras_all: dict,
    econ: dict,
    kpi: dict,
    pick_idx: int,
    ac: Any,
) -> None:
    from datetime import datetime, timezone, timedelta
    import importlib
    try:
        from zoneinfo import ZoneInfo
    except Exception:  # pragma: no cover - fallback for minimal Python builds
        ZoneInfo = None

    import dashboard_support.export_center as export_center_module

    export_center_module = importlib.reload(export_center_module)
    ExportCenterData = export_center_module.ExportCenterData
    ExportCenterHelpers = export_center_module.ExportCenterHelpers
    build_all_runs_zip_bytes = export_center_module.build_all_runs_zip_bytes
    render_export_center = export_center_module.render_export_center

    route_key = str(scen_sel.get("route", "") or "")
    if ZoneInfo is not None:
        generated_at_dt = datetime.now(ZoneInfo("Europe/Berlin"))
    else:
        generated_at_dt = datetime.now(timezone.utc) + timedelta(hours=2)
    generated_at = generated_at_dt.strftime("%Y-%m-%d %H:%M")
    run_sig = _export_center_run_signature(pick_idx, scen_sel)
    cache_key = f"libra_export_artifacts:{run_sig}"
    run_history = st.session_state.get("run_history", []) or []
    zip_key = f"libra_export_zip:{_export_center_zip_signature(run_history)}"

    artifacts = st.session_state.get(cache_key) or {"excel": None, "pdf": None, "warnings": []}

    zip_error = st.session_state.pop(f"{zip_key}_error", None)
    if zip_error:
        st.warning(f"Batch export failed: {zip_error}")

    artifacts = st.session_state.get(cache_key) or artifacts
    if artifacts:
        for warning in artifacts.get("warnings", []):
            st.warning(warning)

    export_action = render_export_center(
        ExportCenterData(
            scen_sel=scen_sel,
            ctx=ctx,
            route_label=ROUTE_DISPLAY_LABELS.get(route_key, route_key or "-"),
            feedstock_label=_black_mass_type_label(scen_sel, short=False),
            excel_bytes=artifacts.get("excel") if artifacts else None,
            pdf_bytes=artifacts.get("pdf") if artifacts else None,
            all_runs_zip_bytes=st.session_state.get(zip_key) if len(run_history) > 1 else None,
            all_runs_count=len(run_history),
            generated_at=generated_at,
            helpers=ExportCenterHelpers(
                overview_section_heading=_overview_section_heading,
                log_download=ac.log_download,
            ),
        )
    )

    if export_action == "excel":
        with st.spinner("Generating Excel workbook..."):
            excel_bytes, warning = _build_export_center_excel(
                scen_sel,
                ctx,
                steps_df,
                extras_all,
                generated_at=generated_at,
            )
            artifacts["excel"] = excel_bytes
            artifacts["warnings"] = [
                w for w in artifacts.get("warnings", []) if not str(w).startswith("Excel export failed:")
            ]
            if warning:
                artifacts["warnings"].append(warning)
            st.session_state[cache_key] = artifacts
        st.rerun()

    if export_action == "pdf":
        with st.spinner("Generating Executive Summary PDF..."):
            pdf_bytes, warning = _build_export_center_pdf(
                scen_sel,
                ctx,
                steps_df,
                econ,
                kpi,
                generated_at=generated_at,
            )
            artifacts["pdf"] = pdf_bytes
            artifacts["warnings"] = [
                w for w in artifacts.get("warnings", []) if not str(w).startswith("PDF export")
            ]
            if warning:
                artifacts["warnings"].append(warning)
            st.session_state[cache_key] = artifacts
        st.rerun()

    if export_action == "zip" and len(run_history) > 1:
        with st.spinner(f"Building batch export ({len(run_history)} runs)..."):
            try:
                st.session_state[zip_key] = build_all_runs_zip_bytes(run_history)
            except Exception as e:
                st.session_state[zip_key] = None
                st.session_state[f"{zip_key}_error"] = f"{type(e).__name__}: {e}"
        st.rerun()


def _overview_section_heading(title: str) -> None:
    st.subheader(title)


def _overview_primary_kpi_html(
    label: str,
    value: str,
    color: str,
    *,
    compact: bool = False,
    fill_tile: bool = False,
    large: bool = False,
    subtitle: str | None = None,
) -> str:
    label_esc = html_module.escape(label)
    value_esc = html_module.escape(str(value)).replace("$", "&#36;")
    if subtitle:
        subtitle_content = html_module.escape(subtitle)
    elif compact:
        subtitle_content = "&nbsp;"
    else:
        subtitle_content = None
    subtitle_html = ""
    if subtitle_content is not None:
        subtitle_html = (
            f'<div style="font-size:0.78rem; color:{OVERVIEW_LABEL_GRAY}; font-weight:500; '
            f'line-height:1.2; margin-top:3px;">{subtitle_content}</div>'
        )
    if fill_tile:
        if large:
            pad, margin, label_size, value_size = (
                "18px 20px",
                "0 0 6px 0",
                "1.08rem",
                "2.9rem",
            )
        else:
            pad, margin, label_size, value_size = (
                "12px 14px",
                "0 0 4px 0",
                OVERVIEW_TILE_PRIMARY_LABEL_REM,
                OVERVIEW_TILE_PRIMARY_VALUE_REM,
            )
        outer_class = "libra-overview-tile-primary-kpi-fill"
    elif compact:
        pad, margin, label_size, value_size = "7px 10px", "0 0 2px 0", "0.82rem", "1.85rem"
        outer_class = ""
    else:
        pad, margin, label_size, value_size = "14px 16px", "6px 0 10px 0", "1.05rem", "2.35rem"
        outer_class = ""
    class_attr = f' class="{outer_class}"' if outer_class else ""
    return (
        f'<div{class_attr}>'
        f'<div style="border:1px solid {OVERVIEW_CARD_BORDER}; border-radius:10px; padding:{pad}; margin:{margin}; background:#fafbfd;">'
        f'<div style="font-size:{label_size}; color:{OVERVIEW_LABEL_GRAY}; font-weight:600; line-height:1.25;">{label_esc}</div>'
        f'<div style="font-size:{value_size}; color:{color}; font-weight:800; line-height:1.05; margin-top:2px;">{value_esc}</div>'
        f"{subtitle_html}"
        f"</div></div>"
    )


def _black_mass_type_label(scen: dict, *, short: bool = False) -> str:
    labels = FEEDSTOCK_TYPE_SHORT_LABELS if short else FEEDSTOCK_TYPE_LABELS
    ft = str(scen.get("feedstock_type", "") or "").strip().lower()
    if ft in labels:
        return labels[ft]
    inferred = _infer_feedstock_type_from_feed(scen.get("feed") or [])
    return labels.get(inferred, "-")


def _variant_label_from_info(info: dict) -> str:
    level = str(info.get("level") or "").strip().lower()
    chem = str(info.get("chemistry") or "").strip()
    geom = str(info.get("geometry") or "").strip().replace("_", " ")
    base = f"{chem} {geom}".strip() if (chem or geom) else str(info.get("cell_id") or "").strip()
    return f"{base} ({level})" if level else base


def _parse_comp_key(k: str) -> tuple[str, str, str]:
    s = str(k)
    if s.startswith("cell:"):
        rest = s.split(":", 1)[1]
        if ":" in rest:
            comp, mat = rest.split(":", 1)
            return "Cell", comp.strip(), mat.strip()
        return "Cell", "Cell", rest.strip()
    if s.startswith("module:"):
        return "Module", "", s.split(":", 1)[1].strip()
    if s.startswith("pack:"):
        return "Pack", "", s.split(":", 1)[1].strip()
    return "Other", "", s.strip()


_FEEDSTOCK_BASIS_ORDER = {"Cell": 0, "Module": 1, "Pack": 2, "Other": 9}
_FEEDSTOCK_COMPONENT_ORDER = {
    "Cathode": 0,
    "Anode": 1,
    "Separator": 2,
    "Electrolyte": 3,
    "Packing Container": 4,
    "Cell": 5,
    "": 6,
}
_FEEDSTOCK_MATERIAL_ORDER = {
    "Cathode": {
        "Li": 0,
        "Ni": 1,
        "Mn": 2,
        "Co": 3,
        "Fe": 4,
        "P": 5,
        "O": 6,
        "Aluminium": 7,
        "Binder Cathode": 8,
        "Carbon Black Cathode": 9,
    },
    "Anode": {
        "Graphite": 0,
        "Copper": 1,
        "Binder Anode": 2,
        "Carbon Black Anode": 3,
    },
    "Separator": {"PP": 0},
    "Electrolyte": {"LiPF6/EC:EMC 3:7": 0},
    "Packing Container": {
        "Nickel-plated steel": 0,
        "Aluminium": 1,
        "Polyethylene-laminated aluminium foil": 2,
    },
    "": {
        "Al": 0,
        "Steel": 1,
        "Fe": 2,
        "Cu": 3,
        "Plastic": 4,
        "Electronics": 5,
        "Other/Waste": 6,
    },
}


def _feedstock_sort_values(row) -> tuple[int, int, int, str]:
    basis = str(row.get("Basis", "")).strip()
    component = str(row.get("Component", "")).strip()
    material = str(row.get("Material", "")).strip()
    basis_rank = _FEEDSTOCK_BASIS_ORDER.get(basis, 99)
    component_rank = _FEEDSTOCK_COMPONENT_ORDER.get(component, 98)
    material_rank = _FEEDSTOCK_MATERIAL_ORDER.get(component, {}).get(
        material,
        _FEEDSTOCK_MATERIAL_ORDER.get("", {}).get(material, 999),
    )
    return basis_rank, component_rank, material_rank, material.lower()


def _sort_feedstock_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    sort_values = out.apply(_feedstock_sort_values, axis=1)
    out["_basis_sort"] = [x[0] for x in sort_values]
    out["_component_sort"] = [x[1] for x in sort_values]
    out["_material_sort"] = [x[2] for x in sort_values]
    out["_material_alpha"] = [x[3] for x in sort_values]
    out = out.sort_values(
        ["_basis_sort", "_component_sort", "_material_sort", "_material_alpha"],
        kind="mergesort",
    )
    return out.drop(columns=["_basis_sort", "_component_sort", "_material_sort", "_material_alpha"])


def _build_feedstock_variant_pivot(ctx: dict) -> pd.DataFrame:
    details = list((ctx or {}).get("feed_details", []) or [])
    rows: list[dict] = []
    for info in details:
        if not isinstance(info, dict):
            continue
        units_y = _safe_float(info.get("units_per_year"), 0.0)
        comp = info.get("comp_abs_kg_per_unit") or {}
        if units_y <= 0 or not isinstance(comp, dict) or not comp:
            continue

        variant = _variant_label_from_info(info)
        for key, kg_per_unit in comp.items():
            kg_y = _safe_float(kg_per_unit, 0.0) * units_y
            if kg_y <= 0:
                continue
            basis, component, material = _parse_comp_key(str(key))
            rows.append(
                {
                    "Basis": basis,
                    "Component": component,
                    "Material": material,
                    "CellVariant": variant,
                    "kg/year": kg_y,
                }
            )

    if not rows:
        return pd.DataFrame(columns=["Basis", "Component", "Material", "Unit", "Total kg/year"])

    raw = pd.DataFrame(rows)
    pivot = (
        raw.assign(Unit="kg")
        .pivot_table(
            index=["Basis", "Component", "Material", "Unit"],
            columns="CellVariant",
            values="kg/year",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    base_cols = ["Basis", "Component", "Material", "Unit"]
    variant_cols = [c for c in pivot.columns if c not in base_cols]
    pivot["Total kg/year"] = pivot[variant_cols].sum(axis=1)
    return _sort_feedstock_df(pivot)


def _build_output_value_emission_df(econ: dict) -> pd.DataFrame:
    """Combine revenue output lines + credit output lines into one signed table."""
    revenue_raw = econ.get("revenue_raw", {}) if isinstance(econ.get("revenue_raw", {}), dict) else {}
    credits_raw = econ.get("credits_raw", {}) if isinstance(econ.get("credits_raw", {}), dict) else {}

    rev_lines = pd.DataFrame(revenue_raw.get("output_lines", []) or [])
    cred_lines = pd.DataFrame(credits_raw.get("output_lines", []) or [])

    if rev_lines.empty:
        rev_df = pd.DataFrame(columns=["step_name", "item", "category", "Quantity", "Quantity unit", "revenue_per_y"])
    else:
        rr = rev_lines.copy()
        rr["qty_kg_y"] = pd.to_numeric(rr.get("qty_kg_y", 0.0), errors="coerce").fillna(0.0)
        rr["amount_per_y"] = pd.to_numeric(rr.get("amount_per_y", 0.0), errors="coerce").fillna(0.0)
        rr["economic_type"] = rr.get("economic_type", "").astype(str).str.strip().str.lower()
        rr["category"] = rr.get("category", "").astype(str).str.strip().str.lower()
        rr["revenue_per_y"] = rr["amount_per_y"].where(rr["economic_type"] == "revenue", -rr["amount_per_y"])
        rr["Quantity"] = rr["qty_kg_y"]
        rr["Quantity unit"] = "kg/y"
        rev_df = rr[["step_name", "item", "category", "Quantity", "Quantity unit", "revenue_per_y"]]

    if cred_lines.empty:
        cred_df = pd.DataFrame(columns=["step_name", "item", "category", "Quantity", "Quantity unit", "credit_kgco2eq_per_y"])
    else:
        cc = cred_lines.copy()
        cc["qty_kg_y"] = pd.to_numeric(cc.get("qty_kg_y", 0.0), errors="coerce").fillna(0.0)
        cc["amount_kgco2e_per_y"] = pd.to_numeric(cc.get("amount_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0)
        cc["environmental_type"] = cc.get("environmental_type", "").astype(str).str.strip().str.lower()
        cc["category"] = cc.get("category", "").astype(str).str.strip().str.lower()
        cc["credit_kgco2eq_per_y"] = cc["amount_kgco2e_per_y"].where(
            cc["environmental_type"] == "credit", -cc["amount_kgco2e_per_y"]
        )
        cc["Quantity"] = cc["qty_kg_y"]
        cc["Quantity unit"] = "kg/y"
        cred_df = cc[["step_name", "item", "category", "Quantity", "Quantity unit", "credit_kgco2eq_per_y"]]

    out = pd.merge(
        rev_df,
        cred_df,
        on=["step_name", "item", "category", "Quantity", "Quantity unit"],
        how="outer",
    )
    if out.empty:
        return pd.DataFrame(
            columns=[
                "step_name",
                "item",
                "category",
                "Quantity",
                "Quantity unit",
                "revenue_per_y",
                "credit_kgco2eq_per_y",
            ]
        )

    out["revenue_per_y"] = pd.to_numeric(out.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
    out["credit_kgco2eq_per_y"] = pd.to_numeric(out.get("credit_kgco2eq_per_y", 0.0), errors="coerce").fillna(0.0)
    out["Quantity"] = pd.to_numeric(out.get("Quantity", 0.0), errors="coerce").fillna(0.0)
    out["Quantity unit"] = out.get("Quantity unit", "").fillna("")
    return out


def _top_n_with_other(df: pd.DataFrame, label_col: str, value_col: str, n: int = 10) -> pd.DataFrame:
    if df is None or df.empty or label_col not in df.columns or value_col not in df.columns:
        return pd.DataFrame(columns=[label_col, value_col])
    tmp = df[[label_col, value_col]].copy()
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce").fillna(0.0)
    tmp = tmp.groupby(label_col, as_index=False)[value_col].sum()
    tmp["abs_value"] = tmp[value_col].abs()
    tmp = tmp.sort_values("abs_value", ascending=False).drop(columns=["abs_value"])
    if len(tmp) <= max(1, int(n)):
        return tmp
    top = tmp.head(int(n)).copy()
    rest = tmp.iloc[int(n) :][value_col].sum()
    if abs(float(rest)) > 0.0:
        top = pd.concat([top, pd.DataFrame([{label_col: "Other", value_col: float(rest)}])], ignore_index=True)
    return top


def _merge_csv_label_lists(values: list[str]) -> str:
    out: set[str] = set()
    for value in values:
        for part in str(value or "").split(","):
            part = part.strip()
            if part:
                out.add(part)
    return ", ".join(sorted(out))


_PROCESS_ECON_DRIVER_MIN_SHARE_PCT = 0.5


def _group_step_driver_with_rounded_other(
    df: pd.DataFrame,
    label_col: str,
    value_col: str,
    *,
    ndigits: int = 2,
    min_share_pct: float = _PROCESS_ECON_DRIVER_MIN_SHARE_PCT,
    stage_col: str | None = None,
    members_detail_col: str | None = None,
) -> pd.DataFrame:
    out_cols = [label_col, value_col, "_other_members"]
    if stage_col:
        out_cols.append(stage_col)
    if members_detail_col:
        out_cols.append(members_detail_col)
    if df is None or df.empty or label_col not in df.columns or value_col not in df.columns:
        return pd.DataFrame(columns=out_cols)

    work_cols = [label_col, value_col]
    if stage_col and stage_col in df.columns:
        work_cols.append(stage_col)
    if members_detail_col and members_detail_col in df.columns:
        work_cols.append(members_detail_col)
    grouped = df[work_cols].copy()
    grouped[value_col] = pd.to_numeric(grouped[value_col], errors="coerce").fillna(0.0)
    agg_map: dict[str, object] = {value_col: "sum"}
    if stage_col and stage_col in grouped.columns:
        agg_map[stage_col] = "first"
    if members_detail_col and members_detail_col in grouped.columns:
        agg_map[members_detail_col] = lambda s: _merge_csv_label_lists(s.astype(str).tolist())
    grouped = grouped.groupby(label_col, as_index=False).agg(agg_map)

    def _rounds_to_zero(v: float) -> bool:
        return round(float(v), ndigits) == 0.0

    visible = grouped[~grouped[value_col].apply(_rounds_to_zero)].copy()
    rounded_zero = grouped[grouped[value_col].apply(_rounds_to_zero)].copy()

    other_members: list[str] = []
    other_detail_chunks: list[str] = []
    other_sum = 0.0

    def _collect_other_rows(sub: pd.DataFrame) -> None:
        nonlocal other_sum
        if sub.empty:
            return
        for _, row in sub.iterrows():
            other_members.append(str(row[label_col]))
            other_sum += float(row[value_col])
            if members_detail_col and members_detail_col in sub.columns:
                other_detail_chunks.append(str(row.get(members_detail_col, "")))

    _collect_other_rows(rounded_zero)

    visible = visible.sort_values(value_col, ascending=False)
    total_abs = float(visible[value_col].abs().sum())
    if float(min_share_pct) > 0.0 and total_abs > 0.0:
        share_pct = visible[value_col].abs() / total_abs * 100.0
        small_mask = share_pct < float(min_share_pct)
        _collect_other_rows(visible[small_mask])
        visible = visible[~small_mask]

    rows: list[dict[str, object]] = []
    for _, row in visible.iterrows():
        item = {
            label_col: row[label_col],
            value_col: float(row[value_col]),
            "_other_members": "",
        }
        if stage_col and stage_col in visible.columns:
            item[stage_col] = str(row[stage_col])
        if members_detail_col and members_detail_col in visible.columns:
            item[members_detail_col] = str(row[members_detail_col])
        rows.append(item)
    if other_members:
        item = {
            label_col: "Other",
            value_col: float(other_sum),
            "_other_members": ", ".join(other_members),
        }
        if stage_col:
            item[stage_col] = "Other"
        if members_detail_col:
            item[members_detail_col] = _merge_csv_label_lists(other_detail_chunks)
        rows.append(item)
    if not rows:
        return pd.DataFrame(columns=out_cols)
    return pd.DataFrame(rows)


_PROCESS_ECON_GWP_CHART_HEIGHT_PX = 360


def _manuf_value_per_y(econ: dict, key: str) -> float:
    manuf_df = econ.get("manuf_df")
    if isinstance(manuf_df, pd.DataFrame) and not manuf_df.empty:
        return _safe_float(manuf_df.iloc[0].get(key, 0.0), 0.0)
    if isinstance(manuf_df, dict):
        return _safe_float(manuf_df.get(key, 0.0), 0.0)
    return 0.0


def _process_econ_gwp_scenario_metrics(econ: dict, kpi: dict, mass_y: float) -> dict[str, float]:
    opex_step_df = _safe_df(econ.get("opex_step_df"))
    drc_y = float(
        pd.to_numeric(opex_step_df.get("cost_direct_total_per_y", 0.0), errors="coerce").fillna(0.0).sum()
    ) if not opex_step_df.empty else 0.0
    material_y = float(
        pd.to_numeric(opex_step_df.get("cost_materials_per_y", 0.0), errors="coerce").fillna(0.0).sum()
    ) if not opex_step_df.empty else 0.0
    utility_y = 0.0
    if not opex_step_df.empty:
        utility_y = float(
            pd.to_numeric(opex_step_df.get("cost_energy_per_y", 0.0), errors="coerce").fillna(0.0).sum()
            + pd.to_numeric(opex_step_df.get("cost_water_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
    labor_y = float(
        pd.to_numeric(opex_step_df.get("cost_labor_per_y", 0.0), errors="coerce").fillna(0.0).sum()
    ) if not opex_step_df.empty else 0.0
    maintenance_y = float(
        pd.to_numeric(opex_step_df.get("maintenance_per_y", 0.0), errors="coerce").fillna(0.0).sum()
    ) if not opex_step_df.empty else 0.0
    supplies_y = float(
        pd.to_numeric(opex_step_df.get("supplies_per_y", 0.0), errors="coerce").fillna(0.0).sum()
    ) if not opex_step_df.empty else 0.0
    depreciation_y = float(
        pd.to_numeric(opex_step_df.get("depreciation_per_y", 0.0), errors="coerce").fillna(0.0).sum()
    ) if not opex_step_df.empty else 0.0

    drc_kg = _per_kg_feed(drc_y, mass_y)
    material_kg = _per_kg_feed(material_y, mass_y)
    utility_kg = _per_kg_feed(utility_y, mass_y)
    labor_kg = _per_kg_feed(labor_y, mass_y)
    revenue_kg = _safe_float(kpi.get("revenue_kg"), 0.0)
    trc_kg = _safe_float(kpi.get("trc_kg"), 0.0)
    profit_kg = _safe_float(kpi.get("profit_kg"), 0.0)
    net_gwp_kg = _safe_float(kpi.get("cf_kg"), 0.0)
    gross_gwp_kg = _safe_float(kpi.get("gwp_burden_kg"), 0.0)
    credits_kg = _safe_float(kpi.get("gwp_credit_kg"), 0.0)

    wf_materials_y = _manuf_value_per_y(econ, "VI.A.1 Raw materials ($/y)") or material_y
    wf_utilities_y = _manuf_value_per_y(econ, "VI.A.2 Utilities ($/y)") or utility_y
    wf_other_variable_y = (
        _manuf_value_per_y(econ, "VI.A.4 Supervisory ($/y)")
        + _manuf_value_per_y(econ, "VI.A.6 Supplies ($/y)")
        + _manuf_value_per_y(econ, "VI.A.7 Laboratory ($/y)")
        + _manuf_value_per_y(econ, "VI.A.8 Patents ($/y)")
    ) or supplies_y
    wf_maintenance_y = _manuf_value_per_y(econ, "VI.A.5 Maintenance ($/y)") or maintenance_y
    wf_labor_y = _manuf_value_per_y(econ, "VI.A.3 Oper. labor ($/y)") or labor_y
    wf_plant_overhead_y = _manuf_value_per_y(econ, "VI.C Overhead ($/y)")
    wf_other_fixed_y = (
        _manuf_value_per_y(econ, "VI.B.2 Taxes ($/y)")
        + _manuf_value_per_y(econ, "VI.B.3 Insurance ($/y)")
        + _manuf_value_per_y(econ, "VI.B.4 Rent ($/y)")
        + _manuf_value_per_y(econ, "VI.B.5 Financing ($/y)")
        + _manuf_value_per_y(econ, "VII General ($/y)")
    )
    wf_capital_y = _manuf_value_per_y(econ, "VI.B.1 Depreciation ($/y)") or depreciation_y
    transport_y = _safe_float(kpi.get("transport_cost_y"), 0.0)
    wf_total_y = _safe_float(kpi.get("trc_y"), 0.0) or _manuf_value_per_y(econ, "VIII Total Product Cost ($/y)")
    if wf_total_y <= 0.0:
        wf_total_y = (
            wf_materials_y
            + wf_utilities_y
            + wf_other_variable_y
            + wf_maintenance_y
            + wf_labor_y
            + wf_plant_overhead_y
            + wf_other_fixed_y
            + wf_capital_y
        )

    revenue_raw = econ.get("revenue_raw", {}) if isinstance(econ.get("revenue_raw"), dict) else {}
    gross_revenue_y = _safe_float(revenue_raw.get("revenue_total_per_y", 0.0), 0.0)
    output_cost_y = _safe_float(revenue_raw.get("output_cost_total_per_y", 0.0), 0.0)
    if gross_revenue_y <= 0.0:
        gross_revenue_y = _safe_float(kpi.get("revenue_y"), 0.0) + output_cost_y

    return {
        "drc_kg": drc_kg,
        "material_kg": material_kg,
        "utility_kg": utility_kg,
        "labor_kg": labor_kg,
        "revenue_kg": revenue_kg,
        "trc_kg": trc_kg,
        "profit_kg": profit_kg,
        "gross_gwp_kg": gross_gwp_kg,
        "credits_kg": credits_kg,
        "net_gwp_kg": net_gwp_kg,
        "wf_materials_kg": _per_kg_feed(wf_materials_y, mass_y),
        "wf_utilities_kg": _per_kg_feed(wf_utilities_y, mass_y),
        "wf_other_variable_kg": _per_kg_feed(wf_other_variable_y, mass_y),
        "wf_maintenance_kg": _per_kg_feed(wf_maintenance_y, mass_y),
        "wf_labor_kg": _per_kg_feed(wf_labor_y, mass_y),
        "wf_plant_overhead_kg": _per_kg_feed(wf_plant_overhead_y, mass_y),
        "wf_other_fixed_kg": _per_kg_feed(wf_other_fixed_y, mass_y),
        "wf_capital_kg": _per_kg_feed(wf_capital_y, mass_y),
        "wf_transport_kg": _per_kg_feed(transport_y, mass_y),
        "wf_materials_process_kg": _per_kg_feed(max(0.0, wf_materials_y - transport_y), mass_y),
        "wf_total_kg": _per_kg_feed(wf_total_y, mass_y),
        "gross_revenue_kg": _per_kg_feed(gross_revenue_y, mass_y),
        "wf_residual_treatment_kg": _per_kg_feed(output_cost_y, mass_y),
    }


def _build_process_economics_step_df(
    steps_df: pd.DataFrame,
    econ: dict,
    ctx: dict,
    scen_sel: dict,
    mass_y: float,
) -> pd.DataFrame:
    opex_step_df = _safe_df(econ.get("opex_step_df"))
    burdens_step_df = _safe_df(econ.get("burdens_step_df"))
    mf_long = _massflow_long_safe(steps_df, str(scen_sel.get("name", "scenario")))
    route_key = str(scen_sel.get("route", "") or "")
    step_base = steps_df[["Step"]].copy() if "Step" in steps_df.columns else pd.DataFrame(columns=["Step"])
    if step_base.empty:
        return pd.DataFrame()

    p = step_base.rename(columns={"Step": "Process step"})
    p["Route/stage"] = p["Process step"].astype(str).map(lambda s: _process_stage(s, route_key))
    if not opex_step_df.empty and "step_name" in opex_step_df.columns:
        p = p.merge(opex_step_df, left_on="Process step", right_on="step_name", how="left")
    if not burdens_step_df.empty and "step_name" in burdens_step_df.columns:
        burden_cols = [
            c
            for c in [
                "emission_direct_total_kgco2e_per_y",
                "emission_materials_kgco2e_per_y",
                "emission_energy_kgco2e_per_y",
                "emission_water_kgco2e_per_y",
            ]
            if c in burdens_step_df.columns
        ]
        burden_merge = burdens_step_df[["step_name", *burden_cols]].rename(
            columns={
                "step_name": "Process step",
                "emission_direct_total_kgco2e_per_y": "GWP burden (kg CO2-eq/y)",
            }
        )
        p = p.merge(burden_merge, on="Process step", how="left")

    steps_energy = steps_df.copy()
    if "Step" in steps_energy.columns:
        steps_energy["Process step"] = steps_energy["Step"].astype(str)
        steps_energy["E_total_kWh_h"] = pd.to_numeric(steps_energy.get("E_kWh_h", 0.0), errors="coerce").fillna(0.0)
        steps_energy["E_thermal_kWh_h"] = pd.to_numeric(
            steps_energy.get("Thermal energy (kWh/h)", 0.0), errors="coerce"
        ).fillna(0.0)
        steps_energy["E_electric_kWh_h"] = (steps_energy["E_total_kWh_h"] - steps_energy["E_thermal_kWh_h"]).clip(lower=0.0)
        p = p.merge(
            steps_energy[["Process step", "E_electric_kWh_h", "E_thermal_kWh_h"]],
            on="Process step",
            how="left",
        )

    hours_y = _hours_per_year(ctx)
    p["Direct material cost ($/kg feed)"] = p.get("cost_materials_per_y", 0.0).apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    utility_per_y = (
        pd.to_numeric(p.get("cost_energy_per_y", 0.0), errors="coerce").fillna(0.0)
        + pd.to_numeric(p.get("cost_water_per_y", 0.0), errors="coerce").fillna(0.0)
    )
    labor_per_y = pd.to_numeric(p.get("cost_labor_per_y", 0.0), errors="coerce").fillna(0.0)
    maintenance_per_y = pd.to_numeric(p.get("maintenance_per_y", 0.0), errors="coerce").fillna(0.0)
    variable_operating_per_y = utility_per_y + labor_per_y + maintenance_per_y
    overhead_total_y = _manuf_value_per_y(econ, "VI.C Overhead ($/y)")
    variable_operating_sum_y = float(variable_operating_per_y.sum())
    if variable_operating_sum_y > 0.0:
        overhead_alloc_per_y = overhead_total_y * variable_operating_per_y / variable_operating_sum_y
    else:
        overhead_alloc_per_y = 0.0
    total_operating_per_y = variable_operating_per_y + overhead_alloc_per_y

    p["Utility cost ($/kg feed)"] = utility_per_y.apply(lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y))
    p["Labor cost ($/kg feed)"] = labor_per_y.apply(lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y))
    p["Maintenance cost ($/kg feed)"] = maintenance_per_y.apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    p["Plant overhead alloc ($/kg feed)"] = overhead_alloc_per_y.apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    p["Operating cost ($/kg feed)"] = p["Utility cost ($/kg feed)"] + p["Labor cost ($/kg feed)"]
    p["Total operating cost ($/kg feed)"] = total_operating_per_y.apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    p["DRC ($/kg feed)"] = p.get("cost_direct_total_per_y", 0.0).apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    p["Electricity demand (kWh/kg feed)"] = p.get("E_electric_kWh_h", 0.0).apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0) * hours_y, mass_y)
    )
    p["Thermal energy demand (kWh/kg feed)"] = p.get("E_thermal_kWh_h", 0.0).apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0) * hours_y, mass_y)
    )
    p["GWP burden (kg CO2-eq/kg feed)"] = p.get("GWP burden (kg CO2-eq/y)", 0.0).apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    materials_em_y = (
        pd.to_numeric(p.get("emission_materials_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0)
        + pd.to_numeric(p.get("emission_water_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0)
    )
    energy_em_y = pd.to_numeric(p.get("emission_energy_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0)
    p["GWP materials (kg CO2-eq/kg feed)"] = materials_em_y.apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    p["GWP energy (kg CO2-eq/kg feed)"] = energy_em_y.apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    credits_step_df = _safe_df(econ.get("credits_step_df"))
    residual_em_y = pd.Series(0.0, index=p.index, dtype=float)
    if not credits_step_df.empty and "step_name" in credits_step_df.columns:
        credit_cols = [c for c in ["burden_kgco2e_per_y"] if c in credits_step_df.columns]
        if credit_cols:
            credit_merge = credits_step_df[["step_name", *credit_cols]].rename(
                columns={"step_name": "Process step"}
            )
            p = p.merge(credit_merge, on="Process step", how="left")
            residual_em_y = pd.to_numeric(p.get("burden_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0)
    p["GWP residual treatment (kg CO2-eq/kg feed)"] = residual_em_y.apply(
        lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y)
    )
    direct_burden_kg = p["GWP burden (kg CO2-eq/kg feed)"].apply(_safe_float)
    p["GWP burden (kg CO2-eq/kg feed)"] = direct_burden_kg + p["GWP residual treatment (kg CO2-eq/kg feed)"]
    p["Step label"] = p["Process step"].astype(str).map(_compact_step_label)
    p["Main material inputs"] = ""
    p["Main outputs"] = ""
    if not mf_long.empty and "_step_context" in mf_long.columns:
        for i, step in p["Process step"].astype(str).items():
            s = mf_long[mf_long["_step_context"].astype(str) == step]
            if s.empty:
                continue
            if "Name Material added" in s.columns:
                inp = (
                    s[["Name Material added", "Materials added (kg/h)"]]
                    .dropna(subset=["Name Material added"])
                    .groupby("Name Material added", as_index=False)["Materials added (kg/h)"]
                    .sum()
                    .sort_values("Materials added (kg/h)", ascending=False)
                    .head(3)
                )
                p.at[i, "Main material inputs"] = ", ".join(inp["Name Material added"].astype(str).tolist())
            if "Name Output Separated" in s.columns:
                out = (
                    s[["Name Output Separated", "Output separated (kg/h)"]]
                    .dropna(subset=["Name Output Separated"])
                    .groupby("Name Output Separated", as_index=False)["Output separated (kg/h)"]
                    .sum()
                    .sort_values("Output separated (kg/h)", ascending=False)
                    .head(3)
                )
                p.at[i, "Main outputs"] = ", ".join(out["Name Output Separated"].astype(str).tolist())
    return p


def _process_econ_gwp_revenue_by_product_df(econ: dict, mass_y: float) -> pd.DataFrame:
    out_df = _build_output_value_emission_df(econ)
    if out_df.empty:
        return pd.DataFrame(columns=["Product", "value_per_kg"])
    df = out_df.copy()
    if "category" in df.columns:
        df = df[df["category"].astype(str).str.lower().str.strip() == "product"]
    df["revenue_per_y"] = pd.to_numeric(df.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
    df = df[df["revenue_per_y"] > 0]
    if df.empty:
        return pd.DataFrame(columns=["Product", "value_per_kg"])
    grouped = (
        df.groupby("item", as_index=False)["revenue_per_y"]
        .sum()
        .rename(columns={"item": "Product", "revenue_per_y": "value_per_kg_y"})
    )
    grouped["value_per_kg"] = grouped["value_per_kg_y"].apply(lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y))
    return grouped[["Product", "value_per_kg"]]


def _process_econ_gwp_credits_by_product_df(econ: dict, mass_y: float) -> pd.DataFrame:
    credits_item_df = _safe_df(econ.get("credits_item_df"))
    if credits_item_df.empty:
        out_df = _build_output_value_emission_df(econ)
        if out_df.empty:
            return pd.DataFrame(columns=["Product", "value_per_kg"])
        df = out_df.copy()
        df["credit_kgco2eq_per_y"] = pd.to_numeric(df.get("credit_kgco2eq_per_y", 0.0), errors="coerce").fillna(0.0)
        df = df[df["credit_kgco2eq_per_y"] > 0]
        if df.empty:
            return pd.DataFrame(columns=["Product", "value_per_kg"])
        grouped = (
            df.groupby("item", as_index=False)["credit_kgco2eq_per_y"]
            .sum()
            .rename(columns={"item": "Product", "credit_kgco2eq_per_y": "value_per_kg_y"})
        )
    else:
        df = credits_item_df.copy()
        amount_col = "amount_kgco2e_per_y" if "amount_kgco2e_per_y" in df.columns else None
        if amount_col is None:
            return pd.DataFrame(columns=["Product", "value_per_kg"])
        df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
        if "environmental_type" in df.columns:
            df = df[df["environmental_type"].astype(str).str.lower().str.strip() == "credit"]
        df = df[df[amount_col] > 0]
        if df.empty:
            return pd.DataFrame(columns=["Product", "value_per_kg"])
        grouped = (
            df.groupby("item", as_index=False)[amount_col]
            .sum()
            .rename(columns={"item": "Product", amount_col: "value_per_kg_y"})
        )
    grouped["value_per_kg"] = grouped["value_per_kg_y"].apply(lambda v: _per_kg_feed(_safe_float(v, 0.0), mass_y))
    return grouped[["Product", "value_per_kg"]]


def _process_econ_gwp_environmental_components(
    econ: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    mass_y: float,
    kpi: dict | None = None,
) -> dict[str, float]:
    burdens_step_df = _safe_df(econ.get("burdens_step_df"))
    net_gwp_summary = econ.get("net_gwp_summary", {}) if isinstance(econ.get("net_gwp_summary"), dict) else {}

    materials_y = 0.0
    water_y = 0.0
    energy_y = 0.0
    if not burdens_step_df.empty:
        materials_y = float(
            pd.to_numeric(burdens_step_df.get("emission_materials_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
        water_y = float(
            pd.to_numeric(burdens_step_df.get("emission_water_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
        energy_y = float(
            pd.to_numeric(burdens_step_df.get("emission_energy_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )

    transport_y = _safe_float((kpi or {}).get("transport_gwp_y"), 0.0)
    if transport_y <= 0.0:
        transport_y = _transport_step_gwp_y(econ, ctx)
    materials_y = max(0.0, materials_y - transport_y)

    hours_y = _hours_per_year(ctx)
    elec_kwh_y = 0.0
    thermal_kwh_y = 0.0
    if "Step" in steps_df.columns:
        steps_energy = steps_df.copy()
        steps_energy["E_total_kWh_h"] = pd.to_numeric(steps_energy.get("E_kWh_h", 0.0), errors="coerce").fillna(0.0)
        steps_energy["E_thermal_kWh_h"] = pd.to_numeric(
            steps_energy.get("Thermal energy (kWh/h)", 0.0), errors="coerce"
        ).fillna(0.0)
        steps_energy["E_electric_kWh_h"] = (
            steps_energy["E_total_kWh_h"] - steps_energy["E_thermal_kWh_h"]
        ).clip(lower=0.0)
        elec_kwh_y = float(steps_energy["E_electric_kWh_h"].sum() * hours_y)
        thermal_kwh_y = float(steps_energy["E_thermal_kWh_h"].sum() * hours_y)

    energy_total_kwh_y = elec_kwh_y + thermal_kwh_y
    if energy_y > 0.0 and energy_total_kwh_y > 0.0:
        electricity_y = energy_y * elec_kwh_y / energy_total_kwh_y
        thermal_y = energy_y * thermal_kwh_y / energy_total_kwh_y
    else:
        electricity_y = energy_y
        thermal_y = 0.0

    materials_y += water_y
    direct_inputs_y = _safe_float(net_gwp_summary.get("direct_inputs_total_kgco2e_per_y", 0.0), 0.0)
    output_burdens_y = _safe_float(net_gwp_summary.get("output_burdens_total_kgco2e_per_y", 0.0), 0.0)
    credits_y = _safe_float(net_gwp_summary.get("output_credits_total_kgco2e_per_y", 0.0), 0.0)
    gross_y = direct_inputs_y + output_burdens_y
    net_y = gross_y - credits_y

    direct_component_y = materials_y + electricity_y + thermal_y + transport_y
    if direct_component_y > 0.0 and direct_inputs_y > 0.0:
        scale = direct_inputs_y / direct_component_y
        materials_y *= scale
        electricity_y *= scale
        thermal_y *= scale
        transport_y *= scale

    return {
        "materials_kg": _per_kg_feed(materials_y, mass_y),
        "electricity_kg": _per_kg_feed(electricity_y, mass_y),
        "thermal_kg": _per_kg_feed(thermal_y, mass_y),
        "transport_kg": _per_kg_feed(transport_y, mass_y),
        "output_burdens_kg": _per_kg_feed(output_burdens_y, mass_y),
        "gross_gwp_kg": _per_kg_feed(gross_y, mass_y),
        "credits_kg": _per_kg_feed(credits_y, mass_y),
        "net_gwp_kg": _per_kg_feed(net_y, mass_y),
    }


def _build_process_econ_waterfall_figure(
    labels: list[str],
    values: list[float],
    measures: list[str],
    *,
    y_title: str,
    value_prefix: str = "",
    value_suffix: str = "",
    value_ndigits: int = 4,
) -> "go.Figure | None":
    if go is None or not labels:
        return None
    text = [f"{value_prefix}{_fmt_metric(v, value_ndigits)}{value_suffix}" for v in values]
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=measures,
            x=labels,
            y=values,
            connector={"line": {"color": OVERVIEW_CARD_BORDER}},
            increasing={"marker": {"color": "#7A8FA6"}},
            decreasing={"marker": {"color": "#6b7280"}},
            totals={"marker": {"color": "#4b5563"}},
            text=text,
            textposition="outside",
        )
    )
    fig.update_traces(cliponaxis=False)
    y_max = max(abs(v) for v in values if v is not None) if values else 0.0
    fig.update_layout(
        height=_PROCESS_ECON_GWP_CHART_HEIGHT_PX,
        margin=dict(l=48, r=20, t=56, b=104),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        xaxis_tickangle=-20,
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        title=y_title,
        range=[min(0.0, min(values + [0.0])) * 1.1, y_max * 1.22 if y_max > 0 else 1.0],
    )
    return fig


def _build_process_econ_horizontal_bar_figure(
    plot_df: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    value_title: str,
    value_prefix: str = "",
    value_suffix: str = "",
    value_ndigits: int = 2,
    bar_color: str | None = None,
    detail_col: str | None = "_other_members",
    steps_detail_col: str | None = None,
    other_bucket_label: str = "Steps",
    stage_col: str | None = "process_stage_short",
    color_by_stage: bool = False,
) -> "go.Figure | None":
    if go is None or plot_df is None or plot_df.empty:
        return None
    df = plot_df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)

    def _keep_row(row: pd.Series) -> bool:
        if round(float(row[value_col]), value_ndigits) != 0.0:
            return True
        if detail_col and detail_col in row.index:
            members = str(row.get(detail_col, "") or "").strip()
            if members:
                return True
        return abs(float(row[value_col])) > 1e-12

    df = df[df.apply(_keep_row, axis=1)]
    if df.empty:
        return None
    total = float(df[value_col].abs().sum())
    other_mask = df[label_col].astype(str) == "Other"
    other_df = df[other_mask]
    main_df = df[~other_mask].sort_values(value_col, ascending=True)
    if not other_df.empty:
        # Plotly horizontal bars: first y category at the bottom → "Other" as last bar (top-to-bottom).
        df = pd.concat([other_df, main_df], ignore_index=True)
    else:
        df = main_df
    hover_rows = []
    for _, row in df.iterrows():
        share = (abs(float(row[value_col])) / total * 100.0) if total > 0 else 0.0
        hover = (
            f"<b>{html_module.escape(str(row[label_col]))}</b><br>"
            f"{html_module.escape(value_title)}: {value_prefix}{_fmt_metric(float(row[value_col]), value_ndigits)}{value_suffix}<br>"
            f"Share: {share:.1f}%"
        )
        if color_by_stage and stage_col and stage_col in row.index:
            hover += f"<br>Process stage: {html_module.escape(str(row[stage_col]))}"
        if steps_detail_col and steps_detail_col in row.index:
            steps = str(row.get(steps_detail_col, "") or "").strip()
            if steps:
                hover += f"<br>Steps: {html_module.escape(steps)}"
        if detail_col and detail_col in row.index:
            members = str(row.get(detail_col, "") or "").strip()
            if members and str(row[label_col]) == "Other":
                bucket = "Materials" if steps_detail_col else other_bucket_label
                hover += f"<br>{html_module.escape(bucket)}: {html_module.escape(members)}"
            elif members and not steps_detail_col:
                hover += f"<br>{html_module.escape(other_bucket_label)}: {html_module.escape(members)}"
        hover_rows.append(hover)
    if color_by_stage and stage_col and stage_col in df.columns:
        bar_colors = [_plant_capex_process_stage_color(str(row[stage_col])) for _, row in df.iterrows()]
    else:
        bar_colors = bar_color or BRAND_BLUE
    fig = go.Figure(
        go.Bar(
            y=df[label_col].astype(str).tolist(),
            x=df[value_col].astype(float).tolist(),
            orientation="h",
            marker=dict(color=bar_colors, line=dict(color="#ffffff", width=1)),
            customdata=hover_rows,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )
    fig_height = max(_PROCESS_ECON_GWP_CHART_HEIGHT_PX, 28 * len(df))
    fig.update_layout(
        height=fig_height,
        margin=dict(l=16, r=24, t=12, b=40),
        showlegend=False,
        hovermode="y",
        hoverdistance=80,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=OVERVIEW_CARD_BORDER,
            font=dict(size=13, color=BRAND_BLUE),
        ),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, title=None, automargin=True)
    fig.update_yaxes(showgrid=False, zeroline=False, title=None, automargin=True)
    return fig


def _build_process_economics_waterfall_figure(metrics: dict[str, float]) -> "go.Figure | None":
    if go is None:
        return None

    transport_kg = float(metrics.get("wf_transport_kg", 0.0))
    materials_kg = float(metrics.get("wf_materials_process_kg", metrics.get("wf_materials_kg", 0.0)))
    cost_components = [
        materials_kg,
        float(metrics.get("wf_utilities_kg", 0.0)),
        float(metrics.get("wf_other_variable_kg", 0.0)),
        float(metrics.get("wf_maintenance_kg", 0.0)),
        float(metrics.get("wf_labor_kg", 0.0)),
        float(metrics.get("wf_plant_overhead_kg", 0.0)),
        float(metrics.get("wf_other_fixed_kg", 0.0)),
        float(metrics.get("wf_capital_kg", 0.0)),
    ]
    trc = float(metrics.get("trc_kg", 0.0))
    gross_revenue = float(metrics.get("gross_revenue_kg", metrics.get("revenue_kg", 0.0)))
    residual_treatment = float(metrics.get("wf_residual_treatment_kg", 0.0))
    profit = float(metrics.get("profit_kg", 0.0))

    labels = [
        "Materials",
        "Utilities",
        "Other variable costs",
        "Maintenance",
        "Labor",
        "Plant overhead",
        "Other fixed costs",
        "Annualized capital cost",
    ]
    if transport_kg > 1e-12:
        labels.append("Transport")
        cost_components.append(transport_kg)
    labels.append("TRC")
    values = [-c for c in cost_components] + [-trc]
    measures = ["relative"] * len(cost_components) + ["total"]
    text = [f"${_fmt_metric(c, 2)}" for c in cost_components] + [f"${_fmt_metric(trc, 2)}"]

    profit_color = "#1a7f37" if profit >= 0.0 else "#c0392b"
    x_categories = labels + ["Product Revenue"]
    if residual_treatment > 1e-12:
        x_categories.append("Residual treatment")
    x_categories.append("Profit")
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=measures,
            x=labels,
            y=values,
            connector={"line": {"color": OVERVIEW_CARD_BORDER}},
            increasing={"marker": {"color": "#7A8FA6"}},
            decreasing={"marker": {"color": "#7A8FA6"}},
            totals={"marker": {"color": "#4b5563"}},
            text=text,
            textposition="outside",
        )
    )
    fig.update_traces(cliponaxis=False)

    trc_idx = len(labels) - 1
    profit_idx = len(x_categories) - 1
    zero_line = dict(
        type="line",
        x0=-0.5,
        x1=len(x_categories) - 0.5,
        y0=0,
        y1=0,
        xref="x",
        yref="y",
        line=dict(color=OVERVIEW_CARD_BORDER, width=1),
        layer="below",
    )
    profit_line = dict(
        type="line",
        x0=trc_idx - 0.35,
        x1=profit_idx + 0.35,
        y0=profit,
        y1=profit,
        xref="x",
        yref="y",
        line=dict(color=profit_color, width=3.5, dash="dash"),
        layer="above",
    )

    y_vals = values + [0.0, gross_revenue]
    if residual_treatment > 1e-12:
        y_vals.append(-residual_treatment)
    y_vals.append(profit)
    y_min = min(y_vals)
    y_max = max(y_vals)
    y_pad = max(abs(y_min), abs(y_max), trc, gross_revenue) * 0.18
    fig.update_layout(
        height=_PROCESS_ECON_GWP_CHART_HEIGHT_PX,
        margin=dict(l=48, r=20, t=56, b=104),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        xaxis_tickangle=-20,
        shapes=[zero_line, profit_line],
        xaxis=dict(categoryorder="array", categoryarray=x_categories),
    )
    fig.add_trace(
        go.Bar(
            x=["Product Revenue"],
            y=[gross_revenue],
            marker_color=BRAND_BLUE,
            width=[0.64],
            text=[f"${_fmt_metric(gross_revenue, 2)}"],
            textposition="outside",
            hovertemplate="Product Revenue: %{y:.2f} $/kg feed<extra></extra>",
            showlegend=False,
        )
    )
    if residual_treatment > 1e-12:
        fig.add_trace(
            go.Bar(
                x=["Residual treatment"],
                y=[-residual_treatment],
                marker_color="#7A8FA6",
                width=[0.64],
                text=[f"${_fmt_metric(residual_treatment, 2)}"],
                textposition="outside",
                hovertemplate="Residual treatment: %{customdata:.2f} $/kg feed<extra></extra>",
                customdata=[residual_treatment],
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Bar(
            x=["Profit"],
            y=[profit],
            marker_color=profit_color,
            width=[0.64],
            text=[f"${_fmt_metric(profit, 2)}"],
            textposition="outside",
            hovertemplate="Profit: %{y:.2f} $/kg feed<extra></extra>",
            showlegend=False,
        )
    )
    fig.add_annotation(
        x="Profit",
        y=profit,
        text=f"Profit ${_fmt_metric(profit, 2)}",
        showarrow=False,
        yshift=14 if profit >= 0.0 else -14,
        font=dict(size=11, color=profit_color),
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor=profit_color,
        borderwidth=1,
        borderpad=4,
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        title="$/kg feed",
        range=[y_min - y_pad, y_max + y_pad],
    )
    return fig


def _build_process_environmental_waterfall_figure(components: dict[str, float]) -> "go.Figure | None":
    materials = float(components.get("materials_kg", 0.0))
    energy = float(components.get("electricity_kg", 0.0)) + float(components.get("thermal_kg", 0.0))
    transport = float(components.get("transport_kg", 0.0))
    output_burdens = float(components.get("output_burdens_kg", 0.0))
    gross = float(components.get("gross_gwp_kg", 0.0))
    credits = float(components.get("credits_kg", 0.0))
    net = float(components.get("net_gwp_kg", 0.0))
    if go is None:
        return None

    labels = ["Materials", "Energy", "Residual treatment"]
    values = [materials, energy, output_burdens]
    if transport > 1e-12:
        labels.append("Transport")
        values.append(transport)
    labels.append("GWP burden")
    values.append(gross)
    measures = ["relative"] * (len(values) - 1) + ["total"]
    text = [f"{_fmt_metric(v, 2)}" for v in values]

    net_color = "#1a7f37" if net <= 0.0 else "#c0392b"
    x_categories = labels + ["GWP credits", "Net GWP"]
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=measures,
            x=labels,
            y=values,
            connector={"line": {"color": OVERVIEW_CARD_BORDER}},
            increasing={"marker": {"color": "#7A8FA6"}},
            decreasing={"marker": {"color": "#7A8FA6"}},
            totals={"marker": {"color": "#4b5563"}},
            text=text,
            textposition="outside",
        )
    )
    fig.update_traces(cliponaxis=False)

    burden_idx = len(labels) - 1
    credits_idx = len(labels)
    net_idx = len(x_categories) - 1
    zero_line = dict(
        type="line",
        x0=-0.5,
        x1=len(x_categories) - 0.5,
        y0=0,
        y1=0,
        xref="x",
        yref="y",
        line=dict(color=OVERVIEW_CARD_BORDER, width=1),
        layer="below",
    )
    net_line = dict(
        type="line",
        x0=burden_idx - 0.35,
        x1=net_idx + 0.35,
        y0=net,
        y1=net,
        xref="x",
        yref="y",
        line=dict(color=net_color, width=3.5, dash="dash"),
        layer="above",
    )

    y_vals = values + [0.0, -credits, net]
    y_min = min(y_vals)
    y_max = max(y_vals)
    y_pad = max(abs(y_min), abs(y_max), gross, credits) * 0.18
    fig.update_layout(
        height=_PROCESS_ECON_GWP_CHART_HEIGHT_PX,
        margin=dict(l=48, r=20, t=56, b=104),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        xaxis_tickangle=-20,
        shapes=[zero_line, net_line],
        xaxis=dict(categoryorder="array", categoryarray=x_categories),
    )
    fig.add_trace(
        go.Bar(
            x=["GWP credits"],
            y=[-credits],
            marker_color=BRAND_BLUE,
            width=[0.64],
            text=[f"{_fmt_metric(credits, 2)}"],
            textposition="outside",
            hovertemplate="GWP credits: %{y:.2f} kg CO2-eq/kg feed<extra></extra>",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Bar(
            x=["Net GWP"],
            y=[net],
            marker_color=net_color,
            width=[0.64],
            text=[f"{_fmt_metric(net, 2)}"],
            textposition="outside",
            hovertemplate="Net GWP: %{y:.2f} kg CO2-eq/kg feed<extra></extra>",
            showlegend=False,
        )
    )
    fig.add_annotation(
        x="Net GWP",
        y=net,
        text=f"Net GWP {_fmt_metric(net, 2)}",
        showarrow=False,
        yshift=14 if net >= 0.0 else -14,
        font=dict(size=11, color=net_color),
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor=net_color,
        borderwidth=1,
        borderpad=4,
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        title="kg CO2-eq / kg feed",
        range=[y_min - y_pad, y_max + y_pad],
    )
    return fig


def _process_econ_gwp_step_driver_df(
    step_df: pd.DataFrame,
    value_col: str,
    *,
    value_ndigits: int = 2,
    min_share_pct: float = _PROCESS_ECON_DRIVER_MIN_SHARE_PCT,
) -> pd.DataFrame:
    stage_col = "process_stage_short"
    out_cols = ["Step label", value_col, "_other_members", stage_col]
    if step_df is None or step_df.empty or value_col not in step_df.columns:
        return pd.DataFrame(columns=out_cols)
    df = step_df[["Step label", value_col]].copy()
    if "Route/stage" in step_df.columns:
        df[stage_col] = (
            step_df["Route/stage"]
            .astype(str)
            .map(_plant_capex_process_stage_short_label)
            .values
        )
    else:
        df[stage_col] = "Other"
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    df = df[df[value_col].abs() > 1e-12]
    if df.empty:
        return pd.DataFrame(columns=out_cols)
    return _group_step_driver_with_rounded_other(
        df,
        "Step label",
        value_col,
        ndigits=value_ndigits,
        min_share_pct=min_share_pct,
        stage_col=stage_col,
    )


def _process_econ_material_by_item_driver_df(econ: dict, mass_y: float) -> pd.DataFrame:
    value_col = "Material cost ($/kg feed)"
    steps_col = "_step_members"
    raw = _safe_df(econ.get("opex_material_df"))
    if raw.empty or "item" not in raw.columns:
        return pd.DataFrame(columns=["Material", value_col, "_other_members", steps_col])
    work = raw.copy()
    work["cost_per_y"] = pd.to_numeric(work.get("cost_per_y", 0.0), errors="coerce").fillna(0.0)
    if "step_name" not in work.columns:
        work["step_name"] = ""
    work = work[work["cost_per_y"].abs() > 1e-12]
    if work.empty:
        return pd.DataFrame(columns=["Material", value_col, "_other_members", steps_col])

    rows: list[dict[str, object]] = []
    for item, grp in work.groupby("item"):
        step_labels = sorted(
            {
                str(_compact_step_label(step))
                for step in grp["step_name"].astype(str)
                if str(step).strip()
            }
        )
        rows.append(
            {
                "Material": format_chemistry_unicode(str(item)),
                value_col: _per_kg_feed(float(grp["cost_per_y"].sum()), mass_y),
                "_other_members": "",
                steps_col: ", ".join(step_labels),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["Material", value_col, "_other_members", steps_col])
    return _group_step_driver_with_rounded_other(
        pd.DataFrame(rows),
        "Material",
        value_col,
        ndigits=2,
        members_detail_col=steps_col,
    )


def _pdf_results_payload(scenario_results: dict | None) -> tuple[dict, dict, dict, pd.DataFrame, float]:
    data = scenario_results if isinstance(scenario_results, dict) else {}
    econ = data.get("econ", {}) if isinstance(data.get("econ", {}), dict) else data
    kpi = data.get("kpi", {}) if isinstance(data.get("kpi", {}), dict) else {}
    ctx = data.get("ctx", {}) if isinstance(data.get("ctx", {}), dict) else {}
    steps_df = _safe_df(data.get("steps_df"))
    mass_y = _safe_float(kpi.get("mass_y", ctx.get("feed_mass_kg_per_year", 0.0)), 0.0)
    return econ, kpi, ctx, steps_df, mass_y


def prepare_economic_breakdown(scenario_results: dict) -> dict[str, object]:
    econ, kpi, _ctx, _steps_df, mass_y = _pdf_results_payload(scenario_results)
    metrics = _process_econ_gwp_scenario_metrics(econ, kpi, mass_y)
    rows = [
        {"label": "Materials", "value": -_safe_float(metrics.get("wf_materials_process_kg"), 0.0)},
        {"label": "Utilities", "value": -_safe_float(metrics.get("wf_utilities_kg"), 0.0)},
        {"label": "Other variable costs", "value": -_safe_float(metrics.get("wf_other_variable_kg"), 0.0)},
        {"label": "Maintenance", "value": -_safe_float(metrics.get("wf_maintenance_kg"), 0.0)},
        {"label": "Labor", "value": -_safe_float(metrics.get("wf_labor_kg"), 0.0)},
        {"label": "Plant overhead", "value": -_safe_float(metrics.get("wf_plant_overhead_kg"), 0.0)},
        {"label": "Other fixed costs", "value": -_safe_float(metrics.get("wf_other_fixed_kg"), 0.0)},
        {"label": "Annualized capital cost", "value": -_safe_float(metrics.get("wf_capital_kg"), 0.0)},
    ]
    if _safe_float(metrics.get("wf_transport_kg"), 0.0) > 1e-12:
        rows.append({"label": "Transport", "value": -_safe_float(metrics.get("wf_transport_kg"), 0.0)})
    rows.append({"label": "TRC", "value": -_safe_float(metrics.get("trc_kg"), _safe_float(kpi.get("trc_kg"), 0.0))})
    rows.append({"label": "Product Revenue", "value": _safe_float(metrics.get("gross_revenue_kg"), _safe_float(kpi.get("revenue_kg"), 0.0))})
    residual = _safe_float(metrics.get("wf_residual_treatment_kg"), 0.0)
    if residual > 1e-12:
        rows.append({"label": "Residual treatment", "value": -residual})
    rows.append({"label": "Profit", "value": _safe_float(metrics.get("profit_kg"), _safe_float(kpi.get("profit_kg"), 0.0))})
    rows = [r for r in rows if abs(float(r.get("value", 0.0))) > 1e-12 or str(r.get("label")) in {"Revenue", "Profit"}]
    return {
        "waterfall": rows,
        "revenue": _safe_float(kpi.get("revenue_kg"), 0.0),
        "total_costs": _safe_float(kpi.get("trc_kg"), 0.0),
        "profit": _safe_float(kpi.get("profit_kg"), 0.0),
    }


def prepare_economic_balance_data(scenario_results: dict) -> dict[str, object]:
    return prepare_economic_breakdown(scenario_results)


def prepare_cost_driver_data(scenario_results: dict) -> list[dict[str, object]]:
    econ, kpi, _ctx, _steps_df, mass_y = _pdf_results_payload(scenario_results)
    metrics = _process_econ_gwp_scenario_metrics(econ, kpi, mass_y)
    rows = [
        ("Materials", _safe_float(metrics.get("wf_materials_process_kg"), 0.0)),
        ("Utilities", _safe_float(metrics.get("wf_utilities_kg"), 0.0)),
        ("Labor", _safe_float(metrics.get("wf_labor_kg"), 0.0)),
        ("Maintenance", _safe_float(metrics.get("wf_maintenance_kg"), 0.0)),
        ("Other variable costs", _safe_float(metrics.get("wf_other_variable_kg"), 0.0)),
        ("Plant overhead", _safe_float(metrics.get("wf_plant_overhead_kg"), 0.0)),
        ("Other fixed costs", _safe_float(metrics.get("wf_other_fixed_kg"), 0.0)),
        ("CAPEX and depreciation", _safe_float(metrics.get("wf_capital_kg"), 0.0)),
        ("Transport", _safe_float(metrics.get("wf_transport_kg"), 0.0)),
        ("Residual treatment", _safe_float(metrics.get("wf_residual_treatment_kg"), 0.0)),
    ]
    out = [{"label": label, "value": value} for label, value in rows if value > 1e-12]
    out.sort(key=lambda r: abs(float(r["value"])), reverse=True)
    return out[:5]


def prepare_top_cost_drivers(scenario_results: dict) -> list[dict[str, object]]:
    return prepare_cost_driver_data(scenario_results)


def prepare_gwp_burden_credit_data(scenario_results: dict) -> dict[str, list[dict[str, object]]]:
    econ, kpi, ctx, steps_df, mass_y = _pdf_results_payload(scenario_results)
    env_components = _process_econ_gwp_environmental_components(econ, ctx, steps_df, mass_y, kpi)
    burdens: list[dict[str, object]] = [
        {"label": "Materials", "value": _safe_float(env_components.get("materials_kg"), 0.0)},
        {
            "label": "Energy",
            "value": _safe_float(env_components.get("electricity_kg"), 0.0)
            + _safe_float(env_components.get("thermal_kg"), 0.0),
        },
        {"label": "Residual treatment", "value": _safe_float(env_components.get("output_burdens_kg"), 0.0)},
    ]

    credits_df = _process_econ_gwp_credits_by_product_df(econ, mass_y)
    credits: list[dict[str, object]] = []
    if not credits_df.empty and "Product" in credits_df.columns and "value_per_kg" in credits_df.columns:
        work = credits_df.copy()
        work["value_per_kg"] = pd.to_numeric(work["value_per_kg"], errors="coerce").fillna(0.0)
        work = work[work["value_per_kg"] > 1e-12].sort_values("value_per_kg", ascending=False).head(5)
        credits = [{"label": format_chemistry_unicode(str(r["Product"])), "value": float(r["value_per_kg"])} for _, r in work.iterrows()]
    return {"burdens": burdens, "credits": credits}


def prepare_gwp_burden_data(scenario_results: dict) -> list[dict[str, object]]:
    return list(prepare_gwp_burden_credit_data(scenario_results).get("burdens") or [])


def prepare_gwp_credit_data(scenario_results: dict) -> list[dict[str, object]]:
    return list(prepare_gwp_burden_credit_data(scenario_results).get("credits") or [])


def _fmt_pdf_flow_t_y(value: float) -> str:
    v = float(value)
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"


def prepare_product_outputs(scenario_results: dict) -> dict[str, object]:
    data = scenario_results if isinstance(scenario_results, dict) else {}
    econ, _kpi, ctx, _steps_df, mass_y = _pdf_results_payload(scenario_results)
    route_key = str(data.get("route_key", ctx.get("route", "")) or "")
    out_df = _build_output_value_emission_df(econ)
    if out_df.empty:
        return {"rows": [], "groups": [], "total_flow_t_y": 0.0, "total_revenue_per_y": 0.0}
    work = out_df.copy()
    if "category" in work.columns:
        work = work[work["category"].astype(str).str.lower().str.strip() == "product"]
    if "Quantity unit" in work.columns:
        work = work[work["Quantity unit"].astype(str).str.lower().str.strip() == "kg/y"]
    work["Quantity"] = pd.to_numeric(work.get("Quantity", 0.0), errors="coerce").fillna(0.0)
    work["revenue_per_y"] = pd.to_numeric(work.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
    work = work[work["Quantity"] > 1e-12]
    if work.empty:
        return {"rows": [], "groups": [], "total_flow_t_y": 0.0, "total_revenue_per_y": 0.0}
    if "step_name" not in work.columns:
        work["step_name"] = ""
    work["stage_short"] = work["step_name"].astype(str).map(lambda step: _overview_stage_short(_process_stage(step, route_key)))
    grouped = (
        work.groupby(["stage_short", "item"], as_index=False)
        .agg({"Quantity": "sum", "revenue_per_y": "sum"})
        .rename(columns={"item": "product"})
    )
    grouped["flow_t_y"] = grouped["Quantity"] / 1000.0
    grouped["output_kg_per_kg"] = grouped["Quantity"].apply(lambda value: _per_kg_feed(value, mass_y))
    grouped["revenue_kg"] = grouped["revenue_per_y"].apply(lambda value: _per_kg_feed(value, mass_y))
    grouped = grouped[grouped["revenue_per_y"] > 1e-12].copy()
    if grouped.empty:
        return {"rows": [], "groups": [], "total_flow_t_y": 0.0, "total_revenue_per_y": 0.0}
    grouped = grouped.sort_values("revenue_per_y", ascending=False)
    total_flow = float(grouped["flow_t_y"].sum())
    total_revenue = float(grouped["revenue_per_y"].clip(lower=0.0).sum())
    stage_defs = [
        ("Front-End", "Front-End Processing"),
        ("Mechanical", "Pyrometallurgy" if route_key == "pyro" else "Mechanical Treatment"),
        ("Hydro", "Hydrometallurgy"),
    ]
    groups: list[dict[str, object]] = []
    for stage_key, stage_title in stage_defs:
        stage_df = grouped[grouped["stage_short"].astype(str) == stage_key].sort_values("revenue_per_y", ascending=False)
        stage_rows = [
            {
                "product": str(r["product"]),
                "flow_t_y": float(r["flow_t_y"]),
                "flow_display": _fmt_pdf_flow_t_y(float(r["flow_t_y"])),
                "output_kg_per_kg": float(r["output_kg_per_kg"]),
                "output_display": _fmt_metric(float(r["output_kg_per_kg"]), 3),
                "revenue_per_y": float(r["revenue_per_y"]),
                "revenue_kg": float(r["revenue_kg"]),
                "revenue_display": _fmt_metric(float(r["revenue_kg"]), 2),
            }
            for _, r in stage_df.iterrows()
        ]
        groups.append({"key": stage_key, "title": stage_title, "rows": stage_rows})

    display = grouped.head(6).copy()
    if len(grouped) > 6:
        other_flow = float(grouped.iloc[6:]["flow_t_y"].sum())
        other_revenue = float(grouped.iloc[6:]["revenue_per_y"].sum())
        if other_flow > 1e-12 or abs(other_revenue) > 1e-12:
            display = pd.concat(
                [
                    display,
                    pd.DataFrame(
                        [
                            {
                                "product": "Other materials",
                                "Quantity": other_flow * 1000.0,
                                "revenue_per_y": other_revenue,
                                "flow_t_y": other_flow,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
    rows = [
        {
            "product": str(r["product"]),
            "flow_t_y": float(r["flow_t_y"]),
            "flow_display": _fmt_pdf_flow_t_y(float(r["flow_t_y"])),
            "revenue_per_y": float(r["revenue_per_y"]),
            "revenue_display": f"{float(r['revenue_per_y']):,.0f}",
        }
        for _, r in display.iterrows()
    ]
    return {"rows": rows, "groups": groups, "total_flow_t_y": total_flow, "total_revenue_per_y": total_revenue}


def prepare_site_layout_data(scenario_config: dict, scenario_results: dict) -> dict[str, object]:
    _econ, _kpi, ctx, _steps_df, _mass_y = _pdf_results_payload(scenario_results)
    scen = scenario_config if isinstance(scenario_config, dict) else {}
    infra = ctx.get("infrastructure", {}) if isinstance(ctx.get("infrastructure"), dict) else {}
    region = str(scen.get("region", ctx.get("region", "-")) or "-")
    if is_hub_spoke_mode(scen):
        distance = _safe_float(infra.get("distance_km"), _safe_float(scen.get("transport_distance_km"), 0.0))
        spokes_v = _safe_float(infra.get("required_spokes"), _safe_float(scen.get("required_spokes"), 0.0))
        hubs_v = _safe_float(infra.get("required_hubs"), _safe_float(scen.get("required_hubs"), 0.0))
        transport_mode = str(infra.get("transport_mode", scen.get("transport_mode", "")) or "").strip()
        return {
            "layout_type": "hub_spoke",
            "hub_count": int(hubs_v) if hubs_v > 0 else "n/a",
            "spokes": int(spokes_v) if spokes_v > 0 else "n/a",
            "transport_mode": transport_mode or "n/a",
            "average_distance_km": distance,
            "average_distance_display": f"{distance:,.0f} km" if distance > 0 else "n/a",
            "hub_location": str(infra.get("hub_location", scen.get("hub_location", "-"))),
            "spoke_location": str(infra.get("spoke_location", scen.get("spoke_location", "-"))),
        }
    return {
        "layout_type": "integrated",
        "title": "Integrated site",
        "subtitle": f"Region: {region}",
        "region": region,
    }


def _driver_phrase(rows: list[dict[str, object]]) -> str:
    labels = [str(r.get("label", "")).strip() for r in rows if str(r.get("label", "")).strip()]
    if not labels:
        return "available drivers"
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]} and {labels[1]}"


def generate_economic_insight(cost_driver_df: list[dict[str, object]], total_costs: float, revenue: float, profit: float) -> str:
    drivers = list(cost_driver_df or [])
    total_driver_value = sum(max(0.0, _safe_float(r.get("value"), 0.0)) for r in drivers)
    top_two = drivers[:2]
    share = 0.0
    if total_costs > 0:
        share = 100.0 * sum(max(0.0, _safe_float(r.get("value"), 0.0)) for r in top_two) / float(total_costs)
    if len(top_two) >= 2 and total_driver_value > 0:
        burden_sentence = (
            f"The main economic burden is driven by {_driver_phrase(top_two)}, "
            f"which together account for {share:.0f}% of total recycling costs."
        )
    elif len(top_two) == 1 and total_driver_value > 0:
        burden_sentence = (
            f"The main economic burden is driven by {_driver_phrase(top_two)}, "
            f"which accounts for {share:.0f}% of total recycling costs."
        )
    else:
        burden_sentence = "Economic driver data is not available for this scenario."
    if profit < 0:
        result_sentence = f"These costs exceed product revenue, resulting in a negative profit of {profit:.2f} $/kg feed."
    else:
        result_sentence = f"Product revenue exceeds total recycling costs, resulting in a positive profit of {profit:.2f} $/kg feed."
    del revenue
    return f"{burden_sentence} {result_sentence}"


def generate_gwp_insight(
    gwp_burden_df: list[dict[str, object]],
    gwp_credit_df: list[dict[str, object]],
    burden_total: float | None = None,
    credit_total: float | None = None,
    net_gwp: float | None = None,
) -> str:
    if net_gwp is None:
        net_gwp = _safe_float(burden_total, 0.0)
    burden_part = _driver_phrase(list(gwp_burden_df or [])[:2])
    credit_part = _driver_phrase(list(gwp_credit_df or [])[:2])
    if gwp_burden_df and gwp_credit_df:
        driver_sentence = f"The GWP burden is mainly driven by {burden_part}, while credits are dominated by {credit_part}."
    elif gwp_burden_df:
        driver_sentence = f"The GWP burden is mainly driven by {burden_part}."
    elif gwp_credit_df:
        driver_sentence = f"GWP credits are dominated by {credit_part}."
    else:
        driver_sentence = "GWP contributor data is not available for this scenario."
    if net_gwp < 0:
        balance_sentence = f"Overall, credits exceed burdens, resulting in a net GWP benefit of {abs(net_gwp):.2f} kg CO2-eq/kg feed."
    else:
        balance_sentence = f"Overall, burdens exceed credits, resulting in a net GWP burden of {net_gwp:.2f} kg CO2-eq/kg feed."
    del burden_total, credit_total
    return f"{driver_sentence} {balance_sentence}"


def generate_product_output_note() -> str:
    return "Outputs represent recoverable products available for battery remanufacturing."


def generate_output_note() -> str:
    return generate_product_output_note()


def generate_site_layout_note(site_layout_type: str) -> str:
    if str(site_layout_type) == "hub_spoke":
        return "Hub handles central refining. Spokes process sorted and preprocessed materials."
    return "All process steps are located at one recycling site."


_PROCESS_ECON_RESIDUAL_STAGE_SHORT = "Residual treatment"
_PROCESS_ECON_RESIDUAL_FILL = "#c0392b"
_PROCESS_ECON_RESIDUAL_TEXT = "#ffffff"
_PROCESS_ECON_RESIDUAL_LIGHT = ("#8b1a1a", "#a93226", "#c0392b", "#d35454", "#e07070", "#eba3a3")
_PROCESS_ECON_PRODUCT_GROUP_ORDER = ("Battery products", "Structural products", "Other products")
_PROCESS_ECON_PRODUCT_GROUP_STYLE: dict[str, dict[str, object]] = {
    "Battery products": {
        "fill": BRAND_BLUE,
        "light": ("#003B75", "#1a528f", "#3369a9", "#4d80c3", "#6697dd", "#80aef0", "#a3c4f5"),
        "text_on_fill": "#ffffff",
        "text_on_light": "#ffffff",
    },
    "Structural products": {
        "fill": "#C9A004",
        "light": ("#a68504", "#b89304", "#c9a004", "#d4ad1a", "#dfbc33", "#eacc5c", "#f0db85"),
        "text_on_fill": BRAND_BLUE,
        "text_on_light": BRAND_BLUE,
    },
    "Other products": {
        "fill": "#6b7280",
        "light": ("#4b5563", "#6b7280", "#9ca3af", "#b0b7c3", "#c5cad3", "#d8dce3", "#eceef2"),
        "text_on_fill": "#ffffff",
        "text_on_light": "#374151",
    },
}


def _process_econ_output_product_group(product: str) -> str:
    key = str(product).lower()
    structural = (
        "copper",
        "aluminium",
        "aluminum",
        "steel",
        "iron scrap",
        "electronic",
        "pack alu",
        "pack copper",
        "pack steel",
        "pack iron",
    )
    battery = (
        "graphite",
        "lithium",
        "nmc",
        "pcam",
        "fepo4",
        "fe po4",
        "precursor",
        "oxalate",
        "ferrous",
        "cobalt",
        "nickel sulfate",
        "manganese sulfate",
        "loaded resin",
    )
    if any(token in key for token in structural):
        return "Structural products"
    if any(token in key for token in battery):
        return "Battery products"
    return "Other products"


def _build_process_econ_product_group_hierarchy(
    lines_df: pd.DataFrame,
    *,
    product_col: str,
    value_col: str,
) -> dict | None:
    if lines_df is None or lines_df.empty or product_col not in lines_df.columns or value_col not in lines_df.columns:
        return None
    work = lines_df[[product_col, value_col]].copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0.0)
    work = work[work[value_col] > 0]
    if work.empty:
        return None
    work["group"] = work[product_col].astype(str).map(_process_econ_output_product_group)
    by_group_item = (
        work.groupby(["group", product_col], as_index=False)[value_col]
        .sum()
        .sort_values(["group", value_col], ascending=[True, False])
    )
    total_y = float(by_group_item[value_col].sum())
    if total_y <= 0:
        return None

    groups: list[dict[str, object]] = []
    products: list[dict[str, object]] = []
    for group_name in _PROCESS_ECON_PRODUCT_GROUP_ORDER:
        group_rows = by_group_item[by_group_item["group"].astype(str) == group_name].copy()
        if group_rows.empty:
            continue
        group_y = float(group_rows[value_col].sum())
        groups.append(
            {
                "group": group_name,
                "value_y": group_y,
                "share_pct": 100.0 * group_y / total_y,
            }
        )
        shade_idx = 0
        for _, row in group_rows.iterrows():
            val_y = float(row[value_col])
            products.append(
                {
                    "group": group_name,
                    "product": str(row[product_col]),
                    "value_y": val_y,
                    "share_pct": 100.0 * val_y / total_y,
                    "shade_idx": shade_idx,
                }
            )
            shade_idx += 1
    if not groups:
        return None
    return {"total_y": total_y, "groups": groups, "products": products}


def _process_econ_product_group_palette(group_name: str, index: int) -> str:
    style = _PROCESS_ECON_PRODUCT_GROUP_STYLE.get(group_name, _PROCESS_ECON_PRODUCT_GROUP_STYLE["Other products"])
    shades = style["light"]
    return str(shades[index % len(shades)])


def _process_econ_product_group_sunburst_figure(
    hierarchy: dict,
    *,
    annual_feed_kg: float,
    center_title: str,
    center_value_kg: float,
    center_value_y: float,
    value_unit_per_kg: str,
    value_unit_annual: str,
    group_label: str,
) -> "go.Figure | None":
    if go is None:
        return None
    total_y = float(hierarchy["total_y"])
    groups: list[dict[str, object]] = hierarchy["groups"]
    products: list[dict[str, object]] = hierarchy["products"]
    if total_y <= 0 or not groups:
        return None

    root_id = "root"
    center_kg = center_value_kg if center_value_kg > 0 else _per_kg_feed(total_y, annual_feed_kg)
    ids = [root_id]
    labels = [_overview_sunburst_label(f"{center_title}<br>{_fmt_metric(center_kg, 2)} {value_unit_per_kg}")]
    parents = [""]
    values = [100.0]
    colors = ["#ffffff"]
    text_colors = [BRAND_BLUE]
    hover_rows: list[tuple[str, str, str, str, str]] = [
        (
            center_title,
            "All",
            f"{_fmt_metric(center_kg, 2)} {value_unit_per_kg}",
            f"{_fmt_metric(center_value_y if center_value_y > 0 else total_y, 2)} {value_unit_annual}",
            "100.0%",
        )
    ]
    group_share_by_name = {str(g["group"]): float(g["share_pct"]) for g in groups}

    for group in groups:
        group_name = str(group["group"])
        group_y = float(group["value_y"])
        group_share = float(group["share_pct"])
        group_kg = _per_kg_feed(group_y, annual_feed_kg)
        group_id = f"group::{group_name}"
        ids.append(group_id)
        ring_label = (
            _overview_sunburst_label(f"{group_name}<br>{group_share:.0f}%")
            if group_share >= _OVERVIEW_REVENUE_LABEL_SHARE_PCT
            else ""
        )
        labels.append(ring_label)
        parents.append(root_id)
        values.append(group_share)
        style = _PROCESS_ECON_PRODUCT_GROUP_STYLE.get(group_name, _PROCESS_ECON_PRODUCT_GROUP_STYLE["Other products"])
        colors.append(str(style["fill"]))
        text_colors.append(str(style["text_on_fill"]))
        hover_rows.append(
            (
                group_name,
                group_name,
                f"{_fmt_metric(group_kg, 2)} {value_unit_per_kg}",
                f"{_fmt_metric(group_y, 2)} {value_unit_annual}",
                f"{group_share:.1f}%",
            )
        )

    for prod in products:
        group_name = str(prod["group"])
        p_name = str(prod["product"])
        p_y = float(prod["value_y"])
        p_share = float(prod["share_pct"])
        p_kg = _per_kg_feed(p_y, annual_feed_kg)
        group_id = f"group::{group_name}"
        p_id = f"prod::{group_name}::{p_name}"
        ids.append(p_id)
        group_share = group_share_by_name.get(group_name, 0.0)
        labels.append(
            _overview_sunburst_label(_overview_product_short_name(p_name))
            if _overview_revenue_show_product_label(p_share, group_share)
            else ""
        )
        parents.append(group_id)
        values.append(p_share)
        style = _PROCESS_ECON_PRODUCT_GROUP_STYLE.get(group_name, _PROCESS_ECON_PRODUCT_GROUP_STYLE["Other products"])
        colors.append(_process_econ_product_group_palette(group_name, int(prod.get("shade_idx", 0))))
        text_colors.append(str(style["text_on_light"]))
        hover_rows.append(
            (
                format_chemistry_unicode(p_name),
                group_name,
                f"{_fmt_metric(p_kg, 2)} {value_unit_per_kg}",
                f"{_fmt_metric(p_y, 2)} {value_unit_annual}",
                f"{p_share:.1f}%",
            )
        )

    text_sizes = [_OVERVIEW_REVENUE_SUNBURST_TEXT_SIZE] * len(ids)
    center_label = labels[0]
    labels[0] = ""
    fig = go.Figure(
        go.Sunburst(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
            customdata=hover_rows,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                f"{html_module.escape(group_label)}: %{{customdata[1]}}<br>"
                "Per kg feed: %{customdata[2]}<br>"
                "Annual: %{customdata[3]}<br>"
                "Share: %{customdata[4]}<extra></extra>"
            ),
            textinfo="label",
            maxdepth=3,
            insidetextorientation="auto",
            insidetextfont=dict(size=text_sizes, color=text_colors),
        )
    )
    fig.update_layout(
        margin=dict(t=8, l=8, r=8, b=8),
        height=OVERVIEW_REVENUE_SUNBURST_HEIGHT_PX,
        paper_bgcolor="rgba(0,0,0,0)",
        uniformtext=dict(minsize=_OVERVIEW_REVENUE_SUNBURST_TEXT_MIN, mode="hide"),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=OVERVIEW_CARD_BORDER,
            font=dict(size=13, color=BRAND_BLUE),
        ),
    )
    _add_sunburst_center_annotation(fig, center_label)
    return fig


def _process_econ_revenue_product_lines_df(econ: dict) -> pd.DataFrame:
    out_df = _build_output_value_emission_df(econ)
    if out_df.empty:
        return pd.DataFrame(columns=["item", "revenue_per_y"])
    df = out_df.copy()
    if "category" in df.columns:
        df = df[df["category"].astype(str).str.lower().str.strip() == "product"]
    df["revenue_per_y"] = pd.to_numeric(df.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
    df = df[df["revenue_per_y"] > 0]
    if df.empty:
        return pd.DataFrame(columns=["item", "revenue_per_y"])
    return df.groupby("item", as_index=False)["revenue_per_y"].sum()


def _process_econ_credit_product_lines_df(econ: dict) -> pd.DataFrame:
    credits_item_df = _safe_df(econ.get("credits_item_df"))
    if not credits_item_df.empty:
        amount_col = "amount_kgco2e_per_y" if "amount_kgco2e_per_y" in credits_item_df.columns else None
        if amount_col:
            df = credits_item_df.copy()
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
            if "environmental_type" in df.columns:
                df = df[df["environmental_type"].astype(str).str.lower().str.strip() == "credit"]
            df = df[df[amount_col] > 0]
            if not df.empty:
                return df.groupby("item", as_index=False)[amount_col].sum().rename(
                    columns={amount_col: "credit_per_y"}
                )
    out_df = _build_output_value_emission_df(econ)
    if out_df.empty:
        return pd.DataFrame(columns=["item", "credit_per_y"])
    df = out_df.copy()
    df["credit_per_y"] = pd.to_numeric(df.get("credit_kgco2eq_per_y", 0.0), errors="coerce").fillna(0.0)
    df = df[df["credit_per_y"] > 0]
    if df.empty:
        return pd.DataFrame(columns=["item", "credit_per_y"])
    return df.groupby("item", as_index=False)["credit_per_y"].sum()


def _render_process_econ_product_group_sunburst_block(
    hierarchy: dict | None,
    *,
    annual_feed_kg: float,
    center_title: str,
    center_value_kg: float,
    center_value_y: float,
    value_unit_per_kg: str,
    value_unit_annual: str,
    group_label: str,
    fallback_df: pd.DataFrame,
    fallback_label_col: str,
    fallback_value_col: str,
    fallback_title: str,
    fallback_suffix: str,
    fallback_prefix: str = "",
) -> None:
    fig = None
    if hierarchy is not None:
        fig = _process_econ_product_group_sunburst_figure(
            hierarchy,
            annual_feed_kg=annual_feed_kg,
            center_title=center_title,
            center_value_kg=center_value_kg,
            center_value_y=center_value_y,
            value_unit_per_kg=value_unit_per_kg,
            value_unit_annual=value_unit_annual,
            group_label=group_label,
        )
    if fig is not None:
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CHART_CONFIG)
        return
    bar_df = _top_n_with_other(fallback_df, fallback_label_col, fallback_value_col, n=12)
    bar_fig = _build_process_econ_horizontal_bar_figure(
        bar_df,
        label_col=fallback_label_col,
        value_col=fallback_value_col,
        value_title=fallback_title,
        value_prefix=fallback_prefix,
        value_suffix=fallback_suffix,
        value_ndigits=2,
        bar_color="#1a528f",
    )
    if bar_fig is not None:
        st.plotly_chart(bar_fig, width="stretch", config=PLOTLY_CHART_CONFIG)
    else:
        st.caption(f"No {fallback_title.lower()} data available.")


def _process_econ_residual_palette(index: int) -> str:
    shades = _PROCESS_ECON_RESIDUAL_LIGHT
    return str(shades[index % len(shades)])


def _process_econ_output_cost_lines_df(econ: dict) -> pd.DataFrame:
    revenue_raw = econ.get("revenue_raw", {}) if isinstance(econ.get("revenue_raw"), dict) else {}
    lines = pd.DataFrame(revenue_raw.get("output_lines", []) or [])
    rows: list[dict[str, object]] = []
    if not lines.empty:
        work = lines.copy()
        work["economic_type"] = work.get("economic_type", "").astype(str).str.strip().str.lower()
        work["value_y"] = pd.to_numeric(work.get("amount_per_y", 0.0), errors="coerce").fillna(0.0)
        work = work[(work["economic_type"] == "cost") & (work["value_y"] > 0)]
        for _, row in work.iterrows():
            rows.append({"item": str(row.get("item", "")), "value_y": float(row["value_y"])})
    else:
        out_df = _build_output_value_emission_df(econ)
        if not out_df.empty:
            work = out_df.copy()
            work["value_y"] = (
                -pd.to_numeric(work.get("revenue_per_y", 0.0), errors="coerce").fillna(0.0)
            ).clip(lower=0.0)
            work = work[work["value_y"] > 0]
            for _, row in work.iterrows():
                rows.append({"item": str(row.get("item", "")), "value_y": float(row["value_y"])})
    if not rows:
        return pd.DataFrame(columns=["item", "value_y"])
    return (
        pd.DataFrame(rows)
        .groupby("item", as_index=False)["value_y"]
        .sum()
        .sort_values("value_y", ascending=False)
    )


def _process_econ_output_burden_lines_df(econ: dict) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    credits_raw = econ.get("credits_raw", {}) if isinstance(econ.get("credits_raw"), dict) else {}
    lines = pd.DataFrame(credits_raw.get("output_lines", []) or [])
    if not lines.empty:
        work = lines.copy()
        work["environmental_type"] = work.get("environmental_type", "").astype(str).str.strip().str.lower()
        work["value_y"] = pd.to_numeric(work.get("amount_kgco2e_per_y", 0.0), errors="coerce").fillna(0.0)
        work = work[(work["environmental_type"] == "burden") & (work["value_y"] > 0)]
        for _, row in work.iterrows():
            rows.append({"item": str(row.get("item", "")), "value_y": float(row["value_y"])})
    else:
        credits_item_df = _safe_df(econ.get("credits_item_df"))
        if not credits_item_df.empty and "environmental_type" in credits_item_df.columns:
            amount_col = "amount_kgco2e_per_y" if "amount_kgco2e_per_y" in credits_item_df.columns else None
            if amount_col:
                work = credits_item_df.copy()
                work[amount_col] = pd.to_numeric(work[amount_col], errors="coerce").fillna(0.0)
                work = work[work["environmental_type"].astype(str).str.lower().str.strip() == "burden"]
                work = work[work[amount_col] > 0]
                for _, row in work.iterrows():
                    rows.append({"item": str(row.get("item", "")), "value_y": float(row[amount_col])})
        if not rows:
            out_df = _build_output_value_emission_df(econ)
            if not out_df.empty:
                work = out_df.copy()
                work["value_y"] = (
                    -pd.to_numeric(work.get("credit_kgco2eq_per_y", 0.0), errors="coerce").fillna(0.0)
                ).clip(lower=0.0)
                work = work[work["value_y"] > 0]
                for _, row in work.iterrows():
                    rows.append({"item": str(row.get("item", "")), "value_y": float(row["value_y"])})
    if not rows:
        return pd.DataFrame(columns=["item", "value_y"])
    return (
        pd.DataFrame(rows)
        .groupby("item", as_index=False)["value_y"]
        .sum()
        .sort_values("value_y", ascending=False)
    )


def _extend_revenue_hierarchy_with_residuals(hierarchy: dict, residual_df: pd.DataFrame) -> dict:
    if residual_df is None or residual_df.empty:
        return hierarchy
    total_residual_y = float(residual_df["value_y"].sum())
    if total_residual_y <= 1e-12:
        return hierarchy

    total_rev_y = float(hierarchy["total_rev_y"])
    total_display_y = total_rev_y + total_residual_y
    stages = [dict(stage) for stage in hierarchy["stages"]]
    products = [dict(prod) for prod in hierarchy["products"]]

    for stage in stages:
        stage["share_pct"] = 100.0 * float(stage["revenue_y"]) / total_display_y
    for prod in products:
        prod["share_pct"] = 100.0 * float(prod["revenue_y"]) / total_display_y

    stages.append(
        {
            "stage_short": _PROCESS_ECON_RESIDUAL_STAGE_SHORT,
            "revenue_y": total_residual_y,
            "share_pct": 100.0 * total_residual_y / total_display_y,
            "is_residual": True,
        }
    )
    for shade_idx, (_, row) in enumerate(residual_df.iterrows()):
        val_y = float(row["value_y"])
        products.append(
            {
                "stage_short": _PROCESS_ECON_RESIDUAL_STAGE_SHORT,
                "product": str(row["item"]),
                "revenue_y": val_y,
                "share_pct": 100.0 * val_y / total_display_y,
                "shade_idx": shade_idx,
                "is_residual": True,
            }
        )

    return {
        **hierarchy,
        "stages": stages,
        "products": products,
        "total_display_y": total_display_y,
        "total_residual_y": total_residual_y,
    }


def _extend_credits_hierarchy_with_residuals(hierarchy: dict, residual_df: pd.DataFrame) -> dict:
    if residual_df is None or residual_df.empty:
        return hierarchy
    total_residual_y = float(residual_df["value_y"].sum())
    if total_residual_y <= 1e-12:
        return hierarchy

    total_credit_y = float(hierarchy["total_credit_y"])
    total_display_y = total_credit_y + total_residual_y
    stages = [dict(stage) for stage in hierarchy["stages"]]
    products = [dict(prod) for prod in hierarchy["products"]]

    for stage in stages:
        stage["share_pct"] = 100.0 * float(stage["credit_y"]) / total_display_y
    for prod in products:
        prod["share_pct"] = 100.0 * float(prod["credit_y"]) / total_display_y

    stages.append(
        {
            "stage_short": _PROCESS_ECON_RESIDUAL_STAGE_SHORT,
            "credit_y": total_residual_y,
            "share_pct": 100.0 * total_residual_y / total_display_y,
            "is_residual": True,
        }
    )
    for shade_idx, (_, row) in enumerate(residual_df.iterrows()):
        val_y = float(row["value_y"])
        products.append(
            {
                "stage_short": _PROCESS_ECON_RESIDUAL_STAGE_SHORT,
                "product": str(row["item"]),
                "credit_y": val_y,
                "share_pct": 100.0 * val_y / total_display_y,
                "shade_idx": shade_idx,
                "is_residual": True,
            }
        )

    return {
        **hierarchy,
        "stages": stages,
        "products": products,
        "total_display_y": total_display_y,
        "total_residual_y": total_residual_y,
    }


def _process_econ_revenue_sunburst_with_residuals(
    econ: dict,
    route_key: str,
    annual_feed_kg: float,
    kpi: dict,
) -> None:
    """Revenue Sources sunburst with optional residual-treatment ring (red)."""
    hierarchy = _build_overview_revenue_hierarchy(econ, route_key)
    if hierarchy is None:
        _render_overview_revenue_block(econ, route_key, annual_feed_kg, kpi)
        return

    residual_df = _process_econ_output_cost_lines_df(econ)
    hierarchy = _extend_revenue_hierarchy_with_residuals(hierarchy, residual_df)

    revenue_raw = econ.get("revenue_raw", {}) if isinstance(econ.get("revenue_raw"), dict) else {}
    output_cost_y = _safe_float(revenue_raw.get("output_cost_total_per_y", 0.0), 0.0)
    # Net revenue for the center label (= gross revenue minus residual treatment).
    net_revenue_kg = _safe_float(kpi.get("revenue_kg"), 0.0)
    if net_revenue_kg <= 0.0:
        gross_revenue_y = _safe_float(revenue_raw.get("revenue_total_per_y", 0.0), 0.0)
        if gross_revenue_y <= 0.0:
            gross_revenue_y = _safe_float(kpi.get("revenue_y"), 0.0) + output_cost_y
        net_revenue_kg = _per_kg_feed(gross_revenue_y - output_cost_y, annual_feed_kg) if annual_feed_kg > 0 else 0.0

    sunburst_fig = _overview_revenue_sunburst_figure(
        hierarchy,
        annual_feed_kg=annual_feed_kg,
        revenue_kg=net_revenue_kg,
        revenue_y=float(hierarchy["total_rev_y"]),
        center_title="Revenue",
    )
    if sunburst_fig is None:
        _render_overview_revenue_block(econ, route_key, annual_feed_kg, kpi)
    else:
        st.plotly_chart(sunburst_fig, width="stretch", config=PLOTLY_CHART_CONFIG)


def _process_econ_credits_sunburst_with_residuals(
    econ: dict,
    route_key: str,
    annual_feed_kg: float,
    kpi: dict,
) -> None:
    """Credit Sources sunburst without residual-treatment entries."""
    hierarchy = _build_overview_credits_hierarchy(econ, route_key)
    if hierarchy is None:
        _render_overview_credits_block(econ, route_key, annual_feed_kg, kpi)
        return

    sunburst_fig = _overview_credits_sunburst_figure(
        hierarchy,
        annual_feed_kg=annual_feed_kg,
        credits_kg=_safe_float(kpi.get("gwp_credit_kg"), 0.0),
        credits_y=_safe_float(kpi.get("gwp_credit_y"), float(hierarchy["total_credit_y"])),
    )
    if sunburst_fig is None:
        _render_overview_credits_block(econ, route_key, annual_feed_kg, kpi)
    else:
        st.plotly_chart(sunburst_fig, width="stretch", config=PLOTLY_CHART_CONFIG)


def _process_econ_gwp_burden_by_source_driver_df(
    econ: dict,
    env_components: dict[str, float],
    mass_y: float,
) -> pd.DataFrame:
    value_col = "GWP burden (kg CO2-eq/kg feed)"
    steps_col = "_step_members"
    rows: list[dict[str, object]] = []
    raw = _safe_df(econ.get("burdens_material_df"))
    if not raw.empty and "item" in raw.columns:
        work = raw.copy()
        work["emission_kgco2e_per_y"] = pd.to_numeric(
            work.get("emission_kgco2e_per_y", 0.0), errors="coerce"
        ).fillna(0.0)
        if "step_name" not in work.columns:
            work["step_name"] = ""
        work = work[work["emission_kgco2e_per_y"].abs() > 1e-12]
        for item, grp in work.groupby("item"):
            step_labels = sorted(
                {
                    str(_compact_step_label(step))
                    for step in grp["step_name"].astype(str)
                    if str(step).strip()
                }
            )
            rows.append(
                {
                    "Source": format_chemistry_unicode(str(item)),
                    value_col: _per_kg_feed(float(grp["emission_kgco2e_per_y"].sum()), mass_y),
                    "_other_members": "",
                    steps_col: ", ".join(step_labels),
                }
            )

    for source_name, component_key in (
        ("Electricity", "electricity_kg"),
        ("Thermal energy", "thermal_kg"),
    ):
        val_kg = float(env_components.get(component_key, 0.0))
        if val_kg <= 1e-12:
            continue
        rows.append(
            {
                "Source": source_name,
                value_col: val_kg,
                "_other_members": "",
                steps_col: "All process steps",
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Source", value_col, "_other_members", steps_col])
    return _group_step_driver_with_rounded_other(
        pd.DataFrame(rows),
        "Source",
        value_col,
        ndigits=2,
        members_detail_col=steps_col,
    )


_PROCESS_ECON_COST_DRIVER_TYPES = (
    "Material inputs",
    "Utilities",
    "Labor",
    "Total operating costs",
)
_PROCESS_ECON_DRIVER_GROUPINGS = ("By category", "By process step")
_PROCESS_ECON_GWP_BURDEN_GROUPINGS = ("By source", "By process step")
_PROCESS_ECON_GWP_BURDEN_TYPES = (
    "Materials",
    "Energy",
    "Residual treatment",
    "Total burden",
)
_PROCESS_ECON_COST_VALUE_COL = "Cost ($/kg feed)"
_PROCESS_ECON_GWP_BURDEN_VALUE_COL = "GWP burden (kg CO2-eq/kg feed)"


def _process_econ_category_driver_df(
    rows: list[tuple[str, float]],
    *,
    label_col: str = "Category",
    value_col: str,
    members_detail_col: str | None = None,
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[label_col, value_col, "_other_members"])
    df = pd.DataFrame(rows, columns=[label_col, value_col])
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    df = df[df[value_col].abs() > 1e-12]
    if df.empty:
        return pd.DataFrame(columns=[label_col, value_col, "_other_members"])
    if members_detail_col:
        df[members_detail_col] = ""
    return _group_step_driver_with_rounded_other(
        df,
        label_col,
        value_col,
        ndigits=2,
        members_detail_col=members_detail_col,
    )


def _process_econ_utility_cost_by_category_df(econ: dict, mass_y: float) -> pd.DataFrame:
    opex_step_df = _safe_df(econ.get("opex_step_df"))
    energy_y = 0.0
    water_y = 0.0
    if not opex_step_df.empty:
        energy_y = float(
            pd.to_numeric(opex_step_df.get("cost_energy_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
        water_y = float(
            pd.to_numeric(opex_step_df.get("cost_water_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
    rows = [
        ("Electricity", _per_kg_feed(energy_y, mass_y)),
        ("Water", _per_kg_feed(water_y, mass_y)),
    ]
    return _process_econ_category_driver_df(rows, value_col=_PROCESS_ECON_COST_VALUE_COL)


def _process_econ_labor_cost_by_category_df(econ: dict, mass_y: float) -> pd.DataFrame:
    opex_step_df = _safe_df(econ.get("opex_step_df"))
    labor_y = 0.0
    if not opex_step_df.empty:
        labor_y = float(
            pd.to_numeric(opex_step_df.get("cost_labor_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
    return _process_econ_category_driver_df(
        [("Operating labor", _per_kg_feed(labor_y, mass_y))],
        value_col=_PROCESS_ECON_COST_VALUE_COL,
    )


def _process_econ_total_operating_cost_by_category_df(econ: dict, mass_y: float) -> pd.DataFrame:
    opex_step_df = _safe_df(econ.get("opex_step_df"))
    utility_y = 0.0
    labor_y = 0.0
    maintenance_y = 0.0
    if not opex_step_df.empty:
        utility_y = float(
            pd.to_numeric(opex_step_df.get("cost_energy_per_y", 0.0), errors="coerce").fillna(0.0).sum()
            + pd.to_numeric(opex_step_df.get("cost_water_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
        labor_y = float(
            pd.to_numeric(opex_step_df.get("cost_labor_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
        maintenance_y = float(
            pd.to_numeric(opex_step_df.get("maintenance_per_y", 0.0), errors="coerce").fillna(0.0).sum()
        )
    overhead_y = _manuf_value_per_y(econ, "VI.C Overhead ($/y)")
    rows = [
        ("Utilities", _per_kg_feed(utility_y, mass_y)),
        ("Labor", _per_kg_feed(labor_y, mass_y)),
        ("Maintenance", _per_kg_feed(maintenance_y, mass_y)),
        ("Plant overhead", _per_kg_feed(overhead_y, mass_y)),
    ]
    return _process_econ_category_driver_df(rows, value_col=_PROCESS_ECON_COST_VALUE_COL)


def _process_econ_material_cost_by_category_df(econ: dict, mass_y: float) -> pd.DataFrame:
    raw_df = _process_econ_material_by_item_driver_df(econ, mass_y)
    if raw_df.empty:
        return pd.DataFrame(columns=["Category", _PROCESS_ECON_COST_VALUE_COL, "_other_members", "_step_members"])
    out = raw_df.rename(
        columns={
            "Material": "Category",
            "Material cost ($/kg feed)": _PROCESS_ECON_COST_VALUE_COL,
        }
    )
    return out


def _process_econ_gwp_materials_by_source_df(econ: dict, mass_y: float) -> pd.DataFrame:
    value_col = _PROCESS_ECON_GWP_BURDEN_VALUE_COL
    steps_col = "_step_members"
    rows: list[dict[str, object]] = []
    raw = _safe_df(econ.get("burdens_material_df"))
    if not raw.empty and "item" in raw.columns:
        work = raw.copy()
        work["emission_kgco2e_per_y"] = pd.to_numeric(
            work.get("emission_kgco2e_per_y", 0.0), errors="coerce"
        ).fillna(0.0)
        if "step_name" not in work.columns:
            work["step_name"] = ""
        work = work[work["emission_kgco2e_per_y"].abs() > 1e-12]
        for item, grp in work.groupby("item"):
            step_labels = sorted(
                {
                    str(_compact_step_label(step))
                    for step in grp["step_name"].astype(str)
                    if str(step).strip()
                }
            )
            rows.append(
                {
                    "Source": format_chemistry_unicode(str(item)),
                    value_col: _per_kg_feed(float(grp["emission_kgco2e_per_y"].sum()), mass_y),
                    "_other_members": "",
                    steps_col: ", ".join(step_labels),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["Source", value_col, "_other_members", steps_col])
    return _group_step_driver_with_rounded_other(
        pd.DataFrame(rows),
        "Source",
        value_col,
        ndigits=2,
        members_detail_col=steps_col,
    )


def _process_econ_gwp_residual_by_source_df(econ: dict, mass_y: float) -> pd.DataFrame:
    value_col = _PROCESS_ECON_GWP_BURDEN_VALUE_COL
    steps_col = "_step_members"
    rows: list[dict[str, object]] = []
    raw = _safe_df(econ.get("credits_item_df"))
    if not raw.empty and "item" in raw.columns:
        work = raw.copy()
        amount_col = "amount_kgco2e_per_y" if "amount_kgco2e_per_y" in work.columns else None
        if amount_col is not None:
            work[amount_col] = pd.to_numeric(work.get(amount_col, 0.0), errors="coerce").fillna(0.0)
            if "environmental_type" in work.columns:
                work = work[work["environmental_type"].astype(str).str.lower().str.strip() == "burden"]
            if "step_name" not in work.columns:
                work["step_name"] = ""
            work = work[work[amount_col].abs() > 1e-12]
            for item, grp in work.groupby("item"):
                step_labels = sorted(
                    {
                        str(_compact_step_label(step))
                        for step in grp["step_name"].astype(str)
                        if str(step).strip()
                    }
                )
                rows.append(
                    {
                        "Source": format_chemistry_unicode(str(item)),
                        value_col: _per_kg_feed(float(grp[amount_col].sum()), mass_y),
                        "_other_members": "",
                        steps_col: ", ".join(step_labels),
                    }
                )
    if not rows:
        return pd.DataFrame(columns=["Source", value_col, "_other_members", steps_col])
    return _group_step_driver_with_rounded_other(
        pd.DataFrame(rows),
        "Source",
        value_col,
        ndigits=2,
        members_detail_col=steps_col,
    )


def _process_econ_gwp_energy_burden_kg(env_components: dict[str, float]) -> float:
    return float(env_components.get("electricity_kg", 0.0)) + float(env_components.get("thermal_kg", 0.0))


def _process_econ_gwp_burden_by_source_category_df(
    env_components: dict[str, float],
) -> pd.DataFrame:
    rows = [
        ("Materials", float(env_components.get("materials_kg", 0.0))),
        ("Energy", _process_econ_gwp_energy_burden_kg(env_components)),
    ]
    residual_kg = float(env_components.get("output_burdens_kg", 0.0))
    if residual_kg > 1e-12:
        rows.append(("Residual treatment", residual_kg))
    transport_kg = float(env_components.get("transport_kg", 0.0))
    if transport_kg > 1e-12:
        rows.append(("Transport", transport_kg))
    return _process_econ_category_driver_df(rows, label_col="Source", value_col=_PROCESS_ECON_GWP_BURDEN_VALUE_COL)


def _process_econ_gwp_single_source_category_df(
    source_name: str,
    value_kg: float,
) -> pd.DataFrame:
    return _process_econ_category_driver_df(
        [(source_name, value_kg)],
        label_col="Source",
        value_col=_PROCESS_ECON_GWP_BURDEN_VALUE_COL,
    )


def _process_econ_cost_driver_plot_df(
    step_df: pd.DataFrame,
    econ: dict,
    mass_y: float,
    *,
    cost_type: str,
    grouping: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    by_step = grouping == "By process step"
    bar_kwargs: dict[str, object] = {
        "value_prefix": "$",
        "value_suffix": "/kg feed",
        "value_ndigits": 2,
        "color_by_stage": False,
        "steps_detail_col": None,
    }

    if cost_type == "Material inputs":
        if by_step:
            value_col = "Direct material cost ($/kg feed)"
            plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
            return plot_df, {
                **bar_kwargs,
                "label_col": "Step label",
                "value_col": value_col,
                "value_title": "Material cost",
                "color_by_stage": True,
            }
        plot_df = _process_econ_material_cost_by_category_df(econ, mass_y)
        return plot_df, {
            **bar_kwargs,
            "label_col": "Category",
            "value_col": _PROCESS_ECON_COST_VALUE_COL,
            "value_title": "Material cost",
            "steps_detail_col": "_step_members",
        }

    if cost_type == "Utilities":
        if by_step:
            value_col = "Utility cost ($/kg feed)"
            plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
            return plot_df, {
                **bar_kwargs,
                "label_col": "Step label",
                "value_col": value_col,
                "value_title": "Utility cost",
                "color_by_stage": True,
            }
        plot_df = _process_econ_utility_cost_by_category_df(econ, mass_y)
        return plot_df, {
            **bar_kwargs,
            "label_col": "Category",
            "value_col": _PROCESS_ECON_COST_VALUE_COL,
            "value_title": "Utility cost",
        }

    if cost_type == "Labor":
        if by_step:
            value_col = "Labor cost ($/kg feed)"
            plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
            return plot_df, {
                **bar_kwargs,
                "label_col": "Step label",
                "value_col": value_col,
                "value_title": "Labor cost",
                "color_by_stage": True,
            }
        plot_df = _process_econ_labor_cost_by_category_df(econ, mass_y)
        return plot_df, {
            **bar_kwargs,
            "label_col": "Category",
            "value_col": _PROCESS_ECON_COST_VALUE_COL,
            "value_title": "Labor cost",
        }

    if by_step:
        value_col = "Total operating cost ($/kg feed)"
        plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
        return plot_df, {
            **bar_kwargs,
            "label_col": "Step label",
            "value_col": value_col,
            "value_title": "Total operating cost",
            "color_by_stage": True,
        }
    plot_df = _process_econ_total_operating_cost_by_category_df(econ, mass_y)
    return plot_df, {
        **bar_kwargs,
        "label_col": "Category",
        "value_col": _PROCESS_ECON_COST_VALUE_COL,
        "value_title": "Total operating cost",
    }


def _process_econ_gwp_burden_plot_df(
    step_df: pd.DataFrame,
    econ: dict,
    env_components: dict[str, float],
    mass_y: float,
    *,
    burden_type: str,
    grouping: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    by_step = grouping == "By process step"
    bar_kwargs: dict[str, object] = {
        "value_prefix": "",
        "value_suffix": " kg CO2-eq/kg feed",
        "value_ndigits": 2,
        "color_by_stage": False,
        "steps_detail_col": None,
    }

    if burden_type == "Materials":
        if by_step:
            value_col = "GWP materials (kg CO2-eq/kg feed)"
            plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
            return plot_df, {
                **bar_kwargs,
                "label_col": "Step label",
                "value_col": value_col,
                "value_title": "Materials burden",
                "color_by_stage": True,
            }
        plot_df = _process_econ_gwp_materials_by_source_df(econ, mass_y)
        return plot_df, {
            **bar_kwargs,
            "label_col": "Source",
            "value_col": _PROCESS_ECON_GWP_BURDEN_VALUE_COL,
            "value_title": "Materials burden",
            "steps_detail_col": "_step_members",
        }

    if burden_type == "Energy":
        if by_step:
            value_col = "GWP energy (kg CO2-eq/kg feed)"
            plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
            return plot_df, {
                **bar_kwargs,
                "label_col": "Step label",
                "value_col": value_col,
                "value_title": "Energy burden",
                "color_by_stage": True,
            }
        plot_df = _process_econ_gwp_single_source_category_df(
            "Energy",
            _process_econ_gwp_energy_burden_kg(env_components),
        )
        return plot_df, {
            **bar_kwargs,
            "label_col": "Source",
            "value_col": _PROCESS_ECON_GWP_BURDEN_VALUE_COL,
            "value_title": "Energy burden",
        }

    if burden_type == "Residual treatment":
        if by_step:
            value_col = "GWP residual treatment (kg CO2-eq/kg feed)"
            plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
            return plot_df, {
                **bar_kwargs,
                "label_col": "Step label",
                "value_col": value_col,
                "value_title": "Residual treatment burden",
                "color_by_stage": True,
            }
        plot_df = _process_econ_gwp_residual_by_source_df(econ, mass_y)
        return plot_df, {
            **bar_kwargs,
            "label_col": "Source",
            "value_col": _PROCESS_ECON_GWP_BURDEN_VALUE_COL,
            "value_title": "Residual treatment burden",
            "steps_detail_col": "_step_members",
        }

    if by_step:
        value_col = "GWP burden (kg CO2-eq/kg feed)"
        plot_df = _process_econ_gwp_step_driver_df(step_df, value_col)
        return plot_df, {
            **bar_kwargs,
            "label_col": "Step label",
            "value_col": value_col,
            "value_title": "Total GWP burden",
            "color_by_stage": True,
        }
    plot_df = _process_econ_gwp_burden_by_source_category_df(env_components)
    return plot_df, {
        **bar_kwargs,
        "label_col": "Source",
        "value_col": _PROCESS_ECON_GWP_BURDEN_VALUE_COL,
        "value_title": "Total GWP burden",
    }


def _render_process_econ_driver_breakdown_chart(
    plot_df: pd.DataFrame,
    bar_kwargs: dict[str, object],
    *,
    empty_caption: str,
) -> None:
    fig = _build_process_econ_horizontal_bar_figure(plot_df, **bar_kwargs)
    if fig is not None:
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CHART_CONFIG)
    else:
        st.caption(empty_caption)


def _render_process_econ_cost_driver_breakdown(
    step_df: pd.DataFrame,
    econ: dict,
    mass_y: float,
) -> None:
    with st.container(border=True):
        st.markdown(_plant_infra_panel_heading_html("Cost Drivers"), unsafe_allow_html=True)
        cost_type = st.radio(
            "Cost type",
            list(_PROCESS_ECON_COST_DRIVER_TYPES),
            horizontal=True,
            key="pep_cost_driver_type",
            index=0,
        )
        grouping = st.radio(
            "Grouping",
            list(_PROCESS_ECON_DRIVER_GROUPINGS),
            horizontal=True,
            key="pep_cost_driver_grouping",
            index=0,
        )
        plot_df, bar_kwargs = _process_econ_cost_driver_plot_df(
            step_df,
            econ,
            mass_y,
            cost_type=cost_type,
            grouping=grouping,
        )
        _render_process_econ_driver_breakdown_chart(
            plot_df,
            bar_kwargs,
            empty_caption="No cost driver data available for the selected view.",
        )


def _render_process_econ_gwp_burden_breakdown(
    step_df: pd.DataFrame,
    econ: dict,
    env_components: dict[str, float],
    mass_y: float,
) -> None:
    with st.container(border=True):
        st.markdown(_plant_infra_panel_heading_html("Burden Sources"), unsafe_allow_html=True)
        burden_type = st.radio(
            "Burden type",
            list(_PROCESS_ECON_GWP_BURDEN_TYPES),
            horizontal=True,
            key="pep_gwp_burden_type",
            index=0,
        )
        grouping = st.radio(
            "Grouping",
            list(_PROCESS_ECON_GWP_BURDEN_GROUPINGS),
            horizontal=True,
            key="pep_gwp_burden_grouping",
            index=0,
        )
        plot_df, bar_kwargs = _process_econ_gwp_burden_plot_df(
            step_df,
            econ,
            env_components,
            mass_y,
            burden_type=burden_type,
            grouping=grouping,
        )
        _render_process_econ_driver_breakdown_chart(
            plot_df,
            bar_kwargs,
            empty_caption="No GWP burden data available for the selected view.",
        )


def _render_process_economics_gwp_dashboard(
    econ: dict,
    ctx: dict,
    steps_df: pd.DataFrame,
    scen_sel: dict,
    kpi: dict,
) -> None:
    mass_y = _safe_float(kpi.get("mass_y"), 0.0)
    step_df = _build_process_economics_step_df(steps_df, econ, ctx, scen_sel, mass_y)
    if step_df.empty:
        st.info("No process-step data available.")
        return

    metrics = _process_econ_gwp_scenario_metrics(econ, kpi, mass_y)
    env_components = _process_econ_gwp_environmental_components(econ, ctx, steps_df, mass_y, kpi)

    route_key = str(scen_sel.get("route", "") or "")

    with st.container(border=True):
        _inject_overview_tab_styles()
        econ_col, env_col = st.columns(2, gap="large")

        with econ_col:
            with st.container(border=True, height=OVERVIEW_DECISION_DASHBOARD_TILE_HEIGHT_PX):
                _render_overview_economics_tile(kpi, large=True)

            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            with st.container(border=True):
                st.markdown(_plant_infra_panel_heading_html("Economic Balance"), unsafe_allow_html=True)
                econ_waterfall = _build_process_economics_waterfall_figure(metrics)
                if econ_waterfall is not None:
                    st.plotly_chart(econ_waterfall, width="stretch", config=PLOTLY_CHART_CONFIG)
                else:
                    st.caption("No economic balance data available.")

            _render_process_econ_cost_driver_breakdown(step_df, econ, mass_y)

            with st.container(border=True):
                st.markdown(_plant_infra_panel_heading_html("Revenue Sources"), unsafe_allow_html=True)
                _process_econ_revenue_sunburst_with_residuals(econ, route_key, mass_y, kpi)

        with env_col:
            with st.container(border=True, height=OVERVIEW_DECISION_DASHBOARD_TILE_HEIGHT_PX):
                _render_overview_environmental_tile(kpi, large=True)

            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            with st.container(border=True):
                st.markdown(_plant_infra_panel_heading_html("Environmental Balance"), unsafe_allow_html=True)
                env_waterfall = _build_process_environmental_waterfall_figure(env_components)
                if env_waterfall is not None:
                    st.plotly_chart(env_waterfall, width="stretch", config=PLOTLY_CHART_CONFIG)
                else:
                    st.caption("No environmental balance data available.")

            _render_process_econ_gwp_burden_breakdown(step_df, econ, env_components, mass_y)

            with st.container(border=True):
                st.markdown(_plant_infra_panel_heading_html("Credit Sources"), unsafe_allow_html=True)
                _process_econ_credits_sunburst_with_residuals(econ, route_key, mass_y, kpi)


def _massflow_long_safe(steps_df: pd.DataFrame, scen_name: str) -> pd.DataFrame:
    try:
        from Save import _massflow_long

        mf = _massflow_long(steps_df, scen_name)
    except Exception:
        return pd.DataFrame()
    if mf.empty:
        return mf
    mf = mf.copy()
    mf["_step_context"] = mf["Step"].ffill()
    return mf


def _compact_step_label(step: str) -> str:
    s = str(step).strip()
    replacements = [
        ("Hydro LFP – ", "LFP: "),
        ("Hydro NMC – ", "NMC: "),
        ("Hydro Mix – ", "Mix: "),
        ("Hydro Pyro – ", "Pyro hydro: "),
        ("Hydro-Pyro - ", "Pyro hydro: "),
        ("Mechanical ", "Mech: "),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def _find_future_step_by_input(
    step_rows: pd.DataFrame,
    *,
    current_pos: int,
    value: float,
    used_targets: set[int],
) -> int | None:
    if value <= 1e-12:
        return None
    for pos in range(current_pos + 1, len(step_rows)):
        if pos in used_targets:
            continue
        target_in = _safe_float(step_rows.iloc[pos].get("In kg/h"), 0.0)
        if target_in <= 0.0:
            continue
        tol = max(1e-6, 0.002 * max(abs(value), abs(target_in)))
        if abs(target_in - value) <= tol:
            return pos
    return None


def _build_process_flow_data(steps_df: pd.DataFrame, scen_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    step_rows = _safe_df(steps_df).copy()
    if step_rows.empty or "Step" not in step_rows.columns:
        return pd.DataFrame(), pd.DataFrame()

    step_rows = step_rows[step_rows["Step"].astype(str).str.strip() != ""].reset_index(drop=True)
    step_rows["_step_label"] = step_rows["Step"].astype(str).map(_compact_step_label)
    mf = _massflow_long_safe(step_rows, scen_name)

    links: list[dict] = []
    terminal_counts: dict[str, int] = {}

    def add_link(source: str, target: str, value: float, stream: str, kind: str, step: str) -> None:
        v = _safe_float(value, 0.0)
        if v <= 1e-12 or not source or not target or source == target:
            return
        links.append(
            {
                "source": source,
                "target": target,
                "value": float(v),
                "stream": str(stream),
                "kind": str(kind),
                "step": str(step),
            }
        )

    first_in = _safe_float(step_rows.iloc[0].get("In kg/h"), 0.0)
    add_link("Feed input", step_rows.iloc[0]["_step_label"], first_in, "feed", "input", step_rows.iloc[0]["Step"])

    used_targets: set[int] = set()
    for pos, row in step_rows.iterrows():
        step_name = str(row["Step"])
        source = str(row["_step_label"])

        if not mf.empty:
            mf_step = mf[mf["_step_context"].astype(str) == step_name]
        else:
            mf_step = pd.DataFrame()

        forward_to_process_step = False
        if not mf_step.empty:
            for _, mrow in mf_step.iterrows():
                mat_v = _safe_float(mrow.get("Materials added (kg/h)"), 0.0)
                mat_name = str(mrow.get("Name Material added") or "Reagent")
                if mat_v > 0.0:
                    add_link(f"Reagent: {mat_name}", source, mat_v, mat_name, "reagent", step_name)

            fwd_rows = mf_step[pd.to_numeric(mf_step.get("Output forwarded (kg/h)", 0.0), errors="coerce").fillna(0.0) > 0.0]
            for _, frow in fwd_rows.iterrows():
                val = _safe_float(frow.get("Output forwarded (kg/h)"), 0.0)
                stream = str(frow.get("Name Output forwarded ") or row.get("Forward key", "forward"))
                target_pos = _find_future_step_by_input(step_rows, current_pos=pos, value=val, used_targets=used_targets)
                if target_pos is not None:
                    used_targets.add(target_pos)
                    forward_to_process_step = True
                    add_link(source, str(step_rows.iloc[target_pos]["_step_label"]), val, stream, "forward", step_name)
                else:
                    terminal_counts[stream] = terminal_counts.get(stream, 0) + 1
                    add_link(source, f"Output: {stream}", val, stream, "output", step_name)

            sep_rows = mf_step[pd.to_numeric(mf_step.get("Output separated (kg/h)", 0.0), errors="coerce").fillna(0.0) > 0.0]
            for _, srow in sep_rows.iterrows():
                val = _safe_float(srow.get("Output separated (kg/h)"), 0.0)
                stream = str(srow.get("Name Output Separated") or "Separated output")
                add_link(source, f"Separated: {stream}", val, stream, "separated", step_name)

            if not forward_to_process_step and pos + 1 < len(step_rows):
                out_v = _safe_float(row.get("Out forward kg/h", row.get("Out kg/h", 0.0)), 0.0)
                if out_v > 0.0:
                    add_link(
                        source,
                        str(step_rows.iloc[pos + 1]["_step_label"]),
                        out_v,
                        row.get("Forward key", "forward"),
                        "forward",
                        step_name,
                    )
        else:
            out_v = _safe_float(row.get("Out forward kg/h", row.get("Out kg/h", 0.0)), 0.0)
            if pos + 1 < len(step_rows):
                add_link(source, str(step_rows.iloc[pos + 1]["_step_label"]), out_v, row.get("Forward key", "forward"), "forward", step_name)
            else:
                add_link(source, "Final output", out_v, row.get("Forward key", "forward"), "output", step_name)

        loss_v = _safe_float(row.get("Loss (kg/h)"), 0.0)
        if loss_v > 0.0:
            add_link(source, "Losses", loss_v, "loss", "loss", step_name)

    link_df = pd.DataFrame(links)
    node_df = pd.DataFrame({"node": pd.unique(link_df[["source", "target"]].values.ravel("K"))}) if not link_df.empty else pd.DataFrame()
    return node_df, link_df


def _process_stage(step: str, route: str | None = None) -> str:
    s = str(step or "").strip()
    sl = s.lower()
    route_key = str(route or "").strip().lower()
    front_end = {"analytics & sorting", "discharge", "pack dismantle"}
    mechanical = {
        "shredding",
        "drying",
        "magnetic separation",
        "air-classification 1",
        "air-classification 2",
        "crushing",
        "sieving",
    }
    if sl in front_end:
        return "Front-end processing"
    if sl == "gas scrubbing":
        return "Mechanical treatment"
    if sl in mechanical:
        return "Pyro treatment" if route_key == "pyro" else "Mechanical treatment"
    if sl.startswith("pyro "):
        return "Pyro treatment" if route_key == "pyro" else "Other processing"
    if s.startswith("Hydro"):
        return "Hydrometallurgy"
    return "Other processing"


def _hydro_pyro_branch(step: str) -> str | None:
    """``alloy`` | ``slag`` for Hydro Pyro steps; ``None`` otherwise."""
    s = str(step or "").strip()
    sl = s.lower()
    if not (sl.startswith("hydro pyro") or sl.startswith("hydro-pyro")):
        return None

    # Slag line = S05_Hydro_Pyro_Slag (S05_1..S05_16), including Li sub-line.
    if "slag" in sl or sl.startswith("hydro pyro – li") or sl.startswith("hydro pyro - li") or "li wastewater" in sl:
        return "slag"

    # Alloy line = S05_Hydro_Pyro_Alloy (S05_1..S05_13), including legacy "Hydro-Pyro - ..." labels.
    if "alloy" in sl or sl.startswith("hydro-pyro -"):
        return "alloy"

    # Pyro hydro step without explicit token: resolved via sequence in _pyro_hydro_branch_keys.
    return None


def _is_hydro_pyro_step(step: str) -> bool:
    sl = str(step or "").strip().lower()
    return sl.startswith("hydro pyro") or sl.startswith("hydro-pyro")


def _pyro_hydro_branch_keys(step_names: list[str]) -> list[str | None]:
    """Resolve alloy/slag branch per step using the hydro-pyro execution sequence."""
    keys: list[str | None] = []
    current: str | None = None
    for name in step_names:
        if not _is_hydro_pyro_step(name):
            keys.append(None)
            continue

        name_l = str(name).lower()
        explicit = _hydro_pyro_branch(name)

        if "slag digestion" in name_l:
            current = "slag"
            keys.append("slag")
        elif "alloy digestion" in name_l:
            current = "alloy"
            keys.append("alloy")
        elif explicit in {"slag", "alloy"}:
            current = explicit
            keys.append(explicit)
        elif current in {"slag", "alloy"}:
            keys.append(current)
        else:
            keys.append(None)
    return keys


def _first_branch_index(branch_keys: list[str | None], branch: str) -> int | None:
    for idx, key in enumerate(branch_keys):
        if key == branch:
            return idx
    return None


def _is_pyro_granulation_alloy_step(step: str) -> bool:
    sl = str(step or "").lower()
    return "granulation" in sl and "alloy" in sl


def _is_pyro_granulation_slag_step(step: str) -> bool:
    sl = str(step or "").lower()
    return "granulation" in sl and "slag" in sl


def _process_flow_plot_stage(step: str, route: str | None, *, split_pyro_hydro: bool) -> str:
    base = _process_stage(step, route)
    route_key = str(route or "").strip().lower()
    if route_key == "pyro" and split_pyro_hydro and base == "Hydrometallurgy":
        branch = _hydro_pyro_branch(step)
        if branch == "slag":
            return "Hydrometallurgy (Slag)"
        if branch == "alloy":
            return "Hydrometallurgy (Alloy)"
    return base


def _process_flow_plot_stage_order(route: str | None, *, split_pyro_hydro: bool) -> dict[str, int]:
    route_key = str(route or "").strip().lower()
    if route_key == "pyro":
        return {
            "Front-end processing": 0,
            "Pyro treatment": 1,
            "Hydrometallurgy (Alloy)": 2,
            "Hydrometallurgy (Slag)": 3,
            "Other processing": 4,
        }
    return {
        "Front-end processing": 0,
        "Mechanical treatment": 1,
        "Pyro treatment": 1,
        "Hydrometallurgy": 2,
        "Other processing": 3,
    }


def _step_flow_branch_key(step: str, route: str | None) -> str | None:
    route_key = str(route or "").strip().lower()
    if route_key == "pyro":
        return _hydro_pyro_branch(step)
    return None


def _first_step_index(step_names: list[str], predicate) -> int | None:
    for idx, name in enumerate(step_names):
        if predicate(name):
            return idx
    return None


def _first_stage_step_index(step_names: list[str], stage: str, route: str | None) -> int | None:
    for idx, name in enumerate(step_names):
        if _process_stage(name, route) == stage:
            return idx
    return None


def _append_step_flow_bridge_edges(
    step_names: list[str],
    route: str | None,
    drawn_edges: set[tuple[int, int]],
) -> None:
    route_key = str(route or "").strip().lower()

    discharge_idx = _first_step_index(step_names, lambda n: str(n).strip().lower() == "discharge")
    if discharge_idx is not None:
        if route_key == "mech":
            treatment_idx = _first_stage_step_index(step_names, "Mechanical treatment", route)
        elif route_key == "pyro":
            treatment_idx = _first_stage_step_index(step_names, "Pyro treatment", route)
        else:
            treatment_idx = None
        if treatment_idx is not None and treatment_idx != discharge_idx:
            drawn_edges.add((discharge_idx, treatment_idx))

    if route_key == "mech":
        sieving_idx = _first_step_index(step_names, lambda n: str(n).strip().lower() == "sieving")
        hydro_idx = _first_step_index(step_names, lambda n: str(n).startswith("Hydro"))
        if sieving_idx is not None and hydro_idx is not None:
            drawn_edges.add((sieving_idx, hydro_idx))

    if route_key == "pyro":
        branch_keys = _pyro_hydro_branch_keys(step_names)
        alloy_gran_idx = _first_step_index(step_names, _is_pyro_granulation_alloy_step)
        slag_gran_idx = _first_step_index(step_names, _is_pyro_granulation_slag_step)
        alloy_hydro_idx = _first_branch_index(branch_keys, "alloy")
        slag_hydro_idx = _first_branch_index(branch_keys, "slag")
        if alloy_gran_idx is not None and alloy_hydro_idx is not None:
            drawn_edges.add((alloy_gran_idx, alloy_hydro_idx))
        if slag_gran_idx is not None and slag_hydro_idx is not None:
            drawn_edges.add((slag_gran_idx, slag_hydro_idx))


def _step_flow_suppressed_edges(step_names: list[str], route: str | None) -> set[tuple[int, int]]:
    """Edges to hide in the process-structure dot plot (mechanical branch split)."""
    route_key = str(route or "").strip().lower()
    suppressed: set[tuple[int, int]] = set()

    if route_key == "mech":
        ac2_idx = _first_step_index(step_names, lambda n: str(n).strip().lower() == "air-classification 2")
        hydro_idx = _first_step_index(step_names, lambda n: str(n).startswith("Hydro"))
        if ac2_idx is not None and hydro_idx is not None:
            suppressed.add((ac2_idx, hydro_idx))
        return suppressed

    if route_key == "pyro":
        branch_keys = _pyro_hydro_branch_keys(step_names)
        alloy_gran_idx = _first_step_index(step_names, _is_pyro_granulation_alloy_step)
        alloy_hydro_idx = _first_branch_index(branch_keys, "alloy")

        if alloy_gran_idx is not None:
            for tgt_idx, branch in enumerate(branch_keys):
                if branch == "slag":
                    suppressed.add((alloy_gran_idx, tgt_idx))

        for src_idx in range(len(step_names)):
            src_branch = branch_keys[src_idx]
            if src_branch is None:
                continue
            for tgt_idx in range(src_idx + 1, len(step_names)):
                tgt_branch = branch_keys[tgt_idx]
                if tgt_branch is None:
                    continue
                if src_branch != tgt_branch:
                    suppressed.add((src_idx, tgt_idx))

        if alloy_gran_idx is not None and alloy_hydro_idx is not None:
            suppressed.discard((alloy_gran_idx, alloy_hydro_idx))

    return suppressed


def _build_stage_flow_data(steps_df: pd.DataFrame, link_df: pd.DataFrame, route: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    step_rows = _safe_df(steps_df).copy()
    links = _safe_df(link_df).copy()
    if step_rows.empty or links.empty or "Step" not in step_rows.columns:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    step_rows["_step_label"] = step_rows["Step"].astype(str).map(_compact_step_label)
    step_rows["Stage"] = step_rows["Step"].astype(str).map(lambda s: _process_stage(s, route))
    label_to_stage = dict(zip(step_rows["_step_label"], step_rows["Stage"]))

    agg: dict[tuple[str, str, str], dict] = {}

    def add_link(source: str, target: str, value: float, kind: str, detail: str) -> None:
        v = _safe_float(value, 0.0)
        if v <= 1e-12 or not source or not target or source == target:
            return
        key = (source, target, kind)
        if key not in agg:
            agg[key] = {"source": source, "target": target, "kind": kind, "value": 0.0, "stream": detail, "step": detail}
        agg[key]["value"] += v

    for _, row in links.iterrows():
        kind = str(row.get("kind", "") or "")
        source_label = str(row.get("source", "") or "")
        target_label = str(row.get("target", "") or "")
        step_name = str(row.get("step", "") or "")
        source_stage = _process_stage(step_name, route)
        value = _safe_float(row.get("value"), 0.0)
        stream = str(row.get("stream", "") or kind)

        if kind == "input":
            target_stage = label_to_stage.get(target_label, source_stage)
            add_link("Feed input", target_stage, value, "input", "feed")
        elif kind == "reagent":
            add_link("Reagents / utilities", source_stage, value, "reagent", "materials added")
        elif kind == "forward":
            target_stage = label_to_stage.get(target_label)
            if target_stage:
                add_link(source_stage, target_stage, value, "forward", stream)
            else:
                add_link(source_stage, "Terminal forwarded outputs", value, "output", stream)
        elif kind == "separated":
            add_link(source_stage, "Separated outputs", value, "separated", stream)
        elif kind == "loss":
            add_link(source_stage, "Losses", value, "loss", stream)
        else:
            add_link(source_stage, target_label, value, kind, stream)

    stage_link_df = pd.DataFrame(agg.values())
    stage_node_df = (
        pd.DataFrame({"node": pd.unique(stage_link_df[["source", "target"]].values.ravel("K"))})
        if not stage_link_df.empty
        else pd.DataFrame()
    )

    stage_order = {
        "Front-end processing": 0,
        "Mechanical treatment": 1,
        "Pyro treatment": 2,
        "Hydrometallurgy": 3,
        "Other processing": 4,
    }
    for col in ["In kg/h", "Out forward kg/h", "E_kWh_h"]:
        if col not in step_rows.columns:
            step_rows[col] = 0.0
        step_rows[col] = pd.to_numeric(step_rows[col], errors="coerce").fillna(0.0)
    stage_summary = step_rows.groupby("Stage", as_index=False).agg(
        Steps=("Step", "count"),
        Input_kg_h=("In kg/h", "sum"),
        Forward_kg_h=("Out forward kg/h", "sum"),
        Energy_kWh_h=("E_kWh_h", "sum"),
    )
    stage_summary["_sort"] = stage_summary["Stage"].map(stage_order).fillna(99)
    stage_summary = stage_summary.sort_values("_sort").drop(columns="_sort")
    stage_summary = stage_summary.rename(
        columns={
            "Input_kg_h": "Input (kg/h)",
            "Forward_kg_h": "Forward (kg/h)",
            "Energy_kWh_h": "Energy (kWh/h)",
        }
    )
    return stage_node_df, stage_link_df, stage_summary


def _clean_display_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    out = out.replace({None: "", "None": "", "none": "", "nan": "", "NaN": ""})
    out = out.fillna("")
    return format_dataframe_chemistry(out)


def _massflow_route_totals(mf_long: pd.DataFrame, route: str | None = None) -> pd.DataFrame:
    mf = _safe_df(mf_long).copy()
    if mf.empty or "_step_context" not in mf.columns:
        return pd.DataFrame()
    mf["Route section"] = mf["_step_context"].astype(str).map(lambda s: _process_stage(s, route))
    cols = [
        "Input (kg/h)",
        "Materials added (kg/h)",
        "Output forwarded (kg/h)",
        "Output separated (kg/h)",
    ]
    for col in cols:
        if col not in mf.columns:
            mf[col] = 0.0
        mf[col] = pd.to_numeric(mf[col], errors="coerce").fillna(0.0)
    totals = mf.groupby("Route section", as_index=False)[cols].sum()
    if totals.empty:
        return totals
    grand = {"Route section": "Total route"}
    for col in cols:
        grand[col] = float(totals[col].sum())
    return pd.concat([totals, pd.DataFrame([grand])], ignore_index=True)


def _stage_order_for_route(route: str | None = None) -> dict[str, int]:
    route_key = str(route or "").strip().lower()
    middle = "Pyro treatment" if route_key == "pyro" else "Mechanical treatment"
    return {
        "Front-end processing": 0,
        middle: 1,
        "Hydrometallurgy": 2,
        "Mechanical treatment": 3 if middle != "Mechanical treatment" else 1,
        "Pyro treatment": 3 if middle != "Pyro treatment" else 1,
        "Other processing": 9,
    }


def _norm_item_name(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _output_category_from_meta(label: str, ctx: dict | None) -> str:
    meta = dict((ctx or {}).get("price_meta", {}) or {})
    label_norm = _norm_item_name(label)
    fallback = str(label or "").strip().lower()
    if "clean gas" in fallback:
        return "utility stream"

    if not meta:
        return ""
    item_meta: list[tuple[str, str, str]] = []
    for item, info in meta.items():
        role = str((info or {}).get("role", "") or "").strip().lower()
        category = str((info or {}).get("category", "") or "").strip().lower()
        if role != "output" or category not in {"product", "residue", "utility", "utility stream", "utility streams"}:
            continue
        if category in {"utility", "utility streams"}:
            category = "utility stream"
        item_meta.append((str(item), _norm_item_name(str(item)), category))

    for item, item_norm, category in item_meta:
        if label_norm == item_norm:
            return category
    for item, item_norm, category in sorted(item_meta, key=lambda x: len(x[1]), reverse=True):
        if item_norm and (item_norm in label_norm or label_norm in item_norm):
            return category

    if "wastewater" in fallback or "waste" in fallback or "residue" in fallback or "sand" in fallback or "caso4" in fallback:
        return "residue"
    if "plastic" in fallback:
        return "residue"
    padded = f" {fallback} "
    product_tokens = [
        "black mass",
        "graphite",
        "precursor",
        "carbonate",
        "hydroxide",
        "oxalate",
        "copper",
        " cu",
        "cu ",
        "cu foil",
        "aluminium",
        " al",
        "al ",
        "al foil",
        "steel",
        "iron",
        " fe",
        "fe ",
        "electronics",
        "electronic",
    ]
    if any(token in padded for token in product_tokens):
        return "product"
    return ""


def _separated_outputs_df(mf_long: pd.DataFrame, ctx: dict | None, route: str | None = None) -> pd.DataFrame:
    mf = _safe_df(mf_long).copy()
    if mf.empty or "_step_context" not in mf.columns:
        return pd.DataFrame(columns=["Route section", "Category", "Name", "kg/h"])
    if "Output separated (kg/h)" not in mf.columns or "Name Output Separated" not in mf.columns:
        return pd.DataFrame(columns=["Route section", "Category", "Name", "kg/h"])

    mf["kg/h"] = pd.to_numeric(mf["Output separated (kg/h)"], errors="coerce").fillna(0.0)
    mf = mf[mf["kg/h"] > 1e-12].copy()
    if mf.empty:
        return pd.DataFrame(columns=["Route section", "Category", "Name", "kg/h"])

    mf["Name"] = mf["Name Output Separated"].astype(str).str.strip()
    mf["Route section"] = mf["_step_context"].astype(str).map(lambda s: _process_stage(s, route))
    mf["Category"] = mf["Name"].map(lambda name: _output_category_from_meta(name, ctx))
    mf["Category"] = mf["Category"].replace("", "unclassified")
    out = mf.groupby(["Route section", "Category", "Name"], as_index=False)["kg/h"].sum()
    return out.sort_values(["Route section", "Category", "kg/h"], ascending=[True, True, False])


def _stage_items_df(mf_long: pd.DataFrame, ctx: dict | None, route: str | None = None) -> pd.DataFrame:
    mf = _safe_df(mf_long).copy()
    if mf.empty or "_step_context" not in mf.columns:
        return pd.DataFrame(columns=["Group", "Route section", "Name", "kg/h"])
    rows: list[dict] = []

    separated = _separated_outputs_df(mf_long, ctx, route)
    group_labels = {
        "product": "Products",
        "residue": "Residues",
        "utility stream": "Utility streams",
        "unclassified": "Unclassified",
    }
    for _, r in separated.iterrows():
        category = str(r.get("Category", "") or "unclassified").strip().lower()
        rows.append(
            {
                "Group": group_labels.get(category, "Unclassified"),
                "Route section": str(r.get("Route section", "")),
                "Name": str(r.get("Name", "") or "").strip(),
                "kg/h": _safe_float(r.get("kg/h"), 0.0),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Group", "Route section", "Name", "kg/h"])
    out = pd.DataFrame(rows)
    stage_order = _stage_order_for_route(route)
    group_order = {"Products": 0, "Residues": 1, "Utility streams": 2, "Unclassified": 3}
    out["_stage_sort"] = out["Route section"].map(stage_order).fillna(99)
    out["_group_sort"] = out["Group"].map(group_order).fillna(9)
    return out.sort_values(["_group_sort", "_stage_sort", "kg/h"], ascending=[True, True, False]).drop(columns=["_group_sort", "_stage_sort"])


def _stage_cards_df(steps_df: pd.DataFrame, mf_long: pd.DataFrame, ctx: dict | None = None, route: str | None = None) -> pd.DataFrame:
    steps = _safe_df(steps_df).copy()
    if steps.empty or "Step" not in steps.columns:
        return pd.DataFrame()

    steps = steps[steps["Step"].astype(str).str.strip() != ""].reset_index(drop=True)
    steps["_label"] = steps["Step"].astype(str).map(_compact_step_label)
    steps["Stage"] = steps["Step"].astype(str).map(lambda s: _process_stage(s, route))
    stage_order = _stage_order_for_route(route)
    stages = (
        steps[["Stage"]]
        .drop_duplicates()
        .assign(_sort=lambda d: d["Stage"].map(stage_order).fillna(99))
        .sort_values("_sort")["Stage"]
        .tolist()
    )

    mf = _safe_df(mf_long).copy()
    if not mf.empty and "_step_context" in mf.columns:
        mf["Stage"] = mf["_step_context"].astype(str).map(lambda s: _process_stage(s, route))
        if "Materials added (kg/h)" in mf.columns:
            mf["Materials added (kg/h)"] = pd.to_numeric(mf["Materials added (kg/h)"], errors="coerce").fillna(0.0)
        else:
            mf["Materials added (kg/h)"] = 0.0

    def handoff_name(stage_name: str) -> str:
        route_key = str(route or "").strip().lower()
        if stage_name == "Front-end processing":
            return "modules"
        if stage_name == "Mechanical treatment":
            return "black mass"
        if stage_name == "Pyro treatment":
            return "Alloy + Slag" if route_key == "pyro" else ""
        return ""

    rows: list[dict] = []
    for idx, stage in enumerate(stages):
        stage_steps = steps[steps["Stage"] == stage].copy()
        if stage_steps.empty:
            continue

        in_v = _safe_float(stage_steps.iloc[0].get("In kg/h"), 0.0)
        reagent_v = (
            float(mf.loc[mf["Stage"] == stage, "Materials added (kg/h)"].sum())
            if not mf.empty and "Stage" in mf.columns
            else 0.0
        )

        if idx + 1 < len(stages):
            next_stage = stages[idx + 1]
            next_steps = steps[steps["Stage"] == next_stage]
            if stage == "Pyro treatment" and str(route or "").strip().lower() == "pyro":
                branch_mask = next_steps["Step"].astype(str).str.contains("Alloy Digestion|Slag Digestion", case=False, na=False)
                branch_steps = next_steps[branch_mask]
                output_v = float(pd.to_numeric(branch_steps["In kg/h"], errors="coerce").fillna(0.0).sum()) if not branch_steps.empty and "In kg/h" in branch_steps.columns else 0.0
            else:
                output_v = _safe_float(next_steps.iloc[0].get("In kg/h"), 0.0) if not next_steps.empty else 0.0
        else:
            output_v = 0.0

        rows.append(
            {
                "Stage": stage,
                "Steps": int((steps["Stage"] == stage).sum()),
                "Input": in_v,
                "Reagents": reagent_v,
                "Forwarded Stream": output_v,
                "Name Stream": handoff_name(stage),
            }
        )

    return pd.DataFrame(rows)


def _step_sequence_df(steps_df: pd.DataFrame, route: str | None = None) -> pd.DataFrame:
    steps = _safe_df(steps_df).copy()
    if steps.empty or "Step" not in steps.columns:
        return pd.DataFrame()

    def num_col(col: str, fallback: str | None = None) -> pd.Series:
        if col in steps.columns:
            raw = steps[col]
        elif fallback and fallback in steps.columns:
            raw = steps[fallback]
        else:
            raw = pd.Series([0.0] * len(steps), index=steps.index)
        return pd.to_numeric(raw, errors="coerce").fillna(0.0)

    out = pd.DataFrame(
        {
            "Stage": steps["Step"].astype(str).map(lambda s: _process_stage(s, route)),
            "Step": steps["Step"].astype(str),
            "Input (kg/h)": num_col("In kg/h"),
            "Forward (kg/h)": num_col("Out forward kg/h", fallback="Out kg/h"),
            "Side / separated (kg/h)": num_col("Side streams (kg/h)"),
            "Forward key": steps.get("Forward key", "").fillna("") if "Forward key" in steps.columns else "",
        }
    )
    return out


_METRIC_GROUP_ORDER = {
    "Mass flow": 0,
    "Materials": 1,
    "Energy": 2,
    "Economics": 3,
    "CAPEX / sizing": 4,
    "Other": 9,
}


def _metric_group(metric: str) -> str:
    m = str(metric).lower()
    if "kg/h" in m or "mass" in m or "loss" in m or "side" in m or "forward" in m:
        return "Mass flow"
    if "added" in m or "makeup" in m or "solution" in m or "water" in m:
        return "Materials"
    if "energy" in m or "kwh" in m:
        return "Energy"
    if "$" in m or "cost" in m or "opex" in m or "revenue" in m:
        return "Economics"
    if "capex" in m or "machine" in m or "capacity" in m or "line" in m:
        return "CAPEX / sizing"
    return "Other"


def _step_metric_df(step_row: pd.Series, steps_df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        c
        for c in steps_df.columns
        if c != "Step"
        and pd.api.types.is_numeric_dtype(steps_df[c])
        and abs(_safe_float(step_row.get(c), 0.0)) > 1e-12
    ]
    if not numeric_cols:
        return pd.DataFrame()
    metric_df = pd.DataFrame(
        {
            "Group": [_metric_group(c) for c in numeric_cols],
            "Metric": numeric_cols,
            "Value": [_safe_float(step_row.get(c), 0.0) for c in numeric_cols],
        }
    )
    metric_df["_group_sort"] = metric_df["Group"].map(_METRIC_GROUP_ORDER).fillna(99)
    metric_df["_abs"] = metric_df["Value"].abs()
    return metric_df.sort_values(["_group_sort", "_abs"], ascending=[True, False]).drop(columns=["_group_sort", "_abs"])


def _sankey_color_for_node(label: str) -> str:
    s = str(label).lower()
    if s.startswith("feed"):
        return "rgba(69, 117, 180, 0.85)"
    if s.startswith("reagent"):
        return "rgba(128, 90, 213, 0.75)"
    if s.startswith("output") or s.startswith("separated"):
        return "rgba(49, 163, 84, 0.75)"
    if "wastewater" in s or "loss" in s:
        return "rgba(215, 48, 39, 0.75)"
    return "rgba(90, 90, 90, 0.65)"


def _sankey_color_for_link(kind: str) -> str:
    return {
        "input": "rgba(69, 117, 180, 0.28)",
        "forward": "rgba(80, 80, 80, 0.26)",
        "output": "rgba(49, 163, 84, 0.30)",
        "separated": "rgba(49, 163, 84, 0.24)",
        "reagent": "rgba(128, 90, 213, 0.24)",
        "loss": "rgba(215, 48, 39, 0.28)",
    }.get(str(kind), "rgba(100, 100, 100, 0.22)")


_MASS_DASHBOARD_PFD_COLORS = {
    "feed": "#f8f9fb",
    "stream": "#f4f6f8",
    "stream_border": "#d8dce3",
    "front_end": "#6b7280",
    "middle": "#C9A004",
    "hydro": "#003B75",
    "products": "#e8f1fa",
    "products_border": "#a8c4e8",
    "side": "#c5cdd8",
    "side_text": "#6b7280",
    "reagent": "#2e7d32",
    "main_arrow": "#003B75",
    "text_light": "#ffffff",
    "stream_text": "#374151",
    "mass_text": "#9ca3af",
    "info_bg": "#eef5fc",
}

_MASS_ENERGY_MATERIAL_VALUE_COL = "Material input (kg/kg feed)"
_MASS_ENERGY_MATERIAL_UNIT_LABEL = "kg/kg feed processed"
_MASS_ENERGY_MATERIAL_HIDE_MINOR_THRESHOLD = 0.05

_MASS_ENERGY_MATERIAL_STAGE_TO_SECTION = {
    "Front-end processing": "Front-end processing",
    "Mechanical treatment": "Mechanical treatment",
    "Pyro treatment": "Pyrometallurgy",
    "Hydrometallurgy": "Hydrometallurgy",
}

_MASS_ENERGY_MATERIAL_SECTION_COLORS = {
    "Front-end processing": "#6b7280",
    "Mechanical treatment": "#c9a84c",
    "Pyrometallurgy": "#d4923a",
    "Hydrometallurgy": BRAND_BLUE,
}


def _mass_energy_material_stages_for_route(route_key: str) -> list[str]:
    route = str(route_key or "").strip().lower()
    if route == "pyro":
        return ["Front-end processing", "Pyrometallurgy", "Hydrometallurgy"]
    if route == "mech":
        return ["Front-end processing", "Mechanical treatment", "Hydrometallurgy"]
    return list(_MASS_ENERGY_MATERIAL_SECTION_COLORS.keys())


def _mass_energy_material_stage_filter_options(
    route_key: str,
    detail_df: pd.DataFrame,
) -> list[str]:
    options = ["All"]
    if detail_df is None or detail_df.empty:
        return ["All", *_mass_energy_material_stages_for_route(route_key)]
    for stage in _mass_energy_material_stages_for_route(route_key):
        if stage not in detail_df.columns:
            continue
        section_vals = pd.to_numeric(detail_df[stage], errors="coerce").fillna(0.0)
        if float(section_vals.sum()) > 1e-12:
            options.append(stage)
    return options


def _is_circulating_material_input(name: str) -> bool:
    """Exclude circulating solvent / extractant inventory from net material input."""
    return "circulating" in str(name or "").strip().lower()


def _mass_energy_material_section_label(stage: str) -> str:
    return _MASS_ENERGY_MATERIAL_STAGE_TO_SECTION.get(
        str(stage or "").strip(),
        _plant_process_stage_display_label(stage),
    )


def _mass_energy_material_input_detail_df(
    mf_long: pd.DataFrame,
    hours_y: float,
    annual_feed_kg: float,
    route_key: str,
) -> pd.DataFrame:
    value_col = _MASS_ENERGY_MATERIAL_VALUE_COL
    section_cols = list(_MASS_ENERGY_MATERIAL_SECTION_COLORS.keys())
    empty = pd.DataFrame(columns=["Material", value_col, "Dominant section", *section_cols])
    mf = _safe_df(mf_long).copy()
    if mf.empty or "Name Material added" not in mf.columns or "Materials added (kg/h)" not in mf.columns:
        return empty
    work = mf.copy()
    work["Materials added (kg/h)"] = pd.to_numeric(work["Materials added (kg/h)"], errors="coerce").fillna(0.0)
    work["Name Material added"] = work["Name Material added"].astype(str).str.strip()
    work = work[
        (work["Name Material added"] != "")
        & (work["Materials added (kg/h)"] > 1e-12)
        & (~work["Name Material added"].map(_is_circulating_material_input))
    ]
    if work.empty:
        return empty
    if "_step_context" not in work.columns:
        work["_step_context"] = ""
    work["_route_section"] = work["_step_context"].astype(str).map(
        lambda step: _mass_energy_material_section_label(_process_stage(step, route_key))
    )
    work["_kg_y"] = work["Materials added (kg/h)"] * float(hours_y)

    rows: list[dict[str, object]] = []
    for material, grp in work.groupby("Name Material added"):
        section_kg_y = {
            section: float(grp.loc[grp["_route_section"] == section, "_kg_y"].sum())
            for section in section_cols
        }
        total_kg_y = float(sum(section_kg_y.values()))
        if total_kg_y <= 1e-12:
            continue
        dominant = max(section_kg_y.items(), key=lambda item: item[1])[0]
        row: dict[str, object] = {
            "Material": format_chemistry_unicode(str(material)),
            value_col: _per_kg_feed(total_kg_y, annual_feed_kg),
            "Dominant section": dominant,
        }
        for section in section_cols:
            row[section] = _per_kg_feed(section_kg_y[section], annual_feed_kg)
        rows.append(row)
    if not rows:
        return empty
    return pd.DataFrame(rows)


_MASS_ENERGY_LOLLIPOP_STEM_COLOR = "#DCE2EB"
_MASS_ENERGY_LOLLIPOP_MARKER_SIZE = 15
_MASS_ENERGY_LOLLIPOP_ROW_HEIGHT_PX = 28
_MASS_ENERGY_LOLLIPOP_VALUE_NDIGITS = 2
_MASS_ENERGY_LOLLIPOP_MIN_HEIGHT_PX = _PROCESS_ECON_GWP_CHART_HEIGHT_PX
MASS_ENERGY_FLOW_TILE_HEIGHT_PX = 480
MASS_ENERGY_FLOW_TILE_CHART_HEIGHT_PX = 260
MASS_ENERGY_FLOW_TILE_OUTPUT_CHART_HEIGHT_PX = 360


def _build_mass_energy_material_lollipop_figure(
    plot_df: pd.DataFrame,
    *,
    selected_section: str,
    value_ndigits: int = _MASS_ENERGY_LOLLIPOP_VALUE_NDIGITS,
    max_height_px: int | None = None,
) -> "go.Figure | None":
    if go is None or plot_df is None or plot_df.empty:
        return None
    value_col = _MASS_ENERGY_MATERIAL_VALUE_COL
    df = plot_df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    df = df[df[value_col] > 1e-12].copy()
    if df.empty:
        return None
    # Ascending for Plotly categorical y: largest value appears at the top.
    df = df.sort_values(value_col, ascending=True)
    labels = df["Material"].astype(str).tolist()
    values = df[value_col].astype(float).tolist()
    value_labels = [f"{v:.{int(value_ndigits)}f}" for v in values]
    if selected_section != "All":
        section_for_row = selected_section
    else:
        section_for_row = None
    if selected_section != "All":
        marker_color = _MASS_ENERGY_MATERIAL_SECTION_COLORS.get(selected_section, BRAND_BLUE)
        colors = [marker_color] * len(df)
    else:
        colors = [
            _MASS_ENERGY_MATERIAL_SECTION_COLORS.get(str(row["Dominant section"]), BRAND_BLUE)
            for _, row in df.iterrows()
        ]

    stem_x: list[float | None] = []
    stem_y: list[str | None] = []
    for label, val in zip(labels, values):
        stem_x.extend([0.0, float(val), None])
        stem_y.extend([label, label, None])

    hover_rows: list[str] = []
    for _, row in df.iterrows():
        total = float(row[value_col])
        section = section_for_row or str(row["Dominant section"])
        hover = (
            f"{html_module.escape(str(row['Material']))}<br>"
            f"Input: {_fmt_metric(total, value_ndigits)} {_MASS_ENERGY_MATERIAL_UNIT_LABEL}<br>"
            f"Section: {html_module.escape(section)}"
        )
        hover_rows.append(hover)

    x_max = max(values) if values else 1.0
    x_pad_right = max(x_max * 0.14, 0.08)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=stem_x,
            y=stem_y,
            mode="lines",
            line={"color": _MASS_ENERGY_LOLLIPOP_STEM_COLOR, "width": 1.5},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=values,
            y=labels,
            mode="markers+text",
            text=value_labels,
            textposition="middle right",
            textfont={"size": 11, "color": "#4b5563", "family": "Inter, Segoe UI, Arial, sans-serif"},
            cliponaxis=False,
            marker={
                "size": _MASS_ENERGY_LOLLIPOP_MARKER_SIZE,
                "color": colors,
                "line": {"color": "#ffffff", "width": 1.5},
            },
            customdata=hover_rows,
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )
    )
    left_margin = max(150, min(300, 7 * max((len(label) for label in labels), default=12) + 32))
    fig_height = max(_MASS_ENERGY_LOLLIPOP_MIN_HEIGHT_PX, _MASS_ENERGY_LOLLIPOP_ROW_HEIGHT_PX * len(labels))
    if max_height_px is not None:
        fig_height = min(fig_height, int(max_height_px))
    fig.update_layout(
        height=fig_height,
        margin={"l": left_margin, "r": 56, "t": 12, "b": 40},
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"size": 12, "color": "#374151", "family": "Inter, Segoe UI, Arial, sans-serif"},
        hoverlabel={
            "bgcolor": "#ffffff",
            "bordercolor": "#d8dee8",
            "font": {"size": 12, "color": "#1f2937", "family": "Inter, Segoe UI, Arial, sans-serif"},
        },
        hovermode="closest",
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=False,
        ticks="",
        title="",
        range=[0.0, x_max + x_pad_right],
    )
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        showline=False,
        automargin=True,
        tickfont={"size": 12, "color": "#1f2937"},
        ticksuffix="  ",
    )
    return fig


def _mass_energy_material_input_by_item_df(
    mf_long: pd.DataFrame,
    hours_y: float,
    annual_feed_kg: float,
    route_key: str,
) -> pd.DataFrame:
    return _mass_energy_material_input_detail_df(mf_long, hours_y, annual_feed_kg, route_key)


def _pfd_process_stage_color(stage: str) -> str:
    key = str(stage or "").strip()
    mapping = {
        "Front-end processing": _MASS_DASHBOARD_PFD_COLORS["front_end"],
        "Mechanical treatment": _MASS_DASHBOARD_PFD_COLORS["middle"],
        "Pyro treatment": _MASS_DASHBOARD_PFD_COLORS["middle"],
        "Hydrometallurgy": _MASS_DASHBOARD_PFD_COLORS["hydro"],
        "Other processing": "#6697dd",
    }
    return mapping.get(key, "#6b7280")


def _render_mass_energy_material_input_chart(
    mf_long: pd.DataFrame,
    hours_y: float,
    annual_feed_kg: float,
    route_key: str,
    *,
    show_heading: bool = True,
    chart_max_height_px: int | None = None,
) -> None:
    if show_heading:
        _overview_section_heading("Reagent Distribution")
    detail_df = _mass_energy_material_input_detail_df(mf_long, hours_y, annual_feed_kg, route_key)
    value_col = _MASS_ENERGY_MATERIAL_VALUE_COL
    stage_options = _mass_energy_material_stage_filter_options(route_key, detail_df)
    _ensure_select_option("mass_energy_material_route_section", stage_options, default_index=0)
    selected_section = st.selectbox(
        "Process stage",
        stage_options,
        key="mass_energy_material_route_section",
    )

    plot_df = detail_df.copy()
    if plot_df.empty:
        st.caption("No material input data available.")
        return

    if selected_section != "All":
        if selected_section in plot_df.columns:
            plot_df[value_col] = pd.to_numeric(plot_df[selected_section], errors="coerce").fillna(0.0)
            plot_df["Dominant section"] = selected_section
            plot_df = plot_df[plot_df[value_col] > 1e-12].copy()

    plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce").fillna(0.0)
    plot_df = plot_df[plot_df[value_col] > 1e-12].copy()
    if plot_df.empty:
        st.caption("No material input data available for the selected process stage.")
        return

    total_input = float(plot_df[value_col].sum())
    hide_minor = st.session_state.get("mass_energy_material_hide_minor", True)
    filtered_df = plot_df.copy()
    if hide_minor and total_input > 0:
        filtered_df = filtered_df[
            filtered_df[value_col] / total_input >= _MASS_ENERGY_MATERIAL_HIDE_MINOR_THRESHOLD
        ].copy()
    filtered_df = filtered_df.sort_values(value_col, ascending=False).head(12).copy()

    if filtered_df.empty:
        st.caption("No material inputs above the 5% threshold.")
        return

    fig = _build_mass_energy_material_lollipop_figure(
        filtered_df,
        selected_section=selected_section,
        max_height_px=chart_max_height_px,
    )
    if fig is not None:
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CHART_CONFIG)
    else:
        st.caption("No material input data available.")

    st.checkbox(
        "Hide minor inputs (<5%)",
        value=True,
        key="mass_energy_material_hide_minor",
    )


_MASS_ENERGY_ROUTE_SECTION_SPECS: dict[str, list[tuple[str, str]]] = {
    "pyro": [
        ("Front-End Processing", "front_end"),
        ("Pyrometallurgy", "pyro"),
        ("Hydrometallurgy (Alloy)", "hydro_alloy"),
        ("Hydrometallurgy (Slag)", "hydro_slag"),
    ],
    "mech": [
        ("Front-End Processing", "front_end"),
        ("Mechanical Treatment", "mechanical"),
        ("Hydrometallurgy", "hydro"),
    ],
}

_MASS_ENERGY_ROUTE_SECTION_COLORS = {
    "Front-End Processing": "#6b7280",
    "Mechanical Treatment": "#C9A004",
    "Pyrometallurgy": "#C9A004",
    "Hydrometallurgy": BRAND_BLUE,
    "Hydrometallurgy (Alloy)": BRAND_BLUE,
    "Hydrometallurgy (Slag)": BRAND_BLUE,
}

_MASS_ENERGY_DISTRIBUTION_MIN_DISPLAY_MW = 0.01
_MASS_ENERGY_RECOVERY_BAR_COLOR = "#059669"


def _fmt_energy_distribution_mw_value(mw: float) -> str:
    val = float(mw)
    if abs(val) < 1e-12:
        return "0.00"
    if 0.0 < val < _MASS_ENERGY_DISTRIBUTION_MIN_DISPLAY_MW:
        return "<0.01"
    if -_MASS_ENERGY_DISTRIBUTION_MIN_DISPLAY_MW < val < 0.0:
        return "-<0.01"
    return _fmt_dashboard_num(val, 2)


def _fmt_energy_distribution_mw_label(mw: float) -> str:
    return f"{_fmt_energy_distribution_mw_value(mw)} MW"


def _mass_energy_distribution_hover_html(
    *,
    energy_mw: float,
    share_total_pct: float,
    share_stage_pct: float,
) -> str:
    if float(energy_mw) < 0.0:
        energy_line = f"Energy recovery: {_fmt_energy_distribution_mw_value(abs(energy_mw))} MW"
    else:
        energy_line = f"Energy demand: {_fmt_energy_distribution_mw_value(energy_mw)} MW"
    lines = [
        energy_line,
        f"Share of total energy demand: {_fmt_dashboard_num(share_total_pct, 1)} %",
        f"Share within process stage: {_fmt_dashboard_num(share_stage_pct, 1)} %",
    ]
    return "".join(
        f'<div style="margin:0;white-space:nowrap;">{html_module.escape(line)}</div>'
        for line in lines
    )


_MASS_ENERGY_DISTRIBUTION_TOOLTIP_CSS = """
.libra-ed-panel details,
.libra-ed-panel summary {
    overflow: visible !important;
}
.libra-ed-row {
    position: relative;
    cursor: help;
}
.libra-ed-row .libra-ed-tip {
    position: absolute;
    left: 0;
    bottom: calc(100% + 6px);
    background: #1f2937;
    color: #f9fafb;
    padding: 8px 10px;
    border-radius: 6px;
    font-family: Inter, Segoe UI, Arial, sans-serif;
    font-size: 0.78rem;
    line-height: 1.45;
    pointer-events: none;
    opacity: 0;
    visibility: hidden;
    z-index: 1000;
    min-width: 220px;
    max-width: 340px;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.22);
    transition: opacity 0.12s ease, visibility 0.12s ease;
}
.libra-ed-row:hover .libra-ed-tip {
    opacity: 1;
    visibility: visible;
}
"""


def _mass_energy_hierarchy_tooltip_wrap_html(inner_html: str, tooltip_html: str) -> str:
    if not tooltip_html:
        return inner_html
    return (
        f'<div class="libra-ed-row">'
        f'<div class="libra-ed-tip">{tooltip_html}</div>'
        f"{inner_html}"
        f"</div>"
    )


def _mass_energy_route_section_key(
    step: str,
    route_key: str,
    hydro_branch: str | None,
) -> str:
    route = str(route_key or "").strip().lower()
    stage = _process_stage(step, route_key)
    if stage == "Front-end processing":
        return "front_end"
    if route == "pyro":
        if stage == "Pyro treatment":
            return "pyro"
        if stage == "Hydrometallurgy":
            if hydro_branch == "slag":
                return "hydro_slag"
            if hydro_branch == "alloy":
                return "hydro_alloy"
    if route == "mech":
        if stage == "Mechanical treatment":
            return "mechanical"
        if stage == "Hydrometallurgy":
            return "hydro"
    return ""


def _mass_energy_hierarchy_df(steps_df: pd.DataFrame, route_key: str) -> pd.DataFrame:
    steps = _safe_df(steps_df).copy()
    empty = pd.DataFrame(columns=["section_key", "section_label", "step_label", "Energy (MW)"])
    if steps.empty or "Step" not in steps.columns or "E_kWh_h" not in steps.columns:
        return empty
    steps = steps[steps["Step"].astype(str).str.strip() != ""].copy()
    if steps.empty:
        return empty

    step_names = steps["Step"].astype(str).tolist()
    route = str(route_key or "").strip().lower()
    branch_keys = _pyro_hydro_branch_keys(step_names) if route == "pyro" else [None] * len(step_names)
    key_to_label = {
        key: label
        for label, key in _MASS_ENERGY_ROUTE_SECTION_SPECS.get(route, _MASS_ENERGY_ROUTE_SECTION_SPECS["mech"])
    }

    rows: list[dict[str, object]] = []
    for (_, row), branch in zip(steps.iterrows(), branch_keys):
        mw = _kwh_h_to_mw(_safe_float(row.get("E_kWh_h"), 0.0))
        if abs(mw) <= 1e-12:
            continue
        step_name = str(row["Step"])
        section_key = _mass_energy_route_section_key(step_name, route_key, branch)
        if not section_key or section_key not in key_to_label:
            continue
        rows.append(
            {
                "section_key": section_key,
                "section_label": key_to_label[section_key],
                "step_label": _compact_step_label(step_name),
                "Energy (MW)": float(mw),
            }
        )
    if not rows:
        return empty
    out = pd.DataFrame(rows)
    out["_abs_mw"] = out["Energy (MW)"].abs()
    return out


def _mass_energy_distribution_signed_scale(
    hierarchy: pd.DataFrame,
    section_totals: dict[str, float],
) -> tuple[float, float]:
    values: list[float] = [float(v) for v in section_totals.values()]
    if not hierarchy.empty and "Energy (MW)" in hierarchy.columns:
        values.extend(float(v) for v in hierarchy["Energy (MW)"].tolist())
    max_pos = max((v for v in values if v > 1e-12), default=0.0)
    max_neg = max((abs(v) for v in values if v < -1e-12), default=0.0)
    if max_pos <= 1e-12 and max_neg <= 1e-12:
        return 1.0, 0.0
    return max_pos, max_neg


def _mass_energy_zero_line_pct(max_pos: float, max_neg: float) -> float:
    if max_neg <= 1e-12:
        return 0.0
    if max_pos <= 1e-12:
        return 100.0
    return max_neg / (max_pos + max_neg) * 100.0


def _mass_energy_distribution_caption_html() -> str:
    return (
        '<div style="margin:0 0 10px 0;font-family:Inter,Segoe UI,Arial,sans-serif;'
        'font-size:0.8rem;color:#6b7280;line-height:1.4;">'
        "Positive values represent energy demand, negative values represent energy recovery."
        "</div>"
    )


def _mass_energy_recovery_bar_color(section_key: str, section_color: str) -> str:
    if section_key == "front_end":
        return section_color
    return _MASS_ENERGY_RECOVERY_BAR_COLOR


def _mass_energy_signed_bar_track_html(
    value_mw: float,
    *,
    max_pos: float,
    max_neg: float,
    color: str,
    bar_h: int = 14,
    recovery_color: str = _MASS_ENERGY_RECOVERY_BAR_COLOR,
) -> str:
    val = float(value_mw)
    zero_pct = _mass_energy_zero_line_pct(max_pos, max_neg)
    zero_line = ""
    if max_neg > 1e-12:
        zero_line = (
            f'<div style="position:absolute;left:{zero_pct:.4f}%;top:0;bottom:0;'
            f'width:2px;margin-left:-1px;background:#000000;z-index:2;"></div>'
        )
    bar_fill = ""
    if val > 1e-12 and max_pos > 1e-12:
        pos_span = 100.0 - zero_pct
        width_pct = min(pos_span, max(0.0, val / max_pos * pos_span))
        bar_fill = (
            f'<div style="position:absolute;left:{zero_pct:.4f}%;top:0;bottom:0;'
            f'width:{width_pct:.4f}%;background:{color};'
            f'border-radius:0 3px 3px 0;z-index:1;"></div>'
        )
    elif val < -1e-12 and max_neg > 1e-12:
        width_pct = min(zero_pct, max(0.0, abs(val) / max_neg * zero_pct))
        left_pct = zero_pct - width_pct
        bar_fill = (
            f'<div style="position:absolute;left:{left_pct:.4f}%;top:0;bottom:0;'
            f'width:{width_pct:.4f}%;background:{recovery_color};'
            f'border-radius:3px 0 0 3px;z-index:1;"></div>'
        )
    return (
        f'<div style="position:relative;height:{bar_h}px;background:#eef1f5;'
        f'border-radius:3px;overflow:visible;">'
        f"{zero_line}{bar_fill}</div>"
    )


def _mass_energy_hierarchy_bar_block_html(
    label: str,
    value_mw: float,
    *,
    max_pos: float,
    max_neg: float,
    color: str,
    indent_px: int = 0,
    bold: bool = False,
    tooltip: str = "",
    recovery_color: str = _MASS_ENERGY_RECOVERY_BAR_COLOR,
) -> str:
    label_esc = html_module.escape(str(label))
    value_txt = _fmt_energy_distribution_mw_label(value_mw)
    weight = 700 if bold else 600
    size = "0.93rem" if bold else "0.88rem"
    bar_h = 18 if bold else 14
    bar_track = _mass_energy_signed_bar_track_html(
        value_mw,
        max_pos=max_pos,
        max_neg=max_neg,
        color=color,
        bar_h=bar_h,
        recovery_color=recovery_color,
    )
    inner = (
        f'<div style="margin:0 0 10px 0;padding-left:{indent_px}px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;'
        f'margin:0 0 4px 0;">'
        f'<div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:{size};'
        f'font-weight:{weight};color:#1f2937;">{label_esc}</div>'
        f'<div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:0.82rem;'
        f'font-weight:600;color:#5f6c7b;white-space:nowrap;">{value_txt}</div>'
        f"</div>"
        f"{bar_track}</div>"
    )
    return _mass_energy_hierarchy_tooltip_wrap_html(inner, tooltip)


def _mass_energy_hierarchy_bar_only_html(
    value_mw: float,
    *,
    max_pos: float,
    max_neg: float,
    color: str,
    bar_h: int = 18,
    tooltip: str = "",
    wrap_tooltip: bool = True,
    recovery_color: str = _MASS_ENERGY_RECOVERY_BAR_COLOR,
) -> str:
    inner = (
        f'<div style="margin:0 0 8px 0;">'
        f"{_mass_energy_signed_bar_track_html(value_mw, max_pos=max_pos, max_neg=max_neg, color=color, bar_h=bar_h, recovery_color=recovery_color)}"
        f"</div>"
    )
    if wrap_tooltip and tooltip:
        return _mass_energy_hierarchy_tooltip_wrap_html(inner, tooltip)
    return inner


def _mass_energy_hierarchy_section_totals(
    hierarchy: pd.DataFrame,
    route_key: str,
) -> dict[str, float]:
    route = str(route_key or "").strip().lower()
    section_specs = _MASS_ENERGY_ROUTE_SECTION_SPECS.get(route, _MASS_ENERGY_ROUTE_SECTION_SPECS["mech"])
    totals = {section_key: 0.0 for _, section_key in section_specs}
    if hierarchy is None or hierarchy.empty:
        return totals
    grouped = hierarchy.groupby("section_key", as_index=False)["Energy (MW)"].sum()
    for _, row in grouped.iterrows():
        key = str(row["section_key"])
        if key in totals:
            totals[key] = float(row["Energy (MW)"])
    return totals


def _render_mass_energy_energy_hierarchy(
    steps_df: pd.DataFrame,
    route_key: str,
    *,
    min_panel_height_px: int | None = None,
) -> None:
    hierarchy = _mass_energy_hierarchy_df(steps_df, route_key)
    route = str(route_key or "").strip().lower()
    section_specs = _MASS_ENERGY_ROUTE_SECTION_SPECS.get(route, _MASS_ENERGY_ROUTE_SECTION_SPECS["mech"])
    section_totals = _mass_energy_hierarchy_section_totals(hierarchy, route_key)
    total_abs_mw = (
        float(hierarchy["_abs_mw"].sum())
        if not hierarchy.empty and "_abs_mw" in hierarchy.columns
        else 0.0
    )
    max_pos, max_neg = _mass_energy_distribution_signed_scale(hierarchy, section_totals)
    caption_html = _mass_energy_distribution_caption_html()

    blocks: list[str] = []
    for section_label, section_key in section_specs:
        section_total = float(section_totals.get(section_key, 0.0))
        section_steps = pd.DataFrame()
        if not hierarchy.empty:
            section_steps = hierarchy[hierarchy["section_key"] == section_key].copy()
            section_steps = section_steps.sort_values("_abs_mw", ascending=False)
        stage_abs_mw = (
            float(section_steps["_abs_mw"].sum())
            if not section_steps.empty and "_abs_mw" in section_steps.columns
            else 0.0
        )
        color = _MASS_ENERGY_ROUTE_SECTION_COLORS.get(section_label, BRAND_BLUE)
        recovery_color = _mass_energy_recovery_bar_color(section_key, color)
        step_rows = "".join(
            _mass_energy_hierarchy_bar_block_html(
                str(row["step_label"]),
                float(row["Energy (MW)"]),
                max_pos=max_pos,
                max_neg=max_neg,
                color=color,
                recovery_color=recovery_color,
                indent_px=18,
                tooltip=_mass_energy_distribution_hover_html(
                    energy_mw=float(row["Energy (MW)"]),
                    share_total_pct=(
                        float(row["_abs_mw"]) / total_abs_mw * 100.0 if total_abs_mw > 1e-12 else 0.0
                    ),
                    share_stage_pct=(
                        float(row["_abs_mw"]) / stage_abs_mw * 100.0 if stage_abs_mw > 1e-12 else 0.0
                    ),
                ),
            )
            for _, row in section_steps.iterrows()
        )
        label_esc = html_module.escape(section_label)
        value_txt = _fmt_energy_distribution_mw_label(section_total)
        section_share_total = (
            abs(section_total) / total_abs_mw * 100.0 if total_abs_mw > 1e-12 else 0.0
        )
        section_tooltip = _mass_energy_distribution_hover_html(
            energy_mw=section_total,
            share_total_pct=section_share_total,
            share_stage_pct=100.0 if abs(section_total) > 1e-12 else 0.0,
        )
        section_bar = _mass_energy_hierarchy_bar_only_html(
            section_total,
            max_pos=max_pos,
            max_neg=max_neg,
            color=color,
            recovery_color=recovery_color,
            wrap_tooltip=False,
        )
        section_summary = _mass_energy_hierarchy_tooltip_wrap_html(
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;">'
            f'<div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:0.93rem;'
            f'font-weight:700;color:#1f2937;">{label_esc}</div>'
            f'<div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:0.82rem;'
            f'font-weight:600;color:#5f6c7b;white-space:nowrap;">{value_txt}</div>'
            f"</div>{section_bar}",
            section_tooltip,
        )
        blocks.append(
            f'<details style="margin:0 0 12px 0;border:1px solid {OVERVIEW_CARD_BORDER};'
            f'border-radius:8px;padding:10px 12px;background:#fafbfd;">'
            f'<summary style="cursor:pointer;list-style-position:outside;margin:0 0 4px 0;">'
            f"{section_summary}</summary>"
            f'<div style="margin-top:4px;">{step_rows}</div></details>'
        )

    min_height = int(min_panel_height_px or _PROCESS_ECON_GWP_CHART_HEIGHT_PX)
    st.markdown(
        f"<style>{_MASS_ENERGY_DISTRIBUTION_TOOLTIP_CSS}</style>"
        f'<div class="libra-ed-panel" style="min-height:{min_height}px;'
        f'font-family:Inter,Segoe UI,Arial,sans-serif;">'
        f'{caption_html}{"".join(blocks)}</div>',
        unsafe_allow_html=True,
    )


def _pfd_stream_inline(title: str, kg_h: float, hours_y: float) -> str:
    title_clean = str(title).replace("<br>", " ").strip()
    mass = _pfd_mass_text(kg_h, hours_y)
    if not mass:
        return title_clean
    return f"{title_clean} ({mass})"


def _pfd_split_title_mass(label: str) -> tuple[str, str]:
    raw = str(label).replace("<br>", " ").strip()
    if " (" in raw and raw.endswith(")"):
        idx = raw.rindex(" (")
        return raw[:idx], raw[idx + 2 : -1]
    return raw, ""


def _pfd_attr_title(text: str) -> str:
    return (
        str(text)
        .replace("<br>", " | ")
        .replace("<b>", "")
        .replace("</b>", "")
        .strip()
    )


def _render_mass_dashboard_pfd_html(model: dict | None, *, compact: bool = False) -> str | None:
    """Render the overview process flow as responsive HTML/CSS (no Plotly)."""
    if model is None or not model.get("nodes"):
        return None

    nodes = list(model["nodes"])
    main_flows = list(model.get("main_flows", []))
    side_streams_by_node = dict(model.get("side_streams_by_node", {}))
    hours_y = float(model.get("hours_y", 8000.0))
    c = _MASS_DASHBOARD_PFD_COLORS

    def _esc(text: str) -> str:
        return html_module.escape(str(text))

    def _side_block(node_id: str) -> str:
        items = side_streams_by_node.get(node_id, [])
        if not items:
            return '<div class="mass-pfd-slot-bottom"></div>'
        if len(items) == 1:
            item = items[0]
            title, mass = _pfd_split_title_mass(str(item.get("label", item.get("title", ""))))
            mass_line = f'<span class="mass-pfd-side-mass">({_esc(mass)})</span>' if mass else ""
            return (
                f'<div class="mass-pfd-slot-bottom">'
                f'<div class="mass-pfd-side-single">'
                f'<div class="mass-pfd-side-trunk" aria-hidden="true"></div>'
                f'<div class="mass-pfd-side-text">{_esc(title)}{mass_line}</div>'
                f"</div></div>"
            )
        branches: list[str] = []
        for item in items:
            title, mass = _pfd_split_title_mass(str(item.get("label", item.get("title", ""))))
            mass_line = f'<span class="mass-pfd-side-mass">({_esc(mass)})</span>' if mass else ""
            branches.append(
                f'<div class="mass-pfd-side-branch">'
                f'<div class="mass-pfd-side-branch-line" aria-hidden="true"></div>'
                f'<div class="mass-pfd-side-text">{_esc(title)}{mass_line}</div>'
                f"</div>"
            )
        return (
            f'<div class="mass-pfd-slot-bottom">'
            f'<div class="mass-pfd-side-fork">'
            f'<div class="mass-pfd-side-branches">{"".join(branches)}</div>'
            f"</div></div>"
        )

    def _reagent_block(node: dict[str, object]) -> str:
        if str(node.get("kind")) != "process":
            return '<div class="mass-pfd-slot-top"></div>'
        reagent_kg_h = _safe_float(node.get("reagents_kg_h"), 0.0)
        if reagent_kg_h <= 1e-12:
            return '<div class="mass-pfd-slot-top"></div>'
        tip = _esc(_pfd_attr_title(f"Reagents: {_pfd_t_y_label(reagent_kg_h, hours_y)}"))
        mass_label = _pfd_mass_text(reagent_kg_h, hours_y)
        mass_html = (
            f'<span class="mass-pfd-reagent-mass">({_esc(mass_label)})</span>' if mass_label else ""
        )
        return (
            f'<div class="mass-pfd-slot-top">'
            f'<div class="mass-pfd-reagent" title="{tip}">'
            f'<span class="mass-pfd-reagent-label">+ Reagents</span>{mass_html}'
            f'<div class="mass-pfd-reagent-line" aria-hidden="true"></div>'
            f"</div></div>"
        )

    def _node_block(node: dict[str, object]) -> str:
        kind = str(node.get("kind", ""))
        tip = _esc(_pfd_attr_title(str(node.get("hover", ""))))
        if kind == "process":
            return (
                f'<div class="mass-pfd-process" style="background:{_esc(str(node["color"]))};" title="{tip}">'
                f'<span class="mass-pfd-process-label">{_esc(str(node.get("display_label", "")))}</span>'
                f"</div>"
            )
        title, mass = _pfd_split_title_mass(str(node.get("display_label", "")))
        border = str(node.get("border", c["stream_border"]))
        bg = str(node.get("color", c["stream"]))
        is_products = str(node.get("id", "")) == "products"
        stream_cls = "mass-pfd-stream mass-pfd-stream-products" if is_products else "mass-pfd-stream"
        mass_html = f'<span class="mass-pfd-stream-mass">{_esc(mass)}</span>' if mass else ""
        return (
            f'<div class="{stream_cls}" style="background:{_esc(bg)};border-color:{_esc(border)};" title="{tip}">'
            f'<span class="mass-pfd-stream-title">{_esc(title)}</span>{mass_html}'
            f"</div>"
        )

    def _arrow_block(flow: dict[str, object]) -> str:
        tip = _esc(str(flow.get("title", "") or ""))
        return (
            f'<div class="mass-pfd-arrow-col" title="{tip}">'
            f'<div class="mass-pfd-arrow" aria-hidden="true">'
            f'<div class="mass-pfd-arrow-shaft"></div>'
            f'<div class="mass-pfd-arrow-head"></div>'
            f"</div></div>"
        )

    chain_parts: list[str] = []
    for idx, node in enumerate(nodes):
        if idx > 0:
            flow = main_flows[idx - 1] if idx - 1 < len(main_flows) else {}
            chain_parts.append(_arrow_block(flow))
        node_id = str(node.get("id", ""))
        chain_parts.append(
            f'<div class="mass-pfd-node-col">'
            f"{_reagent_block(node)}"
            f'<div class="mass-pfd-slot-main">{_node_block(node)}</div>'
            f"{_side_block(node_id)}"
            f"</div>"
        )

    pfd_css = f"""
.mass-pfd-wrap {{
  font-family: inherit;
  margin: 4px 0 0 0;
}}
.mass-pfd-wrap-centered {{
  margin: 4px auto 0 auto;
  width: 100%;
  max-width: 100%;
}}
.mass-pfd-wrap-centered .mass-pfd-scroll {{
  display: flex;
  justify-content: flex-start;
  width: 100%;
}}
.mass-pfd-scroll {{
  overflow-x: auto;
  overflow-y: hidden;
  padding: 4px 2px 10px 2px;
  -webkit-overflow-scrolling: touch;
}}
.mass-pfd-chain {{
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  min-width: max-content;
  margin: 0 auto;
  gap: 0;
}}
.mass-pfd-node-col {{
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
}}
.mass-pfd-slot-top {{
  height: 38px;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}}
.mass-pfd-slot-main {{
  min-height: 95px;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.mass-pfd-slot-bottom {{
  min-height: 90px;
  width: 100%;
  display: flex;
  justify-content: center;
  padding-top: 4px;
}}
.mass-pfd-process {{
  min-width: 220px;
  width: 220px;
  height: 95px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 10px 14px;
  box-sizing: border-box;
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}}
.mass-pfd-process-label {{
  color: {c["text_light"]};
  font-size: 15px;
  font-weight: 700;
  line-height: 1.25;
}}
.mass-pfd-stream {{
  width: 145px;
  min-width: 145px;
  height: 58px;
  border-radius: 29px;
  border: 2px solid {c["stream_border"]};
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 6px 10px;
  box-sizing: border-box;
}}
.mass-pfd-stream-products {{
  border-width: 2px;
}}
.mass-pfd-stream-title {{
  color: {BRAND_BLUE};
  font-size: 13px;
  font-weight: 600;
  line-height: 1.2;
}}
.mass-pfd-stream-mass {{
  color: #4b5563;
  font-size: 12px;
  line-height: 1.2;
  margin-top: 2px;
}}
.mass-pfd-arrow-col {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 44px;
  margin-top: 38px;
  min-height: 95px;
}}
.mass-pfd-arrow {{
  display: flex;
  align-items: center;
  width: 100%;
}}
.mass-pfd-arrow-shaft {{
  flex: 1;
  height: 4px;
  background: {c["main_arrow"]};
  border-radius: 2px;
}}
.mass-pfd-arrow-head {{
  width: 0;
  height: 0;
  border-top: 7px solid transparent;
  border-bottom: 7px solid transparent;
  border-left: 11px solid {c["main_arrow"]};
  margin-left: -1px;
}}
.mass-pfd-reagent {{
  display: flex;
  flex-direction: column;
  align-items: center;
}}
.mass-pfd-reagent-label {{
  color: {c["reagent"]};
  font-size: 12px;
  font-weight: 600;
  line-height: 1.15;
  margin-bottom: 1px;
}}
.mass-pfd-reagent-mass {{
  display: block;
  color: #4b5563;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.1;
  margin-bottom: 3px;
}}
.mass-pfd-reagent-line {{
  width: 0;
  height: 14px;
  border-left: 2px dashed {c["reagent"]};
}}
.mass-pfd-side-single,
.mass-pfd-side-fork {{
  display: flex;
  flex-direction: column;
  align-items: center;
}}
.mass-pfd-side-trunk {{
  width: 0;
  height: 16px;
  border-left: 2px dotted {c["side"]};
}}
.mass-pfd-side-branches {{
  display: flex;
  flex-direction: row;
  gap: 18px;
  align-items: flex-start;
  justify-content: center;
}}
.mass-pfd-side-branch {{
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 100px;
  max-width: 142px;
}}
.mass-pfd-side-branch-line {{
  width: 28px;
  height: 0;
  border-top: 2px dotted {c["side"]};
  margin-bottom: 0;
}}
.mass-pfd-side-fork .mass-pfd-side-branch-line {{
  width: 0;
  height: 18px;
  border-top: none;
  border-left: 2px dotted {c["side"]};
}}
.mass-pfd-side-text {{
  color: {c["side_text"]};
  font-size: 12.5px;
  line-height: 1.3;
  text-align: center;
  margin-top: 4px;
}}
.mass-pfd-side-mass {{
  display: block;
  color: #6b7280;
  font-size: 11px;
  margin-top: 1px;
}}
.mass-pfd-legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 18px 28px;
  align-items: center;
  margin-top: 8px;
  padding: 0 4px;
  font-size: 12px;
  color: #5f6c7b;
}}
.mass-pfd-legend-item {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.mass-pfd-legend-main {{
  width: 34px;
  height: 4px;
  background: {c["main_arrow"]};
  border-radius: 2px;
}}
.mass-pfd-legend-reagent {{
  width: 22px;
  height: 0;
  border-top: 2px dashed {c["reagent"]};
}}
.mass-pfd-legend-side {{
  width: 22px;
  height: 0;
  border-top: 2px dotted {c["side"]};
}}
"""
    if compact:
        scale = OVERVIEW_PFD_COMPACT_SCALE
        pfd_css += f"""
.mass-pfd-wrap-compact {{
  --pfd-s: {scale};
}}
.mass-pfd-wrap-compact .mass-pfd-scroll {{
  overflow-x: auto;
  overflow-y: hidden;
  padding: 2px 2px 10px 2px;
  -webkit-overflow-scrolling: touch;
}}
.mass-pfd-wrap-compact .mass-pfd-chain {{
  min-width: max-content;
  align-items: flex-start;
}}
.mass-pfd-wrap-compact .mass-pfd-node-col {{
  position: relative;
  align-items: center;
  padding-bottom: 90px;
  flex-shrink: 0;
}}
.mass-pfd-wrap-compact .mass-pfd-slot-top {{
  height: 46px;
  min-height: 46px;
  width: 100%;
}}
.mass-pfd-wrap-compact .mass-pfd-slot-main {{
  min-height: calc(95px * var(--pfd-s));
  width: fit-content;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.mass-pfd-wrap-compact .mass-pfd-slot-bottom {{
  position: absolute;
  left: 50%;
  bottom: 0;
  transform: translateX(-50%);
  min-height: 86px;
  width: max-content;
  max-width: 332px;
  padding-top: 4px;
}}
.mass-pfd-wrap-compact .mass-pfd-process {{
  min-width: calc(220px * var(--pfd-s));
  width: calc(220px * var(--pfd-s));
  height: calc(95px * var(--pfd-s));
  padding: calc(10px * var(--pfd-s)) calc(14px * var(--pfd-s));
}}
.mass-pfd-wrap-compact .mass-pfd-process-label {{
  font-size: calc(15px * var(--pfd-s));
}}
.mass-pfd-wrap-compact .mass-pfd-stream {{
  width: calc(145px * var(--pfd-s));
  min-width: calc(145px * var(--pfd-s));
  height: calc(58px * var(--pfd-s));
  border-radius: calc(29px * var(--pfd-s));
  padding: calc(6px * var(--pfd-s)) calc(10px * var(--pfd-s));
}}
.mass-pfd-wrap-compact .mass-pfd-stream-title {{
  font-size: calc(13px * var(--pfd-s));
}}
.mass-pfd-wrap-compact .mass-pfd-stream-mass {{
  font-size: calc(12px * var(--pfd-s));
}}
.mass-pfd-wrap-compact .mass-pfd-arrow-col {{
  width: 44px;
  min-width: 44px;
  margin-top: 46px;
  min-height: calc(95px * var(--pfd-s));
  align-self: flex-start;
}}
.mass-pfd-wrap-compact .mass-pfd-arrow-head {{
  border-top-width: 7px;
  border-bottom-width: 7px;
  border-left-width: 11px;
}}
.mass-pfd-wrap-compact .mass-pfd-side-branches {{
  gap: 18px;
}}
.mass-pfd-wrap-compact .mass-pfd-side-branch {{
  min-width: 90px;
  max-width: 130px;
}}
.mass-pfd-wrap-compact .mass-pfd-side-text {{
  font-size: 12px;
}}
.mass-pfd-wrap-compact .mass-pfd-side-mass {{
  font-size: 11px;
}}
.mass-pfd-wrap-compact .mass-pfd-reagent-label {{
  font-size: 12px;
}}
.mass-pfd-wrap-compact .mass-pfd-reagent-mass {{
  font-size: 11px;
}}
.mass-pfd-wrap-compact .mass-pfd-legend {{
  margin-top: 4px;
  gap: 10px 18px;
  font-size: 11px;
}}
"""
    wrap_class = (
        "mass-pfd-wrap mass-pfd-wrap-compact"
        if compact
        else "mass-pfd-wrap mass-pfd-wrap-centered"
    )
    return f"""
<style>
{pfd_css}
</style>
<div class="{wrap_class}">
  <div class="mass-pfd-scroll">
    <div class="mass-pfd-chain">
      {"".join(chain_parts)}
    </div>
  </div>
  <div class="mass-pfd-legend">
    <div class="mass-pfd-legend-item"><span class="mass-pfd-legend-main"></span>Main material flow</div>
    <div class="mass-pfd-legend-item"><span class="mass-pfd-legend-reagent"></span>Reagents added</div>
    <div class="mass-pfd-legend-item"><span class="mass-pfd-legend-side"></span>Side streams / outputs</div>
  </div>
</div>
"""


def _pfd_mass_paren(kg_h: float, hours_y: float, *, ndigits: int = 0) -> str:
    mass = _pfd_mass_text(kg_h, hours_y, ndigits=ndigits)
    return f"({mass})" if mass else ""


def _pfd_mass_text(kg_h: float, hours_y: float, *, ndigits: int = 0) -> str:
    if kg_h <= 1e-12:
        return ""
    return f"{_fmt_dashboard_num(_kg_h_to_t_y(kg_h, hours_y), ndigits)} t/y"


def _infer_pfd_pyro_topology(steps_df: pd.DataFrame) -> str:
    """``alloy_slag`` | ``alloy_only`` | ``discard`` — from actual step list."""
    if steps_df is None or steps_df.empty or "Step" not in steps_df.columns:
        return "alloy_slag"
    step_names = steps_df["Step"].astype(str).tolist()
    has_alloy_hydro = any("Alloy Digestion" in s for s in step_names)
    has_slag_hydro = any("Slag Digestion" in s for s in step_names)
    if has_alloy_hydro and has_slag_hydro:
        return "alloy_slag"
    if has_alloy_hydro:
        return "alloy_only"
    if any(str(s).startswith("Hydro") for s in step_names):
        return "alloy_only"
    return "discard"


def _pyro_branch_masses_kg_h(steps_df: pd.DataFrame) -> dict[str, float]:
    """Alloy/slag stream rates inferred from pyro and hydro-pyro digestion steps."""
    out = {"alloy": 0.0, "slag": 0.0, "slag_discarded": 0.0}
    if steps_df is None or steps_df.empty or "Step" not in steps_df.columns:
        return out
    for _, row in steps_df.iterrows():
        step = str(row.get("Step", ""))
        in_v = _safe_float(row.get("In kg/h"), 0.0)
        fwd_v = _safe_float(row.get("Out forward kg/h", row.get("Out kg/h")), 0.0)
        if "Granulation Alloy" in step:
            out["alloy"] = max(out["alloy"], fwd_v if fwd_v > 0 else in_v)
        if "Granulation Slag" in step:
            out["slag"] = max(out["slag"], fwd_v if fwd_v > 0 else in_v)
        if "Alloy Digestion" in step and in_v > 0:
            out["alloy"] = max(out["alloy"], in_v)
        if "Slag Digestion" in step and in_v > 0:
            out["slag"] = max(out["slag"], in_v)
        if "Smelting" in step:
            slag_col = _safe_float(row.get("Slag (kg/h)"), 0.0)
            if slag_col > 0 and out["slag"] <= 1e-12:
                out["slag_discarded"] = slag_col
    if out["slag_discarded"] > 0 and out["slag"] > 0:
        out["slag_discarded"] = max(0.0, out["slag_discarded"] - out["slag"])
    return out


def _pfd_massflow_item_key(name: str) -> str:
    label = str(name or "").strip()
    mapped = MASSFLOW_SEPARATED_TO_OUTPUT_ITEM.get(label, label)
    return resolve_output_item_key(mapped)


def _pfd_item_revenue_lookup(econ: dict) -> dict[str, float]:
    """Signed annual revenue ($/y) per economics output item (all steps combined)."""
    out_df = _build_output_value_emission_df(econ)
    if out_df.empty:
        return {}
    work = out_df.copy()
    work["item"] = work["item"].astype(str).map(lambda x: resolve_output_item_key(x))
    work["revenue_per_y"] = pd.to_numeric(work["revenue_per_y"], errors="coerce").fillna(0.0)
    grouped = work.groupby("item", as_index=False)["revenue_per_y"].sum()
    return {str(r["item"]): float(r["revenue_per_y"]) for _, r in grouped.iterrows()}


def _pfd_is_forward_handoff_output(name: str, stage: str) -> bool:
    """Main-chain streams must not appear as side outputs."""
    nl = str(name).lower()
    if stage == "Mechanical treatment" and "black mass" in nl:
        return True
    if stage == "Front-end processing" and nl in {"modules", "module"}:
        return True
    return False


def _pfd_is_component_material_item(
    item_key: str,
    name: str,
    ctx: dict | None,
    route_key: str,
) -> bool:
    from recovery_config import find_product_rule, get_product_rules, resolve_recovery_route

    recovery_route = resolve_recovery_route(ctx)
    rules = get_product_rules(recovery_route)
    for candidate in (item_key, name):
        rule = find_product_rule(str(candidate), rules)
        if rule is not None:
            return rule.category == "component"
    structural_items = {
        "Aluminium scrap",
        "Copper scrap",
        "Steel scrap",
        "Iron scrap",
        "Electronic scrap",
        "Aluminium hydroxide",
        "Iron hydroxide",
    }
    return str(item_key) in structural_items


def _pfd_is_wastewater(name: str) -> bool:
    nl = str(name).lower()
    return "wastewater" in nl or "waste water" in nl


def _aggregate_pfd_streams_for_model(
    mf_long: pd.DataFrame,
    ctx: dict | None,
    route_key: str,
    econ: dict | None,
    hours_y: float,
) -> dict[str, object]:
    """
    Classify separated outputs for the PFD:
    - Hydro revenue > 0 → Final Products mass
    - Hydro revenue < 0 → Residues; wastewater always separate
    - Mech: item-level revenue + structural component mapping
    """
    side_by_stage: dict[str, dict[str, float]] = {}
    hydro_products_kg_h = 0.0

    sep = _separated_outputs_df(mf_long, ctx, route_key)
    by_item_revenue: dict[str, float] = {}
    if isinstance(econ, dict) and econ:
        by_item_revenue = _pfd_item_revenue_lookup(econ)

    if not sep.empty:
        for _, row in sep.iterrows():
            stage = str(row.get("Route section", ""))
            name = str(row.get("Name", ""))
            kg_h = _safe_float(row.get("kg/h"), 0.0)
            category = str(row.get("Category", ""))
            if kg_h <= 1e-12:
                continue

            if _pfd_is_forward_handoff_output(name, stage):
                continue

            if _pfd_is_wastewater(name):
                if stage == "Hydrometallurgy":
                    side_by_stage.setdefault(stage, {})
                    side_by_stage[stage]["Wastewater"] = side_by_stage[stage].get("Wastewater", 0.0) + kg_h
                continue

            item_key = _pfd_massflow_item_key(name)
            item_rev_y = float(by_item_revenue.get(item_key, 0.0)) if by_item_revenue else 0.0

            if stage == "Front-end processing":
                side_by_stage.setdefault(stage, {})
                if item_rev_y < 0 or str(category).lower() == "residue":
                    side_by_stage[stage]["Residues"] = side_by_stage[stage].get("Residues", 0.0) + kg_h
                elif feed_has_pack_level(ctx):
                    side_by_stage[stage]["Pack materials"] = (
                        side_by_stage[stage].get("Pack materials", 0.0) + kg_h
                    )
                continue

            if stage == "Pyro treatment":
                bucket = _pfd_side_stream_bucket(name, stage, category=category)
                if bucket:
                    side_by_stage.setdefault(stage, {})
                    side_by_stage[stage][bucket] = side_by_stage[stage].get(bucket, 0.0) + kg_h
                continue

            if stage == "Mechanical treatment":
                side_by_stage.setdefault(stage, {})
                if item_rev_y > 0 and _pfd_is_component_material_item(item_key, name, ctx, route_key):
                    side_by_stage[stage]["Component materials"] = (
                        side_by_stage[stage].get("Component materials", 0.0) + kg_h
                    )
                elif item_rev_y < 0:
                    side_by_stage[stage]["Residues"] = side_by_stage[stage].get("Residues", 0.0) + kg_h
                elif _pfd_is_component_material_item(item_key, name, ctx, route_key):
                    side_by_stage[stage]["Component materials"] = (
                        side_by_stage[stage].get("Component materials", 0.0) + kg_h
                    )
                elif str(category).lower() == "residue":
                    side_by_stage[stage]["Residues"] = side_by_stage[stage].get("Residues", 0.0) + kg_h
                continue

            if stage == "Hydrometallurgy":
                stage_rev_y = item_rev_y
                if stage_rev_y > 0:
                    hydro_products_kg_h += kg_h
                elif stage_rev_y < 0:
                    side_by_stage.setdefault(stage, {})
                    side_by_stage[stage]["Residues"] = side_by_stage[stage].get("Residues", 0.0) + kg_h
                continue

            bucket = _pfd_side_stream_bucket(name, stage, category=category)
            if bucket is None:
                continue
            side_by_stage.setdefault(stage, {})
            side_by_stage[stage][bucket] = side_by_stage[stage].get(bucket, 0.0) + kg_h

    if hydro_products_kg_h <= 1e-12 and isinstance(econ, dict) and econ and hours_y > 0:
        out_df = _build_output_value_emission_df(econ)
        if not out_df.empty:
            work = out_df.copy()
            work["stage"] = work["step_name"].astype(str).map(lambda s: _process_stage(s, route_key))
            work = work[work["stage"].astype(str) == "Hydrometallurgy"]
            work["revenue_per_y"] = pd.to_numeric(work["revenue_per_y"], errors="coerce").fillna(0.0)
            work["Quantity"] = pd.to_numeric(work["Quantity"], errors="coerce").fillna(0.0)
            pos = work[(work["revenue_per_y"] > 0.0) & (work["Quantity"] > 0.0)]
            hydro_products_kg_h = float(pos["Quantity"].sum()) / float(hours_y)

    return {"side_by_stage": side_by_stage, "hydro_products_kg_h": hydro_products_kg_h}


def _pfd_side_stream_bucket(name: str, route_section: str, *, category: str = "") -> str | None:
    """Map separated outputs to at most one high-level PFD side-stream label."""
    stage = str(route_section)
    nl = str(name).lower()
    cat = str(category or "").strip().lower()
    if stage == "Front-end processing":
        return "Pack materials"
    if stage == "Mechanical treatment":
        if cat == "residue":
            return "Residues"
        if cat == "product":
            return "Component materials"
        if any(
            token in f" {nl} "
            for token in (
                "copper",
                " cu",
                "cu ",
                "aluminium",
                " al",
                "al ",
                "steel",
                "iron",
                " fe",
                "fe ",
                "electronics",
                "electronic",
                "foil",
            )
        ):
            return "Component materials"
        if "wastewater" in nl or "waste water" in nl:
            return None
        if "residue" in nl or "plastic" in nl or "sand" in nl:
            return "Residues"
        return None
    if stage == "Pyro treatment":
        if "fly" in nl and "ash" in nl:
            return "Fly ash"
        if ("off" in nl and "gas" in nl) or "clean gas" in nl or "flue" in nl:
            return "Off-gas"
        if "ash" in nl or "slag" in nl:
            return "Fly ash"
        if "gas" in nl:
            return "Off-gas"
        return None
    if stage == "Hydrometallurgy":
        if "wastewater" in nl or "waste water" in nl:
            return "Wastewater"
        return "Residues"
    return None


def _stage_energy_mw(steps_df: pd.DataFrame, route_key: str, stage: str) -> float:
    steps = _safe_df(steps_df).copy()
    if steps.empty or "Step" not in steps.columns:
        return 0.0
    steps["_stage"] = steps["Step"].astype(str).map(lambda s: _process_stage(s, route_key))
    sub = steps[steps["_stage"].astype(str) == stage]
    if sub.empty or "E_kWh_h" not in sub.columns:
        return 0.0
    return _kwh_h_to_mw(float(pd.to_numeric(sub["E_kWh_h"], errors="coerce").fillna(0.0).sum()))


def _stage_residues_kg_h(mf_long: pd.DataFrame, ctx: dict | None, route_key: str, stage: str) -> float:
    sep = _separated_outputs_df(mf_long, ctx, route_key)
    if sep.empty:
        return 0.0
    sub = sep[sep["Route section"].astype(str) == stage]
    if sub.empty:
        return 0.0
    return float(pd.to_numeric(sub["kg/h"], errors="coerce").fillna(0.0).sum())


def _pfd_t_y_label(kg_h: float, hours_y: float) -> str:
    return f"{_fmt_dashboard_num(_kg_h_to_t_y(kg_h, hours_y), 1)} t/y"


def _pfd_stage_hover_html(
    stage_label: str,
    *,
    n_steps: int,
    input_kg_h: float,
    reagents_kg_h: float,
    main_output_kg_h: float,
    residues_kg_h: float,
    energy_mw: float,
    hours_y: float,
) -> str:
    return (
        f"<b>{html_module.escape(stage_label)}</b><br>"
        f"Steps: {n_steps}<br>"
        f"Input: {_pfd_t_y_label(input_kg_h, hours_y)}<br>"
        f"Reagents added: {_pfd_t_y_label(reagents_kg_h, hours_y)}<br>"
        f"Main output: {_pfd_t_y_label(main_output_kg_h, hours_y)}<br>"
        f"Residues: {_pfd_t_y_label(residues_kg_h, hours_y)}<br>"
        f"Energy demand: {_fmt_dashboard_num(energy_mw, 1)} MW"
    )


def _pfd_front_end_handoff_label(ctx: dict | None) -> str:
    """PFD label for the stream after front-end processing."""
    levels: set[str] = set()
    for row in (ctx or {}).get("feed_details") or []:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level", "")).strip().lower()
        share = _safe_float(row.get("share"), 0.0)
        if level in {"pack", "module", "cell"} and share > 1e-12:
            levels.add(level)
    has_pack = "pack" in levels
    has_module = "module" in levels
    has_cell = "cell" in levels
    if has_cell and not has_pack and not has_module:
        return "Cells"
    if has_pack and has_cell:
        return "Modules/Cells"
    return "Modules"


def _pfd_main_chain(route_key: str, *, pyro_topology: str = "alloy_slag") -> list[dict[str, object]]:
    route = str(route_key or "").strip().lower()
    if route == "pyro":
        if pyro_topology == "alloy_only":
            handoff_label = "Alloy"
            handoff_id = "alloy"
        else:
            handoff_label = "Alloy + Slag"
            handoff_id = "handoff"
        return [
            {"id": "feed", "label": "Feed Input", "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["feed"]},
            {"id": "fe", "label": "Front-End Processing", "stage_key": "Front-end processing", "kind": "process", "color": _MASS_DASHBOARD_PFD_COLORS["front_end"]},
            {"id": "modules", "label": "Modules", "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["stream"]},
            {"id": "middle", "label": "Pyrometallurgy", "stage_key": "Pyro treatment", "kind": "process", "color": _MASS_DASHBOARD_PFD_COLORS["middle"]},
            {"id": handoff_id, "label": handoff_label.replace("<br>", " "), "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["stream"]},
            {"id": "hydro", "label": "Hydrometallurgy", "stage_key": "Hydrometallurgy", "kind": "process", "color": _MASS_DASHBOARD_PFD_COLORS["hydro"]},
            {"id": "products", "label": "Final Products", "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["products"], "border": _MASS_DASHBOARD_PFD_COLORS["products_border"]},
        ]
    return [
        {"id": "feed", "label": "Feed Input", "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["feed"]},
        {"id": "fe", "label": "Front-End Processing", "stage_key": "Front-end processing", "kind": "process", "color": _MASS_DASHBOARD_PFD_COLORS["front_end"]},
        {"id": "modules", "label": "Modules", "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["stream"]},
        {"id": "middle", "label": "Mechanical Treatment", "stage_key": "Mechanical treatment", "kind": "process", "color": _MASS_DASHBOARD_PFD_COLORS["middle"]},
        {"id": "handoff", "label": "Black mass", "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["stream"]},
        {"id": "hydro", "label": "Hydrometallurgy", "stage_key": "Hydrometallurgy", "kind": "process", "color": _MASS_DASHBOARD_PFD_COLORS["hydro"]},
        {"id": "products", "label": "Final Products", "stage_key": None, "kind": "stream", "color": _MASS_DASHBOARD_PFD_COLORS["products"], "border": _MASS_DASHBOARD_PFD_COLORS["products_border"]},
    ]


def _pfd_side_stream_specs(
    route_key: str,
    *,
    pyro_topology: str = "alloy_slag",
) -> list[dict[str, object]]:
    """Non-hydro side streams; hydro residues/wastewater are rendered as a fork."""
    route = str(route_key or "").strip().lower()
    specs: list[dict[str, object]] = [
        {"stage": "Front-end processing", "label": "Pack materials", "anchor": "node", "node": "fe"},
    ]
    if route == "pyro":
        handoff_anchor = "alloy" if pyro_topology == "alloy_only" else "handoff"
        specs.extend(
            [
                {"stage": "Pyro treatment", "label": "Off-gas", "anchor": "mid", "from": "middle", "to": handoff_anchor},
                {"stage": "Pyro treatment", "label": "Fly ash", "anchor": "mid", "from": "middle", "to": handoff_anchor},
            ]
        )
        if pyro_topology == "alloy_only":
            specs.append(
                {"stage": "Pyro treatment", "label": "Slag", "anchor": "node", "node": "middle", "use_slag_discarded": True}
            )
    return specs


def _build_mass_dashboard_pfd_model(
    stage_card_df: pd.DataFrame,
    steps_df: pd.DataFrame,
    mf_long: pd.DataFrame,
    ctx: dict,
    route_key: str,
    hours_y: float,
    feed_input_kg_h: float,
    saleable_kg_h: float,
    econ: dict | None = None,
) -> dict | None:
    route = str(route_key or "").strip().lower()
    pyro_topology = _infer_pfd_pyro_topology(steps_df) if route == "pyro" else "mech"
    pyro_masses = _pyro_branch_masses_kg_h(steps_df) if route == "pyro" else {}

    chain = _pfd_main_chain(route_key, pyro_topology=pyro_topology if route == "pyro" else "alloy_slag")
    if not chain:
        return None

    stage_lookup: dict[str, pd.Series] = {}
    if stage_card_df is not None and not stage_card_df.empty and "Stage" in stage_card_df.columns:
        for _, row in stage_card_df.iterrows():
            stage_lookup[str(row["Stage"])] = row

    stream_data = _aggregate_pfd_streams_for_model(mf_long, ctx, route_key, econ, hours_y)
    side_by_stage = dict(stream_data.get("side_by_stage", {}))
    hydro_products_kg_h = _safe_float(stream_data.get("hydro_products_kg_h"), 0.0)
    products_kg_h = hydro_products_kg_h if hydro_products_kg_h > 1e-12 else saleable_kg_h

    nodes: list[dict[str, object]] = []

    for spec in chain:
        kind = str(spec["kind"])
        stage_key = spec.get("stage_key")
        stage_row = stage_lookup.get(str(stage_key)) if stage_key else None
        node_id = str(spec["id"])
        base_title = str(spec["label"])
        display_label = base_title
        flow_kg_h = 0.0

        if node_id == "feed":
            flow_kg_h = feed_input_kg_h
            display_label = _pfd_stream_inline("Feed Input", flow_kg_h, hours_y)
            hover = f"<b>Feed Input</b><br>Input: {_pfd_t_y_label(feed_input_kg_h, hours_y)}"
        elif node_id == "products":
            flow_kg_h = products_kg_h
            display_label = _pfd_stream_inline("Final Products", flow_kg_h, hours_y)
            hover = f"<b>Final Products</b><br>Revenue-bearing hydro products: {_pfd_t_y_label(flow_kg_h, hours_y)}"
        elif node_id == "modules":
            fe_row = stage_lookup.get("Front-end processing")
            flow_kg_h = _safe_float(fe_row.get("Forwarded Stream"), 0.0) if fe_row is not None else 0.0
            stream_name = _pfd_front_end_handoff_label(ctx)
            display_label = _pfd_stream_inline(stream_name, flow_kg_h, hours_y)
            hover = f"<b>{html_module.escape(stream_name)}</b><br>Stream: {_pfd_t_y_label(flow_kg_h, hours_y)}"
        elif node_id in ("handoff", "alloy"):
            mid_row = stage_lookup.get("Pyro treatment" if route == "pyro" else "Mechanical treatment")
            if route == "pyro" and pyro_topology == "alloy_only":
                flow_kg_h = float(pyro_masses.get("alloy", 0.0)) or (
                    _safe_float(mid_row.get("Forwarded Stream"), 0.0) if mid_row is not None else 0.0
                )
                stream_name = "Alloy"
            elif route == "pyro":
                alloy_v = float(pyro_masses.get("alloy", 0.0))
                slag_v = float(pyro_masses.get("slag", 0.0))
                flow_kg_h = alloy_v + slag_v if (alloy_v + slag_v) > 0 else (
                    _safe_float(mid_row.get("Forwarded Stream"), 0.0) if mid_row is not None else 0.0
                )
                stream_name = "Alloy + Slag"
            else:
                flow_kg_h = _safe_float(mid_row.get("Forwarded Stream"), 0.0) if mid_row is not None else 0.0
                stream_name = "Black mass"
            display_label = _pfd_stream_inline(stream_name, flow_kg_h, hours_y)
            hover = f"<b>{html_module.escape(stream_name)}</b><br>Stream: {_pfd_t_y_label(flow_kg_h, hours_y)}"
        elif stage_row is not None:
            input_kg_h = _safe_float(stage_row.get("Input"), 0.0)
            reagents_kg_h = _safe_float(stage_row.get("Reagents"), 0.0)
            main_output_kg_h = _safe_float(stage_row.get("Forwarded Stream"), 0.0)
            residues_kg_h = _stage_residues_kg_h(mf_long, ctx, route_key, str(stage_key))
            energy_mw = _stage_energy_mw(steps_df, route_key, str(stage_key))
            flow_kg_h = main_output_kg_h if main_output_kg_h > 0 else input_kg_h
            display_label = base_title
            hover = _pfd_stage_hover_html(
                display_label,
                n_steps=int(stage_row.get("Steps", 0) or 0),
                input_kg_h=input_kg_h,
                reagents_kg_h=reagents_kg_h,
                main_output_kg_h=main_output_kg_h,
                residues_kg_h=residues_kg_h,
                energy_mw=energy_mw,
                hours_y=hours_y,
            )
        else:
            flow_kg_h = 0.0
            display_label = base_title
            hover = display_label

        nodes.append(
            {
                "id": node_id,
                "display_label": display_label,
                "color": str(spec["color"]),
                "border": str(spec.get("border", _MASS_DASHBOARD_PFD_COLORS["stream_border"])),
                "hover": hover,
                "flow_kg_h": flow_kg_h,
                "stage_key": stage_key,
                "kind": kind,
                "reagents_kg_h": _safe_float(stage_row.get("Reagents"), 0.0) if stage_row is not None else 0.0,
            }
        )

    main_flows: list[dict[str, object]] = []
    for i in range(len(nodes) - 1):
        src = nodes[i]
        tgt = nodes[i + 1]
        mass = _safe_float(tgt.get("flow_kg_h"), _safe_float(src.get("flow_kg_h"), 0.0))
        if mass <= 0 and src["id"] == "feed":
            mass = feed_input_kg_h
        main_flows.append(
            {
                "mass_kg_h": mass,
                "label": _pfd_mass_text(mass, hours_y),
                "title": f"Main flow: {_pfd_t_y_label(mass, hours_y)}",
            }
        )

    side_streams_by_node: dict[str, list[dict[str, str]]] = {}

    def _record_side(node_id: str, bucket_label: str, mass: float) -> None:
        if mass <= 1e-12:
            return
        side_streams_by_node.setdefault(node_id, []).append(
            {
                "title": bucket_label,
                "label": _pfd_stream_inline(bucket_label, mass, hours_y),
                "mass_label": _pfd_mass_text(mass, hours_y),
            }
        )

    slag_discarded = float(pyro_masses.get("slag_discarded", 0.0)) if route == "pyro" else 0.0
    if slag_discarded > 1e-12:
        _record_side("middle", "Slag", slag_discarded)

    fe_side = side_by_stage.get("Front-end processing", {})
    if feed_has_pack_level(ctx):
        _record_side("fe", "Pack materials", float(fe_side.get("Pack materials", 0.0)))
    _record_side("fe", "Residues", float(fe_side.get("Residues", 0.0)))

    if route == "pyro":
        for bucket_label, mass in side_by_stage.get("Pyro treatment", {}).items():
            _record_side("middle", str(bucket_label), float(mass))
    else:
        mech_side = side_by_stage.get("Mechanical treatment", {})
        _record_side("middle", "Residues", float(mech_side.get("Residues", 0.0)))
        _record_side("middle", "Component materials", float(mech_side.get("Component materials", 0.0)))

    hydro_side = side_by_stage.get("Hydrometallurgy", {})
    _record_side("hydro", "Residues", float(hydro_side.get("Residues", 0.0)))
    _record_side("hydro", "Wastewater", float(hydro_side.get("Wastewater", 0.0)))

    return {
        "nodes": nodes,
        "main_flows": main_flows,
        "side_streams_by_node": side_streams_by_node,
        "hours_y": hours_y,
    }


def _render_mass_dashboard_process_flow(
    steps_df: pd.DataFrame,
    ctx: dict,
    econ: dict | None,
    route_key: str,
    scen_name: str,
    saleable_kg_h: float,
    *,
    show_heading: bool = True,
    heading: str = "Process Flow",
    compact: bool = False,
) -> bool:
    hours_y = _hours_per_year(ctx)
    mf_long = _massflow_long_safe(steps_df, scen_name)
    stage_card_df = _stage_cards_df(steps_df, mf_long, ctx, route=route_key)
    feed_input_kg_h = _safe_float(steps_df.iloc[0].get("In kg/h"), 0.0) if not steps_df.empty else 0.0
    pfd_model = _build_mass_dashboard_pfd_model(
        stage_card_df,
        steps_df,
        mf_long,
        ctx,
        route_key,
        hours_y,
        feed_input_kg_h,
        saleable_kg_h,
        econ=econ,
    )
    pfd_html = _render_mass_dashboard_pfd_html(pfd_model, compact=compact)
    if show_heading:
        st.markdown(f"**{heading}**")
    if pfd_html:
        st.markdown(pfd_html, unsafe_allow_html=True)
        return True
    st.info("No process flow data available for this scenario.")
    return False


def _render_overview_process_flow_panel(
    steps_df: pd.DataFrame,
    ctx: dict,
    econ: dict | None,
    route_key: str,
    scen_name: str,
    saleable_kg_h: float,
) -> None:
    st.markdown('<div class="libra-overview-process-flow-marker"></div>', unsafe_allow_html=True)
    with st.container(border=True, height=OVERVIEW_BOTTOM_TILE_HEIGHT_PX):
        _overview_section_heading("Process Flow")
        _render_mass_dashboard_process_flow(
            steps_df,
            ctx,
            econ,
            route_key,
            scen_name,
            saleable_kg_h,
            show_heading=False,
            compact=True,
        )


def _render_overview_recovery_summary_panel(
    items: list[tuple[str, float | None, str]],
) -> None:
    st.markdown('<div class="libra-overview-recovery-marker"></div>', unsafe_allow_html=True)
    with st.container(border=True, height=OVERVIEW_BOTTOM_TILE_HEIGHT_PX):
        _render_overview_recovery_summary_column(items)


def _make_step_node_flow(
    steps_df: pd.DataFrame,
    link_df: pd.DataFrame,
    route: str | None = None,
    mf_long: pd.DataFrame | None = None,
    selected_step: str | None = None,
    *,
    color_scheme: str = "default",
):
    if go is None:
        return None
    steps = _safe_df(steps_df).copy()
    links = _safe_df(link_df).copy()
    if steps.empty or "Step" not in steps.columns:
        return None

    steps = steps[steps["Step"].astype(str).str.strip() != ""].copy()
    if steps.empty:
        return None

    steps["_step_number"] = steps.index.astype(int) + 1
    steps = steps.reset_index(drop=True)
    steps["_label"] = steps["Step"].astype(str).map(_compact_step_label)
    step_names = steps["Step"].astype(str).tolist()
    route_key = str(route or "").strip().lower()

    # Resolve Hydro-Pyro branch per step index (sequence-aware keys).
    step_branch_keys = _pyro_hydro_branch_keys(step_names) if route_key == "pyro" else [None] * len(step_names)

    split_pyro_hydro = route_key == "pyro" and (
        "slag" in step_branch_keys or "alloy" in step_branch_keys
    )
    stages: list[str] = []
    for name, branch in zip(step_names, step_branch_keys):
        if route_key == "pyro" and branch == "slag":
            stages.append("Hydrometallurgy (Slag)")
        elif route_key == "pyro" and branch == "alloy":
            stages.append("Hydrometallurgy (Alloy)")
        else:
            stages.append(_process_flow_plot_stage(name, route, split_pyro_hydro=split_pyro_hydro))
    steps["Stage"] = stages
    steps["_reagents_added"] = 0.0
    steps["_output_separated"] = 0.0
    mf = _safe_df(mf_long).copy()
    if not mf.empty and "_step_context" in mf.columns:
        for col in ["Materials added (kg/h)", "Output separated (kg/h)"]:
            if col not in mf.columns:
                mf[col] = 0.0
            mf[col] = pd.to_numeric(mf[col], errors="coerce").fillna(0.0)
        step_sums = mf.groupby("_step_context", as_index=True)[["Materials added (kg/h)", "Output separated (kg/h)"]].sum()
        steps["_reagents_added"] = steps["Step"].map(step_sums["Materials added (kg/h)"]).fillna(0.0)
        steps["_output_separated"] = steps["Step"].map(step_sums["Output separated (kg/h)"]).fillna(0.0)
    elif "Side streams (kg/h)" in steps.columns:
        steps["_output_separated"] = pd.to_numeric(steps["Side streams (kg/h)"], errors="coerce").fillna(0.0)
    stage_order = _process_flow_plot_stage_order(route, split_pyro_hydro=split_pyro_hydro)
    stages = (
        steps[["Stage"]]
        .drop_duplicates()
        .assign(_sort=lambda d: d["Stage"].map(stage_order).fillna(99))
        .sort_values("_sort")["Stage"]
        .tolist()
    )
    stage_to_y = {stage: (len(stages) - i - 1) for i, stage in enumerate(stages)}
    x = process_flow_plot_x_positions(step_names, step_branch_keys, route)
    y = [stage_to_y[s] for s in steps["Stage"]]
    x_span = max(x) if x else 0.0

    fig = go.Figure()

    label_to_idx = {str(label): i for i, label in enumerate(steps["_label"])}
    drawn_edges: set[tuple[int, int]] = set()
    if not links.empty and {"source", "target", "kind"}.issubset(links.columns):
        forward_links = links[links["kind"].astype(str) == "forward"]
        for _, row in forward_links.iterrows():
            src = label_to_idx.get(str(row.get("source", "")))
            tgt = label_to_idx.get(str(row.get("target", "")))
            if src is None or tgt is None or src == tgt:
                continue
            drawn_edges.add((src, tgt))

    for i in range(len(steps) - 1):
        src_branch = step_branch_keys[i]
        tgt_branch = step_branch_keys[i + 1]
        if src_branch is not None and tgt_branch is not None and src_branch != tgt_branch:
            continue
        drawn_edges.add((i, i + 1))

    _append_step_flow_bridge_edges(step_names, route, drawn_edges)
    drawn_edges -= _step_flow_suppressed_edges(step_names, route)

    for src, tgt in sorted(drawn_edges):
        fig.add_trace(
            go.Scatter(
                x=[x[src], x[tgt]],
                y=[y[src], y[tgt]],
                mode="lines",
                line={"color": "rgba(80, 80, 80, 0.35)", "width": 2},
                hoverinfo="skip",
                showlegend=False,
            )
        )

    _stage_color_maps = {
        "default": {
            "Front-end processing": "rgba(69, 117, 180, 0.9)",
            "Mechanical treatment": "rgba(90, 90, 90, 0.85)",
            "Pyro treatment": "rgba(230, 126, 34, 0.88)",
            "Hydrometallurgy": "rgba(49, 163, 84, 0.88)",
            "Hydrometallurgy (Slag)": "rgba(49, 163, 84, 0.88)",
            "Hydrometallurgy (Alloy)": "rgba(49, 163, 84, 0.88)",
            "Other processing": "rgba(128, 90, 213, 0.78)",
        },
        "libra": {
            "Front-end processing": "#6b7280",
            "Mechanical treatment": "#C9A004",
            "Pyro treatment": "#C9A004",
            "Hydrometallurgy": "#003B75",
            "Hydrometallurgy (Slag)": "#003B75",
            "Hydrometallurgy (Alloy)": "#003B75",
            "Other processing": "#6697dd",
        },
        "pfd": {
            "Front-end processing": _MASS_DASHBOARD_PFD_COLORS["front_end"],
            "Mechanical treatment": _MASS_DASHBOARD_PFD_COLORS["middle"],
            "Pyro treatment": _MASS_DASHBOARD_PFD_COLORS["middle"],
            "Hydrometallurgy": _MASS_DASHBOARD_PFD_COLORS["hydro"],
            "Hydrometallurgy (Slag)": _MASS_DASHBOARD_PFD_COLORS["hydro"],
            "Hydrometallurgy (Alloy)": _MASS_DASHBOARD_PFD_COLORS["hydro"],
            "Other processing": "#6697dd",
        },
    }
    stage_colors = _stage_color_maps.get(color_scheme, _stage_color_maps["default"])
    colors = [stage_colors.get(stage, "#6b7280") for stage in steps["Stage"]]
    customdata = [
        [
            int(row["_step_number"]),
            str(row["Step"]),
            _safe_float(row.get("In kg/h"), 0.0),
            _safe_float(row.get("_reagents_added"), 0.0),
            _safe_float(row.get("E_kWh_h"), 0.0),
            _safe_float(row.get("Out forward kg/h", row.get("Out kg/h")), 0.0),
            _safe_float(row.get("_output_separated"), 0.0),
        ]
        for _, row in steps.iterrows()
    ]
    selected_indices = [
        idx
        for idx, step_name in enumerate(steps["Step"].astype(str).tolist())
        if str(step_name) == str(selected_step or "")
    ]

    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="markers",
            marker={
                "size": 15,
                "color": colors,
                "line": {"color": "rgba(40,40,40,0.35)", "width": 1},
            },
            customdata=customdata,
            hovertemplate=(
                "<b>Step %{customdata[0]}: %{customdata[1]}</b><br>"
                "Input: %{customdata[2]:,.3f} kg/h<br>"
                "Reagents: %{customdata[3]:,.3f} kg/h<br>"
                "Energy: %{customdata[4]:,.3f} kWh/h<br>"
                "Forwarded: %{customdata[5]:,.3f} kg/h<br>"
                "Separated: %{customdata[6]:,.3f} kg/h"
                "<extra></extra>"
            ),
            showlegend=False,
        )
    )

    if selected_indices:
        fig.add_trace(
            go.Scatter(
                x=[x[i] for i in selected_indices],
                y=[y[i] for i in selected_indices],
                mode="markers",
                marker={
                    "size": 23,
                    "color": "rgba(0,0,0,0)",
                    "line": {"color": "rgba(20,20,20,0.9)", "width": 2.5},
                },
                hoverinfo="skip",
                showlegend=False,
            )
        )

    for sep_y in [y_pos + 0.5 for y_pos in range(max(0, len(stages) - 1))]:
        fig.add_hline(y=sep_y, line_width=1, line_dash="dot", line_color="rgba(160,160,160,0.45)")

    fig.update_layout(
        height=max(300, 105 * max(1, len(stages))),
        width=max(820, 42 * max(1, int(x_span) + 1)),
        margin={"l": 145, "r": 35, "t": 20, "b": 20},
        xaxis={
            "showticklabels": False,
            "showgrid": False,
            "zeroline": False,
            "title": "",
            "range": [-0.8, max(0.8, x_span + 0.8)],
        },
        yaxis={
            "tickmode": "array",
            "tickvals": list(stage_to_y.values()),
            "ticktext": list(stage_to_y.keys()),
            "showgrid": False,
            "zeroline": False,
            "title": "",
            "range": [-0.6, max(0.6, len(stages) - 0.4)],
        },
        plot_bgcolor="rgba(0,0,0,0)",
        clickmode="event+select",
    )
    return fig


def _make_process_sankey(node_df: pd.DataFrame, link_df: pd.DataFrame):
    if go is None or node_df.empty or link_df.empty:
        return None
    labels = node_df["node"].astype(str).tolist()
    node_idx = {label: i for i, label in enumerate(labels)}
    sources = [node_idx[str(x)] for x in link_df["source"]]
    targets = [node_idx[str(x)] for x in link_df["target"]]
    values = [float(x) for x in link_df["value"]]
    custom = [
        f"{row['stream']}<br>{row['step']}<br>{row['kind']}"
        for _, row in link_df.iterrows()
    ]
    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node={
                    "pad": 16,
                    "thickness": 16,
                    "line": {"color": "rgba(60,60,60,0.35)", "width": 0.5},
                    "label": labels,
                    "color": [_sankey_color_for_node(x) for x in labels],
                },
                link={
                    "source": sources,
                    "target": targets,
                    "value": values,
                    "customdata": custom,
                    "color": [_sankey_color_for_link(k) for k in link_df["kind"]],
                    "hovertemplate": "%{customdata}<br><b>%{value:.4f} kg/h</b><extra></extra>",
                },
            )
        ]
    )
    fig.update_layout(
        height=680,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        font={"size": 11},
    )
    return fig


# -------------------------------------------------------------------
# Session state
# -------------------------------------------------------------------
if "last_run" not in st.session_state:
    st.session_state["last_run"] = None
if "run_history" not in st.session_state:
    st.session_state["run_history"] = []
if "auto_scenario_seq" not in st.session_state:
    st.session_state["auto_scenario_seq"] = 0
if "feed_rows" not in st.session_state:
    st.session_state["feed_rows"] = [
        {"cell_id": "NMC811_Prismatic", "level": "pack", "share": 0.5},
        {"cell_id": "LFP_Pouch", "level": "cell", "share": 0.5},
    ]


def _clear_results_callback() -> None:
    st.session_state["last_run"] = None
    st.session_state["run_history"] = []
    st.session_state["auto_scenario_seq"] = 0
    st.session_state["_just_cleared"] = True


_inject_sidebar_width(results_visible=st.session_state.get("last_run") is not None)


# -------------------------------------------------------------------
# Sidebar inputs
# -------------------------------------------------------------------
st.sidebar.header("Scenario Inputs")
_inject_sidebar_section_styles()

name = st.sidebar.text_input(
    "Scenario Name",
    value="",
    placeholder="Optional",
    key="sidebar_scenario_name",
    help="Leave empty to auto-name runs as Scenario 1, Scenario 2, and so on.",
)
cost_region_xlsx = COST_REGION_XLSX

region_options = _region_options_from_workbook(str(cost_region_xlsx))
region_select_options = list(region_options)
if "Custom" not in region_select_options:
    region_select_options.append("Custom")

_sidebar_section("Basic Setup")

route = st.sidebar.radio(
    "Recycling Route",
    options=["mech", "pyro"],
    format_func=lambda x: ROUTE_SIDEBAR_LABELS.get(x, x),
    index=0,
    key="sidebar_route",
)

annual_feed_t_y = st.sidebar.number_input(
    "Annual Recycling Feed [t/y]",
    min_value=0.001,
    value=float(st.session_state.get("sidebar_annual_feed_t_y", 10000.0) or 10000.0),
    step=100.0,
    key="sidebar_annual_feed_t_y",
    help=(
        "Total annual pack, module, and/or cell feed processed by LIBRA. "
        "Results are reported per kg feed processed."
    ),
)
mass_feed_kg_y = float(annual_feed_t_y) * 1000.0

_infrastructure_mode_options = ["integrated", "hub_spoke"]
_ensure_select_option("sidebar_infrastructure_mode", _infrastructure_mode_options, default_index=0)
infrastructure_mode = st.sidebar.radio(
    "Infrastructure Configuration",
    options=_infrastructure_mode_options,
    format_func=lambda x: "Integrated Site" if x == "integrated" else "Hub-Spoke System",
    index=_infrastructure_mode_options.index(
        st.session_state.get("sidebar_infrastructure_mode", _infrastructure_mode_options[0])
    ),
    key="sidebar_infrastructure_mode",
    help=(
        "Define the recycling infrastructure and plant locations. "
        "Select a single-site or hub-spoke recycling infrastructure."
    ),
)

spoke_location = "Germany"
hub_location = "Germany"
pretreatment_capacity_t_y = float(st.session_state.get("sidebar_pretreatment_capacity_t_y", annual_feed_t_y) or annual_feed_t_y)
hydro_capacity_t_bm_y = float(st.session_state.get("sidebar_hydro_capacity_t_bm_y", 5000.0) or 5000.0)
custom_transport_distance_km = 0.0
spoke_latitude = 0.0
spoke_longitude = 0.0
hub_latitude = 0.0
hub_longitude = 0.0
site_latitude = 0.0
site_longitude = 0.0
transport_cost_per_t_km = float(DEFAULT_TRANSPORT_COST_PER_T_KM)
transport_gwp_per_t_km = float(DEFAULT_TRANSPORT_GWP_PER_T_KM)

_ensure_select_option("sidebar_region", region_select_options, default_index=0)
_region_help = (
    "Select the region used for electricity prices, material prices, "
    "labor costs, and environmental impact data."
)

if infrastructure_mode == "hub_spoke":
    _ensure_select_option("sidebar_spoke_location", list(LOCATION_OPTIONS), default_index=0)
    spoke_location = st.sidebar.selectbox(
        "Front-End / Pretreatment Location",
        list(LOCATION_OPTIONS),
        key="sidebar_spoke_location",
    )
    _ensure_select_option("sidebar_hub_location", list(LOCATION_OPTIONS), default_index=0)
    hub_location = st.sidebar.selectbox(
        "Hydrometallurgical Refining Location",
        list(LOCATION_OPTIONS),
        key="sidebar_hub_location",
    )

    _preview_region = st.session_state.get("sidebar_region", region_select_options[0])
    if (spoke_location == "Custom" or hub_location == "Custom") and "Custom" in region_select_options:
        _preview_region = "Custom"
    _preview_scen = {
        "infrastructure_mode": "hub_spoke",
        "spoke_location": spoke_location,
        "hub_location": hub_location,
        "region": _preview_region,
    }
    _spoke_reg_preview = resolve_spoke_region(_preview_scen)
    _hub_reg_preview = resolve_hub_region(_preview_scen)
    st.sidebar.caption(
        f"Regional setup:\n"
        f"Pretreatment = **{region_display_label(_spoke_reg_preview)}**\n"
        f"Hydrometallurgy = **{region_display_label(_hub_reg_preview)}**"
    )
    st.sidebar.caption(
        "Economic and environmental parameters are applied separately for both regions."
    )

    with st.sidebar.expander("Advanced infrastructure", expanded=False):
        pretreatment_capacity_t_y = st.number_input(
            "Pretreatment Spoke Capacity [t feed/y]",
            min_value=1.0,
            value=float(st.session_state.get("sidebar_pretreatment_capacity_t_y", annual_feed_t_y) or annual_feed_t_y),
            step=100.0,
            key="sidebar_pretreatment_capacity_t_y",
            help=(
                "Design capacity of a single pretreatment spoke. LIBRA automatically calculates the required "
                "number of spokes and their utilization based on the annual recycling feed."
            ),
        )
        hydro_capacity_t_bm_y = st.number_input(
            "Hydrometallurgical Hub Capacity [t hydro feed/y]",
            min_value=1.0,
            value=float(st.session_state.get("sidebar_hydro_capacity_t_bm_y", 5000.0) or 5000.0),
            step=100.0,
            key="sidebar_hydro_capacity_t_bm_y",
            help=(
                "Design capacity of a single hydrometallurgical refining hub. LIBRA automatically calculates "
                "the required number of hubs and their utilization based on the transported hydro feed."
            ),
        )
        transport_cost_per_t_km = st.number_input(
            "Transport costs [$/t·km]",
            min_value=0.0,
            value=float(
                st.session_state.get("sidebar_transport_cost_per_t_km", DEFAULT_TRANSPORT_COST_PER_T_KM)
                or DEFAULT_TRANSPORT_COST_PER_T_KM
            ),
            step=0.01,
            format="%.4f",
            key="sidebar_transport_cost_per_t_km",
        )
        transport_gwp_per_t_km = st.number_input(
            "Transport emission factor [kg CO2-eq/t·km]",
            min_value=0.0,
            value=float(
                st.session_state.get("sidebar_transport_gwp_per_t_km", DEFAULT_TRANSPORT_GWP_PER_T_KM)
                or DEFAULT_TRANSPORT_GWP_PER_T_KM
            ),
            step=0.001,
            format="%.4f",
            key="sidebar_transport_gwp_per_t_km",
        )

    if spoke_location == "Custom" or hub_location == "Custom":
        st.session_state["sidebar_region"] = "Custom"
        region = "Custom"
        with st.sidebar.expander("Custom location", expanded=False):
            st.caption(
                "Enter the location of your site. Enter the latitude and longitude of the site location."
            )
            if spoke_location == "Custom":
                _spoke_fb = REGION_COORDINATES.get(
                    resolve_spoke_region(
                        {
                            "infrastructure_mode": "hub_spoke",
                            "spoke_location": spoke_location,
                            "hub_location": hub_location,
                            "region": region,
                        }
                    ),
                    LOCATION_COORDINATES["Germany"],
                )
                _s_lat_col, _s_lon_col = st.columns(2)
                with _s_lat_col:
                    spoke_latitude = st.number_input(
                        "Pretreatment latitude [°]",
                        min_value=-90.0,
                        max_value=90.0,
                        value=float(st.session_state.get("sidebar_spoke_latitude", _spoke_fb[0]) or _spoke_fb[0]),
                        step=0.1,
                        format="%.4f",
                        key="sidebar_spoke_latitude",
                    )
                with _s_lon_col:
                    spoke_longitude = st.number_input(
                        "Pretreatment longitude [°]",
                        min_value=-180.0,
                        max_value=180.0,
                        value=float(st.session_state.get("sidebar_spoke_longitude", _spoke_fb[1]) or _spoke_fb[1]),
                        step=0.1,
                        format="%.4f",
                        key="sidebar_spoke_longitude",
                    )
            if hub_location == "Custom":
                _hub_fb = REGION_COORDINATES.get(
                    resolve_hub_region(
                        {
                            "infrastructure_mode": "hub_spoke",
                            "spoke_location": spoke_location,
                            "hub_location": hub_location,
                            "region": region,
                        }
                    ),
                    LOCATION_COORDINATES["Germany"],
                )
                _h_lat_col, _h_lon_col = st.columns(2)
                with _h_lat_col:
                    hub_latitude = st.number_input(
                        "Hydro latitude [°]",
                        min_value=-90.0,
                        max_value=90.0,
                        value=float(st.session_state.get("sidebar_hub_latitude", _hub_fb[0]) or _hub_fb[0]),
                        step=0.1,
                        format="%.4f",
                        key="sidebar_hub_latitude",
                    )
                with _h_lon_col:
                    hub_longitude = st.number_input(
                        "Hydro longitude [°]",
                        min_value=-180.0,
                        max_value=180.0,
                        value=float(st.session_state.get("sidebar_hub_longitude", _hub_fb[1]) or _hub_fb[1]),
                        step=0.1,
                        format="%.4f",
                        key="sidebar_hub_longitude",
                    )
    else:
        region = resolve_spoke_region(
            {
                "infrastructure_mode": "hub_spoke",
                "spoke_location": spoke_location,
                "hub_location": hub_location,
                "region": st.session_state.get("sidebar_region", region_select_options[0]),
            }
        )
else:
    region = st.sidebar.selectbox(
        "Region",
        region_select_options,
        index=region_select_options.index(st.session_state.get("sidebar_region", region_select_options[0])),
        format_func=region_display_label,
        help=_region_help,
        key="sidebar_region",
    )
    with st.sidebar.expander("Advanced infrastructure", expanded=False):
        pretreatment_capacity_t_y = st.number_input(
            "Integrated Recycling Site Capacity [t feed/y]",
            min_value=1.0,
            value=float(st.session_state.get("sidebar_pretreatment_capacity_t_y", annual_feed_t_y) or annual_feed_t_y),
            step=100.0,
            key="sidebar_pretreatment_capacity_t_y",
            help=(
                "Design capacity of the integrated recycling site. LIBRA calculates "
                "capacity utilization based on the annual recycling feed."
            ),
        )
    if region == "Custom":
        with st.sidebar.expander("Custom location", expanded=False):
            st.caption(
                "Enter the location of your site. Enter the latitude and longitude of the site location."
            )
            _site_fb = REGION_COORDINATES.get(
                str(st.session_state.get("custom_region_base", region_select_options[0])),
                LOCATION_COORDINATES["Germany"],
            )
            _site_lat_col, _site_lon_col = st.columns(2)
            with _site_lat_col:
                site_latitude = st.number_input(
                    "Site latitude [°]",
                    min_value=-90.0,
                    max_value=90.0,
                    value=float(st.session_state.get("sidebar_site_latitude", _site_fb[0]) or _site_fb[0]),
                    step=0.1,
                    format="%.4f",
                    key="sidebar_site_latitude",
                )
            with _site_lon_col:
                site_longitude = st.number_input(
                    "Site longitude [°]",
                    min_value=-180.0,
                    max_value=180.0,
                    value=float(st.session_state.get("sidebar_site_longitude", _site_fb[1]) or _site_fb[1]),
                    step=0.1,
                    format="%.4f",
                    key="sidebar_site_longitude",
                )

if region == "Custom":
    with st.sidebar.expander("Custom Regional Parameters", expanded=False):
        base_region_options = [r for r in region_options if r != "Custom"] or ["DE"]
        _ensure_select_option("custom_region_base", base_region_options, default_index=0)
        base_region = st.selectbox(
            "Reference Region",
            base_region_options,
            format_func=region_display_label,
            key="custom_region_base",
            help="Reference region whose cost and environmental values are used as the starting point.",
        )
        try:
            cost_raw = pd.read_excel(str(cost_region_xlsx), sheet_name="Cost Parameter")
            gwp_raw = pd.read_excel(str(cost_region_xlsx), sheet_name="GWP Parameter")
            st.markdown("**Cost Parameters**")
            cost_custom_df = _custom_region_editor_df(cost_raw, base_region, "custom_cost_parameter_editor")
            st.markdown("**Environmental Parameters**")
            gwp_custom_df = _custom_region_editor_df(gwp_raw, base_region, "custom_gwp_parameter_editor")
            cost_region_xlsx = _write_custom_region_workbook(
                str(cost_region_xlsx),
                base_region,
                cost_custom_df,
                gwp_custom_df,
            )
        except Exception as exc:
            st.error(f"Custom region could not be prepared: {type(exc).__name__}: {exc}")

pack_energy_kWh = 100.0
if "_pending_run_id" not in st.session_state:
    st.session_state["_pending_run_id"] = str(uuid.uuid4())
run_id = str(st.session_state["_pending_run_id"])

cell_tech_xlsx = CELL_TECH_XLSX

_sidebar_section("Feedstock Configuration")

_last_scen = st.session_state.get("last_scen", {}) or {}
_default_feedstock_type = _resolve_feedstock_type(_last_scen, None)
_ft_idx = (
    list(FEEDSTOCK_TYPE_OPTIONS).index(_default_feedstock_type)
    if _default_feedstock_type in FEEDSTOCK_TYPE_OPTIONS
    else 2
)
feedstock_type = st.sidebar.selectbox(
    "Feedstock Type",
    options=list(FEEDSTOCK_TYPE_OPTIONS),
    index=_ft_idx,
    format_func=lambda k: FEEDSTOCK_TYPE_LABELS.get(k, k),
    help="Choose which battery chemistries can be selected in the feedstock table.",
    key="sidebar_feedstock_type",
)

with st.sidebar.expander("Custom Battery Configuration", expanded=False):
    st.caption(
        "Use an existing battery type as a template. Changes only affect your custom configuration."
    )
    try:
        db_for_custom = CellDB(str(cell_tech_xlsx))
        ct_custom = db_for_custom.cell_types.copy()
        ct_custom["cell_id"] = ct_custom["cell_id"].astype(str).str.strip()
        ct_custom["chemistry"] = ct_custom["chemistry"].astype(str).str.strip()
        ct_custom["format"] = ct_custom["format"].astype(str).str.strip()
        ct_custom["chem_family"] = ct_custom["chemistry"].map(_chem_family_for_label)

        chem_family_options = [x for x in ["NMC", "LFP"] if x in set(ct_custom["chem_family"])]
        if not chem_family_options:
            chem_family_options = sorted(ct_custom["chem_family"].dropna().unique().tolist())
        _ensure_select_option("custom_chem_family", chem_family_options, default_index=0)
        selected_chem_family = st.selectbox(
            "Custom chemistry",
            chem_family_options,
            key="custom_chem_family",
            help=(
                "Select whether the custom battery should be treated as an NMC or LFP "
                "battery throughout the recycling process."
            ),
        )

        geometry_df = ct_custom[ct_custom["chem_family"] == selected_chem_family]
        geometry_options = sorted(geometry_df["format"].dropna().unique().tolist())
        _ensure_select_option("custom_geometry", geometry_options, default_index=0)

        def _geometry_label(fmt: str) -> str:
            labels = {
                "pouch": "Pouch",
                "prismatic": "Prismatic",
                "cylindrical21700": "Cylindrical 21700",
                "cylindrical4680": "Cylindrical 4680",
            }
            return labels.get(str(fmt), str(fmt))

        selected_format = st.selectbox(
            "Custom geometry",
            geometry_options,
            format_func=_geometry_label,
            key="custom_geometry",
            help="Choose the physical battery format (pouch, prismatic, or cylindrical).",
        )

        available_custom_bases = sorted(
            ct_custom[
                (ct_custom["chem_family"] == selected_chem_family)
                & (ct_custom["format"] == selected_format)
            ]["cell_id"].dropna().unique().tolist()
        )
        _ensure_select_option("custom_cell_base_id", available_custom_bases, default_index=0)
        base_cell_id = st.selectbox(
            "Copy default values from",
            available_custom_bases,
            format_func=_format_cell_display_label,
            key="custom_cell_base_id",
            help="Start from an existing battery type and adjust its properties.",
        )
        base_ct = db_for_custom.cell_types[
            db_for_custom.cell_types["cell_id"].astype(str).str.strip() == str(base_cell_id).strip()
        ].iloc[0]
        base_format = str(base_ct.get("format", "")).strip()
        chem_family = str(selected_chem_family)

        geometry_id = {
            "pouch": "Pouch",
            "prismatic": "Prismatic",
            "cylindrical21700": "Cylindrical_21700",
            "cylindrical4680": "Cylindrical_4680",
        }.get(str(selected_format), str(selected_format).strip().replace(" ", "_"))
        custom_cell_id = f"{chem_family}_{geometry_id}_Custom"
        st.caption(f"Custom battery: {_format_cell_display_label(custom_cell_id)}")
        custom_format = f"{base_format}_custom"
        cell_weight_kg = st.number_input(
            "Custom cell weight (kg)",
            min_value=0.0,
            value=_safe_float(base_ct.get("cell_weight_kg"), 0.0),
            step=0.001,
            format="%.6f",
            key="custom_cell_weight_kg",
        )
        cell_energy_Wh = st.number_input(
            "Custom cell energy (Wh)",
            min_value=0.0,
            value=_safe_float(base_ct.get("cell_energy_Wh"), 0.0),
            step=1.0,
            format="%.3f",
            key="custom_cell_energy_Wh",
        )
        base_fr = db_for_custom.format_rules[
            db_for_custom.format_rules["format"].astype(str).str.strip() == base_format
        ]
        base_cells_per_module = int(_safe_float(base_fr.iloc[0].get("cells_per_module"), 1.0)) if not base_fr.empty else 1
        cells_per_module = st.number_input(
            "Custom cells per module",
            min_value=1,
            value=max(1, int(base_cells_per_module)),
            step=1,
            key="custom_cells_per_module",
        )
        st.caption("Custom cell materials")
        cell_base_rows = db_for_custom.cell_mats[
            db_for_custom.cell_mats["cell_id"].astype(str).str.strip() == str(base_cell_id).strip()
        ][["component", "material", "kg_per_cell"]]
        cell_edit = _material_editor(cell_base_rows, "kg_per_cell", "custom_cell_materials_editor")

        st.caption("Custom module materials")
        module_base_rows = db_for_custom.mod_mats[
            (db_for_custom.mod_mats["format"].astype(str).str.strip() == base_format)
            & (db_for_custom.mod_mats["chemistry"].astype(str).str.strip().str.upper() == chem_family)
        ][["material", "kg_per_module"]]
        module_edit = _material_editor(module_base_rows, "kg_per_module", "custom_module_materials_editor")

        st.caption("Custom pack materials")
        pack_base_rows = db_for_custom.pack_mats[
            (db_for_custom.pack_mats["format"].astype(str).str.strip() == base_format)
            & (db_for_custom.pack_mats["chemistry"].astype(str).str.strip().str.upper() == chem_family)
        ][["material", "kg_per_100kWhpack"]]
        pack_edit = _material_editor(pack_base_rows, "kg_per_100kWhpack", "custom_pack_materials_editor")

        cell_tech_xlsx = _write_custom_cell_tech_workbook(
            str(cell_tech_xlsx),
            base_cell_id=str(base_cell_id),
            custom_cell_id=custom_cell_id,
            custom_chemistry=chem_family,
            custom_format=custom_format,
            cell_weight_kg=float(cell_weight_kg),
            cell_energy_Wh=float(cell_energy_Wh),
                cells_per_module=int(cells_per_module),
                cell_edit=cell_edit,
            module_edit=module_edit,
            pack_edit=pack_edit,
        )
        st.caption(
            "This custom battery will appear in the feedstock list for pack, module, and cell input levels."
        )
    except Exception as exc:
        st.error(f"Custom battery technology could not be prepared: {type(exc).__name__}: {exc}")

_cell_meta, CELL_OPTIONS, _cell_meta_error = _load_cell_meta(str(cell_tech_xlsx))
if _cell_meta_error:
    st.sidebar.error(f"Recycling Feedstock Data workbook could not be loaded: {_cell_meta_error}")

FILTERED_CELL_OPTIONS = _filter_cell_options_for_feedstock_type(CELL_OPTIONS, _cell_meta, feedstock_type)
if FILTERED_CELL_OPTIONS:
    st.session_state["feed_rows"] = _sanitize_feed_rows_for_feedstock_type(
        st.session_state["feed_rows"],
        FILTERED_CELL_OPTIONS,
    )
else:
    st.sidebar.warning("No cell technologies match the selected feedstock type.")

c1, c2 = st.sidebar.columns(2)
if c1.button("Add Feedstock"):
    default_cid = FILTERED_CELL_OPTIONS[0] if FILTERED_CELL_OPTIONS else ""
    st.session_state["feed_rows"].append({"cell_id": default_cid, "level": "pack", "share": 0.0})
if c2.button("Remove Feedstock"):
    if st.session_state["feed_rows"]:
        st.session_state["feed_rows"].pop()

levels = ["pack", "module", "cell"]
edited_rows = []
for i, r in enumerate(st.session_state["feed_rows"]):
    st.sidebar.markdown(
        f'<p class="libra-feedstock-row-label">Feedstock stream {i + 1}</p>',
        unsafe_allow_html=True,
    )
    current_id = str(r.get("cell_id", "")).strip()
    row_cell_options = FILTERED_CELL_OPTIONS or CELL_OPTIONS

    if row_cell_options:
        chem_options = _chemistry_options_for_cells(row_cell_options, _cell_meta)
        cur_chem = (
            _chemistry_for_cell_id(current_id, _cell_meta)
            if current_id in row_cell_options
            else chem_options[0]
        )
        chem_key = f"feed_chemistry_{i}"
        chem_default_idx = chem_options.index(cur_chem) if cur_chem in chem_options else 0
        _ensure_select_option(chem_key, chem_options, default_index=chem_default_idx)
        selected_chem = st.sidebar.selectbox(
            "Battery Chemistry",
            chem_options,
            key=chem_key,
        )
        fmt_options = _format_options_for_chemistry(row_cell_options, _cell_meta, selected_chem)
        cur_fmt = (
            _format_for_cell_id(current_id, _cell_meta)
            if current_id in row_cell_options
            else (fmt_options[0] if fmt_options else "")
        )
        fmt_key = f"feed_format_{i}"
        fmt_default_idx = fmt_options.index(cur_fmt) if cur_fmt in fmt_options else 0
        _ensure_select_option(fmt_key, fmt_options, default_index=fmt_default_idx)
        selected_fmt = st.sidebar.selectbox(
            "Cell Format",
            fmt_options,
            format_func=_format_display_label,
            key=fmt_key,
        )
        cell_id = _resolve_cell_id_from_parts(row_cell_options, _cell_meta, selected_chem, selected_fmt)
    else:
        cell_id = st.sidebar.text_input(
            "Battery Chemistry",
            value=current_id,
            key=f"feed_cell_id_{i}",
        )

    level_key = f"feed_level_{i}"
    level_idx = (
        levels.index(str(r.get("level", "pack")).lower())
        if str(r.get("level", "")).lower() in levels
        else 0
    )
    _ensure_select_option(level_key, levels, default_index=level_idx)
    level = st.sidebar.selectbox(
        "Input Level",
        levels,
        key=level_key,
    )
    share_key = f"feed_share_{i}"
    if share_key not in st.session_state:
        st.session_state[share_key] = _safe_float(r.get("share"), 0.0)
    share = st.sidebar.number_input(
        "Feedstock Share",
        min_value=0.0,
        step=0.05,
        format="%.3f",
        key=share_key,
    )
    edited_rows.append({"cell_id": cell_id, "level": level, "share": share})

st.session_state["feed_rows"] = edited_rows
feed_norm = _normalize_shares(edited_rows)

if not feed_norm:
    st.sidebar.warning("Recycling Feedstock is empty/invalid.")

_sidebar_section("Product & Recovery Configuration")

_nmc_opts = [c for c in ["111", "532", "622", "811"] if c in NMC_PRECURSOR_CODES]
if not _nmc_opts:
    _nmc_opts = ["811", "622", "532", "111"]
_default_nmc = resolve_nmc_code(_last_scen, default="811")
_default_nmc_idx = _nmc_opts.index(_default_nmc) if _default_nmc in _nmc_opts else 0
_show_nmc_precursor = route == "mech" and feedstock_type in ("nmc", "mix")
_show_nmc_hydro_scope = route == "mech" and feedstock_type == "nmc"
_show_lfp_hydro_scope = route == "mech" and feedstock_type == "lfp"
_show_mix_hydro_scope = route == "mech" and feedstock_type == "mix"
_show_pyro_hydro_scope = route == "pyro"
_has_recovery_scope = any(
    (_show_nmc_hydro_scope, _show_lfp_hydro_scope, _show_mix_hydro_scope, _show_pyro_hydro_scope)
)

if _show_nmc_precursor:
    nmc_code = st.sidebar.selectbox(
        "Target NMC pCAM Grade",
        options=_nmc_opts,
        index=_default_nmc_idx,
        format_func=lambda code: f"NMC{code}",
        help=(
            "Target cathode precursor composition (Ni:Co:Mn ratio). "
            "Examples: NMC111, NMC532, NMC622, NMC811."
        ),
        key="sidebar_nmc_code",
    )
    _default_tb = resolve_nmc_target_basis(_last_scen)
    _tb_idx = list(NMC_TARGET_BASIS_OPTIONS).index(_default_tb) if _default_tb in NMC_TARGET_BASIS_OPTIONS else 0
    nmc_target_basis = st.sidebar.selectbox(
        "NMC pCAM Production Constraint",
        options=list(NMC_TARGET_BASIS_OPTIONS),
        index=_tb_idx,
        format_func=lambda k: _NMC_PRODUCTION_CONSTRAINT_LABELS.get(k, k),
        help=(
            "Defines how LIBRA balances recovered nickel, cobalt, and manganese toward the "
            "target NMC pCAM grade — and which recovered metal limits how much product can be "
            "produced."
        ),
        key="sidebar_nmc_target_basis",
    )

    _anchor_is_limiting = str(nmc_target_basis).strip().lower() == "min"
    if _anchor_is_limiting:
        _prev_supply = st.session_state.get("sidebar_external_metal_supply")
        if _prev_supply and _prev_supply != "none":
            st.session_state["_external_supply_before_limiting"] = _prev_supply
        st.session_state["sidebar_external_metal_supply"] = "none"
        external_metal_supply = "none"
        st.sidebar.markdown("**External Metal Supply**")
        st.sidebar.caption(_EXTERNAL_METAL_SUPPLY_CAPTIONS["none"])
        st.sidebar.caption(
            "Automatically set to **None** when *Limiting Metal Availability* is selected."
        )
    else:
        if (
            st.session_state.get("sidebar_external_metal_supply") == "none"
            and st.session_state.get("_external_supply_before_limiting") in _EXTERNAL_METAL_SUPPLY_OPTIONS
            and st.session_state["_external_supply_before_limiting"] != "none"
        ):
            st.session_state["sidebar_external_metal_supply"] = st.session_state[
                "_external_supply_before_limiting"
            ]
        if "sidebar_external_metal_supply" not in st.session_state:
            _default_supply = _external_metal_supply_from_scenario(_last_scen)
            if st.session_state.get("sidebar_nmc_makeup_policy") in NMC_MAKEUP_POLICY_OPTIONS:
                _legacy_policy = str(st.session_state["sidebar_nmc_makeup_policy"])
                if _legacy_policy == "none":
                    _default_supply = "none"
                elif _legacy_policy == "unlimited":
                    _default_supply = "flexible"
                elif _legacy_policy == "capped":
                    _default_supply = "limited"
        else:
            _default_supply = str(st.session_state.get("sidebar_external_metal_supply", "limited"))
        if _default_supply == "none":
            _default_supply = "limited"
        _supply_idx = (
            list(_EXTERNAL_METAL_SUPPLY_OPTIONS).index(_default_supply)
            if _default_supply in _EXTERNAL_METAL_SUPPLY_OPTIONS
            else 1
        )
        external_metal_supply = st.sidebar.radio(
            "External Metal Supply",
            options=list(_EXTERNAL_METAL_SUPPLY_OPTIONS),
            index=_supply_idx,
            format_func=lambda k: _EXTERNAL_METAL_SUPPLY_LABELS.get(k, k),
            help=(
                "How much externally supplied metal sulfates are allowed when balancing "
                "the target NMC composition."
            ),
            key="sidebar_external_metal_supply",
        )
        st.sidebar.caption(_EXTERNAL_METAL_SUPPLY_CAPTIONS.get(external_metal_supply, ""))

    if external_metal_supply == "none":
        nmc_makeup_policy = "none"
        nmc_max_makeup_fill_fraction = 0.0
    elif external_metal_supply == "flexible":
        nmc_makeup_policy = "unlimited"
        nmc_max_makeup_fill_fraction = 1.0
    else:
        nmc_makeup_policy = "capped"
        _cap_frac = resolve_nmc_makeup_fill_fraction(
            {**_last_scen, "nmc_makeup_policy": "capped"},
            0.25,
        )
        _cap_pct_default = int(round(float(_cap_frac) * 100))
        _cap_pct = st.sidebar.slider(
            "Maximum External Metal Supply (%)",
            min_value=0,
            max_value=100,
            value=_cap_pct_default,
            step=5,
            format="%d%%",
            help=(
                "Maximum share of externally supplied metal sulfates allowed for balancing "
                "the target NMC composition."
            ),
            key="sidebar_nmc_makeup_fill_pct",
        )
        nmc_max_makeup_fill_fraction = float(_cap_pct) / 100.0
else:
    nmc_code = _default_nmc
    nmc_target_basis = "min"
    nmc_makeup_policy = "capped"
    nmc_max_makeup_fill_fraction = 0.25

if not _show_nmc_precursor and not _has_recovery_scope:
    st.sidebar.caption("No product or recovery options for the current route and feedstock type.")

if _has_recovery_scope:
    with st.sidebar.expander("Advanced Recovery Settings", expanded=False):
        if _show_nmc_hydro_scope:
            _default_scope = resolve_nmc_hydro_recovery_scope(_last_scen)
            _scope_idx = (
                list(NMC_HYDRO_RECOVERY_SCOPE_OPTIONS).index(_default_scope)
                if _default_scope in NMC_HYDRO_RECOVERY_SCOPE_OPTIONS
                else 0
            )
            nmc_hydro_recovery_scope = st.radio(
                "Metal recovery scope",
                options=list(NMC_HYDRO_RECOVERY_SCOPE_OPTIONS),
                index=_scope_idx,
                format_func=lambda k: NMC_HYDRO_RECOVERY_SCOPE_LABELS.get(k, k),
                help=_METAL_RECOVERY_SCOPE_HELP,
                key="sidebar_nmc_hydro_recovery_scope",
            )
            if nmc_hydro_recovery_scope == "nmc":
                st.caption("Recover NMC only. Lithium remains unrecovered.")
            else:
                st.caption("Recover NMC and lithium products.")
        else:
            nmc_hydro_recovery_scope = "all"

        if _show_lfp_hydro_scope:
            _default_lfp_scope = resolve_lfp_hydro_recovery_scope(_last_scen)
            _lfp_scope_idx = (
                list(LFP_HYDRO_RECOVERY_SCOPE_OPTIONS).index(_default_lfp_scope)
                if _default_lfp_scope in LFP_HYDRO_RECOVERY_SCOPE_OPTIONS
                else 0
            )
            lfp_hydro_recovery_scope = st.radio(
                "Metal recovery scope",
                options=list(LFP_HYDRO_RECOVERY_SCOPE_OPTIONS),
                index=_lfp_scope_idx,
                format_func=lambda k: LFP_HYDRO_RECOVERY_SCOPE_LABELS.get(k, k),
                help=_METAL_RECOVERY_SCOPE_HELP,
                key="sidebar_lfp_hydro_recovery_scope",
            )
            st.caption(_LFP_RECOVERY_SCOPE_CAPTIONS.get(lfp_hydro_recovery_scope, ""))
        else:
            lfp_hydro_recovery_scope = "all"

        if _show_mix_hydro_scope:
            _default_mix_scope = resolve_mix_hydro_recovery_scope(_last_scen)
            _mix_scope_idx = (
                list(MIX_HYDRO_RECOVERY_SCOPE_OPTIONS).index(_default_mix_scope)
                if _default_mix_scope in MIX_HYDRO_RECOVERY_SCOPE_OPTIONS
                else 0
            )
            mix_hydro_recovery_scope = st.radio(
                "Metal recovery scope",
                options=list(MIX_HYDRO_RECOVERY_SCOPE_OPTIONS),
                index=_mix_scope_idx,
                format_func=lambda k: MIX_HYDRO_RECOVERY_SCOPE_LABELS.get(k, k),
                help=_METAL_RECOVERY_SCOPE_HELP,
                key="sidebar_mix_hydro_recovery_scope",
            )
            st.caption(_MIX_RECOVERY_SCOPE_CAPTIONS.get(mix_hydro_recovery_scope, ""))
        else:
            mix_hydro_recovery_scope = "all"

        if _show_pyro_hydro_scope:
            _default_pyro_scope = resolve_pyro_hydro_recovery_scope(_last_scen)
            _pyro_scope_idx = (
                list(PYRO_HYDRO_RECOVERY_SCOPE_OPTIONS).index(_default_pyro_scope)
                if _default_pyro_scope in PYRO_HYDRO_RECOVERY_SCOPE_OPTIONS
                else 0
            )
            pyro_hydro_recovery_scope = st.radio(
                "Metal recovery scope",
                options=list(PYRO_HYDRO_RECOVERY_SCOPE_OPTIONS),
                index=_pyro_scope_idx,
                format_func=lambda k: PYRO_HYDRO_RECOVERY_SCOPE_LABELS.get(k, k),
                help=_METAL_RECOVERY_SCOPE_HELP,
                key="sidebar_pyro_hydro_recovery_scope",
            )
            st.caption(_PYRO_RECOVERY_SCOPE_CAPTIONS.get(pyro_hydro_recovery_scope, ""))
        else:
            pyro_hydro_recovery_scope = "all"
else:
    nmc_hydro_recovery_scope = "all"
    lfp_hydro_recovery_scope = "all"
    mix_hydro_recovery_scope = "all"
    pyro_hydro_recovery_scope = "all"

_sidebar_section("Advanced Options")

eff_xlsx = EFF_XLSX
with st.sidebar.expander("Custom process efficiencies", expanded=False):
    enable_custom_eff = st.checkbox(
        "Enable Custom process efficiencies",
        value=False,
        key="enable_custom_eff",
        help=(
            "Adjust process efficiencies for your selected recycling route and feedstock. "
            "Only efficiency values can be edited."
        ),
    )
    if enable_custom_eff:
        try:
            eff_base_df = _process_eff_editor_df(EFF_XLSX)
            if "custom_eff_values" not in st.session_state or not isinstance(st.session_state["custom_eff_values"], dict):
                st.session_state["custom_eff_values"] = {
                    int(r["__row_id"]): _safe_float(r.get("Value"), 0.0)
                    for _, r in eff_base_df.iterrows()
                }
            stored_eff_values = dict(st.session_state["custom_eff_values"])
            eff_base_df["Value"] = eff_base_df.apply(
                lambda r: stored_eff_values.get(int(r["__row_id"]), _safe_float(r.get("Value"), 0.0)),
                axis=1,
            )
            _eff_route_key = f"{route}:{feedstock_type}"
            eff_view_df = filter_eff_df_for_scenario(
                eff_base_df,
                route,
                feedstock_type,
                pyro_hydro_recovery_scope=pyro_hydro_recovery_scope,
                feed=st.session_state.get("feed_rows"),
            )
            st.caption(
                f"Showing efficiencies for **{process_eff_scenario_filter_label(route, feedstock_type)}**."
            )
            if eff_view_df.empty:
                st.warning("No efficiency rows match the current route and feedstock type.")

            st.caption("Edit only the `Value` column.")
            eff_edit_df = st.data_editor(
                eff_view_df,
                key=f"custom_eff_editor_{_eff_route_key}",
                hide_index=True,
                width="stretch",
                disabled=[c for c in eff_view_df.columns if c != "Value"],
                column_config={
                    "__row_id": None,
                    "Area": st.column_config.TextColumn("Area"),
                    "Value": st.column_config.NumberColumn("Value", format="%.8g"),
                },
            )
            eff_full_df = eff_base_df.copy()
            if "__row_id" in eff_edit_df.columns:
                values_by_id = {
                    int(r["__row_id"]): _safe_float(r.get("Value"), 0.0)
                    for _, r in eff_edit_df.iterrows()
                    if pd.notna(r.get("__row_id"))
                }
                stored_eff_values.update(values_by_id)
                st.session_state["custom_eff_values"] = stored_eff_values
                eff_full_df["Value"] = eff_full_df.apply(
                    lambda r: stored_eff_values.get(int(r["__row_id"]), _safe_float(r.get("Value"), 0.0)),
                    axis=1,
                )
            eff_xlsx = _write_custom_eff_workbook(eff_full_df, EFF_XLSX)
            st.caption("Only `Value` is editable; the full process-efficiency table is kept for the run.")
        except Exception as exc:
            st.error(f"Custom process efficiencies could not be prepared: {type(exc).__name__}: {exc}")

with st.sidebar.expander("Custom machine database", expanded=False):
    enable_custom_machines = st.checkbox(
        "Enable Custom machine database",
        value=False,
        key="enable_custom_machines",
        help=(
            "Adjust machine investment costs, capacities, scaling, and operating factors. "
            "Changes apply to the model run only."
        ),
    )
    if enable_custom_machines:
        try:
            machine_raw_df = _machine_editor_raw_df(str(cost_region_xlsx))
            machine_view_df = _machine_editor_view_df(machine_raw_df)
            if "custom_machine_baseline" not in st.session_state or not isinstance(
                st.session_state["custom_machine_baseline"], dict
            ):
                st.session_state["custom_machine_baseline"] = _machine_baseline_lookup(COST_REGION_XLSX)
            if "custom_machine_values" not in st.session_state or not isinstance(
                st.session_state["custom_machine_values"], dict
            ):
                st.session_state["custom_machine_values"] = {
                    str(r["name"]).strip(): {
                        col: _safe_float(r.get(col), 0.0)
                        for col in _MACHINE_EDITOR_EDITABLE
                        if col in machine_view_df.columns
                    }
                    for _, r in machine_view_df.iterrows()
                    if str(r.get("name", "")).strip()
                }
            machine_baseline = dict(st.session_state["custom_machine_baseline"])
            stored_machine_values = dict(st.session_state["custom_machine_values"])
            machine_view_df = _apply_stored_machine_values(machine_view_df, stored_machine_values)
            st.caption("Edit machine parameters for all machines in the database.")
            machine_edit_df = st.data_editor(
                machine_view_df,
                key="custom_machine_editor",
                hide_index=True,
                width="stretch",
                disabled=["name", "capacity_unit"],
                column_config=_machine_editor_column_config(),
            )
            for _, r in machine_edit_df.iterrows():
                name = str(r.get("name", "")).strip()
                if not name:
                    continue
                stored_machine_values[name] = {
                    col: _safe_float(r.get(col), 0.0)
                    for col in _MACHINE_EDITOR_EDITABLE
                    if col in machine_edit_df.columns
                }
            st.session_state["custom_machine_values"] = stored_machine_values
            machine_full_view = _apply_stored_machine_values(
                _machine_editor_view_df(machine_raw_df),
                stored_machine_values,
            )
            cost_region_xlsx = _write_custom_machines_workbook(
                machine_full_view,
                str(cost_region_xlsx),
                baseline=machine_baseline,
            )
            st.caption(
                "Machine name and capacity unit are fixed; all other shown columns are editable. "
                "If you change Investment costs, the reference date is set to 2026 automatically "
                "(no further price indexation)."
            )
        except Exception as exc:
            st.error(f"Custom machine database could not be prepared: {type(exc).__name__}: {exc}")

st.sidebar.divider()
ac.render_privacy_sidebar()

if ac.is_enabled():
    st.sidebar.checkbox(
        "I agree to anonymous usage statistics as described above.",
        key="analytics_consent",
    )
    if not st.session_state.get("analytics_consent", False):
        st.sidebar.caption("Confirm usage statistics to enable **Run Model**.")

_run_disabled = ac.is_enabled() and not bool(st.session_state.get("analytics_consent", False))
run = st.sidebar.button("Run Model", type="primary", disabled=_run_disabled)
st.sidebar.button("Clear results", on_click=_clear_results_callback)

_show_cleared_banner = bool(st.session_state.pop("_just_cleared", False))


# -------------------------------------------------------------------
# Build scenario
# -------------------------------------------------------------------
scen = {
    "name": name,
    "region": region,
    "infrastructure_mode": infrastructure_mode,
    "spoke_location": spoke_location,
    "hub_location": hub_location,
    "pretreatment_capacity_t_y": float(pretreatment_capacity_t_y),
    "hydro_capacity_t_bm_y": float(hydro_capacity_t_bm_y),
    "transport_cost_per_t_km": float(transport_cost_per_t_km),
    "transport_gwp_per_t_km": float(transport_gwp_per_t_km),
    "route": route,
    "cost_region_xlsx": str(cost_region_xlsx),
    "cell_tech_xlsx": str(cell_tech_xlsx),
    "eff_xlsx": str(eff_xlsx),
    "nmc_code": str(nmc_code),
    "nmc_target_basis": str(nmc_target_basis),
    "nmc_makeup_policy": str(nmc_makeup_policy),
    "nmc_max_makeup_fill_fraction": float(nmc_max_makeup_fill_fraction),
    "nmc_hydro_recovery_scope": str(nmc_hydro_recovery_scope),
    "lfp_hydro_recovery_scope": str(lfp_hydro_recovery_scope),
    "mix_hydro_recovery_scope": str(mix_hydro_recovery_scope),
    "pyro_hydro_recovery_scope": str(pyro_hydro_recovery_scope),
    "feedstock_type": str(feedstock_type),
    "mass_feed_kg_y": float(mass_feed_kg_y),
    "annual_feed_t_y": float(annual_feed_t_y),
    "pack_energy_kWh": float(pack_energy_kWh),
    "pack_energy_by_id": {},
    "feed": feed_norm,
    "run_id": run_id,
}
if infrastructure_mode == "hub_spoke" and (spoke_location == "Custom" or hub_location == "Custom"):
    scen["custom_transport_distance_km"] = float(custom_transport_distance_km)
if infrastructure_mode == "hub_spoke" and spoke_location == "Custom":
    scen["spoke_latitude"] = float(spoke_latitude)
    scen["spoke_longitude"] = float(spoke_longitude)
if infrastructure_mode == "hub_spoke" and hub_location == "Custom":
    scen["hub_latitude"] = float(hub_latitude)
    scen["hub_longitude"] = float(hub_longitude)
if infrastructure_mode == "integrated" and region == "Custom":
    scen["site_latitude"] = float(site_latitude)
    scen["site_longitude"] = float(site_longitude)


# -------------------------------------------------------------------
# Run model
# -------------------------------------------------------------------
if run:
    try:
        scen["name"] = _resolve_scenario_name(name)
        if not scen["feed"]:
            raise ValueError("Recycling Feedstock is empty/invalid.")
        _invalid_feed = [
            str(row.get("cell_id", ""))
            for row in scen["feed"]
            if not _cell_matches_feedstock_type(str(row.get("cell_id", "")), feedstock_type, _cell_meta)
        ]
        if _invalid_feed:
            raise ValueError(
                "Feedstock entries are incompatible with the selected feedstock type: "
                + ", ".join(sorted(set(_invalid_feed)))
            )
        with st.spinner("Running model..."):
            steps_df, extras_all, ctx = run_scenario(scen)

        steps_df = _safe_df(steps_df)
        if not steps_df.empty and "run_id" not in steps_df.columns:
            steps_df.insert(0, "run_id", str(run_id))

        payload = {"scen": dict(scen), "steps_df": steps_df, "extras_all": extras_all, "ctx": ctx}
        st.session_state["last_scen"] = dict(scen)
        st.session_state["last_run"] = payload
        st.session_state["run_history"].insert(0, payload)
        st.session_state["_pending_run_id"] = str(uuid.uuid4())
        ac.log_model_run(scen)
        st.success("Run completed.")
    except Exception as e:
        ac.log_run_failed(e)
        st.error(f"Run failed: {type(e).__name__}: {e}")
        st.exception(e)

_inject_sidebar_width(results_visible=st.session_state.get("last_run") is not None)

if st.session_state["last_run"] is None:
    _render_landing_welcome_page(show_cleared=_show_cleared_banner)
    st.stop()

_render_header_with_logo()

# -------------------------------------------------------------------
# History selector
# -------------------------------------------------------------------
history = st.session_state.get("run_history", [])
pick_idx = 0
if len(history) > 1:
    labels = []
    for i, r in enumerate(history[:20]):
        s0 = r.get("scen", {}) or {}
        labels.append(f"{i+1}: {s0.get('name','scenario')}")
    _ensure_select_option("run_history_select", labels, default_index=0)
    pick_label = st.selectbox("Select run", labels, key="run_history_select")
    pick_idx = labels.index(pick_label)

selected = history[pick_idx] if history else st.session_state["last_run"]
scen_sel = selected["scen"]
steps_df = selected["steps_df"]
extras_all = selected["extras_all"]
ctx = selected["ctx"]

econ = _extract_econ(extras_all)
kpi = _kpi_block(ctx, econ)


# -------------------------------------------------------------------
# Section dashboards (bordered page tiles)
# -------------------------------------------------------------------

def _render_mass_energy_flow_dashboard(
    scen_sel: dict,
    ctx: dict,
    econ: dict,
    steps_df: pd.DataFrame,
    kpi: dict,
) -> None:
    route_key = str(scen_sel.get("route", "") or "")
    hours_y = _hours_per_year(ctx)
    annual_feed_kg = _safe_float(kpi.get("mass_y", 0.0), 0.0)
    _, link_df = _build_process_flow_data(steps_df, str(scen_sel.get("name", "scenario")))
    mf_long = _massflow_long_safe(steps_df, str(scen_sel.get("name", "scenario")))
    libra_recovery = compute_libra_recovery(ctx, steps_df, econ)
    saleable_kg_h = float(libra_recovery.saleable_product_mass_kg_h or 0.0)

    _overview_section_heading("Process Flow")
    _render_mass_dashboard_process_flow(
        steps_df,
        ctx,
        econ,
        route_key,
        str(scen_sel.get("name", "scenario")),
        saleable_kg_h,
        show_heading=False,
    )
    _render_recovery_performance(
        steps_df,
        ctx,
        econ,
        libra=libra_recovery,
        heading="Recovery Performance",
    )

    _overview_section_heading("Process Structure")
    graph_steps = steps_df.copy()
    if not graph_steps.empty and "Step" in graph_steps.columns:
        graph_steps["_Stage"] = graph_steps["Step"].astype(str).map(lambda s: _process_stage(s, route_key))
        graph_stage_order = _stage_order_for_route(route_key)
        graph_stage_options = ["All"] + (
            graph_steps[["_Stage"]]
            .drop_duplicates()
            .assign(_sort=lambda d: d["_Stage"].map(graph_stage_order).fillna(99))
            .sort_values("_sort")["_Stage"]
            .astype(str)
            .tolist()
        )
        _ensure_select_option("process_flow_graph_stage", graph_stage_options, default_index=0)
        selected_graph_stage = st.selectbox("Recycling stage", graph_stage_options, key="process_flow_graph_stage")
        if selected_graph_stage != "All":
            graph_steps = graph_steps[graph_steps["_Stage"].astype(str) == selected_graph_stage].copy()
        graph_steps = graph_steps.drop(columns=["_Stage"], errors="ignore")

    step_flow_fig = _make_step_node_flow(
        graph_steps,
        link_df,
        route=route_key,
        mf_long=mf_long,
        selected_step=st.session_state.get("process_flow_step_select"),
        color_scheme="pfd",
    )
    if step_flow_fig is not None:
        try:
            plot_event = st.plotly_chart(
                step_flow_fig,
                width="content",
                config=PLOTLY_CHART_CONFIG,
                key="process_flow_step_graph",
                on_select="rerun",
                selection_mode="points",
            )
        except TypeError:
            plot_event = None
            st.plotly_chart(step_flow_fig, width="content", config=PLOTLY_CHART_CONFIG)

        selected_graph_step = None
        points = []
        if plot_event is not None:
            selection = getattr(plot_event, "selection", None)
            if selection is not None:
                points = getattr(selection, "points", []) or (selection.get("points", []) if isinstance(selection, dict) else [])
            elif isinstance(plot_event, dict):
                points = plot_event.get("selection", {}).get("points", [])
        if points:
            point = points[0]
            customdata = point.get("customdata") if hasattr(point, "get") else getattr(point, "customdata", None)
            if isinstance(customdata, (list, tuple)) and len(customdata) >= 2:
                selected_graph_step = str(customdata[1])
            elif customdata:
                selected_graph_step = str(customdata)

        if selected_graph_step and "Step" in steps_df.columns and selected_graph_step in steps_df["Step"].astype(str).tolist():
            st.session_state["process_flow_step_select"] = selected_graph_step
            st.session_state["process_flow_drilldown_stage"] = _process_stage(selected_graph_step, route_key)
    elif go is None:
        st.warning("Plotly is not installed locally. After deployment/install, the process graph will render here.")
    else:
        st.info("No process graph could be generated for this run.")

    st.divider()
    st.subheader("Detailed step overview")
    drill_steps = steps_df.copy()
    if not drill_steps.empty and "Step" in drill_steps.columns:
        drill_steps["_Stage"] = drill_steps["Step"].astype(str).map(lambda s: _process_stage(s, route_key))
        stage_order = _stage_order_for_route(route_key)
        stage_options = ["All"] + (
            drill_steps[["_Stage"]]
            .drop_duplicates()
            .assign(_sort=lambda d: d["_Stage"].map(stage_order).fillna(99))
            .sort_values("_sort")["_Stage"]
            .astype(str)
            .tolist()
        )
        f1, f2 = st.columns([1, 2])
        _ensure_select_option("process_flow_drilldown_stage", stage_options, default_index=0)
        selected_drilldown_stage = f1.selectbox("Filter by route section", stage_options, key="process_flow_drilldown_stage")
        if selected_drilldown_stage != "All":
            drill_steps = drill_steps[drill_steps["_Stage"].astype(str) == selected_drilldown_stage]
    else:
        f1, f2 = st.columns([1, 2])
        selected_drilldown_stage = "All"
    step_options = drill_steps["Step"].astype(str).tolist() if "Step" in drill_steps.columns else []
    if step_options:
        _ensure_select_option("process_flow_step_select", step_options, default_index=0)
        selected_step_name = f2.selectbox("Select process step", step_options, key="process_flow_step_select")
        step_row = steps_df[steps_df["Step"].astype(str) == selected_step_name].iloc[0]

        step_mf_full = pd.DataFrame()
        if not mf_long.empty and "_step_context" in mf_long.columns:
            step_mf_full = mf_long[mf_long["_step_context"].astype(str) == selected_step_name].copy()
        reagents_added_v = (
            float(pd.to_numeric(step_mf_full["Materials added (kg/h)"], errors="coerce").fillna(0.0).sum())
            if not step_mf_full.empty and "Materials added (kg/h)" in step_mf_full.columns
            else 0.0
        )
        output_separated_v = (
            float(pd.to_numeric(step_mf_full["Output separated (kg/h)"], errors="coerce").fillna(0.0).sum())
            if not step_mf_full.empty and "Output separated (kg/h)" in step_mf_full.columns
            else _safe_float(step_row.get("Side streams (kg/h)"), 0.0)
        )

        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Input (t/h)", _fmt_dashboard_num(_kg_h_to_t_h(_safe_float(step_row.get("In kg/h"), 0.0))))
        d2.metric("Reagents added (t/h)", _fmt_dashboard_num(_kg_h_to_t_h(reagents_added_v)))
        d3.metric("Energy demand (MW)", _fmt_dashboard_num(_kwh_h_to_mw(_safe_float(step_row.get("E_kWh_h"), 0.0))))
        d4.metric(
            "Main output (t/h)",
            _fmt_dashboard_num(_kg_h_to_t_h(_safe_float(step_row.get("Out forward kg/h"), 0.0))),
        )
        d5.metric("Output separated (t/h)", _fmt_dashboard_num(_kg_h_to_t_h(output_separated_v)))

        if not step_mf_full.empty:
            step_mf = step_mf_full[
                [
                    c
                    for c in [
                        "Input (kg/h)",
                        "Materials added (kg/h)",
                        "Name Material added",
                        "Output forwarded (kg/h)",
                        "Name Output forwarded ",
                        "Output separated (kg/h)",
                        "Name Output Separated",
                    ]
                    if c in step_mf_full.columns
                ]
            ].copy()
            step_rate_cols = {
                "Input (kg/h)": "Input (t/h)",
                "Materials added (kg/h)": "Materials added (t/h)",
                "Output forwarded (kg/h)": "Main output (t/h)",
                "Output separated (kg/h)": "Output separated (t/h)",
            }
            for src, dst in step_rate_cols.items():
                if src in step_mf.columns:
                    step_mf[dst] = pd.to_numeric(step_mf[src], errors="coerce").fillna(0.0).map(_kg_h_to_t_h)
            step_mf = step_mf.drop(columns=[c for c in step_rate_cols if c in step_mf.columns], errors="ignore")
            if "Name Output forwarded " in step_mf.columns:
                step_mf = step_mf.rename(columns={"Name Output forwarded ": "Main output stream"})
            step_mf = _order_massflow_detail_columns(step_mf)
            st.dataframe(_clean_display_df(_round_df_numeric(step_mf, 2)), width="stretch", height=180)

    with st.expander("Detailed mass-flow table", expanded=False):
        if not mf_long.empty:
            st.dataframe(
                _clean_display_df(_format_massflow_detail_t_y(mf_long, hours_y, route_key)),
                width="stretch",
                height=420,
            )
        else:
            st.dataframe(_clean_display_df(_round_df_numeric(steps_df, 2)), width="stretch", height=420)

    st.divider()
    mat_col, energy_col, output_col = st.columns(3, gap="medium")
    tile_chart_height = MASS_ENERGY_FLOW_TILE_CHART_HEIGHT_PX
    with mat_col:
        with st.container(border=True, height=MASS_ENERGY_FLOW_TILE_HEIGHT_PX):
            _overview_tile_heading("Reagent Distribution")
            _render_mass_energy_material_input_chart(
                mf_long,
                hours_y,
                annual_feed_kg,
                route_key,
                show_heading=False,
                chart_max_height_px=tile_chart_height,
            )
    with energy_col:
        with st.container(border=True, height=MASS_ENERGY_FLOW_TILE_HEIGHT_PX):
            _overview_tile_heading("Energy Distribution")
            _render_mass_energy_energy_hierarchy(
                steps_df,
                route_key,
                min_panel_height_px=tile_chart_height,
            )
    with output_col:
        with st.container(border=True, height=MASS_ENERGY_FLOW_TILE_HEIGHT_PX):
            _overview_tile_heading("Output Distribution")
            _render_mass_dashboard_output_distribution(
                econ,
                route_key,
                annual_feed_kg,
                ctx,
                mf_long,
                hours_y,
                chart_height_px=MASS_ENERGY_FLOW_TILE_OUTPUT_CHART_HEIGHT_PX,
            )


def _render_recycling_feedstock_dashboard(ctx: dict) -> None:
    feedstock_df = _build_feedstock_variant_pivot(ctx)
    if feedstock_df.empty:
        st.info("No feedstock composition data found in context.")
    else:
        feedstock_display_df = feedstock_df.copy()
        feedstock_value_cols = [
            c for c in feedstock_display_df.columns if c not in ["Basis", "Component", "Material", "Unit"]
        ]
        for col in feedstock_value_cols:
            feedstock_display_df[col] = (
                pd.to_numeric(feedstock_display_df[col], errors="coerce").fillna(0.0) / 1000.0
            )
        if "Unit" in feedstock_display_df.columns:
            feedstock_display_df["Unit"] = "t/y"
        feedstock_display_df = feedstock_display_df.rename(columns={"Total kg/year": "Total t/y"})
        feedstock_display_df = _round_df_numeric(feedstock_display_df, 2)

        total_by_material = (
            feedstock_df.assign(_material_order=range(len(feedstock_df)))
            .groupby("Material", as_index=False)
            .agg({"Total kg/year": "sum", "_material_order": "min"})
            .sort_values("_material_order", kind="mergesort")
        )
        total_by_material = total_by_material[total_by_material["Total kg/year"] > 0]

        if not total_by_material.empty:
            _overview_section_heading("Feedstock Composition")
            feedstock_ring_df = (
                feedstock_df[feedstock_df["Total kg/year"] > 0]
                .assign(_order=range(len(feedstock_df)))
                .copy()
            )
            feedstock_ring_df["Origin"] = feedstock_ring_df["Basis"].astype(str)
            feedstock_ring_df["Origin"] = feedstock_ring_df["Origin"].replace({"Other": "Pack"})
            feedstock_ring_df["_origin_sort"] = feedstock_ring_df["Origin"].map({"Cell": 0, "Module": 1, "Pack": 2}).fillna(2)
            feedstock_ring_df["_sort"] = feedstock_ring_df["_origin_sort"] * 10000 + feedstock_ring_df["_order"]
            material_ring_df = (
                feedstock_ring_df.groupby(["Origin", "Component", "Material"], as_index=False)
                .agg({"Total kg/year": "sum", "_sort": "min"})
                .sort_values("_sort", kind="mergesort")
            )
            material_ring_df["Total t/y"] = material_ring_df["Total kg/year"] / 1000.0
            material_ring_df["Component display"] = material_ring_df.apply(
                lambda r: str(r["Component"]).strip() or str(r["Origin"]).strip() or "Pack",
                axis=1,
            )
            material_ring_df["Material segment"] = material_ring_df.apply(
                lambda r: (
                    f"{r['Material']} ({r['Component']})"
                    if str(r["Component"]).strip()
                    else f"{r['Material']} ({r['Origin']})"
                ),
                axis=1,
            )
            component_palettes = {
                "Cathode": ["#0B2E4A", "#174A73", "#1F6692", "#2D82B7", "#3A9DCC", "#55B6DD", "#76C8E8", "#98D8F0", "#B9E4F6", "#D6EFFB", "#2454A6", "#4A78C2"],
                "Anode": ["#276749", "#2F855A", "#48A868", "#74C69D", "#95D5B2", "#B7E4C7", "#1B7F5A", "#52B788"],
                "Separator": ["#B85C5C", "#C97A7A", "#D99A9A", "#E8BABA"],
                "Electrolyte": ["#A63F52", "#C45A6A", "#D97B86", "#E9A3AA"],
                "Packing Container": ["#8F3A3A", "#A94E4E", "#C76F6F", "#DD9696", "#EBC0B8", "#F3D6CF"],
                "Module": ["#4B5563", "#6B7280", "#9CA3AF", "#D1D5DB", "#374151", "#7B8794", "#A7B0BA", "#C4CBD3"],
                "Pack": ["#6B5B45", "#8A7356", "#A68A64", "#C0A77B", "#D6C09A", "#7D6B5D", "#9B8878", "#B8A99A"],
                "Cell": ["#5F6B73", "#7B8790", "#A1AAB2", "#C8CDD2"],
            }
            component_counts: dict[str, int] = {}
            material_color_domain: list[str] = []
            material_color_range: list[str] = []
            for _, color_row in material_ring_df.iterrows():
                comp_key = str(color_row.get("Component display") or "Pack")
                label = str(color_row.get("Material segment"))
                if label in material_color_domain:
                    continue
                palette = component_palettes.get(comp_key, component_palettes["Pack"])
                idx = component_counts.get(comp_key, 0)
                component_counts[comp_key] = idx + 1
                material_color_domain.append(label)
                material_color_range.append(palette[idx % len(palette)])
            origin_ring_df = (
                feedstock_ring_df.groupby("Origin", as_index=False)
                .agg({"Total kg/year": "sum", "_origin_sort": "min"})
                .sort_values("_origin_sort", kind="mergesort")
            )
            origin_ring_df["Total t/y"] = origin_ring_df["Total kg/year"] / 1000.0
            donut_all = (
                alt.Chart(material_ring_df)
                .mark_arc(innerRadius=55, outerRadius=135)
                .encode(
                    theta=alt.Theta("Total t/y:Q"),
                    color=alt.Color(
                        "Material segment:N",
                        scale=alt.Scale(domain=material_color_domain, range=material_color_range),
                        legend=alt.Legend(orient="right", title="Material"),
                    ),
                    order=alt.Order("_sort:Q"),
                    tooltip=[
                        "Origin:N",
                        "Component:N",
                        "Material:N",
                        alt.Tooltip("Total t/y:Q", title="Total (t/y)", format=",.2f"),
                    ],
                )
                .properties(height=420)
            )
            origin_ring = (
                alt.Chart(origin_ring_df)
                .mark_arc(innerRadius=140, outerRadius=170, stroke="white", strokeWidth=1)
                .encode(
                    theta=alt.Theta("Total t/y:Q"),
                    color=alt.Color(
                        "Origin:N",
                        scale=alt.Scale(
                            domain=["Cell", "Module", "Pack"],
                            range=["#D9D9D9", "#8C8C8C", "#333333"],
                        ),
                        legend=alt.Legend(orient="bottom", title="Origin"),
                    ),
                    order=alt.Order("_origin_sort:Q"),
                    tooltip=[
                        "Origin:N",
                        alt.Tooltip("Total t/y:Q", title="Total (t/y)", format=",.2f"),
                    ],
                )
            )
            st.altair_chart(
                alt.layer(donut_all, origin_ring).resolve_scale(color="independent"),
                width="stretch",
            )

        _overview_section_heading("Feedstock Inventory")
        with st.expander("Show detailed inventory table", expanded=False):
            st.dataframe(feedstock_display_df, width="stretch", height=360, hide_index=True)

        total_by_material = (
            feedstock_df.assign(_material_order=range(len(feedstock_df)))
            .groupby("Material", as_index=False)
            .agg({"Total kg/year": "sum", "_material_order": "min"})
            .sort_values("_material_order", kind="mergesort")
        )
        total_by_material = total_by_material[total_by_material["Total kg/year"] > 0]

        if not total_by_material.empty:
            _overview_section_heading("Material Breakdown")
            material_options = total_by_material["Material"].tolist()
            _ensure_select_option("feedstock_material", material_options, default_index=0)
            st.selectbox(
                "Material selection",
                options=material_options,
                key="feedstock_material",
            )
            selected_material = str(st.session_state["feedstock_material"])
            variant_cols = [c for c in feedstock_df.columns if c not in ["Basis", "Component", "Material", "Unit", "Total kg/year"]]
            mat_rows = _sort_feedstock_df(feedstock_df[feedstock_df["Material"] == selected_material])

            detail_rows: list[dict] = []
            for _, mat_row in mat_rows.iterrows():
                origin = str(mat_row.get("Basis", "")).strip()
                component = str(mat_row.get("Component", "")).strip()
                source = f"{origin} / {component}" if component else origin
                for variant in variant_cols:
                    kg_y = _safe_float(mat_row.get(variant), 0.0)
                    if kg_y <= 0.0:
                        continue
                    detail_rows.append(
                        {
                            "Source": source,
                            "Basis": origin,
                            "Component": component if component else "-",
                            "Material": selected_material,
                            "Variant": str(variant),
                            "t/y": kg_y / 1000.0,
                        }
                    )
            detail_df = pd.DataFrame(detail_rows)
            by_variant = (
                detail_df.groupby("Variant", as_index=False)["t/y"].sum()
                if not detail_df.empty
                else pd.DataFrame(columns=["Variant", "t/y"])
            )
            if by_variant.empty:
                st.caption("No non-zero variant split for selected material.")
            else:
                by_variant["t/y"] = by_variant["t/y"].round(2)
                c1, c2 = st.columns([2, 1])
                donut_mat = (
                    alt.Chart(by_variant)
                    .mark_arc(innerRadius=65)
                    .encode(
                        theta=alt.Theta("t/y:Q"),
                        color=alt.Color("Variant:N", legend=alt.Legend(orient="right")),
                        tooltip=["Variant:N", alt.Tooltip("t/y:Q", title="Total (t/y)", format=",.2f")],
                    )
                    .properties(height=360)
                )
                c1.altair_chart(donut_mat, width="stretch")
                c2.metric(
                    f"{selected_material} total (t/y)",
                    f"{float(by_variant['t/y'].sum()):,.2f}",
                )

# Main views (radio keeps active section across reruns; st.tabs resets to first)
# -------------------------------------------------------------------
_VIEW_LABELS = [
    "Overview",
    "Mass & Energy Flow",
    PROCESS_ECON_ENV_VIEW_LABEL,
    PLANT_INFRA_INVESTMENT_VIEW_LABEL,
    "Recycling Feedstock",
    "Export Center",
]
if st.session_state.get("main_view_tab") in (
    "Plant Economics",
    "Plant CAPEX & Infrastructure",
    "Infrastructure & Investment Overview",
):
    st.session_state["main_view_tab"] = PLANT_INFRA_INVESTMENT_VIEW_LABEL
if st.session_state.get("main_view_tab") == "Process Economics & GWP":
    st.session_state["main_view_tab"] = PROCESS_ECON_ENV_VIEW_LABEL
if st.session_state.get("main_view_tab") == "Mass & Energy flow":
    st.session_state["main_view_tab"] = "Mass & Energy Flow"
if st.session_state.get("main_view_tab") == "Mass & Energy Dashboard v2":
    st.session_state["main_view_tab"] = "Mass & Energy Flow"
if st.session_state.get("main_view_tab") == "Mass & Energy Dashboard":
    st.session_state["main_view_tab"] = "Mass & Energy Flow"
_ensure_select_option("main_view_tab", _VIEW_LABELS, default_index=0)

view = st.radio(
    "Section",
    _VIEW_LABELS,
    horizontal=True,
    key="main_view_tab",
    label_visibility="collapsed",
)

if view == "Overview":
    ac.log_tab_once("overview")
    st.subheader("Overview")
    with st.container(border=True):
        _inject_overview_tab_styles()

        route_label = ROUTE_DISPLAY_LABELS.get(str(scen_sel.get("route", "mech")), "Mech → Hydro")
        refining_route_v = (
            _black_mass_type_label(scen_sel, short=True) if scen_sel.get("route") == "mech" else "-"
        )
        feed_t_y = _safe_float(ctx.get("feed_mass_kg_per_year"), 0.0) / 1000.0
        op_hours_y = _safe_float(ctx.get("hours_per_year"), 0.0)

        annual_feed_kg = _safe_float(kpi.get("mass_y", 0.0), 0.0)
        route_key = str(scen_sel.get("route", "") or "")
        libra_overview = compute_libra_recovery(ctx, steps_df, econ)

        left_block, right_block = st.columns([2, 1], gap="large")
        with left_block:
            cfg_col, econ_col = st.columns(2, gap="large")
            with cfg_col:
                with st.container(border=True, height=OVERVIEW_TILE_HEIGHT_PX):
                    _render_overview_scenario_configuration_tile(
                        scen_sel,
                        ctx,
                        route_label=route_label,
                        refining_route_v=refining_route_v,
                        feed_t_y=feed_t_y,
                        op_hours_y=op_hours_y,
                    )
            with econ_col:
                with st.container(border=True, height=OVERVIEW_TILE_HEIGHT_PX):
                    _render_overview_economics_tile(kpi)
            st.markdown('<div class="libra-overview-left-block"></div>', unsafe_allow_html=True)
            _render_overview_process_flow_panel(
                steps_df,
                ctx,
                econ,
                route_key,
                str(scen_sel.get("name", "scenario")),
                float(libra_overview.saleable_product_mass_kg_h or 0.0),
            )
        with right_block:
            with st.container(border=True, height=OVERVIEW_TILE_HEIGHT_PX):
                _render_overview_environmental_tile(kpi)
            st.markdown('<div class="libra-overview-right-block"></div>', unsafe_allow_html=True)
            _render_overview_recovery_summary_panel(_overview_recovery_summary_items(libra_overview))

        st.divider()

        # SECTION 2: Recycling products | Revenue sunburst
        prod_col, rev_col = st.columns(2, gap="medium")
        with prod_col:
            _overview_section_heading("Recycling Products")
            grouped_products = _overview_products_grouped_by_stage(
                econ,
                annual_feed_kg,
                route_key,
                ctx=ctx,
                steps_df=steps_df,
            )
            any_products = any(not df.empty for df in grouped_products.values())
            if not any_products:
                st.info("No recovered product outputs found.")
            else:
                for section_title, stage_df in grouped_products.items():
                    if stage_df.empty:
                        continue
                    n_products = len(stage_df)
                    with st.expander(
                        f"{section_title} ({n_products})",
                        expanded=section_title.startswith("Hydrometallurgical"),
                    ):
                        for _, r in stage_df.iterrows():
                            st.markdown(
                                _overview_product_chip_html(
                                    str(r["Product"]), float(r["Output (kg/kg feed)"])
                                ),
                                unsafe_allow_html=True,
                            )

        with rev_col:
            _overview_section_heading("Revenue Explorer")
            _render_overview_revenue_block(econ, route_key, annual_feed_kg, kpi)

elif view == "Mass & Energy Flow":
    ac.log_tab_once("process_flow")
    st.subheader("Mass & Energy Flow")
    with st.container(border=True):
        _inject_overview_tab_styles()
        _render_mass_energy_flow_dashboard(scen_sel, ctx, econ, steps_df, kpi)

elif view == PROCESS_ECON_ENV_VIEW_LABEL:
    ac.log_tab_once("process_econ_gwp")
    st.subheader(PROCESS_ECON_ENV_VIEW_LABEL)
    _render_process_economics_gwp_dashboard(econ, ctx, steps_df, scen_sel, kpi)

elif view == PLANT_INFRA_INVESTMENT_VIEW_LABEL:
    ac.log_tab_once("plant_capex")
    st.subheader(PLANT_INFRA_INVESTMENT_VIEW_LABEL)
    _render_plant_capex_dashboard(scen_sel, ctx, econ, steps_df, extras_all)

elif view == "Recycling Feedstock":
    ac.log_tab_once("feedstock")
    st.subheader("Recycling Feedstock")
    with st.container(border=True):
        _inject_overview_tab_styles()
        _render_recycling_feedstock_dashboard(ctx)

elif view == "Export Center":
    ac.log_tab_once("export")
    _render_export_center_tab(scen_sel, ctx, steps_df, extras_all, econ, kpi, pick_idx, ac)

st.divider()
st.caption("© 2026 University Münster. All rights reserved.")
