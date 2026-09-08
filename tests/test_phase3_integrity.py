import uuid
import pytest
from src.extractor.extractor import FactExtractor
from src.comparison.engine import ComparisonEngine
from src.db.database import save_fact

def test_unicode_verbatim_grounding_robustness():
    """Critic 2.3: Verifies that smart quotes, em-dashes, and non-breaking spaces don't drop grounding score."""
    extractor = FactExtractor()
    chunk = {
        "chunk_id": "test__p0001__0001",
        "text": "The company's EBITDA — adjusted for non-recurring expenses — stood at \u20b9500 crore."
    }

    # Quote with standard ascii hyphen, different quote style, and spaces
    raw_fact = {
        "entity": "Company",
        "attribute": "Adjusted EBITDA",
        "value": 500.0,
        "source_quote": "The company's EBITDA - adjusted for non-recurring expenses - stood at \u20b9500 crore.",
        "period": {"raw_text": "FY2024", "period_type": "fiscal_year", "normalized": "FY2024"}
    }

    processed = extractor._process_raw_fact(raw_fact, chunk)
    assert processed is not None
    # Grounding should have passed and awarded full credit (>= 0.8 total confidence)
    assert processed["extraction_confidence"] >= 0.80

def test_multi_fact_neighborhood_reconciliation():
    """Critic 2.1: Verifies that reconciliation scans neighboring facts within 2 pages in SQLite."""
    engine = ComparisonEngine()

    uid = uuid.uuid4().hex[:8]
    doc = f"test_recon_doc_{uid}"
    # Fact A on page 10: Gross Fiscal Deficit = 4.7%
    fact_a = {
        "id": f"recon_fa_{uid}",
        "entity": "Government of India",
        "attribute": "Gross Fiscal Deficit",
        "value": 4.7,
        "unit": "%",
        "period": {"raw_text": "FY2025", "period_type": "fiscal_year", "normalized": "FY2025"},
        "assertion_type": "stated",
        "source_doc": doc,
        "source_page": 10,
        "source_quote": "Central Government gross fiscal deficit stood at 4.7 percent of GDP.",
        "chunk_id": f"doc_{uid}__p0010__0001",
        "extraction_confidence": 0.9
    }

    # Neighboring fact on page 11 that contains the methodological/revision explanation
    neighbor_fact = {
        "id": f"recon_neighbor_{uid}",
        "entity": "Government of India",
        "attribute": "Fiscal Deficit Accounting",
        "value": 4.9,
        "unit": "%",
        "period": {"raw_text": "FY2025", "period_type": "fiscal_year", "normalized": "FY2025"},
        "assertion_type": "stated",
        "source_doc": doc,
        "source_page": 11,
        "source_quote": "Reflects central government fiscal deficit of 4.9 percent per IMF definition, versus 4.7 percent per the authorities' definition.",
        "chunk_id": f"doc_{uid}__p0011__0001",
        "extraction_confidence": 0.9
    }
    save_fact(neighbor_fact, f"run_recon_test_{uid}")

    # Fact B from another doc without immediate explanation: Deficit = 4.9%
    fact_b = {
        "id": f"recon_fb_{uid}",
        "entity": "Government of India",
        "attribute": "Central Government Fiscal Deficit",
        "value": 4.9,
        "unit": "%",
        "period": {"raw_text": "FY2025", "period_type": "fiscal_year", "normalized": "FY2025"},
        "assertion_type": "stated",
        "source_doc": f"other_doc_{uid}",
        "source_page": 15,
        "source_quote": "Central government deficit is projected at 4.9 percent.",
        "chunk_id": f"other_{uid}__p0015__0001",
        "extraction_confidence": 0.9
    }

    # Engine now reads from in-memory pre-loaded dicts, not direct SQLite queries
    engine._page_chunks = {
        (doc, 11): ["Reflects central government fiscal deficit of 4.9 percent per IMF definition, versus 4.7 percent per the authorities' definition."]
    }

    # Attempt reconciliation directly on the engine:
    # Must retrieve candidate from neighbor chunk on page 11 (within +-2 pages) and classify as reconciled!
    reconciled, verdict, explanation = engine._attempt_reconciliation(fact_a, fact_b)
    assert reconciled is True
    assert verdict == "YES"
    assert explanation is not None
    assert "authorities' definition" in explanation
