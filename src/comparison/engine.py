import json
import re
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
import numpy as np
from openai import OpenAI
from src.config import (
    OPENROUTER_API_KEY, LLM_BASE_URL, LLM_MODEL,
    PERCENTAGE_TOLERANCE, ABSOLUTE_TOLERANCE, RECONCILIATION_CHUNK_WINDOW
)
from src.comparison.entity_resolver import EntityResolver
from src.normalizer.unit_normalizer import UnitNormalizer
from src.db.database import (
    get_active_facts, save_relation, save_relations_batch, get_db_connection,
    get_chunk_text, get_chunks_by_page,
    get_all_chunk_texts, get_all_page_chunks
)

RECONCILIATION_SYSTEM_PROMPT = """You are a strict financial reconciliation auditor.
You will be given two conflicting facts from reports and one candidate sentence from the text.
Classify whether this sentence EXPLICITLY explains the discrepancy between the two values (e.g. one is a projection vs stated, or an advance estimate vs final, or based on a different definition).

If the sentence is just vaguely topically related but does NOT explain why the numbers differ, output NO.
If the sentence directly explains the difference, output YES.

Output MUST be a JSON object:
{
  "verdict": "YES | PARTIAL | NO",
  "reason": "short 1-sentence reason"
}
Do NOT generate a new explanation. Only classify the candidate sentence.
"""

MAX_EMB_CACHE_SIZE = 32768


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
        # Pre-loaded caches — populated once at start of run_comparison
        self._chunk_cache: Dict[str, str] = {}
        self._page_chunks: Dict[tuple, List[str]] = {}

    def _precompute_embeddings(self, strings: List[str]):
        unique = [s for s in set(strings) if s and s not in self.emb_cache]
        if unique:
            vecs = self.resolver.model.encode(unique, normalize_embeddings=True, show_progress_bar=False)
            for s, v in zip(unique, vecs):
                if len(self.emb_cache) >= MAX_EMB_CACHE_SIZE:
                    first_key = next(iter(self.emb_cache))
                    del self.emb_cache[first_key]
                self.emb_cache[s] = v

    def _fast_similarity(self, s1: str, s2: str) -> float:
        if s1.lower().strip() == s2.lower().strip():
            return 1.0
        v1 = self.emb_cache.get(s1)
        if v1 is None:
            v1 = self.resolver.model.encode([s1], normalize_embeddings=True)[0]
            if len(self.emb_cache) < MAX_EMB_CACHE_SIZE:
                self.emb_cache[s1] = v1
        v2 = self.emb_cache.get(s2)
        if v2 is None:
            v2 = self.resolver.model.encode([s2], normalize_embeddings=True)[0]
            if len(self.emb_cache) < MAX_EMB_CACHE_SIZE:
                self.emb_cache[s2] = v2
        return float(np.dot(v1, v2))

    # --- Blocking Index for O(N·K) comparison ---

    def _get_dimension_key(self, fact: Dict[str, Any]) -> str:
        """Extract dimension from unit for blocking index partitioning."""
        unit = fact.get("unit") or ""
        norm, _ = UnitNormalizer.normalize_unit(unit)
        dim = UnitNormalizer.DIMENSIONS.get(norm) if norm else None
        return dim or "UNKNOWN"

    def _build_blocking_index(self, facts: List[Dict[str, Any]]) -> Dict[tuple, List[Dict[str, Any]]]:
        """Partition facts by (dimension, period) for sub-linear candidate generation.
        Only facts within the same block are compared, reducing O(N²) to O(N·K)."""
        blocks = defaultdict(list)
        for f in facts:
            dim = self._get_dimension_key(f)
            period = f.get("period_normalized") or "UNSPECIFIED"
            blocks[(dim, period)].append(f)
        return blocks

    def run_comparison(self, doc_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        facts = get_active_facts(doc_filter)
        relations = []
        n = len(facts)
        print(f"Running comparison over {n} active facts...")

        # Pre-load ALL chunks and page texts into memory — eliminates N+1 SQLite queries
        self._chunk_cache = get_all_chunk_texts()
        self._page_chunks = get_all_page_chunks()
        print(f"Pre-loaded {len(self._chunk_cache)} chunks and {len(self._page_chunks)} page groups into memory.")

        # Precompute embeddings in 1 single fast batch
        all_terms = [f["entity"] for f in facts] + [f["attribute"] for f in facts]
        self._precompute_embeddings(all_terms)

        # Build blocking index for efficient comparison
        blocks = self._build_blocking_index(facts)
        total_comparisons = 0

        for block_key, block_facts in blocks.items():
            block_n = len(block_facts)
            if block_n < 2:
                continue

            for i in range(block_n):
                for j in range(i + 1, block_n):
                    fact_a = block_facts[i]
                    fact_b = block_facts[j]

                    # Don't compare identical facts from same chunk
                    if fact_a["id"] == fact_b["id"] or fact_a["chunk_id"] == fact_b["chunk_id"]:
                        continue

                    total_comparisons += 1

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
                        relations.append(rel)
                        print(f"Found relation: [{rel['relation_type'].upper()}] between p.{fact_a['source_page']} and p.{fact_b['source_page']} ({fact_a['attribute']})")

        print(f"Blocking index: {len(blocks)} blocks, {total_comparisons} comparisons (vs {n*(n-1)//2} brute-force)")

        # Also compare across blocks where dimension is UNKNOWN (catch cross-unit pairs)
        unknown_facts = blocks.get(("UNKNOWN", "UNSPECIFIED"), [])
        for block_key, block_facts in blocks.items():
            if block_key[0] == "UNKNOWN":
                continue
            for uf in unknown_facts:
                for bf in block_facts:
                    if uf["id"] == bf["id"] or uf["chunk_id"] == bf["chunk_id"]:
                        continue
                    same_entity, entity_conf, entity_label = self.resolver.are_same_entity(
                        uf["entity"], bf["entity"],
                        uf.get("source_quote", ""), bf.get("source_quote", "")
                    )
                    if not same_entity:
                        continue
                    if not self._attributes_match(uf["attribute"], bf["attribute"]):
                        continue
                    rel = self._classify_pair(uf, bf, entity_conf)
                    if rel:
                        relations.append(rel)

        # Atomic batch insert
        if relations:
            save_relations_batch(relations)

        return relations

    # Sector qualifiers — NO holdout contamination (b2c, pbf PURGED)
    SECTOR_QUALIFIERS = {
        "agriculture", "allied", "industry", "services", "manufacturing",
        "mining", "construction", "rural", "urban", "food", "fuel", "core"
    }

    def _attributes_match(self, attr_a: str, attr_b: str) -> bool:
        """
        General attribute matcher:
        1. Exact string match after lowercase cleanup.
        2. Ratio / denominator semantic check (no longer binary reject).
        3. Sector/segment qualifier isolation guard.
        4. Core substantive token overlap + semantic similarity floor.
        """
        a = attr_a.lower().strip()
        b = attr_b.lower().strip()
        if a == b:
            return True

        # Ratio / denominator check — SEMANTIC, not binary reject
        # Instead of rejecting when one has "/gdp" and the other doesn't,
        # we let it through — the unit normalizer handles dimensional compatibility downstream.
        # We ONLY reject when the mismatch is clearly a different metric type (e.g., "margin" vs level).
        ratio_pattern = re.compile(r"\b(margin|ratio)\b", re.IGNORECASE)
        a_ratio = bool(ratio_pattern.search(a))
        b_ratio = bool(ratio_pattern.search(b))
        if a_ratio != b_ratio:
            return False

        # Extract substantive tokens (ignoring common noise words)
        stopwords = {"in", "of", "the", "at", "for", "from", "total", "rate", "annual", "and", "by", "all"}
        tokens_a = set(re.findall(r"\b[a-z]{3,}\b", a)) - stopwords
        tokens_b = set(re.findall(r"\b[a-z]{3,}\b", b)) - stopwords

        # Sector / segment qualifier guard: prevent aggregate from matching sub-sector
        qualifiers_a = tokens_a.intersection(self.SECTOR_QUALIFIERS)
        qualifiers_b = tokens_b.intersection(self.SECTOR_QUALIFIERS)
        if qualifiers_a != qualifiers_b:
            return False

        sim = self._fast_similarity(attr_a, attr_b)

        # High confidence semantic similarity
        if sim >= 0.81:
            return True

        # If they share substantive core tokens and have moderate semantic similarity
        if tokens_a and tokens_b:
            overlap = tokens_a.intersection(tokens_b)
            union = tokens_a.union(tokens_b)
            jaccard = len(overlap) / len(union) if union else 0.0
            if jaccard >= 0.5 and sim >= 0.65:
                return True
            if len(overlap) >= 2 and sim >= 0.60:
                return True
            if len(overlap) >= 1 and sim >= 0.72:
                return True

        return False

    def _classify_pair(self, fact_a: Dict[str, Any], fact_b: Dict[str, Any], entity_conf: float) -> Optional[Dict[str, Any]]:
        # Guard 1: Period basis check (calendar vs fiscal)
        period_a = fact_a.get("period_type")
        period_b = fact_b.get("period_type")

        if period_a and period_b and period_a != period_b and period_a != "unspecified" and period_b != "unspecified":
            # Also block half-year vs full-year, partial vs full, etc.
            return {
                "fact_a_id": fact_a["id"],
                "fact_b_id": fact_b["id"],
                "relation_type": "not_comparable_period",
                "explanation": f"Different period types ({period_a} vs {period_b}).",
                "evidence_quote": None,
                "entity_resolution_confidence": entity_conf
            }

        # Guard 2: Assertion type — SOFTENED (annotate, don't block)
        # Previously this hard-blocked projection vs stated pairs, silencing contradictions.
        # Now we annotate the difference but STILL compare values.
        assert_a = fact_a.get("assertion_type", "stated")
        assert_b = fact_b.get("assertion_type", "stated")
        assertion_note = None
        if assert_a != assert_b and "stated" in [assert_a, assert_b] and "projection" in [assert_a, assert_b]:
            assertion_note = f"assertion_types differ ({assert_a} vs {assert_b})"

        # Guard 3: Safe value check (numeric tolerance & categorical string handling)
        val_a = fact_a.get("value")
        val_b = fact_b.get("value")
        unit_a = fact_a.get("unit")
        unit_b = fact_b.get("unit")

        if val_a is not None and val_b is not None:
            num_a, num_b = None, None
            try:
                if isinstance(val_a, (int, float)):
                    num_a = float(val_a)
                elif isinstance(val_a, str):
                    num_a = float(val_a.replace(",", "").replace("%", "").strip())
            except (ValueError, TypeError):
                num_a = None

            try:
                if isinstance(val_b, (int, float)):
                    num_b = float(val_b)
                elif isinstance(val_b, str):
                    num_b = float(val_b.replace(",", "").replace("%", "").strip())
            except (ValueError, TypeError):
                num_b = None

            is_match = False
            if num_a is not None and num_b is not None:
                is_match = UnitNormalizer.values_match(num_a, num_b, unit_a, unit_b)
            else:
                str_a = str(val_a).strip().lower()
                str_b = str(val_b).strip().lower()
                is_match = (str_a == str_b)

            if is_match:
                q_a = fact_a.get('source_quote', '')
                q_b = fact_b.get('source_quote', '')
                unit_str = unit_a or unit_b or ''
                explanation = f"Both sources agree on {fact_a['attribute']} ({val_a}{unit_str})."
                if assertion_note:
                    explanation += f" Note: {assertion_note}."
                return {
                    "fact_a_id": fact_a["id"],
                    "fact_b_id": fact_b["id"],
                    "relation_type": "corroboration",
                    "explanation": explanation,
                    "evidence_quote": f"Source A: '{q_a}' | Source B: '{q_b}'",
                    "entity_resolution_confidence": entity_conf
                }
            else:
                # Values conflict -> Attempt reconciliation
                reconciled, verdict, cand_sentence = self._attempt_reconciliation(fact_a, fact_b)
                if reconciled:
                    explanation = f"Apparent contradiction ({val_a} vs {val_b}) explained by context: {cand_sentence[:180]}"
                    if assertion_note:
                        explanation += f" Note: {assertion_note}."
                    return {
                        "fact_a_id": fact_a["id"],
                        "fact_b_id": fact_b["id"],
                        "relation_type": "reconciled" if verdict == "YES" else "candidate_reconciliation",
                        "explanation": explanation,
                        "evidence_quote": cand_sentence,
                        "entity_resolution_confidence": entity_conf
                    }
                else:
                    q_a = fact_a.get('source_quote', '')
                    q_b = fact_b.get('source_quote', '')
                    unit_str = unit_a or unit_b or ''
                    explanation = f"Sources report conflicting values for {fact_a['attribute']}: {val_a}{unit_str} vs {val_b}{unit_str}."
                    if assertion_note:
                        explanation += f" Note: {assertion_note}."
                    return {
                        "fact_a_id": fact_a["id"],
                        "fact_b_id": fact_b["id"],
                        "relation_type": "contradiction",
                        "explanation": explanation,
                        "evidence_quote": f"A: '{q_a}' | B: '{q_b}'",
                        "entity_resolution_confidence": entity_conf
                    }

        return None

    def _attempt_reconciliation(self, fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
        # General reporting and accounting variance cues
        cue_pattern = re.compile(
            r"\b(advance|preliminary|revised|revision|provisional|restated|restatement|definition|methodology|reclassified|constant currency|nominal|real terms)\b",
            re.IGNORECASE
        )
        candidates = []

        def extract_matching_sentences(text_block: str):
            if not text_block:
                return
            sentences = re.split(r'(?<=[.!?])\s+|\s+(?=\d+\s+[A-Z])|\n+', text_block)
            for s in sentences:
                s_clean = s.strip()
                if len(s_clean) >= 20 and cue_pattern.search(s_clean) and s_clean not in candidates:
                    candidates.append(s_clean)

        # 1. Check full text of the source chunks (from pre-loaded cache — NO SQLite query)
        for f in [fact_a, fact_b]:
            chunk_id = f.get("chunk_id")
            if chunk_id:
                chunk_text = self._chunk_cache.get(chunk_id)
                if chunk_text:
                    extract_matching_sentences(chunk_text)

        # 2. Check direct fact quotes
        for f in [fact_a, fact_b]:
            q = f.get("source_quote", "")
            if q and cue_pattern.search(q) and q not in candidates:
                candidates.append(q)

        # 3. Scan neighboring chunks on adjacent pages (from pre-loaded cache — NO SQLite query)
        if not candidates:
            for f in [fact_a, fact_b]:
                doc = f.get("source_doc")
                page = f.get("source_page", 1)
                if doc:
                    for offset in range(-1, 2):
                        neighbor_key = (doc, page + offset)
                        for nt in self._page_chunks.get(neighbor_key, []):
                            extract_matching_sentences(nt)

        # 4. Scan neighboring fact quotes (from pre-loaded facts — avoids N+1)
        if not candidates:
            for f in [fact_a, fact_b]:
                doc = f.get("source_doc")
                page = f.get("source_page", 1)
                if doc:
                    # Use cached active facts grouped by doc
                    for offset in range(-2, 3):
                        neighbor_key = (doc, page + offset)
                        for nt in self._page_chunks.get(neighbor_key, []):
                            extract_matching_sentences(nt)

        if not candidates:
            return False, "NO", None

        # --- SEMANTIC RELEVANCE GATE ---
        # Before accepting a candidate, verify it's topically related to the conflicting facts.
        fact_context = f"{fact_a['attribute']} {fact_b['attribute']}".lower()
        fact_tokens = set(re.findall(r"\b[a-z]{3,}\b", fact_context)) - {"the", "and", "for", "from", "all", "per", "gdp", "percent"}

        for candidate in candidates[:5]:
            cand_lower = candidate.lower()
            cand_tokens = set(re.findall(r"\b[a-z]{3,}\b", cand_lower)) - {"the", "and", "for", "from", "all", "per", "gdp", "percent"}
            token_overlap = fact_tokens & cand_tokens

            if not token_overlap:
                sim = self._fast_similarity(fact_context, candidate)
                if sim < 0.4:
                    continue  

            if self.client:
                try:
                    prompt = f"Fact A: {fact_a['attribute']} = {fact_a['value']} ({fact_a.get('source_quote', '')})\nFact B: {fact_b['attribute']} = {fact_b['value']} ({fact_b.get('source_quote', '')})\nCandidate Explanation Sentence: \"{candidate}\"\n\nClassify if this sentence specifically explains why the two numerical values differ. If it's just related topic but doesn't explain the discrepancy, return NO."

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
                    if verdict == "YES":
                        return True, verdict, candidate
                except Exception:
                    pass

            if candidate != fact_a.get("source_quote", "") and candidate != fact_b.get("source_quote", ""):
                generic_variance_markers = [
                    "advance", "preliminary", "revised", "revision", "provisional",
                    "restated", "restatement", "definition", "methodology", "reclassified",
                    "constant currency", "nominal", "real terms"
                ]
                if any(term in cand_lower for term in generic_variance_markers) and len(token_overlap) >= 2:
                    return True, "YES", candidate

        return False, "NO", None
