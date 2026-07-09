from app_helpers.chemistry_labels import (
    format_chemistry_html,
    format_chemistry_subscripts,
    format_chemistry_unicode,
)


def test_unicode_subscripts_for_common_products():
    assert format_chemistry_unicode("Li2CO3") == "Li₂CO₃"
    assert format_chemistry_unicode("FePO4-C") == "FePO₄-C"
    assert format_chemistry_unicode("NiSO4") == "NiSO₄"
    assert format_chemistry_unicode("Al(OH)3") == "Al(OH)₃"


def test_html_subscripts_escape_and_format():
    assert format_chemistry_html("Li2CO3") == "Li<sub>2</sub>CO<sub>3</sub>"
    assert format_chemistry_html("<script>") == "&lt;script&gt;"


def test_grade_numbers_not_subscripted():
    assert format_chemistry_unicode("NMC811 precursor") == "NMC811 precursor"
    assert format_chemistry_unicode("LFP21700") == "LFP21700"


def test_idempotent_when_already_formatted():
    assert format_chemistry_unicode("Li₂CO₃") == "Li₂CO₃"
    assert format_chemistry_html("Li<sub>2</sub>CO<sub>3</sub>") == "Li<sub>2</sub>CO<sub>3</sub>"
