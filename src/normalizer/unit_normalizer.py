import re
from typing import Optional, Tuple

class UnitNormalizer:
    """
    Deterministic unit normalizer and tolerance-based numeric matcher.
    Handles INR Crore, Lakh, USD Billion, and Percentages.
    """

    DIMENSIONS = {
        "PERCENT": "PERCENTAGE",
        "BPS": "PERCENTAGE",
        "INR_CRORE": "CURRENCY_INR",
        "INR_LAKH": "CURRENCY_INR",
        "USD_BILLION": "CURRENCY_USD",
        "USD_MILLION": "CURRENCY_USD",
        "MILLION_TONNES": "WEIGHT",
        "GW": "POWER"
    }

    @classmethod
    def normalize_unit(cls, raw_unit: Optional[str]) -> Tuple[Optional[str], float]:
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
        if any(p in u for p in ["usd million", "us$ million", "$ million", "million usd", "mn usd"]):
            return "USD_MILLION", 0.001
        if "million tonnes" in u or "million tonne" in u or "mt" in u:
            return "MILLION_TONNES", 1.0
        if "gw" in u or "gigawatt" in u:
            return "GW", 1.0

        return raw_unit.strip(), 1.0

    @classmethod
    def values_match(cls, val_a: float, val_b: float, unit_a: Optional[str] = None, unit_b: Optional[str] = None) -> bool:
        """
        Multi-dimensional numeric tolerance rule (Decision 16 & Critic 2.4):
        - Prevents cross-currency / cross-dimension false corroboration (e.g. $5B USD != ₹5 Cr INR).
        - Applies multiplier transformations (e.g. 100 Lakh = 1 Crore, 100 BPS = 1.0%).
        - Percentage / rate: abs(a - b) <= 0.1
        - Absolute values (crore, billion, etc.): relative diff <= 0.01 (within 1%)
        """
        u_b = unit_b if unit_b is not None else unit_a
        norm_a, mult_a = cls.normalize_unit(unit_a)
        norm_b, mult_b = cls.normalize_unit(u_b)

        dim_a = cls.DIMENSIONS.get(norm_a) if norm_a else None
        dim_b = cls.DIMENSIONS.get(norm_b) if norm_b else None

        # If both units are specified and mapped to different physical/financial dimensions, reject
        if dim_a and dim_b and dim_a != dim_b:
            return False

        # If one has a currency unit and the other has a different or unmapped currency indicator, reject
        if (dim_a in ["CURRENCY_INR", "CURRENCY_USD"] or dim_b in ["CURRENCY_INR", "CURRENCY_USD"]) and dim_a != dim_b:
            return False

        # Apply multiplier transformations to common base unit
        std_a = val_a * mult_a
        std_b = val_b * mult_b

        common_dim = dim_a or dim_b

        if common_dim == "PERCENTAGE" or norm_a in ["PERCENT", "BPS"] or norm_b in ["PERCENT", "BPS"]:
            return abs(std_a - std_b) <= 0.1

        if common_dim in ["CURRENCY_INR", "CURRENCY_USD", "WEIGHT", "POWER"] or norm_a in ["INR_CRORE", "USD_BILLION", "MILLION_TONNES", "GW"]:
            denom = max(abs(std_a), abs(std_b))
            if denom == 0:
                return std_a == std_b
            return (abs(std_a - std_b) / denom) <= 0.01

        # Fallback: within 1% or exact match
        denom = max(abs(std_a), abs(std_b))
        if denom == 0:
            return std_a == std_b
        return (abs(std_a - std_b) / denom) <= 0.01 or abs(std_a - std_b) <= 0.001
