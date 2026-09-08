import pytest
from src.normalizer.period_normalizer import PeriodNormalizer

def test_half_year_patterns():
    # Fiscal half-years
    assert PeriodNormalizer.normalize("H1 FY24")["normalized"] == "FY2024-H1"
    assert PeriodNormalizer.normalize("H2 FY2024")["normalized"] == "FY2024-H2"
    assert PeriodNormalizer.normalize("1H of FY25")["normalized"] == "FY2025-H1"
    
    # Calendar half-years
    assert PeriodNormalizer.normalize("H1 2024")["normalized"] == "CY2024-H1"
    assert PeriodNormalizer.normalize("2H of CY2024")["normalized"] == "CY2024-H2"

def test_partial_year_patterns():
    # Fiscal partial years
    assert PeriodNormalizer.normalize("9M FY24")["normalized"] == "FY2024-9M"
    assert PeriodNormalizer.normalize("9 months of FY25")["normalized"] == "FY2025-9M"
    
    # Calendar partial years
    assert PeriodNormalizer.normalize("9M 2024")["normalized"] == "CY2024-9M"
    assert PeriodNormalizer.normalize("3-months 2024")["normalized"] == "CY2024-3M"

def test_half_year_does_not_fall_through_to_full_year():
    res = PeriodNormalizer.normalize("H1 FY24")
    assert res["period_type"] == "fiscal_half"
    assert res["normalized"] == "FY2024-H1"
