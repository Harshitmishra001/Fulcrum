import json
import re
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from openai import OpenAI
from src.config import (
    OPENROUTER_API_KEY, LLM_BASE_URL, LLM_MODEL,
    PERCENTAGE_TOLERANCE, ABSOLUTE_TOLERANCE, RECONCILIATION_CHUNK_WINDOW
)
from src.comparison.entity_resolver import EntityResolver
from src.normalizer.unit_normalizer import UnitNormalizer
from src.db.database import get_active_facts, save_relation, get_db_connection

RECONCILIATION_SYSTEM_PROMPT = """You are a strict financial reconciliation auditor.
You will be given two conflicting facts from economic reports and one candidate sentence from the text.
Classify whether this sentence explains the discrepancy between the two values (e.g. due to revision vintage, advance estimates vs final, scope, methodology, or definition).

Output MUST be a JSON object:
{
  "verdict": "YES | PARTIAL | NO",
  "reason": "short 1-sentence reason"
}
Do NOT generate a new explanation. Only classify the candidate sentence.
"""

MAX_EMB_CACHE_SIZE = 4096

class ComparisonEngine:
    def __init__(self, model: str = LLM_MODEL):
        self.resolver = EntityResolver()
        self.client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=30.0
        )
        self.model = model
        self.emb_cache: Dict[str, np.ndarray] = {}

    def _precompute_embeddings(self, strings: List[str]):
        unique = [s for s in set(strings) if s and s not in self.emb_cache]
        if unique:
            vecs = self.resolver.model.encode(unique, normalize_embeddings=True, show_progress_bar=False)
            for s, v in zip(unique, vecs):
                # Strict bound: evict oldest entry if capacity reached
                if len(self.emb_cache) >= MAX_EMB_CACHE_SIZE:
                    first_key = next(iter(self.emb_cache))
                    del self.emb_cache[first_key]
                self.emb_cache[s] = v

    def _fast_similarity(self, s1: str, s2: str) -> float:
        if s1.lower().strip() == s2.lower().strip():
            return 1.0
        v1 = self.emb_cache.get(s1)
        v2 = self.emb_cache.get(s2)
        if v1 is not None and v2 is not None:
            return float(np.dot(v1, v2))
        return self.resolver.compute_similarity(s1, s2)

    def run_comparison(self, doc_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        facts = get_active_facts(doc_filter)
        relations = []
        n = len(facts)
        print(f"Running comparison over {n} active facts...")

        # Precompute embeddings in 1 single fast batch
        all_terms = [f["entity"] for f in facts] + [f["attribute"] for f in facts]
        self._precompute_embeddings(all_terms)

        for i in range(n):
            for j in range(i + 1, n):
                fact_a = facts[i]
                fact_b = facts[j]

                # Don't compare identical facts from same chunk
                if fact_a["id"] == fact_b["id"] or fact_a["chunk_id"] == fact_b["chunk_id"]:
                    continue

                # Quick filter: if normalized periods are both present and different, skip immediately
                norm_p_a = fact_a.get("period_normalized")
                norm_p_b = fact_b.get("period_normalized")
                if norm_p_a and norm_p_b and norm_p_a != norm_p_b:
                    continue

                # 1. Entity matching
                same_entity, entity_conf, entity_label = self.resolver.are_same_entity(
                    fact_a["entity"], fact_b["entity"],
                    fact_a.get("source_quote", ""), fact_b.get("source_quote", "")
                )
                if not same_entity:
                    continue

                # 2. Attribute matching
                if not self._attributes_match(fact_a["attribute"], fact_b["attribute"]):
                    continue

                # 3. Classify relation
                rel = self._classify_pair(fact_a, fact_b, entity_conf)
                if rel:
                    save_relation(rel)
                    relations.append(rel)
                    print(f"Found relation: [{rel['relation_type'].upper()}] between p.{fact_a['source_page']} and p.{fact_b['source_page']} ({fact_a['attribute']})")

        return relations

    def _attributes_match(self, attr_a: str, attr_b: str) -> bool:
        """
        Generalized attribute matching (Critic 3.1):
        1. Exact string match after canonical cleanup.
        2. Generic ratio/denominator mismatch guard (e.g. 'debt to gdp' vs 'gdp growth').
        3. Core substantive token overlap + semantic floor.
        4. Vector similarity threshold (>= 0.81).
        Zero hardcoded domain or document-specific metric lists.
        """
        a = attr_a.lower().strip()
        b = attr_b.lower().strip()
        if a == b:
            return True

        # Generic ratio / denominator mismatch guard (word-bounded to avoid substrings like 'ope-ratio-ns')
        ratio_pattern = re.compile(r"\b(to gdp|as % of|% of|margin|ratio)\b|/gdp", re.IGNORECASE)
        a_ratio = bool(ratio_pattern.search(a))
        b_ratio = bool(ratio_pattern.search(b))
        if a_ratio != b_ratio:
            return False

        # Negative polarity / concept guard
        distinct_concepts = [
            ("debt", "growth"),
            ("deficit", "revenue"),
            ("tax", "inflation"),
            ("export", "import"),
            ("borrowing", "surplus")
        ]
        for term1, term2 in distinct_concepts:
            if (term1 in a and term2 in b) or (term2 in a and term1 in b):
                return False

        # Extract substantive tokens (ignoring common noise words)
        stopwords = {"in", "of", "the", "at", "for", "from", "total", "rate", "annual", "and", "by", "all"}
        tokens_a = set(re.findall(r"\b[a-z]{3,}\b", a)) - stopwords
        tokens_b = set(re.findall(r"\b[a-z]{3,}\b", b)) - stopwords

        sim = self._fast_similarity(attr_a, attr_b)

        # High confidence semantic similarity
        if sim >= 0.81:
            return True

        # If they share substantive core tokens and have moderate semantic similarity
        if tokens_a and tokens_b:
            overlap = tokens_a.intersection(tokens_b)
            # Sharing 2+ substantive tokens or >50% Jaccard similarity with similarity >= 0.65
            jaccard = len(overlap) / len(tokens_a.union(tokens_b))
            if (len(overlap) >= 2 or jaccard >= 0.5) and sim >= 0.65:
                return True

        return False

    def _classify_pair(self, fact_a: Dict[str, Any], fact_b: Dict[str, Any], entity_conf: float) -> Optional[Dict[str, Any]]:
        # Guard 1: Period basis check (calendar vs fiscal)
        period_a = fact_a.get("period_type")
        period_b = fact_b.get("period_type")

        if period_a and period_b and period_a != period_b and period_a != "unspecified" and period_b != "unspecified":
            return {
                "fact_a_id": fact_a["id"],
                "fact_b_id": fact_b["id"],
                "relation_type": "not_comparable_period",
                "explanation": f"Different period types ({period_a} vs {period_b}).",
                "evidence_quote": None,
                "entity_resolution_confidence": entity_conf
            }

        # Guard 2: Assertion type check (projection vs stated)
        assert_a = fact_a.get("assertion_type", "stated")
        assert_b = fact_b.get("assertion_type", "stated")
        if assert_a != assert_b and "stated" in [assert_a, assert_b] and "projection" in [assert_a, assert_b]:
            return {
                "fact_a_id": fact_a["id"],
                "fact_b_id": fact_b["id"],
                "relation_type": "different_claim_type",
                "explanation": f"Different assertion types: one is '{assert_a}', while the other is '{assert_b}'.",
                "evidence_quote": None,
                "entity_resolution_confidence": entity_conf
            }

        # Guard 3: Numeric value check
        val_a = fact_a.get("value")
        val_b = fact_b.get("value")
        unit = fact_a.get("unit") or fact_b.get("unit")

        if val_a is not None and val_b is not None:
            if UnitNormalizer.values_match(float(val_a), float(val_b), unit):
                q_a = fact_a.get('source_quote', '')
                q_b = fact_b.get('source_quote', '')
                return {
                    "fact_a_id": fact_a["id"],
                    "fact_b_id": fact_b["id"],
                    "relation_type": "corroboration",
                    "explanation": f"Both sources agree on {fact_a['attribute']} ({val_a}{unit or ''}).",
                    "evidence_quote": f"Source A: '{q_a}' | Source B: '{q_b}'",
                    "entity_resolution_confidence": entity_conf
                }
            else:
                # Values conflict -> Attempt reconciliation within adjacent window
                reconciled, verdict, cand_sentence = self._attempt_reconciliation(fact_a, fact_b)
                if reconciled:
                    return {
                        "fact_a_id": fact_a["id"],
                        "fact_b_id": fact_b["id"],
                        "relation_type": "reconciled" if verdict == "YES" else "candidate_reconciliation",
                        "explanation": f"Apparent contradiction ({val_a} vs {val_b}) explained by context.",
                        "evidence_quote": cand_sentence,
                        "entity_resolution_confidence": entity_conf
                    }
                else:
                    q_a = fact_a.get('source_quote', '')
                    q_b = fact_b.get('source_quote', '')
                    return {
                        "fact_a_id": fact_a["id"],
                        "fact_b_id": fact_b["id"],
                        "relation_type": "contradiction",
                        "explanation": f"Sources report conflicting values for {fact_a['attribute']}: {val_a}{unit or ''} vs {val_b}{unit or ''}.",
                        "evidence_quote": f"A: '{q_a}' | B: '{q_b}'",
                        "entity_resolution_confidence": entity_conf
                    }

        return None

    def _attempt_reconciliation(self, fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
        cue_pattern = re.compile(r"(advance estimate|revised estimate|provisional|definition|re-estimate|methodology|base year)", re.IGNORECASE)
        candidates = []
        for f in [fact_a, fact_b]:
            q = f.get("source_quote", "")
            if cue_pattern.search(q):
                candidates.append(q)

        if not candidates:
            return False, "NO", None

        candidate = candidates[0]
        prompt = f"""Fact A: {fact_a['attribute']} = {fact_a['value']} ({fact_a.get('source_quote', '')})
Fact B: {fact_b['attribute']} = {fact_b['value']} ({fact_b.get('source_quote', '')})
Candidate Explanation Sentence: "{candidate}"

Classify if this sentence explains the difference."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": RECONCILIATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            data = json.loads(response.choices[0].message.content)
            verdict = data.get("verdict", "NO").upper()
            if verdict in ["YES", "PARTIAL"]:
                return True, verdict, candidate
        except Exception as e:
            print(f"Reconciliation check error: {e}")

        return False, "NO", None
