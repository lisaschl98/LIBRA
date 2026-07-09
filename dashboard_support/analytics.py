"""
Anonymous usage analytics via GoatCounter (https://www.goatcounter.com).

- Pageviews (script): countries / visits in the GoatCounter dashboard.
- Custom events (API): model runs, tabs, downloads — no names, no run_id.

Enable with Streamlit secrets or environment variables:
  [goatcounter]
  site_url = "https://YOUR_CODE.goatcounter.com"
  api_token = "YOUR_API_TOKEN"

Or: GOATCOUNTER_SITE_URL, GOATCOUNTER_API_TOKEN
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_SECRETS_FILE_CACHED: bool | None = None


def _secrets_file_present() -> bool:
    """True if Streamlit can load a secrets.toml (avoids UI errors on local runs)."""
    global _SECRETS_FILE_CACHED
    if _SECRETS_FILE_CACHED is not None:
        return _SECRETS_FILE_CACHED
    root = Path(__file__).resolve().parent
    candidates = (
        root / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
        Path.home() / ".streamlit" / "secrets.toml",
    )
    _SECRETS_FILE_CACHED = any(p.is_file() for p in candidates)
    return _SECRETS_FILE_CACHED


def _secret_get(section: str, key: str) -> str:
    """Read one key from st.secrets (works with Streamlit SecretDict, not only dict)."""
    if not _secrets_file_present():
        return ""
    try:
        import streamlit as st

        if not hasattr(st, "secrets"):
            return ""
        sec = st.secrets.get(section)
        if sec is None:
            return ""
        if hasattr(sec, "get"):
            val = sec.get(key)
        else:
            val = sec[key]
        return str(val or "").strip()
    except Exception:
        return ""


def _cfg() -> dict[str, str]:
    site = _secret_get("goatcounter", "site_url") or _secret_get("goatcounter", "site")
    token = _secret_get("goatcounter", "api_token") or _secret_get("goatcounter", "token")
    if site and token:
        return {"site_url": site.rstrip("/"), "api_token": token}

    site = str(os.environ.get("GOATCOUNTER_SITE_URL") or "").strip().rstrip("/")
    token = str(os.environ.get("GOATCOUNTER_API_TOKEN") or "").strip()
    if site and token:
        return {"site_url": site, "api_token": token}
    return {}


def is_enabled() -> bool:
    c = _cfg()
    return bool(c.get("site_url") and c.get("api_token"))


def count_url() -> str:
    site = _cfg().get("site_url", "")
    return f"{site}/count" if site else ""


def session_token() -> str:
    """Anonymous session grouping for GoatCounter (not stored in our DB)."""
    try:
        import streamlit as st

        key = "_gc_session"
        if key not in st.session_state:
            raw = secrets.token_bytes(16)
            st.session_state[key] = hashlib.sha256(raw).hexdigest()[:24]
        return str(st.session_state[key])
    except Exception:
        return hashlib.sha256(secrets.token_bytes(16)).hexdigest()[:24]


def _header_get(name: str) -> str:
    """Read a request header from st.context (case-insensitive)."""
    try:
        import streamlit as st

        headers = getattr(st.context, "headers", None)
        if not headers:
            return ""
        want = name.lower()
        if hasattr(headers, "get"):
            val = headers.get(name) or headers.get(want)
            if val is None and hasattr(headers, "keys"):
                for k in headers.keys():
                    if str(k).lower() == want:
                        val = headers[k]
                        break
        else:
            val = headers[name]
        if isinstance(val, list):
            val = val[0]
        return str(val or "").strip()
    except Exception:
        return ""


def _client_ip() -> str:
    """
    Best-effort client IP for GoatCounter geolocation.
    Streamlit Cloud is behind a proxy; X-Forwarded-For may work when ip_address is None.
    """
    try:
        import streamlit as st

        ip = getattr(st.context, "ip_address", None)
        if ip:
            return str(ip).strip()
    except Exception:
        pass
    xff = _header_get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xri = _header_get("X-Real-Ip")
    if xri:
        return xri.split(",")[0].strip()
    return ""


def _client_user_agent() -> str:
    return _header_get("User-Agent")


def _enrich_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Attach IP / User-Agent so GoatCounter can resolve country (Locations)."""
    out = dict(hit)
    ip = _client_ip()
    if ip:
        out["ip"] = ip
    ua = _client_user_agent()
    if ua:
        out["user_agent"] = ua[:512]
    return out


def _post_hits(hits: list[dict[str, Any]]) -> None:
    cfg = _cfg()
    site = cfg.get("site_url")
    token = cfg.get("api_token")
    if not site or not token or not hits:
        return

    body: dict[str, Any] = {"hits": hits}
    if not any(h.get("ip") for h in hits):
        body["no_sessions"] = True

    url = f"{site}/api/v0/count"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return


def log_pageview_once() -> None:
    """One pageview per session (for Locations / country), via API + client IP if available."""
    if not is_enabled():
        return
    try:
        import streamlit as st

        if st.session_state.get("_gc_pageview_logged"):
            return
        st.session_state["_gc_pageview_logged"] = True
    except Exception:
        pass

    hit = _enrich_hit(
        {
            "path": "/",
            "title": "LIBRA Dashboard",
            "event": False,
            "session": session_token(),
        }
    )
    _post_hits([hit])


def _mass_bucket(kg_y: float) -> str:
    x = float(kg_y or 0.0)
    if x < 10_000:
        return "lt10k"
    if x < 50_000:
        return "10k-50k"
    if x < 200_000:
        return "50k-200k"
    return "gt200k"


def _feed_chemistry_profile(feed: list[dict]) -> str:
    """Coarse feed mix for stats: lfp / nmc / mixed / unknown."""
    lfp = nmc = other = 0.0
    for row in feed or []:
        if not isinstance(row, dict):
            continue
        share = float(row.get("share") or 0.0)
        cid = str(row.get("cell_id") or "").upper()
        if not cid or share <= 0:
            continue
        if "LFP" in cid:
            lfp += share
        elif "NMC" in cid:
            nmc += share
        else:
            other += share
    total = lfp + nmc + other
    if total <= 0:
        return "unknown"
    if lfp >= 0.6:
        return "lfp-heavy"
    if nmc >= 0.6:
        return "nmc-heavy"
    if lfp > 0 and nmc > 0:
        return "mixed"
    return "other"


def log_events(paths: list[str], title: str | None = None) -> None:
    """Send one or more GoatCounter events (fail-silent)."""
    if not is_enabled() or not paths:
        return

    sess = session_token()
    hits: list[dict[str, Any]] = []
    for p in paths:
        path = str(p).strip().lstrip("/")
        if not path:
            continue
        hit: dict[str, Any] = {"path": path, "event": True, "session": sess}
        if title:
            hit["title"] = str(title)[:200]
        hits.append(_enrich_hit(hit))

    if hits:
        _post_hits(hits)


def log_model_run(scen: dict) -> None:
    """Log anonymized scenario knobs after a successful model run."""
    if not is_enabled():
        return
    route = str(scen.get("route") or "unknown").strip().lower()
    region = str(scen.get("region") or "unknown").strip().upper()
    mass_b = _mass_bucket(float(scen.get("mass_feed_kg_y") or 0.0))
    feed_prof = _feed_chemistry_profile(scen.get("feed") or [])
    paths = [
        "event-model-run",
        f"event-route-{route}",
        f"event-region-{region}",
        f"event-mass-{mass_b}",
        f"event-feed-{feed_prof}",
    ]
    if route == "mech":
        nmc = str(scen.get("nmc_code") or "").strip() or "na"
        basis = str(scen.get("nmc_target_basis") or "na").strip()
        policy = str(scen.get("nmc_makeup_policy") or "na").strip()
        paths.extend(
            [
                f"event-nmc-{nmc}",
                f"event-nmc-basis-{basis}",
                f"event-nmc-makeup-{policy}",
            ]
        )
    title = f"run {route} {region} {feed_prof} {mass_b}"
    log_events(paths, title=title)


def log_download(kind: str = "xlsx") -> None:
    log_events([f"event-download-{kind}", "event-download"])


def log_tab_once(tab_key: str) -> None:
    """Log tab view at most once per browser session."""
    if not is_enabled():
        return
    try:
        import streamlit as st

        seen = st.session_state.setdefault("_gc_tabs_seen", set())
        key = str(tab_key).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
    except Exception:
        key = str(tab_key).strip().lower()
    log_events([f"event-tab-{key}", "event-tab-view"])


def log_run_failed(exc: BaseException) -> None:
    log_events(["event-run-failed"], title=type(exc).__name__[:200])


def render_tracker_snippet() -> None:
    """Inject GoatCounter pageview script (countries in GC dashboard)."""
    url = count_url()
    if not url:
        return
    try:
        import streamlit as st

        st.html(
            f'<script data-goatcounter="{url}" async src="//gc.zgo.at/count.js"></script>',
            height=0,
        )
    except Exception:
        pass


RETENTION_MONTHS = 12

PRIVACY_NOTICE_EN = f"""
### Privacy notice — usage statistics (research)

This app uses **[GoatCounter](https://www.goatcounter.com)** for **anonymous** usage statistics
to improve this research tool. GoatCounter is used in a **cookieless** mode (no marketing trackers).

**What we collect**

- **Page visits** (including an aggregated **country** from the connection via GoatCounter, not stored by us;
  on some hosts e.g. Streamlit Cloud, country may appear as unknown if no client IP is available)
- **Anonymous events**, e.g. a model run started, coarse **route** (mechanical / pyro),
  **region** (DE / EU / US / CN), feed mass **bucket**, coarse feed chemistry (LFP / NMC / mixed),
  which **tabs** were opened (once per session), and whether an **Excel/CSV export** was downloaded

**What we do not collect**

- Scenario names, run IDs, free-text inputs, or anything that identifies you personally

**Hosting**

- The app runs on **Streamlit Community Cloud** (operation of the web app).
- Analytics data is processed by **GoatCounter** as a separate service.

**Legal basis (GDPR)**

- **Legitimate interest** (Art. 6(1)(f) GDPR): understanding how this research app is used,
  with minimal impact on visitors.

**Retention**

- Data is kept for about **{RETENTION_MONTHS} months** for aggregated research statistics,
  then deleted or no longer used for reporting.

**Your rights**

- You may request access, erasure, or object to processing. Because events are anonymous,
  we may be unable to link a request to a specific visit.

**Processor / more information**

- [GoatCounter privacy policy](https://www.goatcounter.com/help/privacy)
"""


def privacy_policy_url() -> str:
    """Optional full policy URL (Streamlit secret or env)."""
    url = _secret_get("goatcounter", "privacy_policy_url")
    if url:
        return url
    if _secrets_file_present():
        try:
            import streamlit as st

            return str(st.secrets.get("privacy_policy_url") or "").strip()
        except Exception:
            pass
    return str(os.environ.get("PRIVACY_POLICY_URL") or "").strip()


def render_privacy_sidebar() -> None:
    """Privacy notice in sidebar (always visible; analytics details if configured)."""
    try:
        import streamlit as st
    except Exception:
        return

    with st.sidebar.expander("Privacy — usage statistics", expanded=False):
        if is_enabled():
            st.markdown(PRIVACY_NOTICE_EN)
            url = privacy_policy_url()
            if url:
                st.link_button("Full privacy policy (institution)", url, width="stretch")
        else:
            st.markdown(
                """
**Usage statistics are not active** on this deployment.

No anonymous analytics are sent until Streamlit **Secrets** are set:

```toml
[goatcounter]
site_url = "https://lisaschl98.goatcounter.com"
api_token = "YOUR_API_TOKEN"
```

Then **Save** and **Reboot** the app.

When active, we use GoatCounter (cookieless) for aggregated country and
feature-use statistics only — see the full notice here.
                """
            )
            st.caption("If you already added secrets: check spelling, `[goatcounter]` section, then Reboot.")
