from dataclasses import dataclass, field
from typing import Dict

@dataclass
class MassFlow:
    """Material stream with mass flow rate [kg/h] and optional composition."""
    mass_kg_per_h: float
    meta: Dict[str, float] = field(default_factory=dict)


def assert_mass_balance(step_name: str, m_in_kg_h: float, outputs: dict, tol: float = 1e-6):
    """Checks that total output mass does not exceed input mass."""
    m_out = sum(m.mass_kg_per_h for m in outputs.values())
    if m_out - m_in_kg_h > tol:
        raise AssertionError(f"[{step_name}] Mass balance error: OUT ({m_out:.6f}) > IN ({m_in_kg_h:.6f})")

def ns(level: str, material: str) -> str:
    return f"{level}:{material}"

def get_level(comp: dict, level: str) -> dict:
    prefix = f"{level}:"
    return {k: v for k, v in comp.items() if k.startswith(prefix)}

def remove_level(comp: dict, level: str) -> dict:
    prefix = f"{level}:"
    return {k: v for k, v in comp.items() if not k.startswith(prefix)}