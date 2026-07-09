# machine.py — cleaned & step-ready
from __future__ import annotations

import math
import pandas as pd
import General_Parameters as gp

# ---------- Price index helper ----------
def price_index_factor(
    capex_ref_date: str,
    target_date: str,
    indices: dict,
    bridge_date: str = "2024-06",
) -> float:
    """
    Multiplier for price indexing:
    - ref == target: 1
    - ref & target <= bridge: CEPCI
    - ref & target >= bridge: IPPI
    - otherwise: CEPCI (ref->bridge) * IPPI (bridge->target)

    Expects: indices={"CEPCI":{YYYY-MM: val}, "IPPI":{YYYY-MM: val}}
    """
    cepci = indices.get("CEPCI", {})
    ippi  = indices.get("IPPI", {})

    if capex_ref_date == target_date:
        return 1.0

    def _get(d: dict, k: str, label: str) -> float:
        if k not in d:
            raise KeyError(f"Missing {label} index for '{k}'.")
        return float(d[k])

    if capex_ref_date <= bridge_date and target_date <= bridge_date:
        return _get(cepci, target_date, "CEPCI") / _get(cepci, capex_ref_date, "CEPCI")

    if capex_ref_date >= bridge_date and target_date >= bridge_date:
        return _get(ippi, target_date, "IPPI") / _get(ippi, capex_ref_date, "IPPI")

    return (_get(cepci, bridge_date, "CEPCI") / _get(cepci, capex_ref_date, "CEPCI")) * (
        _get(ippi, target_date, "IPPI") / _get(ippi, bridge_date, "IPPI")
    )

def load_machines_from_excel(
    path: str | None = None,
    sheet_name: str = "Machines",
) -> list["Machine"]:
    if path is None:
        path = gp.REGION_FILE  # Cost_Region_Values.xlsx

    df = pd.read_excel(path, sheet_name=sheet_name)
    df.columns = df.columns.astype(str).str.strip()

    machines: list[Machine] = []

    for _, row in df.iterrows():
        # Skip rows without a valid name
        raw_name = row.get("name", None)
        if pd.isna(raw_name):
            continue
        name = str(raw_name).strip()
        if not name:
            continue

        def _opt(col, default=None):
            v = row.get(col, default)
            if pd.isna(v):
                return default
            return v

        m = Machine(
            name=name,
            invest_cost=float(row["invest_cost"]),
            lifetime=float(row["lifetime_y"]),
            capacity=float(row["capacity"]),
            labor=float(row["labor_person_h_per_day"]),
            area_per_machine=float(row["area_per_machine_m2"]),
            electrical_power_design=float(row["electrical_power_design_kW"]),
            capex_ref_date=str(row["capex_ref_date"]),
            scale_exponent=float(row["scale_exponent"]),
            min_capacity_tph=_opt("min_capacity_tph", None),
            max_capacity_tph=_opt("max_capacity_tph", None),
            capacity_unit=str(_opt("capacity_unit", "t/h")),
            install_factor=_opt("install_factor", None),
            instr_factor=_opt("instr_factor", None),
            piping_factor=_opt("piping_factor", None),
            electr_factor=_opt("electr_factor", None),
            maint_pct_installed=_opt("maint_pct_installed", None),
            supplies_pct_of_maint=_opt("supplies_pct_of_maint", None),
        )
        machines.append(m)

    return machines
# ---------- Global defaults ----------

INSTALL_FACTOR_DEFAULT = 0.15
INSTR_FACTOR_DEFAULT   = 0.10
PIPING_FACTOR_DEFAULT  = 0.10
ELECTR_FACTOR_DEFAULT  = 0.00

MAINT_PCT_INSTALLED_DEFAULT   = 0.05
SUPPLIES_PCT_OF_MAINT_DEFAULT = 0.15

TARGET_DATE = "2026-04"
BRIDGE_DATE = "2024-06"


# ---------- Machine ----------
class Machine:
    def __init__(
        self,
        name: str,
        invest_cost: float,             # $ (reference date)
        lifetime: float,                # years
        capacity: float,                # design capacity per line
        labor: float,                   # person-hours/day per line
        area_per_machine: float,        # m²
        electrical_power_design: float, # kW at design capacity per line
        capex_ref_date: str,            # "YYYY-MM"
        scale_exponent: float,
        *,
        min_capacity_tph: float | None = None,
        max_capacity_tph: float | None = None,
        capacity_unit: str = "t/h",     # "t/h" | "m3/h" | "m3"
        install_factor: float | None = None,
        instr_factor: float | None = None,
        piping_factor: float | None = None,
        electr_factor: float | None = None,
        maint_pct_installed: float | None = None,
        supplies_pct_of_maint: float | None = None,
    ):
        self.name = str(name)
        self.invest_cost = float(invest_cost)
        self.lifetime = float(lifetime)
        self.capacity = float(capacity)
        self.labor = float(labor)
        self.area_per_machine = float(area_per_machine)
        self.electrical_power_design = float(electrical_power_design)
        self.capex_ref_date = str(capex_ref_date)
        self.scale_exponent = float(scale_exponent)

        if capacity_unit not in ("t/h", "m3/h", "m3"):
            raise ValueError("capacity_unit must be 't/h', 'm3/h', or 'm3'")
        self.capacity_unit = capacity_unit

        # min/max: meaningful for throughput machines; clamp ignored later for storage
        self.min_capacity_tph = (self.capacity * 0.8) if min_capacity_tph is None else float(min_capacity_tph)
        self.max_capacity_tph = (self.capacity * 1.2) if max_capacity_tph is None else float(max_capacity_tph)

        self.install_factor = INSTALL_FACTOR_DEFAULT if install_factor is None else float(install_factor)
        self.instr_factor   = INSTR_FACTOR_DEFAULT   if instr_factor   is None else float(instr_factor)
        self.piping_factor  = PIPING_FACTOR_DEFAULT  if piping_factor  is None else float(piping_factor)
        self.electr_factor  = ELECTR_FACTOR_DEFAULT  if electr_factor  is None else float(electr_factor)

        self.maint_pct_installed   = MAINT_PCT_INSTALLED_DEFAULT   if maint_pct_installed   is None else float(maint_pct_installed)
        self.supplies_pct_of_maint = SUPPLIES_PCT_OF_MAINT_DEFAULT if supplies_pct_of_maint is None else float(supplies_pct_of_maint)

    # ---------- Convenience ----------
    def capacity_unit_pretty(self) -> str:
        return {"t/h": "t/h", "m3/h": "m³/h", "m3": "m³"}.get(self.capacity_unit, self.capacity_unit)

    def calc_capacity_year(self, hours: float | None = None) -> float:
        """
        Annual capacity (= capacity * hours) for throughput machines.
        Not meaningful for storage (m³) -> NaN.
        """
        if self.capacity_unit == "m3":
            return float("nan")
        h = float(hours if hours is not None else gp.get_working_hours_per_year())
        return float(self.capacity) * h

    # ---------- CAPEX ----------
    def calc_scaled_invest(self, target_capacity: float) -> float:
        """
        Scale investment costs from design capacity -> target_capacity.
        target_capacity uses the same unit as capacity_unit.
        """
        c = max(self.capacity, 1e-9)
        tc = max(float(target_capacity), 1e-9)

        # clamp only for throughput (t/h or m3/h)
        if self.capacity_unit in ("t/h", "m3/h"):
            tc = max(self.min_capacity_tph, min(tc, self.max_capacity_tph))

        return self.invest_cost * (tc / c) ** self.scale_exponent

    def indexed_cost_at_capacity(
        self,
        line_capacity: float,
        target_date: str,
        indices: dict,
        bridge_date: str = BRIDGE_DATE,
        ctx: dict | None = None,
    ) -> float:
        base_scaled = self.calc_scaled_invest(line_capacity)
        f = price_index_factor(self.capex_ref_date, target_date, indices, bridge_date)
        cost = base_scaled * f
        if ctx is not None:
            cost *= float(ctx.get("capex_factor", 1.0))
        return cost

    # ---- Installed / Maintenance / Supplies ----
    def installed_from_purchased(self, capex_equip: float) -> dict:
        ia2 = self.install_factor * capex_equip
        ia3 = self.instr_factor   * capex_equip
        ia4 = self.piping_factor  * capex_equip
        ia5 = self.electr_factor  * capex_equip
        installed = capex_equip + ia2 + ia3 + ia4 + ia5
        return {
            "capex_install_model": ia2,
            "capex_instr":         ia3,
            "capex_piping":        ia4,
            "capex_electrical":    ia5,
            "capex_installed":     installed,
        }

    def depreciation_from_purchased(self, capex_equip: float) -> float:
        return capex_equip / max(self.lifetime, 1e-9)

    def maintenance_from_installed(self, capex_installed: float) -> float:
        return self.maint_pct_installed * capex_installed

    def supplies_from_maintenance(self, maint_y: float) -> float:
        return self.supplies_pct_of_maint * maint_y

    def maint_and_supplies_for(self, capex_installed: float) -> tuple[float, float]:
        m = self.maintenance_from_installed(capex_installed)
        s = self.supplies_from_maintenance(m)
        return m, s

    # ---- Sizing & CAPEX ----
    def size_and_capex(
        self,
        annual_input_tons: float,
        target_date: str,
        indices: dict,
        ctx: dict | None = None,
        bridge_date: str = BRIDGE_DATE,
        design_load: float = 0.85,
        max_lines: int = 20,
        external_required: dict | None = None,  # {"unit": "...", "value": ...}
    ) -> dict:
        hours = float(gp.get_working_hours_per_year())

        # required in machine unit
        if external_required:
            req_unit = str(external_required.get("unit", self.capacity_unit))
            required = float(external_required["value"])
        else:
            req_unit = "t/h"
            required = float(annual_input_tons) / max(hours, 1e-9)

        if self.capacity_unit != req_unit:
            raise ValueError(
                f"Capacity unit mismatch for {self.name}: machine is {self.capacity_unit}, required is {req_unit}"
            )

        # -------- Throughput machines --------
        if req_unit in ("t/h", "m3/h"):
            if required <= 0:
                return {
                    "n_lines": 0, "line_capacity_tph": 0.0,
                    "capex_equip": 0.0,
                    "capex_install_model": 0.0, "capex_instr": 0.0, "capex_piping": 0.0, "capex_electrical": 0.0,
                    "capex_installed": 0.0, "capex_total": 0.0,
                    "provided_tph_at_load": 0.0, "required_tph": 0.0,
                }

            best = None
            for n in range(1, max_lines + 1):
                line_capacity = (required / n) / max(design_load, 1e-6)

                if line_capacity < self.min_capacity_tph:
                    line_capacity = self.min_capacity_tph
                if line_capacity > self.max_capacity_tph:
                    continue

                cost_line = self.indexed_cost_at_capacity(
                    line_capacity=line_capacity,
                    target_date=target_date,
                    indices=indices,
                    bridge_date=bridge_date,
                    ctx=ctx,
                )
                capex_equip = n * cost_line
                br = self.installed_from_purchased(capex_equip)

                cand = {
                    "n_lines": n,
                    "line_capacity_tph": line_capacity,  # keep label
                    "capex_equip": capex_equip,
                    "capex_install_model": br["capex_install_model"],
                    "capex_instr": br["capex_instr"],
                    "capex_piping": br["capex_piping"],
                    "capex_electrical": br["capex_electrical"],
                    "capex_installed": br["capex_installed"],
                    "capex_total": br["capex_installed"],
                    "provided_tph_at_load": n * line_capacity * design_load,
                    "required_tph": required,
                }

                if (best is None) or (cand["capex_total"] < best["capex_total"]):
                    best = cand

            if best is None:
                n = int(math.ceil(required / (self.capacity * max(design_load, 1e-6))))
                line_capacity = self.capacity
                cost_line = self.indexed_cost_at_capacity(line_capacity, target_date, indices, bridge_date, ctx)
                capex_equip = n * cost_line
                br = self.installed_from_purchased(capex_equip)
                best = {
                    "n_lines": n,
                    "line_capacity_tph": line_capacity,
                    "capex_equip": capex_equip,
                    "capex_install_model": br["capex_install_model"],
                    "capex_instr": br["capex_instr"],
                    "capex_piping": br["capex_piping"],
                    "capex_electrical": br["capex_electrical"],
                    "capex_installed": br["capex_installed"],
                    "capex_total": br["capex_installed"],
                    "provided_tph_at_load": n * line_capacity * design_load,
                    "required_tph": required,
                }
            return best

        # -------- Storage machines (m3) --------
        if req_unit == "m3":
            if required <= 0:
                return {
                    "n_lines": 0, "line_capacity_tph": 0.0,
                    "capex_equip": 0.0,
                    "capex_install_model": 0.0, "capex_instr": 0.0, "capex_piping": 0.0, "capex_electrical": 0.0,
                    "capex_installed": 0.0, "capex_total": 0.0,
                    "provided_tph_at_load": 0.0, "required_tph": 0.0,
                }

            n = int(math.ceil(required / max(self.capacity, 1e-9)))
            line_capacity = self.capacity
            cost_line = self.indexed_cost_at_capacity(line_capacity, target_date, indices, bridge_date, ctx)
            capex_equip = n * cost_line
            br = self.installed_from_purchased(capex_equip)

            return {
                "n_lines": n,
                "line_capacity_tph": line_capacity,          # keep label
                "capex_equip": capex_equip,
                "capex_install_model": br["capex_install_model"],
                "capex_instr": br["capex_instr"],
                "capex_piping": br["capex_piping"],
                "capex_electrical": br["capex_electrical"],
                "capex_installed": br["capex_installed"],
                "capex_total": br["capex_installed"],
                "provided_tph_at_load": n * line_capacity,   # semantically: volume
                "required_tph": required,                    # semantically: volume
            }

        raise RuntimeError("Unhandled capacity unit case.")

    # ---- Energy estimate (kWh/y) ----
    def energy_for_sized(self, annual_input_tons: float, n_lines: int, line_tph: float) -> float:
        hours = float(gp.get_working_hours_per_year())

        if self.capacity_unit == "m3":
            return 0.0

        if self.capacity_unit == "m3/h":
            design_power_line = self.electrical_power_design * (line_tph / max(self.capacity, 1e-9))
            return design_power_line * hours * n_lines

        # Default: "t/h"
        required_tph = float(annual_input_tons) / max(hours, 1e-9)
        denom = max(n_lines * line_tph, 1e-9)
        load = min(1.0, required_tph / denom)
        design_power_line = self.electrical_power_design * (line_tph / max(self.capacity, 1e-9))
        return design_power_line * hours * load * n_lines

    # ---- Building ----
    def calc_building_investment_costs(self, number_of_machines: int, ctx: dict) -> float:
        base_cost = float(ctx["building_cost_m2_base"])
        factor = float(ctx.get("building_factor", 1.0))
        price_per_m2 = base_cost * factor
        total_area = self.area_per_machine * int(number_of_machines)
        return price_per_m2 * total_area

    def calc_annual_building_costs_per_kg(
        self,
        number_of_machines: int,
        kg_batteries_per_year: float,
        ctx: dict,
        building_lifetime: int = 25,
    ) -> float:
        invest = self.calc_building_investment_costs(number_of_machines, ctx)
        annual = invest / max(int(building_lifetime), 1)
        return (annual / kg_batteries_per_year) if kg_batteries_per_year > 0 else 0.0


# ---------- Machine instances ----------
_MACHINE_ALIASES = {
    "analytics": "Analytics & Sorting stack",
    "discharge": "Discharge tool",
    "dismantle": "Dismantle area",
    "crusher": "Crusher",
    "smelter": "Smelter",
    "gas_scrubbing": "Gas scrubbing",
    "granulator": "Granulator",
    "vibrating_screen": "Vibrating screen",
    "dryer": "Dryer",
    "reactor": "Reactor",
    "solvent_extraction": "Solvent extraction unit",
    "filterpress": "Filterpress",
    "crystallizer": "Crystallizer",
    "magnetic_separation": "Magnetic separator",
    "zigzag": "AirClassification",
    "evaporator": "Evaporator",
    "ion_exchanger": "Ion exchange unit",
    "roaster": "Roaster",
    "wastewater_treatment": "Wastewater treatment",
}


def reload_machines_from_excel(path: str | None = None) -> None:
    """Reload machine definitions from the active Price and Emission Data workbook."""
    global _all_machines, MACHINES_BY_NAME, machines

    loaded = load_machines_from_excel(path)
    loaded_by_name = {m.name: m for m in loaded}
    missing = [name for name in _MACHINE_ALIASES.values() if name not in loaded_by_name]
    if missing:
        raise KeyError("Missing required machine(s) in Machines sheet: " + ", ".join(missing))

    _all_machines = loaded
    MACHINES_BY_NAME = loaded_by_name
    machines = _all_machines
    for attr, machine_name in _MACHINE_ALIASES.items():
        globals()[attr] = MACHINES_BY_NAME[machine_name]


reload_machines_from_excel()

# ---------- Export ----------
def machines_to_dataframe(
    machines: list[Machine],
    target_date: str | None = None,
    indices: dict | None = None,
    ctx: dict | None = None,
    bridge_date: str = BRIDGE_DATE,
) -> pd.DataFrame:
    if target_date is None:
        target_date = TARGET_DATE
    if indices is None:
        from General_Parameters import INDICES
        indices = INDICES

    rows = []
    for ma in machines:
        capex_indexed_design = ma.indexed_cost_at_capacity(
            line_capacity=ma.capacity,
            target_date=target_date,
            indices=indices,
            bridge_date=bridge_date,
            ctx=ctx,
        )

        norm_cost_val = capex_indexed_design / ma.capacity if ma.capacity > 0 else float("nan")

        rows.append({
            "Machine Name": ma.name,
            "Machine invest ref ($)": ma.invest_cost,
            "Machine invest ref date": ma.capex_ref_date,
            "Machine invest target date": target_date,
            "Indexed CAPEX at target ($)": capex_indexed_design,
            "Indexed CAPEX per capacity ($/unit)": norm_cost_val,

            "Design capacity": ma.capacity,
            "Min capacity": ma.min_capacity_tph,
            "Max capacity": ma.max_capacity_tph,
            "Capacity unit": ma.capacity_unit_pretty(),

            "Lifetime (y)": ma.lifetime,
            "Scale exponent (-)": ma.scale_exponent,
            "Labor (person h/day)": ma.labor,
            "Electrical design (kW)": ma.electrical_power_design,

            "Install factor (-)": ma.install_factor,
            "Instr factor (-)": ma.instr_factor,
            "Piping factor (-)": ma.piping_factor,
            "Electrical factor (-)": ma.electr_factor,
            "Maint % installed (/y)": ma.maint_pct_installed,
            "Supplies % of maint": ma.supplies_pct_of_maint,

            "Annual capacity (capacity*hours)": ma.calc_capacity_year(),
        })

    return pd.DataFrame(rows)


def save_machines_to_excel(machines_df: pd.DataFrame, writer) -> None:
    machines_df.to_excel(writer, sheet_name="Machines", index=False)
