"""Format chemical formulas with subscripts for UI display."""
from __future__ import annotations

import html as html_module
import re

_SUBSCRIPT_UNICODE = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_GRADE_PREFIXES = ("NMC", "LFP")
_CHEM_DIGIT_RE = re.compile(r"(?<=[A-Za-z\)])(\d+)")


def _should_keep_digits_plain(text: str, start: int, digits: str) -> bool:
    if len(digits) >= 3:
        prefix = text[max(0, start - 4) : start]
        return any(prefix.endswith(g) for g in _GRADE_PREFIXES)
    return False


def format_chemistry_subscripts(text: object, *, html: bool) -> str:
    """Subscript stoichiometric digits after element symbols, e.g. Li2CO3 -> Li₂CO₃."""
    if text is None:
        return ""
    s = str(text).strip()
    if not s or "<sub>" in s or any(ch in s for ch in "₀₁₂₃₄₅₆₇₈₉"):
        return s

    def _replace(match: re.Match[str]) -> str:
        digits = match.group(1)
        if _should_keep_digits_plain(s, match.start(), digits):
            return digits
        if html:
            return f"<sub>{digits}</sub>"
        return digits.translate(_SUBSCRIPT_UNICODE)

    return _CHEM_DIGIT_RE.sub(_replace, s)


def format_chemistry_html(text: object) -> str:
    """Escape user text, then apply HTML subscripts for safe markup."""
    if text is None:
        return ""
    s = str(text)
    if "<sub>" in s:
        return s
    return format_chemistry_subscripts(html_module.escape(s), html=True)


def format_chemistry_unicode(text: object) -> str:
    """Plain-text / dataframe subscripts via Unicode characters."""
    if text is None:
        return ""
    return format_chemistry_subscripts(str(text), html=False)


def format_dataframe_chemistry(df):
    """Return a copy with chemistry subscripts in string-like columns."""
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_string_dtype(out[col]) or out[col].dtype == object:
            out[col] = out[col].map(lambda v: format_chemistry_unicode(v) if isinstance(v, str) else v)
    return out
