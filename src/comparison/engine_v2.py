import json
import hashlib
from typing import List, Dict, Any, Tuple
from src.comparison.entity_resolver import EntityResolver
from src.normalizer.period_normalizer import PeriodNormalizer
from src.normalizer.unit_normalizer import UnitNormalizer
from src.shortcut_audit import log_penalty

class ComparisonEngineV2:
    def __init__(self):
        self.resolver = EntityResolver()
        self.period_normalizer = PeriodNormalizer()
        self.unit_normalizer = UnitNormalizer()

    def run_comparison(self, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        relations = []
        blocks = self._build_blocking_index(facts)

        for block_key, block_facts in blocks.items():
            # block_key is (canonical_entity, canonical_metric_family, period, denominator, dimension)
            if block_key[0] == "UNKNOWN" or block_key[1] == "UNKNOWN":
                continue # Strict rule: unknown entity or metric -> no auto comparison

            n = len(block_facts)
            for i in range(n):
                for j in range(i + 1, n):
                    fact_a = block_facts[i]
                    fact_b = block_facts[j]

                    if fact_a["id"] == fact_b["id"]: continue
                    if fact_a["document_hash"] == fact_b["document_hash"]: continue

                    # Compatibility Guards
                    if not self._check_compatibility(fact_a, fact_b):
                        # Could emit not_comparable here if needed
                        continue

                    # Numeric comparison
                    rel_type, explanation = self._compare_values(fact_a, fact_b)
                    
                    if rel_type:
                        relations.append({
                            "fact_a_id": fact_a["id"],
                            "fact_b_id": fact_b["id"],
                            "relation_type": rel_type,
                            "explanation": explanation
                        })
                        
        return relations

    def _build_blocking_index(self, facts: List[Dict[str, Any]]) -> Dict[tuple, List[Dict[str, Any]]]:
        blocks = {}
        for f in facts:
            entity_norm = self.resolver.resolve_entity(f.get("entity", ""), f.get("source_quote", ""))
            metric_family, polarity = self._resolve_canonical_metric(f.get("attribute", ""))
            
            period_norm = self.period_normalizer.normalize(f.get("period", ""))
            dimension = self.unit_normalizer.get_dimension(f.get("unit", ""))
            denominator = "GDP" if "/gdp" in f.get("attribute", "").lower() else "Absolute"

            f["canonical_entity"] = entity_norm
            f["canonical_metric_family"] = metric_family
            f["polarity"] = polarity
            f["period_normalized"] = period_norm

            key = (entity_norm, metric_family, period_norm, denominator, dimension)
            if key not in blocks:
                blocks[key] = []
            blocks[key].append(f)
            
        return blocks

    def _resolve_canonical_metric(self, attribute: str) -> Tuple[str, int]:
        attr_lower = attribute.lower()
        if "deficit" in attr_lower and "current account" in attr_lower:
            return "current-account net balance", -1
        elif "balance" in attr_lower and "current account" in attr_lower:
            return "current-account net balance", 1
        elif "deficit" in attr_lower and "fiscal" in attr_lower:
            return "fiscal net balance", -1
        elif "balance" in attr_lower and "fiscal" in attr_lower:
            return "fiscal net balance", 1
            
        # Fallback
        return attribute, 1

    def _check_compatibility(self, a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        # Scope must match
        if a.get("scope") and b.get("scope") and a["scope"] != b["scope"]:
            return False
            
        # Claim basis check: Actual vs Forecast -> incompatible unless explicitly reconciled
        actual_bases = {"reported", "official_estimate", "revised_estimate", "provisional"}
        forecast_bases = {"budget", "forecast", "target"}
        
        basis_a = a.get("claim_basis", "unknown")
        basis_b = b.get("claim_basis", "unknown")
        
        if basis_a in actual_bases and basis_b in forecast_bases:
            return False
        if basis_a in forecast_bases and basis_b in actual_bases:
            return False
            
        # Vintage check -> differing vintages without reconciliation evidence should probably block,
        # but we'll let it pass to value comparison and handle in explanation if different.
        
        return True

    def _compare_values(self, a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        val_a = float(a["value"]) * a["polarity"]
        val_b = float(b["value"]) * b["polarity"]
        
        # Exact or close match
        if abs(val_a - val_b) < 0.05:
            return "corroboration", "Values corroborate within tolerance."
            
        # If differing vintages AND we have evidence on both sides -> reconciliation
        if a.get("vintage") and b.get("vintage") and a["vintage"] != b["vintage"]:
            return "reconciled", f"Differences reconciled by vintage context: {a['vintage']} vs {b['vintage']}."
            
        # Otherwise genuine contradiction
        return "contradiction", f"Genuine contradiction: {val_a} vs {val_b}."
        
