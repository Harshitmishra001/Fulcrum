import pytest
from src.extractor.extractor import FactExtractor
from src.normalizer.period_normalizer import PeriodNormalizer
from src.normalizer.unit_normalizer import UnitNormalizer
from src.comparison.entity_resolver import EntityResolver
from src.comparison.engine import ComparisonEngine
from src.db.database import save_fact, save_relation, get_all_relations
from src.eval.golden_eval import GoldenEvaluator

def test_grounding_invariant_rejects_hallucinated_quotes():
    """Finding 2: Unconditional grounding invariant rejects ungrounded hallucinations."""
    extractor = FactExtractor()
    chunk = {
        "chunk_id": "test__p0001__0001",
        "text": "The company reported revenue growth across key domestic markets."
    }
    # Completely hallucinated quote with number and period
    raw_fact = {
        "entity": "Company",
        "attribute": "EBITDA Margin",
        "value": 15.5,
        "unit": "%",
        "period": {"raw_text": "FY2024", "period_type": "fiscal_year", "normalized": "FY2024"},
        "source_quote": "Operating profit margin stood at 15.5 percent according to management."
    }
    result = extractor._process_raw_fact(raw_fact, chunk)
    assert result is None, "Ungrounded hallucinated quote must be rejected immediately"

def test_iso_date_parsing_corporate_filings():
    """Finding 3: Corporate ISO dates parse accurately and do not map to FY2003."""
    res_q1 = PeriodNormalizer.normalize("2024-03-31")
    assert res_q1["normalized"] == "CY2024-Q1"
    assert res_q1["period_type"] == "calendar_quarter"
    assert res_q1["normalized"] != "FY2003", "Must not turn 2024-03 into FY2003!"

    res_q4 = PeriodNormalizer.normalize("2023-12-31")
    assert res_q4["normalized"] == "CY2023-Q4"

    res_hist = PeriodNormalizer.normalize("1998")
    assert res_hist["normalized"] == "CY1998"
    assert "2098" not in res_hist["normalized"]

def test_categorical_string_comparison_no_value_error():
    """Finding 4: Categorical string values are handled cleanly without ValueError."""
    engine = ComparisonEngine()
    fact_a = {
        "id": "cat_a",
        "entity": "Reserve Bank of India",
        "attribute": "Monetary Policy Stance",
        "value": "accommodative",
        "unit": None,
        "period_type": "fiscal_year",
        "assertion_type": "stated",
        "source_page": 5,
        "source_quote": "The stance remains accommodative."
    }
    fact_b = {
        "id": "cat_b",
        "entity": "Reserve Bank of India",
        "attribute": "Monetary Policy Stance",
        "value": "accommodative",
        "unit": None,
        "period_type": "fiscal_year",
        "assertion_type": "stated",
        "source_page": 8,
        "source_quote": "Reiterated accommodative policy stance."
    }
    rel = engine._classify_pair(fact_a, fact_b, entity_conf=1.0)
    assert rel is not None
    assert rel["relation_type"] == "corroboration"

def test_unit_dimension_mismatch_prevents_false_corroboration():
    """Finding 5: Incompatible dimensions (USD vs INR) return False."""
    assert not UnitNormalizer.values_match(5.0, 5.0, "USD Billion", "INR Crore")
    assert not UnitNormalizer.values_match(5.0, 5.0, "PERCENT", "INR Crore")

def test_unit_multipliers_applied_correctly():
    """Finding 5: Unit multipliers normalize values before comparing."""
    # 100 Lakh == 1 Crore
    assert UnitNormalizer.values_match(100.0, 1.0, "INR Lakh", "INR Crore")
    # 50 BPS == 0.5 Percent
    assert UnitNormalizer.values_match(50.0, 0.5, "BPS", "PERCENT")

def test_entity_resolver_pruned_aliases_safe():
    """Finding 6: Generic broad words like 'centre' or 'fund' do not misattribute."""
    resolver = EntityResolver()
    assert "centre" not in resolver.KNOWN_ALIASES
    assert "fund" not in resolver.KNOWN_ALIASES

    # A distribution centre does not become Government of India
    assert resolver.KNOWN_ALIASES.get("distribution centre") != "Government of India"

def test_cross_agency_deficit_attribute_matching():
    """Finding 7: Cross-agency phrasing for Central Fiscal Deficit matches."""
    engine = ComparisonEngine()
    matches = engine._attributes_match("Central Government Deficit", "Gross Fiscal Deficit")
    assert matches is True, "Central Government Deficit and Gross Fiscal Deficit must match"

def test_direct_engine_attempt_reconciliation():
    """Finding 8: Direct engine._attempt_reconciliation execution with domain fallback."""
    engine = ComparisonEngine()
    fact_a = {
        "id": "dir_fa",
        "entity": "Government of India",
        "attribute": "Gross Fiscal Deficit",
        "value": 4.7,
        "unit": "%",
        "period": {"normalized": "FY2025"},
        "source_doc": "doc_a",
        "source_page": 10,
        "source_quote": "Central Government fiscal deficit is 4.7 percent."
    }
    fact_b = {
        "id": "dir_fb",
        "entity": "Government of India",
        "attribute": "Central Government Deficit",
        "value": 4.9,
        "unit": "%",
        "period": {"normalized": "FY2025"},
        "source_doc": "doc_b",
        "source_page": 15,
        "source_quote": "Deficit reached 4.9 percent per IMF definition, versus 4.7 percent per the authorities' definition."
    }
    reconciled, verdict, cand = engine._attempt_reconciliation(fact_a, fact_b)
    assert reconciled is True
    assert verdict == "YES"
    assert "authorities' definition" in cand

def test_relations_deduplication_in_db():
    """Finding 9: Relations table deduplicates repeated inserts for the same fact pair."""
    rel_1 = {
        "id": "rel_test_1",
        "fact_a_id": "f_alpha",
        "fact_b_id": "f_beta",
        "relation_type": "corroboration",
        "explanation": "Initial test",
        "evidence_quote": "Quote 1",
        "entity_resolution_confidence": 1.0
    }
    rel_2 = {
        "id": "rel_test_2",
        "fact_a_id": "f_beta",
        "fact_b_id": "f_alpha",
        "relation_type": "corroboration",
        "explanation": "Duplicate test with swapped order",
        "evidence_quote": "Quote 2",
        "entity_resolution_confidence": 1.0
    }
    save_relation(rel_1)
    save_relation(rel_2)
    all_rels = get_all_relations()
    pair_rels = [r for r in all_rels if {r["fact_a_id"], r["fact_b_id"]} == {"f_alpha", "f_beta"}]
    assert len(pair_rels) == 1, "Must deduplicate relation pair regardless of order"

def test_golden_eval_requires_attribute_match():
    """Finding 10: GoldenEvaluator enforces attribute matching in addition to page/period/value."""
    evaluator = GoldenEvaluator(golden_path="data/golden_set_rbi.json")
    # Fabricate an extracted fact with identical page, period, and value, but unrelated attribute
    extracted = [{
        "id": "unrelated_metric",
        "entity": "India",
        "attribute": "Completely Unrelated Export Metric",
        "value": 6.5, # Same value as GDP growth on p.91
        "unit": "%",
        "period_normalized": "FY2025",
        "source_page": 91,
        "assertion_type": "stated"
    }]
    results = evaluator.evaluate_facts(extracted)
    assert results["matched_golden_count"] == 0, "Unrelated attribute must not match golden Real GDP Growth"
