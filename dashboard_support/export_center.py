"""Export Center — reporting and download hub for LIBRA scenario results."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import html as html_module
import io
import mimetypes
from pathlib import Path
import re
from typing import Any, Callable
import zipfile

import streamlit as st

BRAND_BLUE = "#003B75"
OVERVIEW_CARD_BORDER = "#d4dce8"
OVERVIEW_LABEL_GRAY = "#5f6c7b"
ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR.parent / "assets"
ABOUT_BATTERY_ICON_PATH = ASSETS_DIR / "about_libra_battery.png"
ABOUT_DEVELOPER_ICON_PATH = ASSETS_DIR / "about_libra_developer.png"
ABOUT_RELEASE_ICON_PATH = ASSETS_DIR / "about_libra_release.png"
ABOUT_FUNDING_ICON_PATH = ASSETS_DIR / "about_libra_funding.png"
ABOUT_CITATION_ICON_PATH = ASSETS_DIR / "about_libra_citation.png"


@dataclass
class ExportCenterHelpers:
    overview_section_heading: Callable[..., None]
    log_download: Callable[[str], None] | None = None


@dataclass
class ExportCenterData:
    scen_sel: dict
    ctx: dict
    route_label: str
    feedstock_label: str
    excel_bytes: bytes | None
    pdf_bytes: bytes | None
    all_runs_zip_bytes: bytes | None
    all_runs_count: int
    generated_at: str
    helpers: ExportCenterHelpers


def _file_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _safe_export_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(name).strip())
    return (cleaned[:80] or "scenario").strip("._ ")


def build_all_runs_zip_bytes(runs: list[dict[str, Any]]) -> bytes | None:
    """Zip one Excel workbook per entry in run history."""
    from Save import export_single_run_to_excel_bytes

    if not runs:
        return None

    buf = io.BytesIO()
    written = 0
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, run in enumerate(runs):
            scen = run.get("scen") or {}
            steps_df = run.get("steps_df")
            extras = run.get("extras_all")
            ctx = run.get("ctx")
            if steps_df is None or ctx is None:
                continue
            scen_name = _safe_export_name(str(scen.get("name", f"scenario_{i + 1}")))
            try:
                xlsx = export_single_run_to_excel_bytes(scen, steps_df, extras or {}, ctx)
            except Exception:
                continue
            zf.writestr(f"{i + 1:02d}_{scen_name}_result.xlsx", xlsx)
            written += 1

    if written == 0:
        return None
    return buf.getvalue()


def _inject_export_styles() -> None:
    st.markdown(
        f"""
        <style>
            section[data-testid="stMain"] .export-card {{
                border:1px solid {OVERVIEW_CARD_BORDER};
                border-radius:10px;
                padding:16px 14px;
                background:#fafbfd;
                height:200px;
                display:flex;
                flex-direction:column;
            }}
            section[data-testid="stMain"] .export-card-title {{
                font-size:1.05rem;
                color:{BRAND_BLUE};
                font-weight:700;
                margin-bottom:8px;
            }}
            section[data-testid="stMain"] .export-card-subtitle {{
                font-size:0.84rem;
                color:{BRAND_BLUE};
                font-weight:700;
                line-height:1.45;
                margin-bottom:18px;
            }}
            section[data-testid="stMain"] .export-card-body {{
                font-size:0.84rem;
                color:{BRAND_BLUE};
                line-height:1.55;
                margin-bottom:18px;
            }}
            section[data-testid="stMain"] .export-card-note {{
                font-size:0.84rem;
                color:{BRAND_BLUE};
                font-style:italic;
                line-height:1.45;
                flex:1;
            }}
            section[data-testid="stMain"] .export-summary-table {{
                width:100%;
                border-collapse:collapse;
                font-size:0.9rem;
            }}
            section[data-testid="stMain"] .export-summary-table td {{
                padding:8px 10px;
                border-bottom:1px solid {OVERVIEW_CARD_BORDER};
                vertical-align:top;
            }}
            section[data-testid="stMain"] .export-summary-table td:first-child {{
                color:{OVERVIEW_LABEL_GRAY};
                font-weight:600;
                width:38%;
            }}
            section[data-testid="stMain"] .export-summary-table td:last-child {{
                color:{BRAND_BLUE};
                font-weight:500;
            }}
            section[data-testid="stMain"] .export-citation-box {{
                border:1px solid {OVERVIEW_CARD_BORDER};
                border-radius:10px;
                padding:16px 18px;
                background:#fafbfd;
                color:{OVERVIEW_LABEL_GRAY};
                font-size:0.88rem;
                line-height:1.55;
            }}
            section[data-testid="stMain"] .export-citation-box strong {{
                color:{BRAND_BLUE};
                font-weight:700;
            }}
            section[data-testid="stMain"] .export-about-card {{
                border:1px solid {OVERVIEW_CARD_BORDER};
                border-radius:12px;
                padding:18px 20px;
                background:#ffffff;
                color:{OVERVIEW_LABEL_GRAY};
            }}
            section[data-testid="stMain"] .export-about-header {{
                display:grid;
                grid-template-columns:220px 1fr;
                gap:28px;
                align-items:center;
                background:#ffffff;
                margin-bottom:20px;
            }}
            section[data-testid="stMain"] .export-about-logo {{
                display:flex;
                align-items:center;
                justify-content:center;
                gap:12px;
                min-height:94px;
                border-right:1px solid {OVERVIEW_CARD_BORDER};
            }}
            section[data-testid="stMain"] .export-about-logo img {{
                width:52px;
                height:52px;
                object-fit:contain;
                filter:brightness(0) saturate(100%) invert(18%) sepia(59%) saturate(1960%) hue-rotate(184deg) brightness(88%) contrast(104%);
            }}
            section[data-testid="stMain"] .export-about-logo span {{
                color:{BRAND_BLUE};
                font-size:2rem;
                font-weight:800;
                letter-spacing:0.02em;
            }}
            section[data-testid="stMain"] .export-about-card-title {{
                font-size:1.06rem;
                color:{BRAND_BLUE};
                font-weight:800;
                margin-bottom:8px;
                line-height:1.25;
            }}
            section[data-testid="stMain"] .export-about-card-desc {{
                font-size:0.82rem;
                color:{OVERVIEW_LABEL_GRAY};
                line-height:1.45;
                margin-bottom:0;
            }}
            section[data-testid="stMain"] .export-about-version {{
                display:inline-block;
                font-size:0.72rem;
                color:#ffffff;
                background:{BRAND_BLUE};
                font-weight:700;
                line-height:1.2;
                border-radius:999px;
                padding:5px 10px;
                margin-bottom:8px;
            }}
            section[data-testid="stMain"] .export-about-grid {{
                display:grid;
                grid-template-columns:repeat(2, minmax(0, 1fr));
                gap:16px;
                margin-bottom:16px;
            }}
            section[data-testid="stMain"] .export-about-mini {{
                border:1px solid {OVERVIEW_CARD_BORDER};
                border-radius:10px;
                background:#ffffff;
                padding:18px 20px;
                min-height:126px;
                display:grid;
                grid-template-columns:66px 1fr;
                gap:18px;
                align-items:center;
            }}
            section[data-testid="stMain"] .export-about-icon {{
                width:56px;
                height:56px;
                border-radius:50%;
                background:#eef6ff;
                color:{BRAND_BLUE};
                display:flex;
                align-items:center;
                justify-content:center;
                font-size:1.55rem;
                font-weight:700;
            }}
            section[data-testid="stMain"] .export-about-icon img {{
                display:block;
                width:28px;
                height:28px;
                object-fit:contain;
                filter:brightness(0) saturate(100%) invert(18%) sepia(59%) saturate(1960%) hue-rotate(184deg) brightness(88%) contrast(104%);
            }}
            section[data-testid="stMain"] .export-about-label {{
                font-size:0.9rem;
                color:{BRAND_BLUE};
                font-weight:800;
                line-height:1.3;
                margin-bottom:12px;
            }}
            section[data-testid="stMain"] .export-about-value {{
                font-size:0.84rem;
                color:{BRAND_BLUE};
                line-height:1.65;
            }}
            section[data-testid="stMain"] .export-about-value strong {{
                font-weight:700;
            }}
            section[data-testid="stMain"] .export-about-info {{
                border:1px solid {OVERVIEW_CARD_BORDER};
                border-radius:10px;
                background:#f8fbff;
                padding:20px 22px;
                margin-top:16px;
                display:grid;
                grid-template-columns:66px 1fr;
                gap:18px;
                align-items:center;
            }}
            section[data-testid="stMain"] .export-about-info.citation {{
                background:#f8fbff;
            }}
            section[data-testid="stMain"] .export-about-info.citation .export-about-icon {{
                background:#eef6ff;
                color:{BRAND_BLUE};
            }}
            section[data-testid="stMain"] .export-about-info-title {{
                font-size:0.9rem;
                color:{BRAND_BLUE};
                font-weight:800;
                margin-bottom:8px;
            }}
            section[data-testid="stMain"] .export-about-info-body {{
                font-size:0.84rem;
                color:{OVERVIEW_LABEL_GRAY};
                line-height:1.6;
                font-style:italic;
            }}
            @media (max-width: 900px) {{
                section[data-testid="stMain"] .export-about-header {{
                    grid-template-columns:1fr;
                    gap:14px;
                }}
                section[data-testid="stMain"] .export-about-logo {{
                    justify-content:flex-start;
                    border-right:0;
                    border-bottom:1px solid {OVERVIEW_CARD_BORDER};
                    padding-bottom:14px;
                }}
                section[data-testid="stMain"] .export-about-grid {{
                    grid-template-columns:1fr;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _export_card_html(title: str, subtitle: str, body: str, note: str) -> str:
    return (
        f'<div class="export-card">'
        f'<div class="export-card-title">{html_module.escape(title)}</div>'
        f'<div class="export-card-subtitle">{html_module.escape(subtitle)}</div>'
        f'<div class="export-card-body">{html_module.escape(body)}</div>'
        f'<div class="export-card-note">{html_module.escape(note)}</div>'
        f"</div>"
    )


def _about_card_html() -> str:
    icon_data_uri = _file_data_uri(ABOUT_BATTERY_ICON_PATH)
    logo_icon = (
        f'<img src="{html_module.escape(icon_data_uri)}" alt="">'
        if icon_data_uri
        else '<span class="export-about-icon">↻</span>'
    )

    def icon_img(path: Path, fallback: str) -> str:
        data_uri = _file_data_uri(path)
        if not data_uri:
            return html_module.escape(fallback)
        return f'<img src="{html_module.escape(data_uri)}" alt="">'

    mini_cards = [
        (icon_img(ABOUT_DEVELOPER_ICON_PATH, "LS"), "Developer", "<strong>Lisa Schlott</strong><br>lisa.schlott@uni-muenster.de"),
        (icon_img(ABOUT_RELEASE_ICON_PATH, "1.0"), "Release", "<strong>Research version 1.0</strong><br>Updated: 2026-06-22"),
    ]
    mini_cards_html = "".join(
        '<div class="export-about-mini">'
        f'<div class="export-about-icon">{icon}</div>'
        "<div>"
        f'<div class="export-about-label">{html_module.escape(label)}</div>'
        f'<div class="export-about-value">{value}</div>'
        "</div>"
        "</div>"
        for icon, label, value in mini_cards
    )
    return (
        '<div class="export-about-card">'
        '<div class="export-about-header">'
        '<div class="export-about-logo">'
        f"{logo_icon}"
        "<span>LIBRA</span>"
        "</div>"
        "<div>"
        '<div class="export-about-card-title">LIBRA – Lithium-Ion Battery Recycling Assessment</div>'
        '<div class="export-about-version">Research version 1.0</div>'
        '<div class="export-about-card-desc">Developed at the Institute of Business Chemistry, University of Münster.</div>'
        "</div>"
        "</div>"
        f'<div class="export-about-grid">{mini_cards_html}</div>'
        '<div class="export-about-info">'
        f'<div class="export-about-icon">{icon_img(ABOUT_FUNDING_ICON_PATH, "F")}</div>'
        "<div>"
        '<div class="export-about-info-title">Funding acknowledgement</div>'
        '<div class="export-about-info-body">Development of LIBRA was supported by the ProRec project (2023–2026), funded by the German Federal Ministry of Education and Research (BMBF) under grant number 03XP0537A.</div>'
        "</div>"
        "</div>"
        '<div class="export-about-info citation">'
        f'<div class="export-about-icon">{icon_img(ABOUT_CITATION_ICON_PATH, chr(34))}</div>'
        "<div>"
        '<div class="export-about-info-title">Citation</div>'
        '<div class="export-about-info-body">Please cite LIBRA when using exported results in publications, reports, or presentations.</div>'
        "</div>"
        "</div>"
        "</div>"
    )


def _render_quick_exports(data: ExportCenterData) -> str | None:
    h = data.helpers
    h.overview_section_heading("Scenario Exports")
    st.info("Download files are generated on request to keep the app responsive.")
    scen_name = str(data.scen_sel.get("name", "scenario"))
    c1, c2 = st.columns(2)
    action: str | None = None

    with c1:
        st.markdown(
            _export_card_html(
                "Excel Workbook",
                "Complete LIBRA scenario dataset for detailed analysis.",
                "Contains the underlying mass and energy balances, economic and environmental results, recovery metrics, and process-level data used throughout the dashboards.",
                "Designed for further evaluation and custom post-processing.",
            ),
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
        if data.excel_bytes:
            st.download_button(
                "Download Excel Workbook",
                data=data.excel_bytes,
                file_name=f"{scen_name}_result.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key="export_center_excel",
                on_click=(lambda: h.log_download("xlsx")) if h.log_download else None,
            )
        elif st.button("Generate Excel Workbook", type="primary", key="export_center_prepare_excel"):
            action = "excel"

    with c2:
        st.markdown(
            _export_card_html(
                "Executive Summary PDF",
                "Compact report summarizing the selected LIBRA scenario.",
                "Provides an overview of the scenario configuration, key performance indicators, process flow, and recovery results.",
                "Designed for quick sharing and reporting.",
            ),
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
        if data.pdf_bytes:
            st.download_button(
                "Download Executive Summary PDF",
                data=data.pdf_bytes,
                file_name=f"{scen_name}_overview.pdf",
                mime="application/pdf",
                width="stretch",
                key="export_center_pdf",
                on_click=(lambda: h.log_download("pdf")) if h.log_download else None,
            )
        elif st.button("Generate Executive Summary PDF", type="primary", key="export_center_prepare_pdf"):
            action = "pdf"

    if data.all_runs_count > 1:
        if data.all_runs_zip_bytes:
            st.download_button(
                f"Download All Runs Raw Data ({data.all_runs_count} workbooks)",
                data=data.all_runs_zip_bytes,
                file_name="LIBRA_all_runs.zip",
                mime="application/zip",
                width="stretch",
                key="export_center_all_runs",
                on_click=(lambda: h.log_download("xlsx_zip")) if h.log_download else None,
            )
        elif st.button(
            f"Generate all raw workbooks ({data.all_runs_count} runs)",
            key="export_center_prepare_zip",
        ):
            action = "zip"

    return action


def _summary_table_html(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><td>{html_module.escape(label)}</td><td>{html_module.escape(value)}</td></tr>"
        for label, value in rows
    )
    return f'<table class="export-summary-table"><tbody>{body}</tbody></table>'


def _render_scenario_summary(data: ExportCenterData) -> None:
    h = data.helpers
    h.overview_section_heading("Current Scenario")
    st.caption("Configuration used for the generated export files.")
    feed_t_y = float(data.ctx.get("feed_mass_kg_per_year", 0.0) or 0.0) / 1000.0
    hours_y = float(data.ctx.get("hours_per_year", 0.0) or 0.0)
    infra = data.ctx.get("infrastructure", {}) if isinstance(data.ctx.get("infrastructure"), dict) else {}
    rows = [
        ("Scenario", str(data.scen_sel.get("name", "scenario"))),
        ("Region", str(data.scen_sel.get("region", "-"))),
        ("Infrastructure Configuration", str(infra.get("mode_label", "Integrated Site"))),
        ("Route", data.route_label),
        ("Feedstock", data.feedstock_label),
        ("Annual Recycling Feed", f"{feed_t_y:,.0f} t/y"),
        ("Operating Hours", f"{hours_y:,.0f} h/y"),
        ("Generated", data.generated_at),
    ]
    if str(infra.get("mode", "integrated")) == "hub_spoke":
        rows.extend(
            [
                ("Spoke → Hub", f"{infra.get('spoke_location', '-')} → {infra.get('hub_location', '-')}"),
                ("Transported Stream", str(infra.get("transport_stream", "-"))),
                ("Transported Mass", f"{float(infra.get('transported_mass_t_per_year', 0.0) or 0.0):,.1f} t/y"),
                ("Transport Distance", f"{float(infra.get('distance_km', 0.0) or 0.0):,.0f} km"),
                ("Transport Cost", f"${float(infra.get('transport_cost_per_kg_feed', 0.0) or 0.0):,.4f} / kg feed"),
                (
                    "Transport GWP",
                    f"{float(infra.get('transport_gwp_kgco2e_per_kg_feed', 0.0) or 0.0):,.4f} kg CO2-eq / kg feed",
                ),
                ("Required Spokes / Hubs", f"{int(infra.get('required_spokes', 0) or 0)} / {int(infra.get('required_hubs', 0) or 0)}"),
            ]
        )
    st.markdown(_summary_table_html(rows), unsafe_allow_html=True)


def _render_citation(data: ExportCenterData) -> None:
    st.markdown(_about_card_html(), unsafe_allow_html=True)


def render_export_center(data: ExportCenterData) -> str | None:
    """Render the Export Center tab."""
    _inject_export_styles()
    st.subheader("Export Center")
    st.markdown("")

    with st.container(border=True):
        action = _render_quick_exports(data)
        st.markdown("")
        _render_scenario_summary(data)
        st.markdown("")
        data.helpers.overview_section_heading("About LIBRA")
        _render_citation(data)
        st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
    return action
