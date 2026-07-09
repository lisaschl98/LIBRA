from __future__ import annotations

import math
from typing import Any, Dict, Iterable

import pandas as pd


class CellDB:
    """
    Load Pack / Module / Cell BOMs from Excel and build mass-composition views at cell, module, and pack level.

    Module and pack sheets often list both NMC and LFP rows for the same format. Filtering by format alone would
    sum both chemistries and overstate module/pack BOP mass. Rows are therefore restricted by **format** and
    **chemistry family** (NMC vs LFP), derived from the cell's chemistry string via `_chem_family`.

    `build_battery` returns:
        - ``cell_comp_abs``   — kg per cell (namespaced cell components only).
        - ``module_comp_abs`` — kg per module (cells in one module × cell BOM + module BOP).
        - ``system_comp_abs`` — kg per pack/system (cells_per_pack × cell BOM + modules_per_pack × module BOP + pack BOP).

    Composition keys use the form ``cell:<Component>:<material>``, ``module:<material>``, ``pack:<material>``.
    """

    def __init__(self, xlsx_path: str) -> None:
        self.xlsx_path = xlsx_path
        self._xls = pd.ExcelFile(xlsx_path)
        self._sheet_map = {s.lower(): s for s in self._xls.sheet_names}

        self.cell_types = self._read_sheet(
            ["cell_types", "cell types", "Cell_Types", "Cell Types"],
            required=True,
        )
        self.cell_mats = self._read_sheet(
            ["cell_materials", "cell materials", "Cell_Materials", "Cell Materials"],
            required=True,
        )
        self.mod_mats = self._read_sheet(
            ["module_materials", "module materials", "Module_Materials"],
            required=True,
        )
        self.pack_mats = self._read_sheet(
            ["pack_materials", "pack materials", "Pack_Materials"],
            required=True,
        )
        self.format_rules = self._read_sheet(
            ["format_rules", "Modules_format_rules"],
            required=True,
        )

        for df in (self.cell_types, self.cell_mats, self.mod_mats, self.pack_mats, self.format_rules):
            if df is None or df.empty:
                continue
            for c in df.columns:
                if df[c].dtype == "object":
                    df[c] = df[c].astype(str).str.strip()

        # Strip column headers (e.g. trailing spaces in "chemistry ")
        self.cell_types.columns = [str(c).strip() for c in self.cell_types.columns]
        self.cell_mats.columns = [str(c).strip() for c in self.cell_mats.columns]
        self.mod_mats.columns = [str(c).strip() for c in self.mod_mats.columns]
        self.pack_mats.columns = [str(c).strip() for c in self.pack_mats.columns]
        self.format_rules.columns = [str(c).strip() for c in self.format_rules.columns]

        if "component" in self.cell_mats.columns:
            self.cell_mats["component"] = (
                self.cell_mats["component"]
                .str.replace("PackingContainer", "Packing Container")
                .str.strip()
            )

    def _read_sheet(self, names: Iterable[str], required: bool) -> pd.DataFrame:
        for n in names:
            if str(n).lower() in self._sheet_map:
                return pd.read_excel(self.xlsx_path, sheet_name=self._sheet_map[str(n).lower()])
        if required:
            raise ValueError(f"Missing required sheet. Tried {names}")
        return pd.DataFrame()

    @staticmethod
    def _ns(level: str, material: str) -> str:
        return f"{level}:{material}"

    @staticmethod
    def _chem_family(chemistry: str) -> str:
        """
        Map a detailed chemistry label to the family used in module/pack BOM rows (typically ``NMC`` or ``LFP``).

        Module and pack sheets use one chemistry column; cell_types may use variants such as ``NMC811``.
        Prefix matching maps those to ``NMC`` or ``LFP``; any other value is returned uppercased for exact match.
        """
        c = str(chemistry or "").strip().upper()
        if c.startswith("NMC"):
            return "NMC"
        if c.startswith("LFP"):
            return "LFP"
        return c

    def _sum_bom(self, df, key_col, key, qty_col):
        """Aggregate BOM rows: all rows where ``key_col == key``, sum ``qty_col`` by material name."""
        if key_col not in df.columns:
            return {}

        part = df[df[key_col] == key]
        out = {}
        for _, r in part.iterrows():
            mat = str(r.get("material", "")).strip()
            if not mat:
                continue
            q = float(r.get(qty_col, 0) or 0)
            if q != 0:
                out[mat] = out.get(mat, 0) + q
        return out

    def _filter_component(self, cell_id: str, component: str) -> Dict[str, float]:
        """Return ``{material: kg_per_cell}`` for one logical cell component (e.g. Cathode) and ``cell_id``."""
        if "component" not in self.cell_mats.columns:
            return {}

        df = self.cell_mats[
            (self.cell_mats["cell_id"] == cell_id)
            & (self.cell_mats["component"] == component)
        ]

        out = {}
        for _, r in df.iterrows():
            mat = str(r.get("material", "")).strip()
            q = float(r.get("kg_per_cell", 0) or 0)
            if mat and q != 0:
                out[mat] = out.get(mat, 0) + q
        return out

    def build_battery(
        self,
        cell_id: str,
        pack_energy_kWh: float = 100.0,
    ) -> Dict[str, Any]:
        """
        Assemble metadata, filtered module/pack BOP, weights, and three parallel composition dicts (cell / module / system).

        Pack BOP is scaled from ``kg_per_100kWhpack`` using ``pack_energy_kWh / 100``.
        System mass matches: ``cells_per_pack * cell_weight + modules_per_pack * module_BOP + pack_BOP`` (BOP sums from filtered BOMs).
        """
        # --- Cell metadata ---
        ct = self.cell_types[self.cell_types["cell_id"] == cell_id]
        if ct.empty:
            raise KeyError(f"Unknown cell_id: {cell_id}")
        ct = ct.iloc[0].to_dict()

        chemistry = str(ct.get("chemistry", "")).strip()
        chem_family = self._chem_family(chemistry)

        cell_format = str(ct.get("format", "")).strip()
        cell_energy_Wh = float(ct.get("cell_energy_Wh", 0) or 0)
        if cell_energy_Wh <= 0:
            raise ValueError(f"cell_energy_Wh missing for {cell_id}")

        # --- Format rules (cells per module, etc.) ---
        fr = self.format_rules[self.format_rules["format"] == cell_format]
        if fr.empty:
            raise KeyError(f"Missing format_rules for format={cell_format}")
        fr = fr.iloc[0].to_dict()

        cells_per_module = int(fr.get("cells_per_module") or 0)
        if cells_per_module <= 0:
            raise ValueError("cells_per_module must be > 0")

        # --- BOMs: cell (per cell_id), module & pack (format + chemistry family) ---
        cell_bom = self._sum_bom(self.cell_mats, "cell_id", cell_id, "kg_per_cell")

        mod_bom = {}
        if {"format", "chemistry", "material", "kg_per_module"}.issubset(set(self.mod_mats.columns)):
            mm = self.mod_mats[
                (self.mod_mats["format"].astype(str).str.strip() == cell_format)
                & (self.mod_mats["chemistry"].astype(str).str.strip().str.upper() == chem_family)
            ]
            for _, r in mm.iterrows():
                mat = str(r.get("material", "")).strip()
                if not mat:
                    continue
                mod_bom[mat] = mod_bom.get(mat, 0.0) + float(r.get("kg_per_module", 0) or 0)

        pack_bom = {}
        if {"format", "chemistry", "material", "kg_per_100kWhpack"}.issubset(set(self.pack_mats.columns)):
            pm = self.pack_mats[
                (self.pack_mats["format"].astype(str).str.strip() == cell_format)
                & (self.pack_mats["chemistry"].astype(str).str.strip().str.upper() == chem_family)
            ]
            scale = float(pack_energy_kWh) / 100.0
            for _, r in pm.iterrows():
                mat = str(r.get("material", "")).strip()
                if not mat:
                    continue
                pack_bom[mat] = pack_bom.get(mat, 0.0) + float(r.get("kg_per_100kWhpack", 0) or 0) * scale

        # --- Weights (module/pack from BOM sums, not a single constant from cell_types) ---
        cell_weight = float(ct.get("cell_weight_kg", 0) or 0)
        if cell_weight <= 0:
            cell_weight = float(sum(cell_bom.values()))

        module_weight = float(sum(mod_bom.values()))
        pack_weight = float(sum(pack_bom.values()))

        # --- Pack sizing ---
        cells_per_pack = int(math.ceil(pack_energy_kWh * 1000.0 / cell_energy_Wh))
        modules_per_pack = int(math.ceil(cells_per_pack / cells_per_module))

        system_weight = (
            cells_per_pack * cell_weight
            + modules_per_pack * module_weight
            + pack_weight
        )
        module_total_weight = cells_per_module * cell_weight + module_weight

        # --- Composition dicts (absolute kg at each level) ---
        system_comp_abs: Dict[str, float] = {}
        cell_comp_abs: Dict[str, float] = {}
        module_comp_abs: Dict[str, float] = {}

        for mat, kg in pack_bom.items():
            k = self._ns("pack", mat)
            system_comp_abs[k] = system_comp_abs.get(k, 0.0) + float(kg)

        for mat, kg in mod_bom.items():
            k = self._ns("module", mat)
            module_comp_abs[k] = module_comp_abs.get(k, 0.0) + float(kg)
            system_comp_abs[k] = system_comp_abs.get(k, 0.0) + float(kg) * modules_per_pack

        COMPONENTS = ["Cathode", "Anode", "Electrolyte", "Separator", "Packing Container"]

        for comp in COMPONENTS:
            comp_mats = self._filter_component(cell_id, comp)
            for mat, kg_per_cell in comp_mats.items():
                key = f"cell:{comp}:{mat}"

                cell_comp_abs[key] = cell_comp_abs.get(key, 0.0) + float(kg_per_cell)
                module_comp_abs[key] = module_comp_abs.get(key, 0.0) + float(kg_per_cell) * cells_per_module
                system_comp_abs[key] = system_comp_abs.get(key, 0.0) + float(kg_per_cell) * cells_per_pack

        return {
            "Type": chemistry,
            "Chem family": chem_family,
            "Format": cell_format,
            "cell_energy_Wh": cell_energy_Wh,
            "Cell weight": cell_weight,
            "Module weight": module_weight,
            "Module weight total": module_total_weight,
            "Pack weight": pack_weight,
            "System weight": system_weight,
            "Cells per module": cells_per_module,
            "Modules per pack": modules_per_pack,
            "Cells per pack": cells_per_pack,
            "cell_comp_abs": cell_comp_abs,
            "module_comp_abs": module_comp_abs,
            "system_comp_abs": system_comp_abs,
        }