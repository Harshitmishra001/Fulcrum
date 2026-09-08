import pytest
from src.comparison.engine import ComparisonEngine, MAX_EMB_CACHE_SIZE
from src.parser.pdf_chunker import PDFChunker
from src.normalizer.period_normalizer import PeriodNormalizer
from src.comparison.entity_resolver import EntityResolver

def test_bounded_embedding_cache():
    """Critic 1.3: Verifies that embedding cache stays bounded."""
    engine = ComparisonEngine()
    dummy_strings = [f"entity_term_{i}" for i in range(5000)]
    engine._precompute_embeddings(dummy_strings)
    assert len(engine.emb_cache) <= MAX_EMB_CACHE_SIZE

def test_generalized_attribute_matching_corporate_and_macro():
    """Critic 3.1: Verifies zero-hardcoded attribute matching across corporate and macro domains."""
    engine = ComparisonEngine()

    # Corporate e-commerce / logistics metrics (Delhivery)
    assert engine._attributes_match("Express Parcel Shipments", "Express Parcel Volume")
    assert engine._attributes_match("Adjusted EBITDA", "EBITDA")
    assert engine._attributes_match("Revenue from Operations", "Total Revenue")

    # Macroeconomic metrics
    assert engine._attributes_match("Real GDP Growth", "Growth in Real GDP")
    assert engine._attributes_match("Gross Fiscal Deficit", "Central Government Fiscal Deficit")
    assert engine._attributes_match("Headline CPI Inflation", "CPI-Combined Inflation")

    # Guard against denominator / ratio / polarity false matches
    assert not engine._attributes_match("Adjusted EBITDA", "Adjusted EBITDA Margin") # Level vs Margin
    assert not engine._attributes_match("Real GDP Growth", "Debt-to-GDP Ratio")
    assert not engine._attributes_match("Real GDP Growth", "Trade Balance (% of GDP)")
    assert not engine._attributes_match("Gross Fiscal Deficit", "Tax Revenue")

def test_generic_header_cleaner():
    """Critic 3.2: Verifies generic header and page number stripping without document-specific words."""
    chunker = PDFChunker("test_doc", "dummy.pdf")
    raw_text = "QUARTERLY FINANCIAL REPORT\nRevenue increased by 14% year over year."
    cleaned = chunker._clean_prose(raw_text)
    assert "QUARTERLY FINANCIAL REPORT" not in cleaned
    assert "Revenue increased by 14%" in cleaned

    # Standalone page number
    page_num_text = "42\nOperating income grew steadily."
    cleaned_page = chunker._clean_prose(page_num_text)
    assert "42" not in cleaned_page
    assert "Operating income grew steadily." in cleaned_page

def test_expanded_period_normalizer():
    """Critic 3.3: Verifies calendar quarters, fiscal quarters, CY, and FY parsing."""
    # Calendar quarter
    cq = PeriodNormalizer.normalize("Q1 2024")
    assert cq["period_type"] == "calendar_quarter"
    assert cq["normalized"] == "CY2024-Q1"

    # Fiscal quarter
    fq = PeriodNormalizer.normalize("Q4 FY24")
    assert fq["period_type"] == "fiscal_quarter"
    assert fq["normalized"] == "FY2024-Q4"

    # Fiscal year 4-digit
    fy = PeriodNormalizer.normalize("FY2024-25")
    assert fy["period_type"] == "fiscal_year"
    assert fy["normalized"] == "FY2025"

    # Calendar year
    cy = PeriodNormalizer.normalize("CY2024")
    assert cy["period_type"] == "calendar_year"
    assert cy["normalized"] == "CY2024"

def test_foreign_authorities_resolution():
    """Critic 2.2: Foreign sovereign mentions must NOT map to Indian institutions."""
    resolver = EntityResolver()

    # Foreign context (US Federal Reserve)
    res_foreign, conf_foreign = resolver.resolve_authorities(
        "The authorities at the Federal Reserve signaled higher policy interest rates."
    )
    assert res_foreign == "National Central Bank"
    assert res_foreign != "Reserve Bank of India"

    # Indian context
    res_india, conf_india = resolver.resolve_authorities(
        "The authorities kept the repo rate unchanged at 6.5 percent."
    )
    assert res_india == "Reserve Bank of India"
    assert conf_india == 0.70
