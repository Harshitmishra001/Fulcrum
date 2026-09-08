import re
import os
import json
from typing import Dict, Any, Tuple, Optional, List
from sentence_transformers import SentenceTransformer
import numpy as np

_SHARED_SENTENCE_MODEL = None

class EntityResolver:
    """
    Two-stage entity resolution (Decision 18):
    1. Fast lookup: exact canonical name / known aliases / acronyms.
    2. Embedding cosine similarity (SentenceTransformer) with threshold 0.85.
    Special handling for 'the authorities' (Decision 19):
       - 3-sentence window keyword vote between monetary and fiscal cues.
    """

    MONETARY_CUES = {
        "repo rate", "monetary policy", "inflation target", "liquidity",
        "mpc", "reserve money", "policy rate", "policy interest rates", "interest rate", "interest rates",
        "reverse repo", "standing deposit facility"
    }

    FISCAL_CUES = {
        "fiscal deficit", "budget", "expenditure", "revenue", "subsidy",
        "tax", "gst", "borrowing", "disinvestment", "capital outlay"
    }

    KNOWN_ALIASES = {}

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from src.shortcut_audit import log_penalty
        
        # Load externalized aliases config
        config_path = os.path.join("config", "entity_aliases.json")
        try:
            with open(config_path, "r", encoding="utf-8-sig") as f:
                EntityResolver.KNOWN_ALIASES = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            log_penalty("entity_resolver", "alias_fallback", "Entity aliases config missing, falling back to empty dict.")
            EntityResolver.KNOWN_ALIASES = {}

        # Log penalties for our remaining hardcoded heuristic lists
        log_penalty("entity_resolver", "hardcode", "Hardcoded MONETARY_CUES heuristics used instead of an ontology.")
        log_penalty("entity_resolver", "hardcode", "Hardcoded FISCAL_CUES heuristics used instead of an ontology.")

        global _SHARED_SENTENCE_MODEL
        if _SHARED_SENTENCE_MODEL is None:
            _SHARED_SENTENCE_MODEL = SentenceTransformer(model_name)
        self.model = _SHARED_SENTENCE_MODEL

    def _clean_entity_name(self, name: str) -> str:
        s = name.lower().strip()
        s = re.sub(r"^the\s+", "", s) # strip leading 'the '
        s = s.replace("&", "and") # normalize '&' to 'and'
        return " ".join(s.split())

    def resolve_authorities(self, surrounding_text: str) -> Tuple[str, float]:
        """
        Decision 19 (Hardened for Critic 2.2):
        3-sentence window keyword vote with sovereign scope awareness.
        - Checks whether context mentions Indian vs foreign sovereigns.
        - Maps to RBI/GoI only when Indian sovereign context is present.
        - Maps to National Central Bank / National Government for international/foreign contexts.
        - Tied or zero -> "AMBIGUOUS" (0.40, falls below 0.65 threshold)
        """
        text_lower = surrounding_text.lower()
        monetary_hits = sum(1 for cue in self.MONETARY_CUES if cue in text_lower)
        fiscal_hits = sum(1 for cue in self.FISCAL_CUES if cue in text_lower)

        foreign_cues = ("federal reserve", "bank of england", "ecb", "treasury", "united states", "united kingdom", "fed", "fomc", "us", "uk", "eurozone")
        indian_cues = ("india", "indian", "rbi", "rupee", "inr", "crore", "lakh", "delhi", "mumbai", "union budget")
        
        is_foreign = any(fc in text_lower for fc in foreign_cues)
        is_indian = any(ic in text_lower for ic in indian_cues)

        if monetary_hits > fiscal_hits:
            if is_foreign or not is_indian:
                return "National Central Bank", 0.65
            return "Reserve Bank of India", 0.70
        elif fiscal_hits > monetary_hits:
            if is_foreign or not is_indian:
                return "National Government", 0.65
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
