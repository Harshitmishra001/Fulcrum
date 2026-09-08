import re
from typing import Optional, Tuple
from src.config import PERCENTAGE_TOLERANCE, ABSOLUTE_TOLERANCE

class UnitNormalizer:
    """
    Deterministic unit normalizer and tolerance-based numeric matcher.
    Enforces dimensional compatibility across currencies, percentages, and physical units.
    """

    DIMENSIONS = {
        "PERCENT": "PERCENTAGE",
        "BPS": "PERCENTAGE",
        "INR_CRORE": "CURRENCY_INR",
        "INR_LAKH": "CURRENCY_INR",
        "INR": "CURRENCY_INR",
        "USD_BILLION": "CURRENCY_USD",
        "USD_MILLION": "CURRENCY_USD",
        "USD": "CURRENCY_USD",
        "EUR_BILLION": "CURRENCY_EUR",
        "EUR_MILLION": "CURRENCY_EUR",
        "EUR": "CURRENCY_EUR",
        "GBP_BILLION": "CURRENCY_GBP",
        "GBP_MILLION": "CURRENCY_GBP",
        "GBP": "CURRENCY_GBP",
        "JPY_TRILLION": "CURRENCY_JPY",
        "JPY_BILLION": "CURRENCY_JPY",
        "JPY": "CURRENCY_JPY",
        "MILLION_TONNES": "WEIGHT",
        "GW": "POWER",
        "MW": "POWER"
    }

    @classmethod
    def normalize_unit(cls, raw_unit: Optional[str]) -> Tuple[Optional[str], float]:
        if not raw_unit:
            return None, 1.0

        u = raw_unit.lower().strip()

        # Percentages
        if any(p in u for p in ["%", "percent", "per cent", "pct"]):
            return "PERCENT", 1.0
        if "bps" in u or "basis points" in u or "basis point" in u:
            return "BPS", 0.01 # 100 bps = 1.0 percent

        # INR
        if "crore" in u:
            return "INR_CRORE", 1.0
        if "lakh" in u:
            return "INR_LAKH", 0.01 # 100 Lakh = 1 Crore
        if any(p in u for p in ["inr", "rupee", "rs", "₹"]):
            return "INR", 1e-7 # 1 INR = 1e-7 Crore

        # USD
        if any(p in u for p in ["usd billion", "us$ billion", "$ billion", "billion usd", "bn usd"]):
            return "USD_BILLION", 1.0
        if any(p in u for p in ["usd million", "us$ million", "$ million", "million usd", "mn usd"]):
            return "USD_MILLION", 0.001
        if any(p in u for p in ["usd", "us$", "$"]):
            return "USD", 1e-9

        # EUR
        if any(p in u for p in ["eur billion", "€ billion", "billion eur"]):
            return "EUR_BILLION", 1.0
        if any(p in u for p in ["eur million", "€ million", "million eur"]):
            return "EUR_MILLION", 0.001
        if any(p in u for p in ["eur", "euro", "€"]):
            return "EUR", 1e-9

        # GBP
        if any(p in u for p in ["gbp billion", "£ billion", "billion gbp"]):
            return "GBP_BILLION", 1.0
        if any(p in u for p in ["gbp million", "£ million", "million gbp"]):
            return "GBP_MILLION", 0.001
        if any(p in u for p in ["gbp", "pound", "£"]):
            return "GBP", 1e-9

        # JPY
        if any(p in u for p in ["jpy trillion", "¥ trillion", "trillion jpy"]):
            return "JPY_TRILLION", 1000.0
        if any(p in u for p in ["jpy billion", "¥ billion", "billion jpy"]):
            return "JPY_BILLION", 1.0
        if any(p in u for p in ["jpy", "yen", "¥"]):
            return "JPY", 1e-9

        # Physical
        if "million tonnes" in u or "million tonne" in u or "mt" in u:
            return "MILLION_TONNES", 1.0
        if "gw" in u or "gigawatt" in u:
            return "GW", 1.0
        if "mw" in u or "megawatt" in u:
            return "MW", 0.001

        return raw_unit.strip().lower(), 1.0

    @classmethod
    def values_match(cls, val_a: float, val_b: float, unit_a: Optional[str] = None, unit_b: Optional[str] = None) -> bool:
        """
        Multi-dimensional numeric tolerance rule:
        - Rejects comparisons across incompatible dimensions (e.g. USD vs INR, JPY vs EUR).
        - Rejects comparisons between different unmapped units (e.g. 'miles' vs 'hours').
        - Applies multiplier transformations (e.g. 100 Lakh = 1 Crore, 100 BPS = 1.0%).
        - Strict percentage tolerance: abs(std_a - std_b) <= PERCENTAGE_TOLERANCE (0.05pp).
          Distinguishes genuine revisions (e.g. 6.4% vs 6.5% is 10bps difference, not a match).
        - Absolute values: relative difference <= ABSOLUTE_TOLERANCE (1%).
        """
        u_b = unit_b if unit_b is not None else unit_a
        norm_a, mult_a = cls.normalize_unit(unit_a)
        norm_b, mult_b = cls.normalize_unit(u_b)

        dim_a = cls.DIMENSIONS.get(norm_a) if norm_a else None
        dim_b = cls.DIMENSIONS.get(norm_b) if norm_b else None

        # 1. If both units are mapped to dimensions, they MUST belong to the same dimension
        if dim_a and dim_b and dim_a != dim_b:
            return False

        # 2. If one unit has a known dimension and the other does not (e.g. USD vs unmapped), reject
        if (dim_a and not dim_b and norm_b) or (dim_b and not dim_a and norm_a):
            return False

        # 3. If neither unit has a known dimension, but both are specified and differ textually, reject
        if not dim_a and not dim_b and norm_a and norm_b and norm_a != norm_b:
            return False

        # Apply multiplier transformations to common base unit
        std_a = val_a * mult_a
        std_b = val_b * mult_b

        common_dim = dim_a or dim_b

        # Percentage comparison: strict rounding tolerance (default 0.05pp)
        if common_dim == "PERCENTAGE" or norm_a in ["PERCENT", "BPS"] or norm_b in ["PERCENT", "BPS"]:
            return abs(std_a - std_b) <= PERCENTAGE_TOLERANCE

        # Denominated physical or financial values: within 1%
        denom = max(abs(std_a), abs(std_b))
        if denom == 0:
            return std_a == std_b

        return (abs(std_a - std_b) / denom) <= ABSOLUTE_TOLERANCE or abs(std_a - std_b) <= 0.001
