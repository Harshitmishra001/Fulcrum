import re
from typing import Dict, Any, Optional, Tuple

class PeriodNormalizer:
    """
    Deterministic period normalizer (no LLM).
    Maps fiscal year, calendar year, and quarterly strings to canonical form.
    Guards against calendar vs fiscal false comparisons.
    """

    # Closed regex lookup table for Indian fiscal years
    FY_PATTERNS = [
        (re.compile(r"FY\s*20?(\d{2})[-/]?20?(\d{2})", re.IGNORECASE), lambda m: f"FY20{m.group(2)}"),
        (re.compile(r"20(\d{2})[-/](\d{2})", re.IGNORECASE), lambda m: f"FY20{m.group(2)}"),
        (re.compile(r"FY\s*(\d{2})\b", re.IGNORECASE), lambda m: f"FY20{m.group(1)}"),
        (re.compile(r"FY\s*20(\d{2})\b", re.IGNORECASE), lambda m: f"FY20{m.group(1)}"),
    ]

    QUARTER_PATTERNS = [
        (re.compile(r"Q([1-4])\s*(?:FY|of\s*FY)?\s*20?(\d{2})", re.IGNORECASE), lambda m: f"Q{m.group(1)}_FY20{m.group(2)}"),
        (re.compile(r"20(\d{2})Q([1-4])", re.IGNORECASE), lambda m: f"Q{m.group(2)}_FY20{m.group(1)}"),
    ]

    CY_PATTERNS = [
        (re.compile(r"CY\s*20?(\d{2})", re.IGNORECASE), lambda m: f"CY20{m.group(1)}"),
        (re.compile(r"\b(20[0-3]\d)\b"), lambda m: f"CY{m.group(1)}"),
    ]

    @classmethod
    def normalize(cls, raw_text: str) -> Dict[str, Optional[str]]:
        if not raw_text or not raw_text.strip():
            return {
                "raw_text": "",
                "period_type": "unspecified",
                "normalized": None
            }

        text = raw_text.strip()

        # Check Quarter patterns first
        for pattern, formatter in cls.QUARTER_PATTERNS:
            match = pattern.search(text)
            if match:
                return {
                    "raw_text": text,
                    "period_type": "quarter",
                    "normalized": formatter(match)
                }

        # Check Fiscal Year patterns
        for pattern, formatter in cls.FY_PATTERNS:
            match = pattern.search(text)
            if match:
                return {
                    "raw_text": text,
                    "period_type": "fiscal_year",
                    "normalized": formatter(match)
                }

        # Check Calendar Year patterns
        # Only treat as CY if explicitly noted as CY or standard 4-digit year without FY cues
        if "fy" not in text.lower() and "-" not in text and "/" not in text:
            for pattern, formatter in cls.CY_PATTERNS:
                match = pattern.search(text)
                if match:
                    return {
                        "raw_text": text,
                        "period_type": "calendar_year",
                        "normalized": formatter(match)
                    }

        return {
            "raw_text": text,
            "period_type": "unspecified",
            "normalized": None
        }
