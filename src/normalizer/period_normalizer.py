import re
from typing import Dict, Any, Optional, Tuple

class PeriodNormalizer:
    """
    Deterministic period normalizer (no LLM).
    Maps fiscal year, calendar year, and quarterly strings to canonical form.
    Guards against calendar vs fiscal false comparisons.
    """

    # Generalized patterns for quarters (separating fiscal vs calendar quarters)
    FISCAL_QUARTER_PATTERNS = [
        (re.compile(r"Q([1-4])\s*(?:of\s+)?FY\s*(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"FY20{m.group(2)[-2:]}-Q{m.group(1)}"),
        (re.compile(r"FY\s*(?:20)?(\d{2,4})\s*[-_]?\s*Q([1-4])", re.IGNORECASE),
         lambda m: f"FY20{m.group(1)[-2:]}-Q{m.group(2)}"),
        (re.compile(r"(?:first|1st|second|2nd|third|3rd|fourth|4th)\s+quarter\s+of\s+FY\s*(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"FY20{m.group(1)[-2:]}-Q1" if "first" in m.group(0).lower() or "1st" in m.group(0).lower()
         else (f"FY20{m.group(1)[-2:]}-Q2" if "second" in m.group(0).lower() or "2nd" in m.group(0).lower()
         else (f"FY20{m.group(1)[-2:]}-Q3" if "third" in m.group(0).lower() or "3rd" in m.group(0).lower()
         else f"FY20{m.group(1)[-2:]}-Q4"))),
    ]

    CALENDAR_QUARTER_PATTERNS = [
        (re.compile(r"Q([1-4])\s*(?:of\s+)?(?:CY)?\s*(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"CY20{m.group(2)[-2:]}-Q{m.group(1)}"),
        (re.compile(r"(?:20)?(\d{2})\s*[-_]?\s*Q([1-4])", re.IGNORECASE),
         lambda m: f"CY20{m.group(1)[-2:]}-Q{m.group(2)}"),
    ]

    # Fiscal year patterns (split year and single year)
    FY_PATTERNS = [
        (re.compile(r"FY\s*(?:20)?(\d{2})[-/](?:20)?(\d{2})", re.IGNORECASE), lambda m: f"FY20{m.group(2)}"),
        (re.compile(r"20(\d{2})[-/](\d{2})", re.IGNORECASE), lambda m: f"FY20{m.group(2)}"),
        (re.compile(r"FY\s*(\d{2})\b", re.IGNORECASE), lambda m: f"FY20{m.group(1)}"),
        (re.compile(r"FY\s*20(\d{2})\b", re.IGNORECASE), lambda m: f"FY20{m.group(1)}"),
        (re.compile(r"fiscal\s+year\s+(?:ended\s+.*?)?(?:20)?(\d{2,4})", re.IGNORECASE), lambda m: f"FY20{m.group(1)[-2:]}"),
    ]

    # Calendar year patterns
    CY_PATTERNS = [
        (re.compile(r"CY\s*(?:20)?(\d{2,4})", re.IGNORECASE), lambda m: f"CY20{m.group(1)[-2:]}"),
        (re.compile(r"calendar\s+year\s+(?:20)?(\d{2,4})", re.IGNORECASE), lambda m: f"CY20{m.group(1)[-2:]}"),
        (re.compile(r"\b(19\d{2}|20\d{2})\b"), lambda m: f"CY{m.group(1)}"),
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

        # 1. Check Fiscal Quarter patterns first
        for pattern, formatter in cls.FISCAL_QUARTER_PATTERNS:
            match = pattern.search(text)
            if match:
                return {
                    "raw_text": text,
                    "period_type": "fiscal_quarter",
                    "normalized": formatter(match)
                }

        # 2. Check Calendar Quarter patterns (only if no explicit FY cue)
        if "fy" not in text.lower() and "fiscal" not in text.lower():
            for pattern, formatter in cls.CALENDAR_QUARTER_PATTERNS:
                match = pattern.search(text)
                if match:
                    return {
                        "raw_text": text,
                        "period_type": "calendar_quarter",
                        "normalized": formatter(match)
                    }

        # 3. Check Fiscal Year patterns
        for pattern, formatter in cls.FY_PATTERNS:
            match = pattern.search(text)
            if match:
                return {
                    "raw_text": text,
                    "period_type": "fiscal_year",
                    "normalized": formatter(match)
                }

        # 4. Check Calendar Year patterns (only if no FY or range cues)
        if "fy" not in text.lower() and "fiscal" not in text.lower() and "-" not in text and "/" not in text:
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
