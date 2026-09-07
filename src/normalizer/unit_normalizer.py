import re
from typing import Optional, Tuple

class UnitNormalizer:
    """
    Deterministic unit normalizer and tolerance-based numeric matcher.
    Handles INR Crore, Lakh, USD Billion, and Percentages.
    """

    @classmethod
    def normalize_unit(cls, raw_unit: Optional[str]) -> Tuple[Optional[str], Optional[float]]:
        if not raw_unit:
            return None, 1.0

        u = raw_unit.lower().strip()

        if any(p in u for p in ["%", "percent", "per cent", "pct"]):
            return "PERCENT", 1.0
        if "bps" in u or "basis points" in u:
            return "BPS", 0.01 # 100 bps = 1.0 percent
        if "crore" in u:
            return "INR_CRORE", 1.0
        if "lakh" in u:
            return "INR_LAKH", 0.01 # 100 Lakh = 1 Crore
        if any(p in u for p in ["usd billion", "us$ billion", "$ billion", "billion usd", "bn usd"]):
            return "USD_BILLION", 1.0
        if "million tonnes" in u or "million tonne" in u or "mt" in u:
            return "MILLION_TONNES", 1.0
        if "gw" in u or "gigawatt" in u:
            return "GW", 1.0

        return raw_unit.strip(), 1.0

    @classmethod
    def values_match(cls, val_a: float, val_b: float, unit: Optional[str]) -> bool:
        """
        Numeric tolerance rule (Decision 16):
        - Percentage / rate: abs(a - b) <= 0.1
        - Large absolute values (crore, billion): relative diff <= 0.01 (within 1%)
        - Other: strict equality
        """
        norm_unit, _ = cls.normalize_unit(unit)

        if norm_unit in ["PERCENT", "BPS"]:
            return abs(val_a - val_b) <= 0.1

        if norm_unit in ["INR_CRORE", "INR_LAKH", "USD_BILLION", "MILLION_TONNES", "GW"]:
            denom = max(abs(val_a), abs(val_b))
            if denom == 0:
                return val_a == val_b
            return (abs(val_a - val_b) / denom) <= 0.01

        return val_a == val_b
