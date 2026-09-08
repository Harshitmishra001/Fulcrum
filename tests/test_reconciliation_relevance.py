import pytest
from src.comparison.engine import ComparisonEngine

def test_semantic_relevance_gate_rejects_irrelevant_cues():
    engine = ComparisonEngine()
    
    fact_a = {
        "id": "f_1",
        "attribute": "Current Account Balance",
        "value": -1.3,
        "source_quote": "Current account balance stood at -1.3% of GDP."
    }
    fact_b = {
        "id": "f_2",
        "attribute": "Current Account Deficit",
        "value": 0.6,
        "source_quote": "Current account deficit was 0.6%."
    }
    
    # This sentence has the cue word "advance" but is totally irrelevant to CAD
    irrelevant_candidate = "The first advance estimate for wheat production was revised downwards."
    
    engine._page_chunks = {
        ("doc_1", 1): [irrelevant_candidate]
    }
    
    reconciled, verdict, cand = engine._attempt_reconciliation(fact_a, fact_b)
    
    assert reconciled is False
    assert verdict == "NO"
    # It should not have selected the agricultural sentence as a candidate explanation

def test_semantic_relevance_gate_accepts_relevant_cues():
    engine = ComparisonEngine()
    engine.client = None
    
    fact_a = {
        "id": "f_1",
        "attribute": "Current Account Balance",
        "value": -1.3,
        "source_doc": "doc_1",
        "source_page": 1,
        "source_quote": "Current account balance stood at -1.3% of GDP."
    }
    fact_b = {
        "id": "f_2",
        "attribute": "Current Account Deficit",
        "value": -1.3,
        "source_doc": "doc_1",
        "source_page": 1,
        "source_quote": "Current account deficit was 1.3%."
    }
    
    # This sentence has the cue word "revision" AND mentions "current account"
    relevant_candidate = "The revision in the current account data reflects methodological changes."
    
    engine._page_chunks = {
        ("doc_1", 1): [relevant_candidate]
    }
    
    reconciled, verdict, cand = engine._attempt_reconciliation(fact_a, fact_b)
    
    # In the deterministic fallback, it should flag this as a YES because it has both cue + topical relevance
    assert reconciled is True
    assert verdict == "YES"
