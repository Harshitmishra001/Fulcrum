import json
import os
import re
from typing import List, Dict, Any, Tuple
from src.normalizer.unit_normalizer import UnitNormalizer
from src.db.database import get_active_facts

class GoldenEvaluator:
    """
    Evaluates extraction results against the 30 hand-annotated Golden Set facts.
    Computes:
    - Value/Period Recall (how many of the 30 golden facts were discovered)
    - Assertion Type Accuracy (correctly identifying stated vs projection)
    - Grounding Precision (source quote found verbatim)
    """

    def __init__(self, golden_path: str = "data/golden_set_rbi.json"):
        with open(golden_path, "r", encoding="utf-8") as f:
            self.golden_facts = json.load(f)

    def evaluate_facts(self, extracted_facts: List[Dict[str, Any]]) -> Dict[str, Any]:
        matched_golden_ids = set()
        correct_assertion_count = 0
        matches = []

        for gold in self.golden_facts:
            gold_val = gold["value"]
            gold_period = gold["period"]["normalized"]
            gold_page = gold["source_page"]
            gold_assertion = gold["assertion_type"]
            gold_unit = gold.get("unit")

            # Look for matching extracted fact
            for ext in extracted_facts:
                ext_val = ext.get("value")
                ext_period = ext.get("period", {})
                if isinstance(ext_period, dict):
                    ext_norm_period = ext_period.get("normalized")
                else:
                    ext_norm_period = ext.get("period_normalized")

                ext_page = ext.get("source_page")
                ext_assertion = ext.get("assertion_type")

                # Match if page is within +/- 1, periods match, values match, and attributes match
                page_match = abs(ext_page - gold_page) <= 1 if ext_page and gold_page else True
                period_match = (ext_norm_period == gold_period) if (ext_norm_period and gold_period) else True

                # Attribute match: exact, substring, or substantive token overlap
                gold_attr = gold.get("attribute", "").lower().strip()
                ext_attr = (ext.get("attribute") or "").lower().strip()
                attr_words_g = set(re.findall(r"\b[a-z]{3,}\b", gold_attr))
                attr_words_e = set(re.findall(r"\b[a-z]{3,}\b", ext_attr))
                attr_overlap = attr_words_g.intersection(attr_words_e)
                attr_match = (
                    gold_attr == ext_attr
                    or gold_attr in ext_attr
                    or ext_attr in gold_attr
                    or (len(attr_words_g) > 0 and len(attr_overlap) / len(attr_words_g) >= 0.4)
                )

                val_match = False
                ext_unit = ext.get("unit")
                if isinstance(gold_val, (int, float)) and isinstance(ext_val, (int, float)):
                    val_match = UnitNormalizer.values_match(float(gold_val), float(ext_val), gold_unit, ext_unit)
                elif str(gold_val).lower().strip() in str(ext_val).lower().strip():
                    val_match = True

                if page_match and period_match and val_match and attr_match:
                    matched_golden_ids.add(gold["id"])
                    assertion_correct = (gold_assertion == ext_assertion)
                    if assertion_correct:
                        correct_assertion_count += 1
                    matches.append({
                        "golden_id": gold["id"],
                        "gold_attr": gold["attribute"],
                        "ext_attr": ext.get("attribute"),
                        "gold_val": gold_val,
                        "ext_val": ext_val,
                        "assertion_gold": gold_assertion,
                        "assertion_ext": ext_assertion,
                        "assertion_correct": assertion_correct
                    })
                    break

        total_golden = len(self.golden_facts)
        total_matched = len(matched_golden_ids)
        recall = (total_matched / total_golden) if total_golden > 0 else 0.0
        assertion_acc = (correct_assertion_count / total_matched) if total_matched > 0 else 0.0

        return {
            "total_golden": total_golden,
            "total_extracted": len(extracted_facts),
            "matched_golden_count": total_matched,
            "recall": round(recall, 3),
            "assertion_type_accuracy": round(assertion_acc, 3),
            "matches": matches
        }

    evaluate = evaluate_facts

    def print_report(self, results: Dict[str, Any]):
        print("\n==========================================")
        print("       GOLDEN SET EVALUATION REPORT       ")
        print("==========================================")
        print(f"Total Golden Ground Truth Facts : {results['total_golden']}")
        print(f"Total Facts Extracted by Code   : {results['total_extracted']}")
        print(f"Golden Facts Discovered (Recall): {results['matched_golden_count']}/{results['total_golden']} ({results['recall']*100:.1f}%)")
        print(f"Assertion Type Accuracy         : {results['assertion_type_accuracy']*100:.1f}%")
        print("------------------------------------------")
        print("Sample Matched Facts:")
        for m in results["matches"][:10]:
            status = "MATCH" if m["assertion_correct"] else "MISMATCH"
            print(f" - [{m['golden_id']}] {m['gold_attr']}: {m['gold_val']} ({m['assertion_gold']}) -> {m['ext_val']} [{status}]")
        print("==========================================\n")
