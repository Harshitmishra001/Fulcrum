import pytest
from src.comparison.engine import ComparisonEngine

def test_holdout_clean():
    engine = ComparisonEngine()
    
    # Ensure logistics/Delhivery specific terms were purged
    assert "b2c" not in engine.SECTOR_QUALIFIERS
    assert "pbf" not in engine.SECTOR_QUALIFIERS
    
    # But macro ones remain
    assert "agriculture" in engine.SECTOR_QUALIFIERS
    assert "manufacturing" in engine.SECTOR_QUALIFIERS
