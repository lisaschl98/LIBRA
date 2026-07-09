from __future__ import annotations

from typing import Iterable


# ---------- constants ----------
MOLAR_MASS = {
    "H2SO4": 98.079,
    "Li": 6.941,
    "Mn": 54.938,
    "Al": 26.982,
    "Ca": 40.078,
    "CaO": 56.077,
    "Co": 58.933,
    "Ni": 58.693,
    "Fe": 55.845,
    "Cu": 63.546,
    "CaSO4": 136.14,
    "SO4": 96.06,
    "NaOH": 40.0,       # g/mol
    "Fe(OH)3": 106.87,  # g/mol
    "Al(OH)3": 78.0,
    "H2O2": 34.014,
    "H2O": 18.015,
    "H2C2O4": 90.03,
    "C2H5OH": 46.069,
    "CH-90 Na": 58.44,
    "Na2CO3": 105.99,
    "Li2CO3": 73.89,
    "Li2SO4": 109.94,
    "P": 30.974,
    "LiH2PO4": 103.97,
    "NiSO4"	: 154.75,
    "CoSO4": 154.99,
    "MnSO4": 151.0,
    "CuSO4": 159.61,
    "FeSO4": 151.92,
    "Al2(SO4)3": 342.15,
    "Na2SO4": 142.04,
    "NH3": 17.031,
    "FePO4": 150.82,
}

# FeC2O4·2H2O (ferrous oxalate dihydrate) — same basis as fe_oxalate_precipitation_stoich_kg_h
MOLAR_MASS["FeC2O4_2H2O"] = (
    float(MOLAR_MASS["Fe"]) + float(MOLAR_MASS["H2C2O4"]) + 2.0 * float(MOLAR_MASS["H2O"])
)


SOLVENT_EXTRACTION_RULES = {
    "Mn": {
        "metal": "Mn",
        "suffixes": [":Mn", "Mn"],
        "organic_solvent": "D2EHPA",
        # Monomer reagent HR (D2EHPA) [g/mol] — used for all extractant mass flows.
        "organic_molar_mass": 322.43,
        # Mn²⁺ + 2 HR → MnR₂ + 2 H⁺  →  2 mol HR per mol Mn²⁺ (before operational excess).
        "reagent_monomers_per_metal": 2.0,
    },
    "Co": {
        "metal": "Co",
        "suffixes": [":Co", "Co"],
        "organic_solvent": "Cyanex 272",
        "organic_molar_mass": 290.43,
        # Co²⁺ + 2 HR → CoR₂ + 2 H⁺
        "reagent_monomers_per_metal": 2.0,
    },
}


LEACHING_SOLUBILITY_KG_PER_M3 = {
    "Li2SO4": 342.0,
    "MnSO4": 762.0,
    "Al2(SO4)3": 1000.0,
    "CoSO4": 383.0,
    "NiSO4": 625.0,
    "CuSO4": 203.0,
    "FeSO4": 400.0,
}
# ---------- generic helpers ----------
def _sum_by_suffixes(comp_abs: dict, suffixes: Iterable[str]) -> float:
    total = 0.0
    sfx = tuple(str(s) for s in suffixes)
    for k, v in (comp_abs or {}).items():
        ks = str(k)
        if any(ks.endswith(s) or ks == s.strip(":") for s in sfx):
            total += float(v or 0.0)
    return total


def metal_mass_in_comp_abs_kg_h(comp_abs: dict | None, symbol: str) -> float:
    """Total kg/h of *symbol* in ``comp_abs`` (keys ending with ``:{symbol}`` or bare ``symbol``)."""
    sym = str(symbol).strip()
    return _sum_by_suffixes(comp_abs or {}, (f":{sym}", sym))


def metal_mass_in_flow_kg_h(flow, symbol: str) -> float:
    """Total kg/h of *symbol* from ``flow.meta['comp_abs']``."""
    meta = dict(getattr(flow, "meta", {}) or {})
    return metal_mass_in_comp_abs_kg_h(meta.get("comp_abs"), symbol)


def solvent_extract_organic_inventory_kg_h(flow, metal_symbol: str) -> float:
    """
    Reporting mass [kg/h] for the organic extract circuit: tagged metal in the stream
    (or whole ``flow.mass_kg_per_h`` if untagged) plus circulating extractant and
    kerosene from ``flow.meta['solvent_extraction']``.

    Matches the booked *loaded organic phase* mass from extraction (without double-counting
    the diluent as part of ``flow.mass_kg_per_h`` when that field is only the metal load).
    """
    m_tag = metal_mass_in_flow_kg_h(flow, metal_symbol)
    m_metal = float(m_tag) if m_tag > 1e-15 else float(getattr(flow, "mass_kg_per_h", 0.0) or 0.0)
    meta = dict(getattr(flow, "meta", {}) or {})
    solm = dict(meta.get("solvent_extraction") or {})
    org_c = float(solm.get("organic_circulating_kg_h", 0.0))
    ker_c = float(solm.get("kerosene_circulating_kg_h", 0.0))
    return m_metal + org_c + ker_c


def solvent_extraction_makeup_kg_h(
    comp_abs: dict,
    metal_key: str,
    *,
    overstoichiometric_factor: float = 1.3,
    organic_mass_fraction: float = 0.30,
    kerosene_mass_fraction: float = 0.70,
    annual_solvent_loss_fraction: float = 0.10,
) -> dict[str, float | str]:
    """Estimate solvent circulation and annual make-up for a solvent extraction step.

    **Stoichiometry (monomer reagent HR, e.g. D2EHPA / Cyanex 272):**

    ``M²⁺ + 2 HR → MR₂ + 2 H⁺``  (e.g. Mn²⁺ + 2 HR → MnR₂ + 2 H⁺)

    Circulating **extractant mass** uses **only** ``organic_molar_mass`` (g/mol monomer).
    Molar flow of HR:

    ``n_HR,h = n_M,h × reagent_monomers_per_metal × overstoichiometric_factor``

    (default: **2 × 1.3** mol HR per mol M²⁺). Then:

    ``m_HR,kg/h = n_HR,h × M(HR) / 1000``

    The **organic : kerosene** split in the diluent stays ``organic_mass_fraction`` /
    ``kerosene_mass_fraction`` (default **30 % / 70 %** by mass).

    ``active_solvent_mol_h`` is **mol HR per hour** (bookkeeping / legacy acid helper).

    Kerosene is treated as a stable diluent: **kerosene_makeup_kg_h** is always ``0.0``.
    Active extractant make-up is in **organic_makeup_kg_h** only.
    """
    rule = SOLVENT_EXTRACTION_RULES[str(metal_key)]
    metal = str(rule["metal"])
    m_metal_h = _sum_by_suffixes(comp_abs, rule["suffixes"])
    if m_metal_h <= 0.0:
        return {
            "metal": metal,
            "organic_solvent": str(rule["organic_solvent"]),
            "metal_kg_h": 0.0,
            "active_solvent_mol_h": 0.0,
            "organic_circulating_kg_h": 0.0,
            "kerosene_circulating_kg_h": 0.0,
            "organic_makeup_kg_h": 0.0,
            "kerosene_makeup_kg_h": 0.0,
        }

    n_metal_h = (m_metal_h * 1000.0) / float(MOLAR_MASS[metal])
    nu_hr = float(rule.get("reagent_monomers_per_metal", 2.0))
    m_hr = float(rule["organic_molar_mass"])
    n_hr_h = (
        n_metal_h
        * max(0.0, nu_hr)
        * max(0.0, float(overstoichiometric_factor))
    )
    organic_circulating_h = (n_hr_h * m_hr) / 1000.0

    org_frac = max(1e-9, float(organic_mass_fraction))
    ker_frac = max(0.0, float(kerosene_mass_fraction))
    kerosene_circulating_h = organic_circulating_h * (ker_frac / org_frac)
    loss = max(0.0, float(annual_solvent_loss_fraction))

    return {
        "metal": metal,
        "organic_solvent": str(rule["organic_solvent"]),
        "metal_kg_h": m_metal_h,
        "active_solvent_mol_h": n_hr_h,
        "organic_circulating_kg_h": organic_circulating_h,
        "kerosene_circulating_kg_h": kerosene_circulating_h,
        "organic_makeup_kg_h": organic_circulating_h * loss,
        "kerosene_makeup_kg_h": 0.0,
    }


def solvent_extraction_naoh_50_for_acid_from_transfer_kg_h(
    m_metal_transferred_kg_h: float,
    metal: str,
    *,
    mol_naoh_per_mol_metal: float = 2.0,
    naoh_solution_wtfrac: float = 0.5,
) -> float:
    """
    NaOH **solution** mass flow [kg/h] (default **50 wt-%**) to neutralise acid released on
    transfer of ``metal`` to the organic phase.

    For ``M²⁺ + 2 HR → MR₂ + 2 H⁺``, use ``mol_naoh_per_mol_metal=2`` (2 mol NaOH per mol M).
    """
    sym = str(metal).strip()
    if sym not in MOLAR_MASS:
        return 0.0
    m_m = max(0.0, float(m_metal_transferred_kg_h))
    if m_m <= 0.0:
        return 0.0
    n_m = (m_m * 1000.0) / float(MOLAR_MASS[sym])
    n_naoh = n_m * max(0.0, float(mol_naoh_per_mol_metal))
    m_naoh_pure = (n_naoh * float(MOLAR_MASS["NaOH"])) / 1000.0
    return naoh_solution_from_pure_kg_h(m_naoh_pure, naoh_solution_wtfrac)


def h2so4_95_for_solvent_stripping_kg_h(
    solvent_info: dict | None,
    *,
    acid_mol_per_mol_solvent: float = 1.5,
    h2so4_wtfrac: float = 0.95,
) -> tuple[float, float]:
    """Return 95 wt-% sulfuric acid demand and active solvent molar flow.

    ``active_solvent_mol_h`` in ``solvent_info`` is **mol HR / h** (monomer) from extraction.
    ``acid_mol_per_mol_solvent`` is mol **H₂SO₄** per mol **HR** (default 1.5).

    .. note::
        For **Mn/Co solvent stripping** in this project, acid dosing follows **metal-based**
        stoichiometry (2 H⁺ per mol M²⁺) via ``h2so4_pure_for_divalent_stripping_kg_h`` instead
        of this helper.
    """
    info = dict(solvent_info or {})
    n_solvent_h = float(info.get("active_solvent_mol_h", 0.0) or 0.0)
    if n_solvent_h <= 0.0:
        return 0.0, 0.0
    n_h2so4_h = n_solvent_h * max(0.0, float(acid_mol_per_mol_solvent))
    m_h2so4_pure_h = (n_h2so4_h * float(MOLAR_MASS["H2SO4"])) / 1000.0
    wt = max(1e-9, float(h2so4_wtfrac))
    return m_h2so4_pure_h / wt, n_solvent_h


def h2so4_pure_for_divalent_stripping_kg_h(
    m_metal_kg_h: float,
    metal_symbol: str,
    *,
    safety_factor: float = 1.0,
    mol_h2so4_per_mol_metal: float = 1.0,
) -> float:
    """
    **Pure** H₂SO₄ mass flow [kg/h] to strip a **divalent** metal from the loaded organic phase.

    Reverse of extraction: **loaded complex + 2 H⁺ → M²⁺ + …**  
    Stoichiometric acid (simplified strong-acid dosing): **1 mol H₂SO₄ per mol M²⁺**
    (provides **2 mol H⁺** per mol sulfuric acid in this balance), multiplied by
    ``safety_factor``. ``mol_h2so4_per_mol_metal`` is usually **1.0**.
    """
    m = max(0.0, float(m_metal_kg_h))
    sym = str(metal_symbol).strip()
    if m <= 0.0 or sym not in MOLAR_MASS:
        return 0.0
    n_m = (m * 1000.0) / float(MOLAR_MASS[sym])
    n_h2so4 = n_m * max(0.0, float(mol_h2so4_per_mol_metal)) * max(0.0, float(safety_factor))
    return (n_h2so4 * float(MOLAR_MASS["H2SO4"])) / 1000.0


def deduct_from_suffixes(comp_abs: dict, suffixes: Iterable[str], amount_kg_h: float) -> float:
    """Remove dissolved mass from all ``comp_abs`` keys matching ``suffixes``. Returns kg/h removed."""
    remaining = max(0.0, float(amount_kg_h))
    if remaining <= 0.0:
        return 0.0
    sfx = tuple(str(s) for s in suffixes)
    for k in list((comp_abs or {}).keys()):
        if remaining <= 0.0:
            break
        ks = str(k)
        if not any(ks.endswith(s) or ks == s.strip(":") for s in sfx):
            continue
        v = float(comp_abs.get(k, 0.0) or 0.0)
        if v <= 0.0:
            continue
        take = min(v, remaining)
        comp_abs[k] = v - take
        remaining -= take
    return max(0.0, float(amount_kg_h)) - remaining


def tag_stoich_product_in_comp_abs(
    comp_abs: dict,
    product_key: str,
    m_product_kg_h: float,
    *,
    absorb_keys: Iterable[str] = ("__untracked__",),
) -> None:
    """
    Add a stoichiometric product to ``comp_abs`` and absorb the same mass from soft keys
    (default ``__untracked__``) so the total tagged mass stays at the liquor mass.
    """
    m = max(0.0, float(m_product_kg_h))
    if m <= 0.0:
        return
    key = str(product_key)
    comp_abs[key] = float(comp_abs.get(key, 0.0) or 0.0) + m
    rem = m
    for sink in absorb_keys:
        if rem <= 1e-12:
            break
        sk = str(sink)
        v = float(comp_abs.get(sk, 0.0) or 0.0)
        if v <= 0.0:
            continue
        take = min(v, rem)
        comp_abs[sk] = v - take
        if comp_abs[sk] <= 1e-12:
            comp_abs.pop(sk, None)
        rem -= take


def reconcile_comp_abs_to_mass(
    comp_abs: dict,
    m_target: float,
    preserve_keys: Iterable[str] = (),
) -> dict:
    """
    Scale non-preserved components so ``sum(comp_abs) == m_target`` without changing preserved keys
    (e.g. stoichiometric Li2CO3 / Na2SO4 / Na2CO3 after precipitation).
    """
    comp_abs = {str(k): float(v) for k, v in (comp_abs or {}).items() if abs(float(v)) > 1e-12}
    m_target = float(m_target)
    preserve = tuple(str(k) for k in preserve_keys)
    preserved = {k: comp_abs[k] for k in preserve if k in comp_abs}
    preserved_sum = float(sum(preserved.values()))
    rest = {k: v for k, v in comp_abs.items() if k not in preserved}
    rest_sum = float(sum(rest.values()))
    m_rest = max(0.0, m_target - preserved_sum)
    if rest_sum > 1e-12 and m_rest > 1e-12:
        f = m_rest / rest_sum
        rest = {k: v * f for k, v in rest.items()}
    elif m_rest > 1e-12:
        rest = {"__untracked__": m_rest}
    else:
        rest = {}
    out = dict(rest)
    out.update(preserved)
    return out


def liquor_inventory_preserve_keys(
    comp_abs: dict,
    *,
    extra_preserve: Iterable[str] = (),
) -> tuple[str, ...]:
    """
    Keys held at absolute kg/h when reconciling liquor after Li2CO3 precipitation.

    Stoich products (Li2CO3, Na2CO3, Na2SO4) stay fixed; dissolved metals and cell
    inventory must not be scaled down — only solvent / untracked absorbs the gap.
    """
    keys: set[str] = {str(k) for k in extra_preserve}
    metal_suffixes = (
        ":Fe",
        ":P",
        ":Ni",
        ":Co",
        ":Mn",
        ":Cu",
        ":Li",
        ":Al",
        ":Mg",
        "Fe_cement",
    )
    for k, v in (comp_abs or {}).items():
        if abs(float(v or 0.0)) <= 1e-12:
            continue
        ks = str(k)
        if ks.startswith("cell:") or ks.startswith("process:Fe_cement"):
            keys.add(ks)
        elif any(ks.endswith(s) or ks == s.strip(":") for s in metal_suffixes):
            keys.add(ks)
    return tuple(keys)


def h2so4_95_digestion_demand_kg_h(
    comp_abs: dict,
    species_rules: dict,
    safety_factor: float = 1.1,
) -> float:
    """
    Generic H2SO4 95 wt-% demand for digestion [kg/h].

    species_rules format:
    {
      "Li": {"suffixes": [":Li"], "nu_h2so4": 0.5},
      "Mn": {"suffixes": [":Mn"], "nu_h2so4": 1.0},
      ...
    }

    Logic:
      m_element [kg/h] -> n_element [mol/h]
      n_h2so4 += nu_h2so4 * n_element
      apply safety factor
      convert pure H2SO4 to 95 wt-%
    """
    n_h2so4 = 0.0

    for elem, rule in species_rules.items():
        suffixes = rule.get("suffixes", [])
        nu_h2so4 = float(rule.get("nu_h2so4", 0.0))

        m_elem_h = _sum_by_suffixes(comp_abs, suffixes)
        if m_elem_h <= 0.0 or nu_h2so4 <= 0.0:
            continue

        mm = MOLAR_MASS[elem]  # g/mol
        n_elem = (m_elem_h * 1000.0) / mm
        n_h2so4 += nu_h2so4 * n_elem

    n_h2so4 *= float(safety_factor)

    m_h2so4_pure_h = (n_h2so4 * MOLAR_MASS["H2SO4"]) / 1000.0
    return (m_h2so4_pure_h / 0.95) if m_h2so4_pure_h > 0.0 else 0.0


# ---------- digestion profiles ----------
DIGESTION_RULES = {
    "slag": {
        "Li": {"suffixes": [":Li"], "nu_h2so4": 0.5},
        "Mn": {"suffixes": [":Mn"], "nu_h2so4": 1.0},
        "Al": {"suffixes": [":Al", ":Aluminium"], "nu_h2so4": 1.5},
        "Fe": {"suffixes": [":Fe"], "nu_h2so4": 1.0},
        "CaO": {"suffixes": [":CaO"], "nu_h2so4": 1.0},
    },
    "alloy": {
        "Co": {"suffixes": [":Co"], "nu_h2so4": 1.0},
        "Ni": {"suffixes": [":Ni"], "nu_h2so4": 1.0},
        "Fe": {"suffixes": [":Fe", ":Steel", ":Nickel-plated steel"], "nu_h2so4": 1.0},
        "Cu": {"suffixes": [":Cu", ":Copper"], "nu_h2so4": 1.0},
    },
    "NMC": {
        "Li": {"suffixes": [":Li"], "nu_h2so4": 0.5},
        "Ni": {"suffixes": [":Ni"], "nu_h2so4": 1.0},
        "Mn": {"suffixes": [":Mn"], "nu_h2so4": 1.0},
        "Co": {"suffixes": [":Co"], "nu_h2so4": 1.0},
        "Cu": {"suffixes": [":Copper"], "nu_h2so4": 1.0},
        "Al": {"suffixes": [":Aluminium"], "nu_h2so4": 1.5},
    },
    "LFP": {
        "Li": {"suffixes": [":Li"], "nu_h2so4": 0.5},
        "Fe": {"suffixes": [":Fe"], "nu_h2so4": 1.0},
        "Cu": {"suffixes": [":Copper"], "nu_h2so4": 1.0},  
    },
    "MIX": {
        "Li": {"suffixes": [":Li"], "nu_h2so4": 0.5},
        "Fe": {"suffixes": [":Fe"], "nu_h2so4": 1.0},
        "Ni": {"suffixes": [":Ni"], "nu_h2so4": 1.0},
        "Mn": {"suffixes": [":Mn"], "nu_h2so4": 1.0},
        "Co": {"suffixes": [":Co"], "nu_h2so4": 1.0},
        "Cu": {"suffixes": [":Copper"], "nu_h2so4": 1.0},
    },
}


def leaching_water_demand_kg_h(
    comp_abs: dict,
    species_rules: dict,
    solubility_kg_per_m3: dict | None = None,
    safety_factor: float = 1.1,
) -> float:
    """
    Generic water demand for leaching [kg/h] from sulfate solubility constraints.
    Parameters
    ----------
    comp_abs : dict
        Absolute component masses [kg/h], typically flow.meta["comp_abs"].
    species_rules : dict
        Route-specific rules, see LEACHING_RULES.
    solubility_kg_per_m3 : dict | None
        Solubility map [kg/m3]. If None, LEACHING_SOLUBILITY_KG_PER_M3 is used.
    safety_factor : float
        Global safety factor on required liquor volume.
    Returns
    -------
    float
        Water demand [kg/h].
    """
    sol_map = solubility_kg_per_m3 or LEACHING_SOLUBILITY_KG_PER_M3
    required_volumes_m3_h: list[float] = []
    for elem, rule in (species_rules or {}).items():
        suffixes = rule.get("suffixes", [])
        salt = str(rule.get("salt", "")).strip()
        nu_elem = float(rule.get("nu_elem_in_salt", 0.0))
        nu_so4 = float(rule.get("nu_so4_in_salt", 0.0))
        if not salt or nu_elem <= 0.0 or nu_so4 <= 0.0:
            continue
        m_elem_h = _sum_by_suffixes(comp_abs, suffixes)  # kg/h of element
        if m_elem_h <= 0.0:
            continue
        mm_elem = float(MOLAR_MASS[elem])  # g/mol
        mm_salt = nu_elem * mm_elem + nu_so4 * MOLAR_MASS["SO4"]
        n_elem_mol_h = (m_elem_h * 1000.0) / mm_elem
        n_salt_mol_h = n_elem_mol_h / nu_elem
        m_salt_h = (n_salt_mol_h * mm_salt) / 1000.0  # kg/h
        sol = float(sol_map.get(salt, 0.0) or 0.0)
        if sol > 0.0 and m_salt_h > 0.0:
            required_volumes_m3_h.append(m_salt_h / sol)
    if not required_volumes_m3_h:
        return 0.0
    water_m3_h = max(required_volumes_m3_h)
    return float(water_m3_h) * float(safety_factor) * 1000.0  # kg/h

LEACHING_RULES = {
    "slag": {
        "Li": {"suffixes": [":Li"], "salt": "Li2SO4", "nu_elem_in_salt": 2, "nu_so4_in_salt": 1},
        "Mn": {"suffixes": [":Mn"], "salt": "MnSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Fe": {"suffixes": [":Fe"], "salt": "FeSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Al": {"suffixes": [":Al", ":Aluminium"], "salt": "Al2(SO4)3", "nu_elem_in_salt": 2, "nu_so4_in_salt": 3},
    },
    "alloy": {
        "Co": {"suffixes": [":Co"], "salt": "CoSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Ni": {"suffixes": [":Ni"], "salt": "NiSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Cu": {"suffixes": [":Cu", ":Copper"], "salt": "CuSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Fe": {"suffixes": [":Fe", ":Steel", ":Nickel-plated steel"], "salt": "FeSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
    },
    "NMC": {
        "Li": {"suffixes": [":Li"], "salt": "Li2SO4", "nu_elem_in_salt": 2, "nu_so4_in_salt": 1},
        "Co": {"suffixes": [":Co"], "salt": "CoSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Ni": {"suffixes": [":Ni"], "salt": "NiSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Mn": {"suffixes": [":Mn"], "salt": "MnSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Cu": {"suffixes": [":Copper"], "salt": "CuSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Al": {"suffixes": [":Aluminium"], "salt": "Al2(SO4)3", "nu_elem_in_salt": 2, "nu_so4_in_salt": 3},
    },
    "LFP": {
        "Li": {"suffixes": [":Li"], "salt": "Li2SO4", "nu_elem_in_salt": 2, "nu_so4_in_salt": 1},
        "Fe": {"suffixes": [":Fe"], "salt": "FeSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Cu": {"suffixes": [":Copper"],"salt": "CuSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
    },
    "MIX": {
        "Li": {"suffixes": [":Li"], "salt": "Li2SO4", "nu_elem_in_salt": 2, "nu_so4_in_salt": 1},
        "Fe": {"suffixes": [":Fe"], "salt": "FeSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Ni": {"suffixes": [":Ni"], "salt": "NiSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Mn": {"suffixes": [":Mn"], "salt": "MnSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Co": {"suffixes": [":Co"], "salt": "CoSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
        "Cu": {"suffixes": [":Copper"], "salt": "CuSO4", "nu_elem_in_salt": 1, "nu_so4_in_salt": 1},
    },
}

def cementation_reductant_demand_kg_h(
    comp_abs: dict,
    rule: dict,
    safety_factor: float = 1.1,
) -> tuple[float, float]:
    """
    Generic reductant demand [kg/h] for cementation reactions.

    Returns
    -------
    tuple[float, float]
        (m_reductant_kg_h, m_target_kg_h)
    """
    target = str(rule.get("target_element", "")).strip()
    reductant = str(rule.get("reductant_element", "")).strip()
    suffixes = rule.get("target_suffixes", [])
    nu = float(rule.get("nu_reductant_per_target", 0.0))

    if not target or not reductant or nu <= 0.0:
        return 0.0, 0.0

    m_target_h = _sum_by_suffixes(comp_abs, suffixes)
    if m_target_h <= 0.0:
        return 0.0, 0.0

    mm_target = float(MOLAR_MASS[target])       # g/mol
    mm_reductant = float(MOLAR_MASS[reductant]) # g/mol

    n_target = (m_target_h * 1000.0) / mm_target          # mol/h
    n_reductant = n_target * nu * float(safety_factor)    # mol/h
    m_reductant_h = (n_reductant * mm_reductant) / 1000.0 # kg/h

    return m_reductant_h, m_target_h

CEMENTATION_RULES = {
    "Cu_with_Fe": {
        "target_element": "Cu",
        "target_suffixes": [":Cu", ":Copper", "Cu"],
        "reductant_element": "Fe",
        "nu_reductant_per_target": 1.0,  # CuSO4 + Fe -> FeSO4 + Cu
    },
}

def h2o2_solution_demand_kg_h_from_slurry_mass(
    m_slurry_kg_h: float,
    vol_frac: float = 0.04,
    rho_slurry_kg_per_m3: float = 1000.0,
    rho_h2o2_solution_kg_per_m3: float = 1110.0,
) -> float:
    """
    H2O2 solution demand [kg/h] from slurry mass flow [kg/h] via a volume fraction.

    Model:
      V_slurry = m_slurry / rho_slurry
      V_h2o2   = vol_frac * V_slurry
      m_h2o2   = V_h2o2 * rho_h2o2_solution
    """
    m = float(m_slurry_kg_h)
    if m <= 0.0:
        return 0.0
    vf = max(0.0, float(vol_frac))
    if vf <= 0.0:
        return 0.0

    v_slurry_m3_h = m / float(rho_slurry_kg_per_m3)
    v_h2o2_m3_h = v_slurry_m3_h * vf
    return v_h2o2_m3_h * float(rho_h2o2_solution_kg_per_m3)



def fe_al_precipitation_stoich_kg_h(
    m_fe_in_kg_h: float,
    m_al_in_kg_h: float,
    stoich_factor: float = 1.0,
) -> dict[str, float]:
    """
    Stoichiometric Fe/Al hydroxide precipitation demand and products [kg/h].

    Reactions:
      Fe3+ + 3OH- -> Fe(OH)3
      Al3+ + 3OH- -> Al(OH)3

    Returns keys:
      - naoh_pure_kg_h
      - feoh3_kg_h
      - aloh3_kg_h
    """
    m_fe = max(0.0, float(m_fe_in_kg_h))
    m_al = max(0.0, float(m_al_in_kg_h))
    sf = max(0.0, float(stoich_factor))

    # mol/h metals
    n_fe = (m_fe * 1000.0) / float(MOLAR_MASS["Fe"]) if m_fe > 0.0 else 0.0
    n_al = (m_al * 1000.0) / float(MOLAR_MASS["Al"]) if m_al > 0.0 else 0.0

    # NaOH pure demand: 3 mol OH- per mol Fe3+/Al3+
    n_naoh = 3.0 * (n_fe + n_al) * sf
    m_naoh_pure = (n_naoh * float(MOLAR_MASS["NaOH"])) / 1000.0

    # Product masses
    m_feoh3 = (n_fe * float(MOLAR_MASS["Fe(OH)3"])) / 1000.0
    m_aloh3 = (n_al * float(MOLAR_MASS["Al(OH)3"])) / 1000.0

    return {
        "naoh_pure_kg_h": max(0.0, m_naoh_pure),
        "feoh3_kg_h": max(0.0, m_feoh3),
        "aloh3_kg_h": max(0.0, m_aloh3),
    }


PRECIPITATION_FE_AL_RULES = {
    "alloy": {
        "fe_suffixes": [":Fe", ":Steel", ":Nickel-plated steel", "Fe_cement"],
        "al_suffixes": [],  # kein Al in alloy-step
        "naoh_solution_wtfrac_default": 0.5,
    },
    "slag": {
        "fe_suffixes": [":Fe", "Fe"],
        "al_suffixes": [":Al", ":Aluminium"],
        "naoh_solution_wtfrac_default": 0.5,
    },
    "nmc": {
        "fe_suffixes": [":Fe", "Fe_cement"],
        "al_suffixes": [":Al", ":Aluminium"],
        "naoh_solution_wtfrac_default": 0.5,
    },
}

def naoh_solution_from_pure_kg_h(
    m_naoh_pure_kg_h: float,
    solution_wtfrac: float = 0.5,
) -> float:
    """
    Convert pure NaOH demand [kg/h] to NaOH solution mass flow [kg/h].

    m_solution = m_pure / wtfrac
    """
    m_pure = max(0.0, float(m_naoh_pure_kg_h))
    w = float(solution_wtfrac)
    if m_pure <= 0.0:
        return 0.0
    if w <= 0.0:
        return 0.0
    return m_pure / w

def prewetting_water_demand_kg_h(
    m_solid_kg_h: float,
    solid_to_liquid_ratio: float = 5.0,
) -> float:
    """
    Water demand for pre-wetting [kg/h] from solid mass flow [kg/h]
    using solid-to-liquid ratio S/L.

    Example:
      S/L = 5:1  -> L/S = 1/5 = 0.2 kg/kg
      m_H2O = m_solid / (S/L)
    """
    m_solid = float(m_solid_kg_h)
    r_sl = float(solid_to_liquid_ratio)

    if m_solid <= 0.0 or r_sl <= 0.0:
        return 0.0

    return m_solid / r_sl

def oxalate_mixing_reagents_kg_h(
    comp_abs: dict,
    fe_suffixes: list[str],
    fe_to_c2o4_molar_ratio: float = 1.3,
    oxalic_solution_wtfrac: float = 0.10,
    ethanol_frac_of_oxalic_solution: float = 0.10,
) -> tuple[float, float, float, float]:
    """
    Returns:
      (m_fe_kg_h, m_oxalic_pure_kg_h, m_water_in_oxalic_solution_kg_h, m_ethanol_kg_h)
    """

    m_fe = _sum_by_suffixes(comp_abs, fe_suffixes)
    if m_fe <= 0.0:
        return 0.0, 0.0, 0.0, 0.0

    # mol Fe
    n_fe = (m_fe * 1000.0) / float(MOLAR_MASS["Fe"])

    # mol C2O4 required with excess
    n_c2o4 = n_fe * float(fe_to_c2o4_molar_ratio)

    # pure oxalic acid [kg/h]
    m_oxalic_pure = (n_c2o4 * float(MOLAR_MASS["H2C2O4"])) / 1000.0

    # 10 wt-% oxalic solution -> total solution mass
    if oxalic_solution_wtfrac > 0.0:
        m_oxalic_solution = m_oxalic_pure / float(oxalic_solution_wtfrac)
    else:
        m_oxalic_solution = m_oxalic_pure

    # water part in oxalic solution
    m_water = max(0.0, m_oxalic_solution - m_oxalic_pure)

    # ethanol addition (10% of oxalic solution mass)
    m_ethanol = float(ethanol_frac_of_oxalic_solution) * m_oxalic_solution

    return m_fe, m_oxalic_pure, m_water, m_ethanol

OXALATE_MIXING_RULES = {
    "LFP": {
        "fe_suffixes": [":Fe", "process:Fe_cement"],
        "fe_to_c2o4_molar_ratio": 1.3,        # Fe:C2O4 = 1:1.3
        "oxalic_solution_wtfrac": 0.10,       # 10 wt-% oxalic acid
        "ethanol_frac_of_oxalic_solution": 0.10,  # 10% of oxalic acid solution
    },
}
    
def fe_oxalate_precipitation_stoich_kg_h(
    m_fe_kg_h: float,
    m_oxalic_pure_kg_h: float,
) -> dict[str, float]:
    """
    Stoichiometric Fe-oxalate precipitation based on limiting reagent.

    Assumption:
      Fe + H2C2O4 -> FeC2O4·2H2O   (1:1 mol Fe : mol oxalic acid)

    Returns keys:
      - fe_reacted_kg_h
      - oxalic_reacted_kg_h
      - fe_oxalate_2h2o_formed_kg_h
    """
    m_fe = max(0.0, float(m_fe_kg_h))
    m_ox = max(0.0, float(m_oxalic_pure_kg_h))

    if m_fe <= 0.0 or m_ox <= 0.0:
        return {
            "fe_reacted_kg_h": 0.0,
            "oxalic_reacted_kg_h": 0.0,
            "fe_oxalate_2h2o_formed_kg_h": 0.0,
        }

    n_fe = (m_fe * 1000.0) / float(MOLAR_MASS["Fe"])
    n_ox = (m_ox * 1000.0) / float(MOLAR_MASS["H2C2O4"])

    n_reacted = min(n_fe, n_ox)

    m_fe_reacted = (n_reacted * float(MOLAR_MASS["Fe"])) / 1000.0
    m_ox_reacted = (n_reacted * float(MOLAR_MASS["H2C2O4"])) / 1000.0

    mm_fe_ox_2h2o = float(MOLAR_MASS["FeC2O4_2H2O"])
    m_product = (n_reacted * mm_fe_ox_2h2o) / 1000.0

    return {
        "fe_reacted_kg_h": m_fe_reacted,
        "oxalic_reacted_kg_h": m_ox_reacted,
        "fe_oxalate_2h2o_formed_kg_h": m_product,
    }

def washing_water_demand_kg_h(
    comp_abs: dict,
    solid_suffixes: list[str],
    water_to_solid_ratio: float = 5.0,
    safety_factor: float = 1.0,
) -> tuple[float, float]:
    """
    Returns (m_solid_kg_h, m_water_kg_h)
    """
    m_solid = _sum_by_suffixes(comp_abs, solid_suffixes)
    if m_solid <= 0.0:
        return 0.0, 0.0
    m_water = m_solid * float(water_to_solid_ratio) * float(safety_factor)
    return m_solid, max(0.0, m_water)

WASHING_RULES = {
    "LFP_OXALATE": {
        "solid_suffixes": ["process:FeC2O4_2H2O"],
        "water_to_solid_ratio_default": 5.0,
    },
    "NMC_PRECURSOR": {
        "solid_suffixes": ["process:NixCoyMnz(OH)2"],
        "water_to_solid_ratio_default": 5.0,
    },
    "NMC_LI2CO3": {
        "solid_suffixes": ["process:Li2CO3"],
        "water_to_solid_ratio_default": 5.0,
    },
    # add more washing steps later
}

# ---------- drying ----------
def drying_water_inventory_kg_h(
    comp_abs: dict,
    water_keys: list[str],
) -> tuple[float, float]:
    """
    Return inlet totals for drying from composition dictionary.

    Parameters
    ----------
    comp_abs : dict
        Absolute component masses [kg/h], typically flow.meta["comp_abs"].
    water_keys : list[str]
        Component keys that represent removable free water in drying.

    Returns
    -------
    tuple[float, float]
        (m_total_in_kg_h, m_water_in_kg_h)
    """
    ca = comp_abs or {}
    m_total = sum(float(v or 0.0) for v in ca.values())
    m_water = sum(float(ca.get(k, 0.0) or 0.0) for k in water_keys)
    return max(0.0, m_total), max(0.0, m_water)


def drying_expected_water_to_remove_kg_h(
    comp_abs: dict,
    water_keys: list[str],
    removal_fraction: float = 1.0,
) -> float:
    """
    Expected removable water in drying [kg/h] from tracked free-water keys.

    This is a KPI helper. Actual stream split should be handled by EFF partitioning
    (e.g. process:H2O_* -> wastewater drying).

    Parameters
    ----------
    comp_abs : dict
        Absolute component masses [kg/h].
    water_keys : list[str]
        Keys treated as removable free water.
    removal_fraction : float
        Fraction of tracked water expected to be removed (0..1).

    Returns
    -------
    float
        Expected removed water [kg/h].
    """
    _, m_water = drying_water_inventory_kg_h(comp_abs=comp_abs, water_keys=water_keys)
    rf = min(1.0, max(0.0, float(removal_fraction)))
    return m_water * rf


DRYING_RULES = {
    "LFP_OXALATE": {
        # free water from upstream washing step (not crystal water in FeC2O4·2H2O)
        "water_keys": ["process:H2O_oxalate_wash"],
        "water_removal_fraction_default": 1.0,
    },
    "NMC_PRECURSOR": {
        "water_keys": ["process:H2O_nmc_wash"],
        "water_removal_fraction_default": 1.0,
    },
    "NMC_LI2CO3": {
        "water_keys": ["process:H2O_wash"],
        "water_removal_fraction_default": 1.0,
    },
    "SLAG_LI2CO3": {
        "water_keys": ["process:H2O_wash"],
        "water_removal_fraction_default": 1.0,
    },
    # Add more routes/products here as needed
}
ION_EXCHANGE_RULES = {
    "LFP": {
        # which ions bind to the resin (as elemental mass in comp_abs)
        "target_ions": [
            {"element": "Fe", "suffixes": [":Fe"], "charge": 2},
        ],
        # CH-90 Na: practically parameterizable
        "capacity_eq_per_kg_resin": 1.8,   # eq/kg (typical range ~1.6-2.0)
        "utilization": 0.65,               # usable fraction of capacity
        "regeneration_efficiency": 0.98,   # fraction reusable after regeneration
        "attrition_makeup_frac": 0.02,     # resin loss / cycle fraction as makeup
        "safety_factor": 1.10,
    },
    "MIX": {
        "target_ions": [
            {"element": "Mn", "suffixes": [":Mn"], "charge": 2},
            {"element": "Ni", "suffixes": [":Ni"], "charge": 2},
            {"element": "Co", "suffixes": [":Co"], "charge": 2},
        ],
        "capacity_eq_per_kg_resin": 1.8,
        "utilization": 0.65,
        "regeneration_efficiency": 0.98,
        "attrition_makeup_frac": 0.02,
        "safety_factor": 1.10,
    },
}

def ion_exchange_resin_makeup_kg_h(
    comp_abs: dict,
    rule: dict,
) -> tuple[float, float]:
    """
    Returns
    -------
    tuple[float, float]
        (m_resin_makeup_kg_h, total_loading_eq_h)
    """
    targets = rule.get("target_ions", [])
    cap = float(rule.get("capacity_eq_per_kg_resin", 1.8))
    util = float(rule.get("utilization", 0.65))
    regen = float(rule.get("regeneration_efficiency", 0.98))
    attr = float(rule.get("attrition_makeup_frac", 0.02))
    sf = float(rule.get("safety_factor", 1.10))

    if cap <= 0.0 or util <= 0.0 or regen <= 0.0:
        return 0.0, 0.0

    total_eq_h = 0.0
    for t in targets:
        elem = str(t.get("element", "")).strip()
        z = abs(float(t.get("charge", 0.0)))
        if not elem or z <= 0.0:
            continue
        m_elem = _sum_by_suffixes(comp_abs, t.get("suffixes", []))  # kg/h
        if m_elem <= 0.0:
            continue
        n_mol_h = (m_elem * 1000.0) / float(MOLAR_MASS[elem])  # mol/h
        total_eq_h += n_mol_h * z  # eq/h

    total_eq_h *= max(0.0, sf)

    # theoretically required resin throughput (loading-based)
    m_resin_theoretical = total_eq_h / (cap * util)  # kg/h resin equivalent

    # only makeup as consumption (attrition + small irreversible losses)
    m_resin_makeup = m_resin_theoretical * attr + m_resin_theoretical * (1.0 - regen)
    return max(0.0, m_resin_makeup), max(0.0, total_eq_h)

IX_STRIPPING_RULES = {
    "MIX": {
        "species": [
            {"element": "Mn", "suffixes": [":Mn"]},
            {"element": "Ni", "suffixes": [":Ni"]},
            {"element": "Co", "suffixes": [":Co"]},
        ],
        "h2so4_wtfrac_default": 0.95,
        "acid_equiv_default": 1.0,   # mol H2SO4 per mol metal (stoichiometric MSO4 route)
        "safety_factor_default": 1.1,
    },
}


def ix_stripping_h2so4_demand_kg_h(
    comp_abs: dict,
    species: list[dict],
    acid_equiv: float = 1.0,
    h2so4_wtfrac: float = 0.95,
    safety_factor: float = 1.1,
) -> dict[str, float]:
    """
    H2SO4 demand for IX stripping from metals on loaded resin.

    n_H2SO4 = n_metals * acid_equiv * safety_factor
    (MIX default: stoichiometric 1 mol H2SO4 per mol Ni/Co/Mn, SF 1.1).

    Returns:
      - n_metals_mol_h
      - n_h2so4_mol_h
      - m_h2so4_pure_kg_h
      - m_h2so4_solution_kg_h
    """
    n_metals = 0.0
    for sp in species:
        elem = str(sp.get("element", "")).strip()
        if not elem or elem not in MOLAR_MASS:
            continue
        m_elem = _sum_by_suffixes(comp_abs, sp.get("suffixes", []))
        if m_elem <= 0.0:
            continue
        n_metals += (m_elem * 1000.0) / float(MOLAR_MASS[elem])

    eq = max(0.0, float(acid_equiv))
    sf = max(0.0, float(safety_factor))
    n_h2so4 = n_metals * eq * sf

    m_h2so4_pure = (n_h2so4 * float(MOLAR_MASS["H2SO4"])) / 1000.0
    w = max(1e-9, float(h2so4_wtfrac))
    m_h2so4_solution = m_h2so4_pure / w

    return {
        "n_metals_mol_h": max(0.0, n_metals),
        "n_h2so4_mol_h": max(0.0, n_h2so4),
        "m_h2so4_pure_kg_h": max(0.0, m_h2so4_pure),
        "m_h2so4_solution_kg_h": max(0.0, m_h2so4_solution),
    }

LI_CONCENTRATION_RULES = {
    "LFP": {
        "li_suffixes": [":Li", "Li"],
        "rho_solution_kg_m3_default": 1000.0,
        "c_min_g_l_default": 3.0,
        "c_target_g_l_default": 20.0,
        "evap_component_key": "process:H2O_evap",
    },
    "MIX": {
        "li_suffixes": [":Li", "Li"],
        "rho_solution_kg_m3_default": 1000.0,
        "c_min_g_l_default": 3.0,
        "c_target_g_l_default": 20.0,
        "evap_component_key": "process:H2O_evap",
    },
        "SLAG": {
        "li_suffixes": [":Li", "Li"],
        "rho_solution_kg_m3_default": 1000.0,
        "c_min_g_l_default": 3.0,
        "c_target_g_l_default": 20.0,
        "evap_component_key": "process:H2O_evap",
    },
}

CONCENTRATION_RULES = {
    "LFP_LI": {
        "solute_suffixes": [":Li", "Li"],
        "rho_solution_kg_m3_default": 1000.0,
        "c_min_g_l_default": 3.0,
        "c_target_g_l_default": 20.0,
        "evap_component_key": "process:H2O_evap",
    },
    "SLAG_LI": {
        "solute_suffixes": [":Li", "Li"],
        "rho_solution_kg_m3_default": 1000.0,
        "c_min_g_l_default": 3.0,
        "c_target_g_l_default": 20.0,
        "evap_component_key": "process:H2O_evap",
    },
    "MIX_FE": {
        "solute_suffixes": [":Fe", "Fe"],
        "rho_solution_kg_m3_default": 1000.0,
        "c_min_g_l_default": 3.0,
        "c_target_g_l_default": 75.0,
        "evap_component_key": "process:H2O_evap",
    },
}

# FePO4-C product (Mix route: carbon dispersion → electrospinning → roasting)
FEPO4_C_PRODUCT_RULES = {
    "fe_suffixes": [":Fe", "Fe"],
    "p_suffixes": [":P", "P"],
    "carbon_wt_frac_default": 0.10,
    "pvp_in_dmf_wtfrac": 0.10,
    "dmf_loss_fraction_default": 0.10,
    "product_key": "process:FePO4_C",
    "fepo4_key": "process:FePO4",
    "carbon_key": "process:Carbon",
    "pvp_key": "process:PVP",
    "dmf_circulating_key": "process:DMF_circulating",
    "dmf_makeup_key": "process:DMF_makeup",
    "dmf_recovered_key": "process:DMF_recovered",
}


def fepo4_c_product_stoich_kg_h(
    comp_abs: dict,
    *,
    fe_suffixes: list[str] | None = None,
    p_suffixes: list[str] | None = None,
    carbon_wt_frac: float | None = None,
    dmf_loss_fraction: float | None = None,
) -> dict[str, float | str]:
    """
    Theoretical FePO4 and FePO4-C (10 wt-% C) from dissolved Fe and P in liquor.

    n_FePO4 = min(n_Fe, n_P); m_FePO4 = n * M_FePO4;
    m_FePO4_C = m_FePO4 / (1 - w_C); m_C = m_FePO4_C - m_FePO4; m_PVP = m_C;
    m_DMF_circulating = 9 * m_PVP (10 wt-% PVP in DMF); m_DMF_makeup = frac_loss * m_DMF_circulating.
    """
    rules = FEPO4_C_PRODUCT_RULES
    fe_sfx = list(fe_suffixes or rules["fe_suffixes"])
    p_sfx = list(p_suffixes or rules["p_suffixes"])
    w_c = float(
        carbon_wt_frac
        if carbon_wt_frac is not None
        else rules["carbon_wt_frac_default"]
    )
    w_c = min(max(w_c, 0.0), 0.99)
    dmf_loss = float(
        dmf_loss_fraction
        if dmf_loss_fraction is not None
        else rules["dmf_loss_fraction_default"]
    )
    dmf_loss = min(max(dmf_loss, 0.0), 1.0)

    m_fe = _sum_by_suffixes(comp_abs, fe_sfx)
    m_p = _sum_by_suffixes(comp_abs, p_sfx)
    m_fe_g = float(MOLAR_MASS["Fe"])
    m_p_g = float(MOLAR_MASS["P"])
    m_fepo4_g = float(MOLAR_MASS["FePO4"])

    if m_fe <= 0.0 or m_p <= 0.0:
        return {
            "m_fe_kg_h": max(0.0, m_fe),
            "m_p_kg_h": max(0.0, m_p),
            "n_fe_mol_h": 0.0,
            "n_p_mol_h": 0.0,
            "n_fepo4_mol_h": 0.0,
            "limiting_reactant": "-",
            "m_fepo4_kg_h": 0.0,
            "m_fepo4_c_kg_h": 0.0,
            "m_carbon_kg_h": 0.0,
            "m_pvp_kg_h": 0.0,
            "m_dmf_circulating_kg_h": 0.0,
            "m_dmf_makeup_kg_h": 0.0,
            "m_fe_used_kg_h": 0.0,
            "m_p_used_kg_h": 0.0,
        }

    n_fe = (m_fe * 1000.0) / m_fe_g
    n_p = (m_p * 1000.0) / m_p_g
    n_fepo4 = min(n_fe, n_p)
    limiting = "Fe" if n_fe <= n_p + 1e-15 else "P"

    m_fepo4 = (n_fepo4 * m_fepo4_g) / 1000.0
    m_fepo4_c = m_fepo4 / (1.0 - w_c) if w_c < 1.0 else m_fepo4
    m_carbon = max(0.0, m_fepo4_c - m_fepo4)
    m_pvp = m_carbon
    m_dmf_circ = 9.0 * m_pvp
    m_dmf_makeup = m_dmf_circ * dmf_loss
    m_fe_used = (n_fepo4 * m_fe_g) / 1000.0
    m_p_used = (n_fepo4 * m_p_g) / 1000.0

    return {
        "m_fe_kg_h": max(0.0, m_fe),
        "m_p_kg_h": max(0.0, m_p),
        "n_fe_mol_h": max(0.0, n_fe),
        "n_p_mol_h": max(0.0, n_p),
        "n_fepo4_mol_h": max(0.0, n_fepo4),
        "limiting_reactant": limiting,
        "m_fepo4_kg_h": max(0.0, m_fepo4),
        "m_fepo4_c_kg_h": max(0.0, m_fepo4_c),
        "m_carbon_kg_h": max(0.0, m_carbon),
        "m_pvp_kg_h": max(0.0, m_pvp),
        "m_dmf_circulating_kg_h": max(0.0, m_dmf_circ),
        "m_dmf_makeup_kg_h": max(0.0, m_dmf_makeup),
        "m_fe_used_kg_h": max(0.0, m_fe_used),
        "m_p_used_kg_h": max(0.0, m_p_used),
    }


def concentration_evaporation_kg_h(
    comp_abs: dict,
    m_in_kg_h: float,
    solute_suffixes: list[str],
    c_target_g_l: float,
    c_min_g_l: float = 3.0,
    rho_solution_kg_m3: float = 1000.0,
) -> dict[str, float]:
    """
    Generic concentration + evaporation helper for any dissolved solute.

    Returns keys:
      - m_solute_kg_h
      - v_in_m3_h
      - c_current_g_l
      - v_target_m3_h
      - m_water_evap_kg_h
      - c_new_g_l
    """
    m_in = max(0.0, float(m_in_kg_h))
    rho = float(rho_solution_kg_m3)
    c_target = float(c_target_g_l)
    c_min = float(c_min_g_l)

    if m_in <= 0.0 or rho <= 0.0:
        return {
            "m_solute_kg_h": 0.0,
            "v_in_m3_h": 0.0,
            "c_current_g_l": 0.0,
            "v_target_m3_h": 0.0,
            "m_water_evap_kg_h": 0.0,
            "c_new_g_l": 0.0,
        }

    m_solute = _sum_by_suffixes(comp_abs, solute_suffixes)
    v_in = m_in / rho
    c_current = (m_solute / v_in) if v_in > 0.0 else 0.0

    v_target = v_in
    m_evap = 0.0
    c_new = c_current

    if m_solute > 0.0 and v_in > 0.0 and c_target > 0.0 and c_current >= c_min and c_current < c_target:
        # numerically g/L == kg/m3
        v_target = m_solute / c_target if c_target > 0.0 else v_in
        if v_target < v_in:
            v_evap = v_in - v_target
            m_evap = v_evap * rho
            c_new = (m_solute / v_target) if v_target > 0.0 else c_current

    return {
        "m_solute_kg_h": max(0.0, m_solute),
        "v_in_m3_h": max(0.0, v_in),
        "c_current_g_l": max(0.0, c_current),
        "v_target_m3_h": max(0.0, v_target),
        "m_water_evap_kg_h": max(0.0, m_evap),
        "c_new_g_l": max(0.0, c_new),
    }

LIH2PO4_CRYSTALLIZATION_RULES = {
    "LFP": {
        "li_suffixes": ["Cathode:Li", ":Li", "Li"],
        "p_suffixes": ["Cathode:P", ":P", "P"],
        "li_component_key": "Cathode:Li",
        "p_component_key": "Cathode:P",
        "product_key": "process:LiH2PO4",
        "li_recovery_default": 1.0,
        "p_recovery_default": 1.0,
    },
}

def lih2po4_crystallization_stoich_kg_h(
    comp_abs: dict,
    li_suffixes: list[str],
    p_suffixes: list[str],
    li_recovery: float = 1.0,
    p_recovery: float = 1.0,
) -> dict[str, float]:
    """
    Stoichiometric LiH2PO4 formation from Li and P (1:1 mol Li:P).

    Returns keys:
      - m_lih2po4_kg_h
      - m_li_used_kg_h
      - m_p_used_kg_h
      - n_product_mol_h
    """
    m_li = _sum_by_suffixes(comp_abs, li_suffixes)
    m_p = _sum_by_suffixes(comp_abs, p_suffixes)

    eta_li = max(0.0, float(li_recovery))
    eta_p = max(0.0, float(p_recovery))

    m_li_eff = m_li * eta_li
    m_p_eff = m_p * eta_p
    if m_li_eff <= 0.0 or m_p_eff <= 0.0:
        return {
            "m_lih2po4_kg_h": 0.0,
            "m_li_used_kg_h": 0.0,
            "m_p_used_kg_h": 0.0,
            "n_product_mol_h": 0.0,
        }

    n_li = (m_li_eff * 1000.0) / MOLAR_MASS["Li"]
    n_p = (m_p_eff * 1000.0) / MOLAR_MASS["P"]
    n_prod = min(n_li, n_p)

    m_prod = (n_prod * MOLAR_MASS["LiH2PO4"]) / 1000.0
    m_li_used = (n_prod * MOLAR_MASS["Li"]) / 1000.0
    m_p_used = (n_prod * MOLAR_MASS["P"]) / 1000.0

    return {
        "m_lih2po4_kg_h": max(0.0, m_prod),
        "m_li_used_kg_h": max(0.0, m_li_used),
        "m_p_used_kg_h": max(0.0, m_p_used),
        "n_product_mol_h": max(0.0, n_prod),
    }
LI2CO3_PRECIPITATION_RULES = {
    "NMC": {
        "li_suffixes": ["Cathode:Li", ":Li", "Li"],
        "li_component_key": "Cathode:Li",
        "product_key": "process:Li2CO3",
        "na2co3_key": "process:Na2CO3",
        "na2so4_key": "process:Na2SO4",
        "li_recovery_default": 1.0,
        "na2co3_purity_default": 1.0,
        "na2co3_excess_default": 1.0,
    },
    "MIX": {
        "li_suffixes": ["Cathode:Li", ":Li", "Li"],
        "li_component_key": "Cathode:Li",
        "product_key": "process:Li2CO3",
        "na2co3_key": "process:Na2CO3",
        "na2so4_key": "process:Na2SO4",
        "li_recovery_default": 1.0,
        "na2co3_purity_default": 1.0,
        "na2co3_excess_default": 1.0,
    },
    "SLAG": {
        "li_suffixes": ["Cathode:Li", "Li"],
        "li_component_key": "Cathode:Li",
        "product_key": "process:Li2CO3",
        "na2co3_key": "process:Na2CO3",
        "na2so4_key": "process:Na2SO4",
        "li_recovery_default": 1.0,
        "na2co3_purity_default": 1.0,
        "na2co3_excess_default": 1.0,
    },
}


def li2co3_precipitation_stoich_kg_h(
    comp_abs: dict,
    li_suffixes: list[str],
    li_recovery: float = 1.0,
    na2co3_purity: float = 1.0,
    na2co3_excess: float = 1.0,
) -> dict[str, float]:
    """
    Li precipitation in sulfate liquor (analog to slag):
      Li2SO4 + Na2CO3 -> Li2CO3 + Na2SO4

    Returns:
      - m_li2co3_kg_h
      - m_na2co3_pure_kg_h
      - m_na2co3_added_kg_h
      - m_na2so4_kg_h
      - m_li_used_kg_h
      - n_li2co3_mol_h
    """
    m_li = _sum_by_suffixes(comp_abs, li_suffixes)
    eta_li = max(0.0, float(li_recovery))
    m_li_eff = m_li * eta_li

    if m_li_eff <= 0.0:
        return {
            "m_li2co3_kg_h": 0.0,
            "m_na2co3_pure_kg_h": 0.0,
            "m_na2co3_added_kg_h": 0.0,
            "m_na2so4_kg_h": 0.0,
            "m_li_used_kg_h": 0.0,
            "n_li2co3_mol_h": 0.0,
        }

    # 2 Li -> 1 Li2CO3
    n_li = (m_li_eff * 1000.0) / float(MOLAR_MASS["Li"])
    n_li2co3 = n_li / 2.0

    m_li2co3 = (n_li2co3 * float(MOLAR_MASS["Li2CO3"])) / 1000.0
    m_li_used = (2.0 * n_li2co3 * float(MOLAR_MASS["Li"])) / 1000.0

    # 1 mol Na2CO3 per mol Li2CO3
    m_na2co3_pure = (n_li2co3 * float(MOLAR_MASS["Na2CO3"])) / 1000.0
    purity = max(1e-9, float(na2co3_purity))
    excess = max(1.0, float(na2co3_excess))
    m_na2co3_added = (m_na2co3_pure * excess) / purity

    # 1 mol Na2SO4 formed per mol Li2CO3
    m_na2so4 = (n_li2co3 * float(MOLAR_MASS["Na2SO4"])) / 1000.0

    return {
        "m_li2co3_kg_h": max(0.0, m_li2co3),
        "m_na2co3_pure_kg_h": max(0.0, m_na2co3_pure),
        "m_na2co3_added_kg_h": max(0.0, m_na2co3_added),
        "m_na2so4_kg_h": max(0.0, m_na2so4),
        "m_li_used_kg_h": max(0.0, m_li_used),
        "n_li2co3_mol_h": max(0.0, n_li2co3),
    }

NMC_PRECURSOR_RULES = {
    "811": {"ni": 8.0, "co": 1.0, "mn": 1.0},
    "622": {"ni": 6.0, "co": 2.0, "mn": 2.0},
    "532": {"ni": 5.0, "co": 3.0, "mn": 2.0},
    "111": {"ni": 1.0, "co": 1.0, "mn": 1.0},
}

def nmc_sulfate_makeup_naoh_solution_kg_h(
    m_niso4_makeup_kg_h: float = 0.0,
    m_coso4_makeup_kg_h: float = 0.0,
    m_mnso4_makeup_kg_h: float = 0.0,
    naoh_solution_wtfrac: float = 0.5,
) -> dict[str, float]:
    """
    NaOH demand to neutralize NiSO4 / CoSO4 / MnSO4 makeup salts:
      MSO4 + 2 NaOH -> Na2SO4 + M(OH)2   (2 mol NaOH per mol sulfate)

    Returns 50 wt-% NaOH solution mass flow [kg/h] and mol bookkeeping.
    """
    mm_niso4 = float(MOLAR_MASS["NiSO4"])
    mm_coso4 = float(MOLAR_MASS["CoSO4"])
    mm_mnso4 = float(MOLAR_MASS["MnSO4"])

    n_so4 = 0.0
    if m_niso4_makeup_kg_h > 0.0:
        n_so4 += (float(m_niso4_makeup_kg_h) * 1000.0) / mm_niso4
    if m_coso4_makeup_kg_h > 0.0:
        n_so4 += (float(m_coso4_makeup_kg_h) * 1000.0) / mm_coso4
    if m_mnso4_makeup_kg_h > 0.0:
        n_so4 += (float(m_mnso4_makeup_kg_h) * 1000.0) / mm_mnso4

    n_naoh = 2.0 * n_so4
    m_naoh_pure = (n_naoh * float(MOLAR_MASS["NaOH"])) / 1000.0
    m_na2so4 = (n_so4 * float(MOLAR_MASS["Na2SO4"])) / 1000.0
    w = max(1e-9, float(naoh_solution_wtfrac))
    m_naoh_solution = m_naoh_pure / w if m_naoh_pure > 0.0 else 0.0

    return {
        "m_naoh_solution_kg_h": max(0.0, m_naoh_solution),
        "m_naoh_pure_kg_h": max(0.0, m_naoh_pure),
        "m_na2so4_kg_h": max(0.0, m_na2so4),
        "n_so4_from_makeup_mol_h": max(0.0, n_so4),
        "n_naoh_for_so4_mol_h": max(0.0, n_naoh),
    }


def nmc_hydroxide_precipitation_stoich_kg_h(
    comp_abs: dict,
    nmc_code: str = "811",
    naoh_solution_wtfrac: float = 0.5,
    product_key: str = "process:NixCoyMnz(OH)2",
    naoh_key: str = "process:NaOH_50",
    m_niso4_makeup_kg_h: float = 0.0,
    m_coso4_makeup_kg_h: float = 0.0,
    m_mnso4_makeup_kg_h: float = 0.0,
    *,
    apply_target_cap: bool = True,
    target_basis: str = "min",
    max_makeup_fill_fraction: float = 1.0,
    precip_target_mol_h: float | None = None,
    include_base_naoh: bool = True,
    nh3_coordination_number: float = 6.0,
    nh3_loss_fraction: float = 0.10,
    nh3_solution_wtfrac: float = 0.25,
) -> dict[str, float | str]:
    """
    Stoichiometric NMC hydroxide precipitation from Ni/Co/Mn and NaOH demand.

    Mixed-metal product: NixCoyMnz(OH)2 (M = NixCoyMnz at fractions from ``nmc_code``).
    Step 9 (mixing) doses base NaOH via ``nmc_mixing_naoh_demand_kg_h`` only.
    Step 10 (precipitation) runs this with ``include_base_naoh=False`` plus sulfate NaOH.

    Supports additional NaOH demand for added sulfate make-up salts:
      MSO4 + 2 NaOH -> Na2SO4 + M(OH)2

    Sodium sulfate in the mother liquor: 1 mol Na2SO4 per mol precursor formed
    (all metals precipitated from sulfate liquor or sulfate makeup).

    If ``apply_target_cap`` is True (default), precursor mol/h is
    ``min(physical_cap, n_target_final)`` where ``n_target_final`` matches
    ``nmc_precip_reagent_demand_kg_h`` (same ``target_basis`` / makeup fill cap).

    Returns keys:
      - m_nmc_solid_kg_h
      - m_naoh_solution_kg_h
      - m_naoh_solution_base_kg_h
      - m_naoh_solution_extra_from_makeup_kg_h
      - m_ni_used_kg_h
      - m_co_used_kg_h
      - m_mn_used_kg_h
      - n_nmc_mol_h, n_nmc_physical_cap_mol_h, n_nmc_target_cap_mol_h
      - anchor_used (str)
      - m_ni_residual_kg_h, m_co_residual_kg_h, m_mn_residual_kg_h
      - m_na2so4_kg_h, n_na2so4_mol_h
    """
    _zero: dict[str, float | str] = {
        "m_nmc_solid_kg_h": 0.0,
        "m_naoh_solution_kg_h": 0.0,
        "m_naoh_solution_base_kg_h": 0.0,
        "m_naoh_solution_extra_from_makeup_kg_h": 0.0,
        "m_ni_used_kg_h": 0.0,
        "m_co_used_kg_h": 0.0,
        "m_mn_used_kg_h": 0.0,
        "n_nmc_mol_h": 0.0,
        "n_nmc_physical_cap_mol_h": 0.0,
        "n_nmc_target_cap_mol_h": 0.0,
        "anchor_used": "-",
        "m_ni_residual_kg_h": 0.0,
        "m_co_residual_kg_h": 0.0,
        "m_mn_residual_kg_h": 0.0,
        "m_na2so4_kg_h": 0.0,
        "n_na2so4_mol_h": 0.0,
    }

    ratios = NMC_PRECURSOR_RULES.get(str(nmc_code), NMC_PRECURSOR_RULES["111"])
    r_ni, r_co, r_mn = float(ratios["ni"]), float(ratios["co"]), float(ratios["mn"])
    s = r_ni + r_co + r_mn
    f_ni, f_co, f_mn = r_ni / s, r_co / s, r_mn / s

    m_ni = _sum_by_suffixes(comp_abs, [":Ni", "Ni"])
    m_co = _sum_by_suffixes(comp_abs, [":Co", "Co"])
    m_mn = _sum_by_suffixes(comp_abs, [":Mn", "Mn"])

    if m_ni <= 0.0 and m_co <= 0.0 and m_mn <= 0.0:
        return dict(_zero)

    n_ni = (m_ni * 1000.0) / float(MOLAR_MASS["Ni"]) if m_ni > 0.0 else 0.0
    n_co = (m_co * 1000.0) / float(MOLAR_MASS["Co"]) if m_co > 0.0 else 0.0
    n_mn = (m_mn * 1000.0) / float(MOLAR_MASS["Mn"]) if m_mn > 0.0 else 0.0

    cand = []
    if f_ni > 0 and n_ni > 0:
        cand.append(n_ni / f_ni)
    if f_co > 0 and n_co > 0:
        cand.append(n_co / f_co)
    if f_mn > 0 and n_mn > 0:
        cand.append(n_mn / f_mn)
    if not cand:
        return dict(_zero)

    n_physical = min(cand)
    n_target_cap = n_physical
    anchor_used: str = "min"

    if apply_target_cap:
        # Nominal target (no virtual sulfate): NaOH / NH3 basis at mixing uses this rate.
        reag_nom = nmc_precip_reagent_demand_kg_h(
            comp_abs=comp_abs,
            nmc_code=nmc_code,
            nh3_coordination_number=float(nh3_coordination_number),
            nh3_loss_fraction=float(nh3_loss_fraction),
            nh3_solution_wtfrac=float(nh3_solution_wtfrac),
            target_basis=str(target_basis),
            max_makeup_fill_fraction=0.0,
        )
        n_nominal = float(reag_nom.get("n_target_nominal_mol_h", 0.0) or 0.0)
        n_target_cap = min(n_physical, n_nominal)
        anchor_used = str(reag_nom.get("anchor_used", "-"))
        reag_extra = reag_nom
    else:
        n_nominal = float(n_physical)
        n_target_cap = float(n_physical)
        reag_extra = {}

    if precip_target_mol_h is not None and float(precip_target_mol_h) > 0.0:
        n_target_cap = min(float(n_target_cap), float(precip_target_mol_h))

    n_nmc = min(n_physical, max(0.0, n_target_cap))

    n_ni_used, n_co_used, n_mn_used = n_nmc * f_ni, n_nmc * f_co, n_nmc * f_mn
    m_ni_used = (n_ni_used * float(MOLAR_MASS["Ni"])) / 1000.0
    m_co_used = (n_co_used * float(MOLAR_MASS["Co"])) / 1000.0
    m_mn_used = (n_mn_used * float(MOLAR_MASS["Mn"])) / 1000.0

    m_ni_residual = max(0.0, float(m_ni) - m_ni_used)
    m_co_residual = max(0.0, float(m_co) - m_co_used)
    m_mn_residual = max(0.0, float(m_mn) - m_mn_used)

    # M(Ni_xCo_yMn_z(OH)2) = M_avg + 2*OH
    m_oh = 17.007
    m_m_avg = (
        f_ni * float(MOLAR_MASS["Ni"])
        + f_co * float(MOLAR_MASS["Co"])
        + f_mn * float(MOLAR_MASS["Mn"])
    )
    n_nmc_mol_h = float(n_nmc)
    m_nmc_solid = (n_nmc * (m_m_avg + 2.0 * m_oh)) / 1000.0

    # Base NaOH (mixing): 2 mol NaOH / mol planned precursor. Skipped at precipitation if already dosed.
    if include_base_naoh:
        n_naoh_basis = float(n_nominal) if apply_target_cap else float(n_nmc)
        n_naoh_base = 2.0 * n_naoh_basis
        m_naoh_pure_base = (n_naoh_base * float(MOLAR_MASS["NaOH"])) / 1000.0
    else:
        m_naoh_pure_base = 0.0

    naoh_so4 = nmc_sulfate_makeup_naoh_solution_kg_h(
        m_niso4_makeup_kg_h=m_niso4_makeup_kg_h,
        m_coso4_makeup_kg_h=m_coso4_makeup_kg_h,
        m_mnso4_makeup_kg_h=m_mnso4_makeup_kg_h,
        naoh_solution_wtfrac=naoh_solution_wtfrac,
    )
    m_naoh_solution_extra = float(naoh_so4["m_naoh_solution_kg_h"])

    w = max(1e-9, float(naoh_solution_wtfrac))
    m_naoh_solution_base = m_naoh_pure_base / w
    m_naoh_solution_total = m_naoh_solution_base + m_naoh_solution_extra

    n_na2so4 = float(n_nmc_mol_h)
    m_na2so4 = (n_na2so4 * float(MOLAR_MASS["Na2SO4"])) / 1000.0

    return {
        "m_nmc_solid_kg_h": max(0.0, m_nmc_solid),
        "m_naoh_solution_kg_h": max(0.0, m_naoh_solution_total),
        "m_naoh_solution_base_kg_h": max(0.0, m_naoh_solution_base),
        "m_naoh_solution_extra_from_makeup_kg_h": max(0.0, m_naoh_solution_extra),
        "m_ni_used_kg_h": max(0.0, m_ni_used),
        "m_co_used_kg_h": max(0.0, m_co_used),
        "m_mn_used_kg_h": max(0.0, m_mn_used),
        "n_nmc_mol_h": max(0.0, n_nmc_mol_h),
        "n_nmc_physical_cap_mol_h": max(0.0, float(n_physical)),
        "n_nmc_target_cap_mol_h": max(0.0, float(n_target_cap)),
        "n_nmc_target_nominal_mol_h": max(0.0, float(n_nominal if apply_target_cap else n_physical)),
        "m_nh3_solution_target_kg_h": max(
            0.0, float(reag_extra.get("m_nh3_solution_makeup_kg_h", 0.0) or 0.0) if apply_target_cap else 0.0
        ),
        "anchor_used": anchor_used,
        "max_makeup_fill_fraction": float(reag_extra.get("max_makeup_fill_fraction", 1.0) or 1.0),
        "makeup_fill_scale_applied": float(reag_extra.get("makeup_fill_scale_applied", 1.0) or 1.0),
        "m_ni_residual_kg_h": m_ni_residual,
        "m_co_residual_kg_h": m_co_residual,
        "m_mn_residual_kg_h": m_mn_residual,
        "m_na2so4_kg_h": max(0.0, m_na2so4),
        "n_na2so4_mol_h": max(0.0, n_na2so4),
    }


def nmc_target_fractions(nmc_code: str) -> tuple[float, float, float]:
    ratios = NMC_PRECURSOR_RULES.get(str(nmc_code), NMC_PRECURSOR_RULES["111"])
    r_ni = float(ratios["ni"])
    r_co = float(ratios["co"])
    r_mn = float(ratios["mn"])
    s = r_ni + r_co + r_mn
    if s <= 0.0:
        return 1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0
    return r_ni / s, r_co / s, r_mn / s


def nmc_plan_target_rates_mol_h(
    comp_abs: dict,
    nmc_code: str = "811",
    target_basis: str = "min",
    max_makeup_fill_fraction: float = 0.0,
) -> dict[str, float | str]:
    """
    Target precursor rates [mol/h] for NMC mixing vs. precipitation.

    - ``n_physical``: max rate from dissolved Ni/Co/Mn in lye (limiting metal / min cap).
    - ``n_nominal``: recipe target from ``target_basis`` (min | ni | co | mn anchor).
    - ``n_naoh_basis``: 2 mol NaOH / mol precursor at mixing — planned hydroxide stoichiometry.
      * ``min`` anchor, no sulfate fill: limiting in-situ cap.
      * Metal anchor, no fill: anchor cap (nominal).
      * With deficit fill (capped / unlimited): in-situ + fill × (nominal − in-situ).
    """
    ca = comp_abs or {}
    f_ni, f_co, f_mn = nmc_target_fractions(nmc_code)

    m_ni = _sum_by_suffixes(ca, [":Ni", "Ni"])
    m_co = _sum_by_suffixes(ca, [":Co", "Co"])
    m_mn = _sum_by_suffixes(ca, [":Mn", "Mn"])

    n_ni = (m_ni * 1000.0) / float(MOLAR_MASS["Ni"]) if m_ni > 0.0 else 0.0
    n_co = (m_co * 1000.0) / float(MOLAR_MASS["Co"]) if m_co > 0.0 else 0.0
    n_mn = (m_mn * 1000.0) / float(MOLAR_MASS["Mn"]) if m_mn > 0.0 else 0.0

    caps = []
    if f_ni > 0 and n_ni > 0:
        caps.append(n_ni / f_ni)
    if f_co > 0 and n_co > 0:
        caps.append(n_co / f_co)
    if f_mn > 0 and n_mn > 0:
        caps.append(n_mn / f_mn)
    n_physical = min(caps) if caps else 0.0

    basis = str(target_basis or "min").strip().lower()
    reag_nom = nmc_precip_reagent_demand_kg_h(
        comp_abs=ca,
        nmc_code=nmc_code,
        target_basis=basis,
        max_makeup_fill_fraction=0.0,
    )
    n_nominal = float(reag_nom.get("n_target_nominal_mol_h", 0.0) or 0.0)
    anchor_used = str(reag_nom.get("anchor_used", "min"))

    s_fill = min(1.0, max(0.0, float(max_makeup_fill_fraction)))
    if s_fill <= 0.0:
        if basis == "min":
            n_naoh_basis = float(n_physical)
        else:
            n_naoh_basis = float(n_nominal)
    else:
        n_naoh_basis = float(n_physical) + s_fill * max(0.0, float(n_nominal) - float(n_physical))

    return {
        "anchor_used": anchor_used,
        "n_physical_mol_h": max(0.0, float(n_physical)),
        "n_nominal_mol_h": max(0.0, float(n_nominal)),
        "n_naoh_basis_mol_h": max(0.0, float(n_naoh_basis)),
        "max_makeup_fill_fraction": s_fill,
    }


def nmc_mixing_naoh_demand_kg_h(
    comp_abs: dict,
    nmc_code: str = "811",
    target_basis: str = "min",
    max_makeup_fill_fraction: float = 0.0,
    naoh_solution_wtfrac: float = 0.5,
) -> dict[str, float | str]:
    """NaOH solution demand for step 9 (mixing): 2 mol NaOH per mol ``n_naoh_basis``."""
    plan = nmc_plan_target_rates_mol_h(
        comp_abs=comp_abs,
        nmc_code=nmc_code,
        target_basis=target_basis,
        max_makeup_fill_fraction=max_makeup_fill_fraction,
    )
    n_basis = float(plan["n_naoh_basis_mol_h"])
    m_naoh_pure = (2.0 * n_basis * float(MOLAR_MASS["NaOH"])) / 1000.0
    w = max(1e-9, float(naoh_solution_wtfrac))
    m_naoh_solution = m_naoh_pure / w if m_naoh_pure > 0.0 else 0.0
    return {
        **plan,
        "m_naoh_solution_kg_h": max(0.0, m_naoh_solution),
        "m_naoh_pure_kg_h": max(0.0, m_naoh_pure),
    }


def nmc_precip_reagent_demand_kg_h(
    comp_abs: dict,
    nmc_code: str = "811",
    nh3_coordination_number: float = 6.0,
    nh3_loss_fraction: float = 0.10,
    nh3_solution_wtfrac: float = 0.25,
    target_basis: str = "min",   # "min" | "ni" | "co" | "mn"
    max_makeup_fill_fraction: float = 1.0,
    cap_precursor_mol_h: float | None = None,
    nominal_target_mol_h: float | None = None,
) -> dict[str, float | str]:
    """
    Reagent demand for NMC precipitation preparation (Step 10 concept).

    Patent / process notation: M = NixCoyMnz (mixed transition metal for the target
    precursor recipe ``nmc_code``). Solid product in the mass balance is
    NixCoyMnz(OH)2.

    Ammonia (circulation + makeup only):
      M2+ + n NH3 -> [M(NH3)n]2+          (complexation)
      [M(NH3)n]2+ + 2OH- -> M(OH)2 + n NH3 (released on hydroxide precipitation)

    Implementation: M is not a separate species in ``comp_abs``; Ni, Co, and Mn in
    the lye are tracked individually at recipe fractions f_Ni, f_Co, f_Mn (sum = 1).
    For normalized fractions, n_Ni,target + n_Co,target + n_Mn,target equals the
    target precursor molar flow n_target (one NixCoyMnz formula unit per mol/h).

    NH3 circulation = nh3_coordination_number * n_metals_target; reported demand is
    makeup only (circulation * nh3_loss_fraction), as net NH3 is returned on precipitation.

    Sulfate makeup closes metal deficits vs. the nominal target (``target_basis``)
    by at most ``max_makeup_fill_fraction`` (0–1).

    When ``nominal_target_mol_h`` and ``cap_precursor_mol_h`` (step-9 effective precursor
    mol/h) are both set and fill > 0, deficits are based on the incremental gap
    ``nominal − step9`` at recipe fractions, minus metals still in the lye (step 10).
    Anchor metals (e.g. Co for ``co`` basis) are not purchased as sulfate.

    If ``max_makeup_fill_fraction`` is 0, ``n_target_final`` is capped by in-situ metals
    and optionally ``cap_precursor_mol_h``. Nominal stays at the anchor for mixing NaOH/NH3.
    """
    ca = comp_abs or {}

    # available dissolved metals [kg/h] -> [mol/h]
    m_ni = _sum_by_suffixes(ca, [":Ni", "Ni"])
    m_co = _sum_by_suffixes(ca, [":Co", "Co"])
    m_mn = _sum_by_suffixes(ca, [":Mn", "Mn"])

    n_ni = (m_ni * 1000.0) / float(MOLAR_MASS["Ni"]) if m_ni > 0.0 else 0.0
    n_co = (m_co * 1000.0) / float(MOLAR_MASS["Co"]) if m_co > 0.0 else 0.0
    n_mn = (m_mn * 1000.0) / float(MOLAR_MASS["Mn"]) if m_mn > 0.0 else 0.0

    f_ni, f_co, f_mn = nmc_target_fractions(nmc_code)

    # precursor capacity per metal for target recipe
    cap_ni = (n_ni / f_ni) if (f_ni > 0 and n_ni > 0) else 0.0
    cap_co = (n_co / f_co) if (f_co > 0 and n_co > 0) else 0.0
    cap_mn = (n_mn / f_mn) if (f_mn > 0 and n_mn > 0) else 0.0

    caps = {"ni": cap_ni, "co": cap_co, "mn": cap_mn}

    # choose anchor / basis
    basis = str(target_basis or "min").strip().lower()
    if basis == "min":
        positive_caps = [c for c in caps.values() if c > 0.0]
        n_target_base = min(positive_caps) if positive_caps else 0.0
        anchor_used = "min"
    elif basis in ("ni", "co", "mn"):
        n_target_base = caps.get(basis, 0.0)
        anchor_used = basis
    else:
        positive_caps = [c for c in caps.values() if c > 0.0]
        n_target_base = min(positive_caps) if positive_caps else 0.0
        anchor_used = "min"

    n_target_nominal = max(0.0, float(n_target_base))
    if nominal_target_mol_h is not None and float(nominal_target_mol_h) > 0.0:
        n_target_nominal = max(0.0, float(nominal_target_mol_h))

    s_fill = min(1.0, max(0.0, float(max_makeup_fill_fraction)))

    step9_eff = (
        float(cap_precursor_mol_h)
        if cap_precursor_mol_h is not None and float(cap_precursor_mol_h) > 0.0
        else None
    )
    use_step9_incremental = (
        s_fill > 0.0
        and step9_eff is not None
        and float(step9_eff) > 0.0
        and nominal_target_mol_h is not None
        and float(nominal_target_mol_h) > 0.0
    )

    # Sulfate deficits vs. full nominal recipe (lye metals are not reduced until step 10).
    d_ni_full = max(0.0, n_target_nominal * f_ni - n_ni)
    d_co_full = max(0.0, n_target_nominal * f_co - n_co)
    d_mn_full = max(0.0, n_target_nominal * f_mn - n_mn)
    n_incr = max(0.0, n_target_nominal - float(step9_eff)) if use_step9_incremental else 0.0

    mm_niso4 = float(MOLAR_MASS["NiSO4"])
    mm_coso4 = float(MOLAR_MASS["CoSO4"])
    mm_mnso4 = float(MOLAR_MASS["MnSO4"])

    dn_ni = s_fill * d_ni_full
    dn_co = s_fill * d_co_full
    dn_mn = s_fill * d_mn_full

    # Anchor metal is not purchased as sulfate (target is defined by its in-situ availability).
    if basis == "ni":
        dn_ni = 0.0
    elif basis == "co":
        dn_co = 0.0
    elif basis == "mn":
        dn_mn = 0.0

    n_ni_eff = n_ni + dn_ni
    n_co_eff = n_co + dn_co
    n_mn_eff = n_mn + dn_mn

    if use_step9_incremental:
        incr_achieved = n_incr
        if f_ni > 0.0:
            if dn_ni > 0.0:
                incr_achieved = min(incr_achieved, dn_ni / f_ni)
            elif basis == "ni":
                incr_achieved = min(incr_achieved, n_ni / f_ni)
        if f_co > 0.0:
            if dn_co > 0.0:
                incr_achieved = min(incr_achieved, dn_co / f_co)
            elif basis == "co":
                incr_achieved = min(incr_achieved, n_co / f_co)
        if f_mn > 0.0:
            if dn_mn > 0.0:
                incr_achieved = min(incr_achieved, dn_mn / f_mn)
            elif basis == "mn":
                incr_achieved = min(incr_achieved, n_mn / f_mn)
        n_target = min(n_target_nominal, float(step9_eff) + max(0.0, incr_achieved))
    else:
        caps_eff = []
        if f_ni > 0 and n_ni_eff > 0:
            caps_eff.append(n_ni_eff / f_ni)
        if f_co > 0 and n_co_eff > 0:
            caps_eff.append(n_co_eff / f_co)
        if f_mn > 0 and n_mn_eff > 0:
            caps_eff.append(n_mn_eff / f_mn)
        n_target = min(caps_eff) if caps_eff else 0.0

        caps_physical = []
        if f_ni > 0 and n_ni > 0:
            caps_physical.append(n_ni / f_ni)
        if f_co > 0 and n_co > 0:
            caps_physical.append(n_co / f_co)
        if f_mn > 0 and n_mn > 0:
            caps_physical.append(n_mn / f_mn)
        n_physical = min(caps_physical) if caps_physical else 0.0

        if s_fill <= 0.0:
            n_target = min(n_target, n_physical)
            if step9_eff is not None:
                n_target = min(n_target, step9_eff)
            # Keep anchor nominal (e.g. Co cap) for NaOH/NH3 basis at mixing.

    n_ni_target = n_target * f_ni
    n_co_target = n_target * f_co
    n_mn_target = n_target * f_mn

    m_niso4 = (dn_ni * mm_niso4) / 1000.0
    m_coso4 = (dn_co * mm_coso4) / 1000.0
    m_mnso4 = (dn_mn * mm_mnso4) / 1000.0
    # NH3 makeup (M = NixCoyMnz): n_metals_target = n_target when f_Ni+f_Co+f_Mn = 1
    n_metals_target = n_ni_target + n_co_target + n_mn_target
    n_nh3_circulation = max(0.0, float(nh3_coordination_number)) * n_metals_target
    n_nh3_makeup = n_nh3_circulation * max(0.0, float(nh3_loss_fraction))

    m_nh3_pure = (n_nh3_makeup * float(MOLAR_MASS["NH3"])) / 1000.0
    w = max(1e-9, float(nh3_solution_wtfrac))
    m_nh3_solution = m_nh3_pure / w if m_nh3_pure > 0.0 else 0.0

    return {
        "anchor_used": anchor_used,
        "n_target_nominal_mol_h": max(0.0, n_target_nominal),
        "n_target_final_mol_h": max(0.0, n_target),
        "max_makeup_fill_fraction": min(1.0, max(0.0, float(max_makeup_fill_fraction))),
        "makeup_fill_scale_applied": s_fill,
        "n_deficit_ni_full_mol_h": max(0.0, d_ni_full),
        "n_deficit_co_full_mol_h": max(0.0, d_co_full),
        "n_deficit_mn_full_mol_h": max(0.0, d_mn_full),
        "n_deficit_ni_filled_mol_h": max(0.0, dn_ni),
        "n_deficit_co_filled_mol_h": max(0.0, dn_co),
        "n_deficit_mn_filled_mol_h": max(0.0, dn_mn),

        "m_niso4_makeup_kg_h": max(0.0, m_niso4),
        "m_coso4_makeup_kg_h": max(0.0, m_coso4),
        "m_mnso4_makeup_kg_h": max(0.0, m_mnso4),

        "m_nh3_pure_makeup_kg_h": max(0.0, m_nh3_pure),
        "m_nh3_solution_makeup_kg_h": max(0.0, m_nh3_solution),

        "m_ni_present_kg_h": max(0.0, m_ni),
        "m_co_present_kg_h": max(0.0, m_co),
        "m_mn_present_kg_h": max(0.0, m_mn),
    }