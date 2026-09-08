import pytest
import sqlite3
from src.config import DB_PATH, PERCENTAGE_TOLERANCE
from src.normalizer.unit_normalizer import UnitNormalizer
from src.comparison.engine import ComparisonEngine
from src.db.database import save_chunks_batch, get_chunk_text, get_chunks_by_page, get_active_facts

def test_tolerance_paradox_eliminated():
    """Auditor 3 Finding 2: Tightened 0.05 tolerance flags 10 bps revision discrepancies."""
    # 6.4% (Economic Survey) vs 6.5% (RBI) must NOT corroborate
    match_rev = UnitNormalizer.values_match(6.4, 6.5, "%", "%")
    assert match_rev is False, "10 bps revision (6.4 vs 6.5) must NOT match; must route to reconciliation"

    # Exact matches must continue to corroborate
    match_exact = UnitNormalizer.values_match(6.5, 6.5, "%", "%")
    assert match_exact is True, "Exact 6.5% vs 6.5% must match"

    # Micro rounding within 0.05 (e.g. 6.50 vs 6.53) matches
    match_micro = UnitNormalizer.values_match(6.50, 6.53, "%", "%")
    assert match_micro is True

def test_currency_and_dimension_safety():
    """Auditor 3 Finding 2: Unmatched currency dimensions must never corroborate."""
    # 500 million JPY vs 500 million EUR
    assert UnitNormalizer.values_match(500, 500, "JPY", "EUR") is False
    assert UnitNormalizer.values_match(100, 100, "GBP", "INR") is False
    assert UnitNormalizer.values_match(50, 50, "MW", "%") is False

def test_sector_qualifier_isolation():
    """Auditor 3 Finding 3: Headline GVA must never collide with Agriculture GVA."""
    engine = ComparisonEngine()
    
    # Headline vs Sector sub-component
    headline_attr = "Real Gross Value Added Growth"
    agri_attr = "Growth in Gross Value Added (GVA) in Agriculture and Allied Sector"
    assert engine._attributes_match(headline_attr, agri_attr) is False

    # Two distinct sectors must not match
    assert engine._attributes_match("Agriculture GVA Growth", "Industry GVA Growth") is False

    # Identical or general deficit variations without sector qualifiers must match
    assert engine._attributes_match("Central Government Deficit", "Gross Fiscal Deficit") is True
    assert engine._attributes_match("Gross Fiscal Deficit", "Central Government Fiscal Deficit") is True

def test_chunk_persistence_and_retrieval(tmp_path):
    """Auditor 3 Finding 1 and Architecture: Parsed document chunks are safely stored and queryable."""
    db_file = str(tmp_path / "test_chunks.db")
    
    # Initialize schema
    from src.db.database import init_db
    init_db(db_file)

    sample_chunks = [
        {
            "chunk_id": "testdoc__p0001__prose__0000",
            "doc_slug": "testdoc",
            "page": 1,
            "chunk_type": "prose",
            "text": "Executive summary: Company revenue grew by 15% in constant currency terms."
        },
        {
            "chunk_id": "testdoc__p0002__prose__0001",
            "doc_slug": "testdoc",
            "page": 2,
            "chunk_type": "prose",
            "text": "Footnote 1: Figures are stated on a preliminary restated basis."
        }
    ]

    saved = save_chunks_batch(sample_chunks, db_path=db_file)
    assert saved == 2

    # Verify retrieval by chunk_id
    t0 = get_chunk_text("testdoc__p0001__prose__0000", db_path=db_file)
    assert "constant currency" in t0

    # Verify retrieval by page window
    page_texts = get_chunks_by_page("testdoc", page=1, window=1, db_path=db_file)
    assert len(page_texts) == 2

def test_zero_injected_facts_in_production_db():
    """Auditor 3 Finding 1: Strict zero-mock invariant. Every fact in fulcrum.db must have legitimate provenance."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, chunk_id, extraction_run_id, source_quote FROM facts WHERE is_active = 1")
    facts = c.fetchall()
    conn.close()

    assert len(facts) > 0, "Production database must contain extracted facts"
    for fid, chunk_id, run_id, quote in facts:
        assert not str(chunk_id).startswith("__footnote__"), f"Synthetic footnote chunk found: {fid}"
        assert not str(run_id).startswith("manual_"), f"Manually injected fact found: {fid}"
        assert quote and len(quote.strip()) > 0, f"Empty quote found: {fid}"
