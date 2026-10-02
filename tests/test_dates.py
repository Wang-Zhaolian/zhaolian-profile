from academic_profile.dates import format_date, format_date_range, validate_date_string


def test_date_validation() -> None:
    assert validate_date_string("2026-09")
    assert validate_date_string("2026-09-26")
    assert not validate_date_string("09/2026")
    assert not validate_date_string("2026-13")


def test_date_formatting() -> None:
    assert format_date("2026-09") == "Sep 2026"
    assert format_date_range("2025-03", "2026-02") == "Mar 2025 - Feb 2026"
    assert format_date_range("2025-03", None, ongoing=True) == "Mar 2025 - Present"
    assert format_date("2026-09", "zh") == "2026年9月"

