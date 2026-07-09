from __future__ import annotations

import machine as Eq
import Recycling_Efficiencies as rfx
from Massflow import MassFlow, assert_mass_balance
from thermal_energy import (
    crystallization_water_evaporation_kwh_h,
    hydrate_water_in_crystal_kg_h,
    water_removed_for_thermal_kg_h,
)
from step_utils import (
    hours_per_year,
    make_row,
    size_machine_for_mass,
    capex_breakdown_df,
    attach_opex_to_row,
)

# Molar masses [g/mol]
M_MN = 54.938
M_MNSO4_H2O = 169.02  # MnSO4·H2O (≈ 54.94 + 32.07 + 64.00 + 18.02)


def _rebalance_comp_abs_to_mass(comp_abs: dict, m_target_kg_h: float) -> None:
    """
    Scale non-crystal components so sum(comp_abs) == m_target (in-place).

    After replacing elemental ``:Mn`` with ``process:MnSO4*H2O`` at full monohydrate
    mass, the tagged sum exceeds the physical strip-out mass unless bulk components
    (water, acid, etc.) are reduced accordingly — no separate water feed.
    """
    target = float(m_target_kg_h)
    crystal_key = _resolve_crystal_comp_key(comp_abs)

    def _total() -> float:
        return float(sum(float(v or 0.0) for v in comp_abs.values()))

    s = _total()
    diff = target - s
    if abs(diff) < 1e-12:
        return

    # Pool = everything except the crystal tag we just sized for the partition
    pool_keys = [k for k in comp_abs if str(k) != crystal_key]
    pool_mass = float(sum(float(comp_abs.get(k) or 0.0) for k in pool_keys))
    if pool_mass <= 1e-15:
        raise ValueError(
            "Mn crystallization rebook: no non-crystal mass pool to absorb "
            f"tagging delta ({diff:.6g} kg/h vs target {target:.6g})."
        )
    if pool_mass + diff < -1e-9:
        raise ValueError(
            "Mn crystallization rebook: pool too small for sulfate/hydrate bookkeeping "
            f"(pool {pool_mass:.6g} kg/h, need {diff:.6g} kg/h)."
        )
    scale = (pool_mass + diff) / pool_mass
    if scale < 0.0:
        raise ValueError(f"Mn crystallization rebook: negative scale {scale}.")

    for k in pool_keys:
        comp_abs[k] = float(comp_abs.get(k) or 0.0) * scale


def _resolve_crystal_comp_key(comp_abs: dict) -> str:
    for k in comp_abs:
        if str(k).lower() == "process:mnso4*h2o":
            return str(k)
    return "process:MnSO4*H2O"


def _mnso4_h2o_from_solution(flow_in: MassFlow) -> tuple[float, float]:
    """
    Convert dissolved manganese in the inlet stream to mass flows of MnSO4·H2O and Mn [kg/h].

    Assumes all dissolved Mn is assigned to monohydrate formation for this step.
    The mass ratio follows M(MnSO4·H2O) / M(Mn).

    Returns
    -------
    tuple[float, float]
        (m_MnSO4_H2O_kg_h, m_Mn_kg_h)
    """
    comp_abs = dict(getattr(flow_in, "meta", {}).get("comp_abs") or {})

    m_mn = 0.0
    for k, v in comp_abs.items():
        ks = str(k)
        if ks.endswith(":Mn") or ks == "Mn":
            m_mn += float(v or 0.0)

    if m_mn <= 0:
        return 0.0, 0.0

    factor = M_MNSO4_H2O / M_MN if M_MN > 0 else 1.0
    m_crystals = m_mn * factor
    return m_crystals, m_mn


def run_hydro_pyro_slag_mn_crystallization(
    ctx: dict,
    flow_in: MassFlow,
    params: dict | None = None,
):
    """
    S05_10: Manganese crystallization (hydro pyro, slag route).

    Crystallizes Mn as MnSO4·H2O from the sulfate liquor. Stream routing, partition,
    and yields are defined in the EFF workbook (Recycling_Efficiencies).

    Streams (names must match EFF and fallbacks below)
    --------------------------------------------------
    In:  Mn stripped solution (forward stream from Mn stripping).
    Out: Mn mother liquor (default forward stream; raffinate after crystallization).
    Side: MnSO4*H2O (solid product stream; partition target in EFF).
    Process tag for partition: ``process:MnSO4*H2O``.

    **Mass continuity with stripping:** ``:Mn`` is elemental mass in ``comp_abs``; the
    liquor already contains sulfate and water from stripping. Re-tagging to
    ``process:MnSO4*H2O`` uses the full monohydrate mass for partitioning; other
    tagged components are scaled down slightly so the total still matches the strip
    outlet (no extra water feed).
    """
    p = params or {}
    step = "Hydro Pyro – Mn Crystallization"

    # 0) Crystal mass from dissolved Mn
    m_crystals_h, m_mn_h = _mnso4_h2o_from_solution(flow_in)

    # 0b) Composition: strip dissolved Mn species, add process MnSO4·H2O for partitioning
    m0 = float(flow_in.mass_kg_per_h)
    meta = dict(getattr(flow_in, "meta", {}) or {})
    comp_abs = dict(meta.get("comp_abs") or {})

    if m_mn_h > 0:
        for k in list(comp_abs.keys()):
            ks = str(k)
            if ks.endswith(":Mn") or ks == "Mn":
                comp_abs[k] = 0.0
        comp_abs["process:MnSO4*H2O"] = comp_abs.get("process:MnSO4*H2O", 0.0) + m_crystals_h
        _rebalance_comp_abs_to_mass(comp_abs, m0)

    meta["comp_abs"] = comp_abs
    flow_aug = MassFlow(m0, meta=meta)

    # 1) Mass balance and partition
    outputs = rfx.apply_step_cfg(step, flow_aug, fallback_default_stream="Mn mother liquor")
    assert_mass_balance(step, float(flow_aug.mass_kg_per_h), outputs)

    summ = rfx.stream_summary(step, outputs, fallback_forward="Mn mother liquor")
    forward_key = summ["forward_key"]
    loss_key = summ["loss_key"]
    side_keys = summ["side_keys"]

    out_forward: MassFlow = outputs.get(
        forward_key,
        MassFlow(0.0, meta={"comp_abs": {}, "comp": {}}),
    )
    crystals_flow = rfx.mf_get(outputs, "MnSO4*H2O")
    crystals_h = float(crystals_flow.mass_kg_per_h)

    # 2) Sizing and CAPEX 
    design_load = float(p.get("design_load", 0.85))
    sizing = size_machine_for_mass(
        step,
        Eq.crystallizer,
        flow_aug,
        ctx,
        design_load=design_load,
        max_lines=int(p.get("max_lines", 600)),
    )
    breakdown = capex_breakdown_df(step, Eq.crystallizer.name, sizing)

    # 3) Load and energy
    required_tph = float(flow_aug.mass_kg_per_h) / 1000.0
    provided_tph_at_load = float(sizing.get("provided_tph_at_load", 0.0) or 0.0)
    load_actual = min(1.0, required_tph / provided_tph_at_load) if provided_tph_at_load > 0 else 0.0

    mother_liquor_h = float(out_forward.mass_kg_per_h)
    m_water_in_crystal_h = hydrate_water_in_crystal_kg_h(crystals_h, M_MNSO4_H2O, 1)
    m_water_removed_h = water_removed_for_thermal_kg_h(eff_wastewater_kg_h=mother_liquor_h)
    thermal = crystallization_water_evaporation_kwh_h(m_water_removed_h, params=p)
    e_thermal_kwh_h = float(thermal["thermal_kwh_h"])
    h_y = hours_per_year(ctx)
    annual_energy_kwh = e_thermal_kwh_h * h_y

    # 4) Reporting row (In = physical strip liquor mass; comp_abs carries crystal partition)
    row = make_row(step, flow_in, out_forward)
    row["Out kg/h"] = float(summ["m_out_kg_h"])
    row["Loss (kg/h)"] = float(summ["m_loss_kg_h"])
    row["Side streams (kg/h)"] = float(summ["m_side_kg_h"])
    row["Forward key"] = str(forward_key)
    row["Loss sink key"] = str(loss_key)
    row["Side keys"] = ", ".join(side_keys) if side_keys else "-"

    row["Mn mother liquor (kg/h)"] = float(mother_liquor_h)
    row["MnSO4·H2O crystals (kg/h)"] = crystals_h
    row["Mn crystallized (kg/h)"] = float(m_mn_h)
    row["Water in crystal (kg/h)"] = float(m_water_in_crystal_h)
    row["Water evaporated (kg/h)"] = float(m_water_removed_h)
    row["Thermal energy (kWh/h)"] = float(e_thermal_kwh_h)
    row["Thermal heat evaporation (kJ/h)"] = float(thermal["q_evap_kj_h"])
    row["Evaporation efficiency"] = float(thermal["eta_evaporation"])
    row["Energy (kWh/y)"] = float(annual_energy_kwh)
    row["E_kWh_h"] = float(e_thermal_kwh_h)

    # 5) OPEX: energy only (no additional reagents in this step)
    row = attach_opex_to_row(
        row,
        machine=Eq.crystallizer,
        sizing=sizing,
        ctx=ctx,
        load_actual=load_actual,
        energy_kwh_y=annual_energy_kwh,
        water_m3_y=0.0,
        materials_cost_y=0.0,
        add_perkg=True,
    )

    # 6) CAPEX columns and extras
    row["Machines"] = float(sizing.get("n_lines", 0.0))
    row["Line capacity (t/h)"] = float(sizing.get("line_capacity_tph", 0.0))
    row["CAPEX equip ($)"] = float(sizing.get("capex_equip", 0.0))
    row["CAPEX building ($)"] = float(sizing.get("capex_building", 0.0))
    row["outputs_kg_h"] = [{"Manganese sulfate": float(crystals_h)}]
    extras = {step: {"breakdown": breakdown}}
    return outputs, row, extras