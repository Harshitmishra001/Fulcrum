import pytest
import sqlite3
import os
from src.comparison.engine import ComparisonEngine
from src.db.database import save_fact, get_db_connection, init_db

def test_blocking_index():
    engine = ComparisonEngine()
    
    facts = [
        {"id": "1", "unit": "% of GDP", "period_normalized": "FY2025"},
        {"id": "2", "unit": "percent of GDP", "period_normalized": "FY2025"},
        {"id": "3", "unit": "INR Crore", "period_normalized": "FY2025"},
        {"id": "4", "unit": "%", "period_normalized": "CY2024"},
    ]
    
    blocks = engine._build_blocking_index(facts)
    
    # % of GDP and percent of GDP should land in PERCENTAGE dimension block for FY2025
    assert ("PERCENTAGE", "FY2025") in blocks
    assert len(blocks[("PERCENTAGE", "FY2025")]) == 2
    
    # INR Crore should land in CURRENCY_INR
    assert ("CURRENCY_INR", "FY2025") in blocks
    assert len(blocks[("CURRENCY_INR", "FY2025")]) == 1
    
    # CY2024 should be separate
    assert ("PERCENTAGE", "CY2024") in blocks

def test_contradiction_cad_pairs_not_rejected_by_ratio():
    # Bug 1: engine.py:138-142 - ratio_pattern regex rejected pairs if only one had "/gdp"
    # We softened this to only reject when BOTH are genuinely different types (margin vs level)
    engine = ComparisonEngine()
    
    a = "Current Account Balance/GDP (%)"
    b = "Current Account Deficit"
    
    # This should now return True, allowing them to be compared
    assert engine._attributes_match(a, b) is True
