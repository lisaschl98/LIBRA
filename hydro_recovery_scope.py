"""Hydro recovery scope: which active-metal product lines run (per route)."""
from __future__ import annotations

NMC_HYDRO_RECOVERY_SCOPE_OPTIONS: tuple[str, ...] = ("all", "nmc")

NMC_HYDRO_RECOVERY_SCOPE_LABELS: dict[str, str] = {
    "all": "NMC & Lithium Recovery",
    "nmc": "NMC Recovery",
}


def resolve_nmc_hydro_recovery_scope(source: dict | None, default: str = "all") -> str:
    """Normalize NMC hydro scope from scenario or ctx (unknown values → ``all``)."""
    raw = str((source or {}).get("nmc_hydro_recovery_scope", default) or default).strip().lower()
    default_norm = str(default).strip().lower()
    if default_norm not in NMC_HYDRO_RECOVERY_SCOPE_OPTIONS:
        default_norm = "all"
    return raw if raw in NMC_HYDRO_RECOVERY_SCOPE_OPTIONS else default_norm


def nmc_hydro_recovery_scope_summary(source: dict | None) -> str:
    scope = resolve_nmc_hydro_recovery_scope(source)
    return NMC_HYDRO_RECOVERY_SCOPE_LABELS.get(scope, scope)


LFP_HYDRO_RECOVERY_SCOPE_OPTIONS: tuple[str, ...] = ("all", "fe")

LFP_HYDRO_RECOVERY_SCOPE_LABELS: dict[str, str] = {
    "all": "Iron & Lithium Recovery",
    "fe": "Iron Recovery",
}


def resolve_lfp_hydro_recovery_scope(source: dict | None, default: str = "all") -> str:
    """Normalize LFP hydro scope from scenario or ctx (unknown values → ``all``)."""
    raw = str((source or {}).get("lfp_hydro_recovery_scope", default) or default).strip().lower()
    default_norm = str(default).strip().lower()
    if default_norm not in LFP_HYDRO_RECOVERY_SCOPE_OPTIONS:
        default_norm = "all"
    return raw if raw in LFP_HYDRO_RECOVERY_SCOPE_OPTIONS else default_norm


def lfp_hydro_recovery_scope_summary(source: dict | None) -> str:
    scope = resolve_lfp_hydro_recovery_scope(source)
    return LFP_HYDRO_RECOVERY_SCOPE_LABELS.get(scope, scope)


MIX_HYDRO_RECOVERY_SCOPE_OPTIONS: tuple[str, ...] = ("all", "nmc_li", "nmc")

MIX_HYDRO_RECOVERY_SCOPE_LABELS: dict[str, str] = {
    "all": "NMC, Lithium & Iron Recovery",
    "nmc_li": "NMC & Lithium Recovery",
    "nmc": "NMC Recovery",
}

_MIX_SCOPE_ALIASES: dict[str, str] = {
    "li": "nmc_li",
    "fepo4": "all",
}


def resolve_mix_hydro_recovery_scope(source: dict | None, default: str = "all") -> str:
    """Normalize Mix hydro scope from scenario or ctx (unknown values → ``all``)."""
    raw = str((source or {}).get("mix_hydro_recovery_scope", default) or default).strip().lower()
    raw = _MIX_SCOPE_ALIASES.get(raw, raw)
    default_norm = str(default).strip().lower()
    if default_norm not in MIX_HYDRO_RECOVERY_SCOPE_OPTIONS:
        default_norm = "all"
    return raw if raw in MIX_HYDRO_RECOVERY_SCOPE_OPTIONS else default_norm


def mix_hydro_recovery_scope_summary(source: dict | None) -> str:
    scope = resolve_mix_hydro_recovery_scope(source)
    return MIX_HYDRO_RECOVERY_SCOPE_LABELS.get(scope, scope)


PYRO_HYDRO_RECOVERY_SCOPE_OPTIONS: tuple[str, ...] = ("all", "co_ni_mn", "co_ni", "co")

PYRO_HYDRO_RECOVERY_SCOPE_LABELS: dict[str, str] = {
    "all": "Cobalt, Nickel, Manganese & Lithium Recovery",
    "co_ni_mn": "Cobalt, Nickel & Manganese Recovery",
    "co_ni": "Cobalt & Nickel Recovery",
    "co": "Cobalt Recovery",
}

_PYRO_SCOPE_ALIASES: dict[str, str] = {
    "co+ni": "co_ni",
    "co+ni+mn": "co_ni_mn",
    "coni": "co_ni",
    "conimn": "co_ni_mn",
}


def resolve_pyro_hydro_recovery_scope(source: dict | None, default: str = "all") -> str:
    """Normalize Pyro hydro scope from scenario or ctx (unknown values → ``all``)."""
    raw = str((source or {}).get("pyro_hydro_recovery_scope", default) or default).strip().lower()
    raw = _PYRO_SCOPE_ALIASES.get(raw, raw)
    default_norm = str(default).strip().lower()
    if default_norm not in PYRO_HYDRO_RECOVERY_SCOPE_OPTIONS:
        default_norm = "all"
    return raw if raw in PYRO_HYDRO_RECOVERY_SCOPE_OPTIONS else default_norm


def pyro_hydro_recovery_scope_summary(source: dict | None) -> str:
    scope = resolve_pyro_hydro_recovery_scope(source)
    return PYRO_HYDRO_RECOVERY_SCOPE_LABELS.get(scope, scope)
