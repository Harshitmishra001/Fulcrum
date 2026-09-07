import re
from typing import Dict, Any, Tuple, Optional, List
from sentence_transformers import SentenceTransformer
import numpy as np

class EntityResolver:
    """
    Entity resolution layer:
    1. Local sentence embedding cosine similarity (0 API cost).
    2. Three confidence bands (Decision 18):
       - >= 0.85: High confidence (compare normally)
       - 0.65 - 0.85: Low confidence (label as uncertain in UI)
       - < 0.65: Below threshold (no relation created)
    3. "The authorities" heuristic (Decision 19):
       - 3-sentence window keyword vote between monetary and fiscal cues.
    """

    MONETARY_CUES = {
        "repo rate", "monetary policy", "inflation target", "liquidity",
        "mpc", "reserve money", "policy rate", "reverse repo", "standing deposit facility"
    }

    FISCAL_CUES = {
        "fiscal deficit", "budget", "expenditure", "revenue", "subsidy",
        "tax", "gst", "borrowing", "disinvestment", "capital outlay"
    }

    # Common canonical abbreviations lookup
    KNOWN_ALIASES = {
        "goi": "Government of India",
        "government of india": "Government of India",
        "central government": "Government of India",
        "centre": "Government of India",
        "rbi": "Reserve Bank of India",
        "reserve bank of india": "Reserve Bank of India",
        "central bank": "Reserve Bank of India",
        "reserve bank": "Reserve Bank of India",
        "imf": "International Monetary Fund",
        "fund": "International Monetary Fund",
        "international monetary fund": "International Monetary Fund",
        "mospi": "Ministry of Statistics and Programme Implementation",
        "ministry of statistics and programme implementation": "Ministry of Statistics and Programme Implementation",
        "nso": "National Statistical Office",
        "national statistical office": "National Statistical Office"
    }

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # Fast, lightweight local embedding model
        self.model = SentenceTransformer(model_name)

    def _clean_entity_name(self, name: str) -> str:
        s = name.lower().strip()
        s = re.sub(r"^the\s+", "", s) # strip leading 'the '
        s = s.replace("&", "and") # normalize '&' to 'and'
        return " ".join(s.split())

    def resolve_authorities(self, surrounding_text: str) -> Tuple[str, float]:
        """
        Decision 19: 3-sentence window keyword vote.
        - monetary_hits > fiscal_hits -> RBI (0.70)
        - fiscal_hits > monetary_hits -> GoI (0.70)
        - tied or zero -> AMBIGUOUS (0.40, falls below 0.65 threshold)
        """
        text_lower = surrounding_text.lower()
        monetary_hits = sum(1 for cue in self.MONETARY_CUES if cue in text_lower)
        fiscal_hits = sum(1 for cue in self.FISCAL_CUES if cue in text_lower)

        if monetary_hits > fiscal_hits:
            return "Reserve Bank of India", 0.70
        elif fiscal_hits > monetary_hits:
            return "Government of India", 0.70
        else:
            return "AMBIGUOUS", 0.40

    def compute_similarity(self, entity_a: str, entity_b: str) -> float:
        """Computes cosine similarity between two entity names."""
        clean_a = self._clean_entity_name(entity_a)
        clean_b = self._clean_entity_name(entity_b)

        canon_a = self.KNOWN_ALIASES.get(clean_a)
        canon_b = self.KNOWN_ALIASES.get(clean_b)

        # Exact canonical match
        if canon_a and canon_b and canon_a == canon_b:
            return 0.95
        if clean_a == clean_b:
            return 1.0

        # Substring / abbreviation match
        if canon_a and canon_a.lower() in clean_b:
            return 0.90
        if canon_b and canon_b.lower() in clean_a:
            return 0.90

        # Vector embedding cosine similarity
        emb = self.model.encode([entity_a, entity_b], normalize_embeddings=True)
        similarity = float(np.dot(emb[0], emb[1]))
        return max(0.0, min(1.0, similarity))

    def are_same_entity(self, entity_a: str, entity_b: str, context_a: str = "", context_b: str = "") -> Tuple[bool, float, str]:
        """
        Returns (is_match, confidence, label)
        - is_match: True if confidence >= 0.65
        - label: 'high', 'uncertain', or 'none'
        """
        # Handle 'the authorities'
        if "the authorities" in entity_a.lower():
            resolved, conf = self.resolve_authorities(context_a)
            if resolved == "AMBIGUOUS":
                return False, conf, "none"
            entity_a = resolved

        if "the authorities" in entity_b.lower():
            resolved, conf = self.resolve_authorities(context_b)
            if resolved == "AMBIGUOUS":
                return False, conf, "none"
            entity_b = resolved

        score = self.compute_similarity(entity_a, entity_b)

        if score >= 0.85:
            return True, score, "high"
        elif score >= 0.65:
            return True, score, "uncertain"
        else:
            return False, score, "none"
