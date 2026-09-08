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

    @staticmethod
    def _format_split_fy(m) -> Optional[str]:
        y1 = int(m.group(1))
        y2 = int(m.group(2))
        # Ensure it's a valid split year (e.g. 24-25 or 2024-25 or 1997-98)
        # and NOT a calendar date like 2024-03
        if y2 == (y1 + 1) % 100 or y2 == y1 + 1:
            cent = "19" if 70 <= y2 <= 99 else "20"
            return f"FY{cent}{y2 % 100:02d}"
        return None

    # Half-year patterns: H1/H2/1H/2H
    HALF_YEAR_PATTERNS = [
        # H1 FY24, H2 FY2024, H1 FY2024-25
        (re.compile(r"\b[Hh]([12])\s*(?:of\s+)?FY\s*(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"FY20{m.group(2)[-2:]}-H{m.group(1)}"),
        (re.compile(r"\b([12])[Hh]\s*(?:of\s+)?FY\s*(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"FY20{m.group(2)[-2:]}-H{m.group(1)}"),
        # H1 2024, H2 2024 (calendar)
        (re.compile(r"\b[Hh]([12])\s*(?:of\s+)?(?:CY\s*)?(\d{4})\b", re.IGNORECASE),
         lambda m: f"CY{m.group(2)}-H{m.group(1)}"),
        (re.compile(r"\b([12])[Hh]\s*(?:of\s+)?(?:CY\s*)?(\d{4})\b", re.IGNORECASE),
         lambda m: f"CY{m.group(2)}-H{m.group(1)}"),
    ]

    # Partial-year patterns: 9M, 3M, etc.
    PARTIAL_YEAR_PATTERNS = [
        # 9M FY24, 3M FY2024
        (re.compile(r"\b(\d{1,2})[Mm]\s*(?:of\s+)?FY\s*(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"FY20{m.group(2)[-2:]}-{m.group(1)}M"),
        (re.compile(r"\b(\d{1,2})\s*-?\s*months?\s*(?:of\s+)?FY\s*(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"FY20{m.group(2)[-2:]}-{m.group(1)}M"),
        # 9M 2024 (calendar)
        (re.compile(r"\b(\d{1,2})[Mm]\s*(?:of\s+)?(?:CY\s*)?(\d{4})\b", re.IGNORECASE),
         lambda m: f"CY{m.group(2)}-{m.group(1)}M"),
        (re.compile(r"\b(\d{1,2})\s*-?\s*months?\s*(?:of\s+)?(?:CY\s*)?(\d{4})\b", re.IGNORECASE),
         lambda m: f"CY{m.group(2)}-{m.group(1)}M"),
    ]

    # Fiscal year patterns (split year and single year)
    FY_PATTERNS = [
        (re.compile(r"\bFY\s*(?:20)?(\d{2})[-/](?:20)?(\d{2})\b", re.IGNORECASE),
         lambda m: PeriodNormalizer._format_split_fy(m) or f"FY20{m.group(2)}"),
        (re.compile(r"\b(?:20)?(\d{2})[-/](\d{2})\b", re.IGNORECASE),
         lambda m: PeriodNormalizer._format_split_fy(m)),
        (re.compile(r"\bFY\s*(\d{2})\b", re.IGNORECASE),
         lambda m: f"FY20{m.group(1)}"),
        (re.compile(r"\bFY\s*20(\d{2})\b", re.IGNORECASE),
         lambda m: f"FY20{m.group(1)}"),
        (re.compile(r"fiscal\s+year\s+(?:ended\s+.*?)?(?:20)?(\d{2,4})", re.IGNORECASE),
         lambda m: f"FY20{m.group(1)[-2:]}"),
    ]

    # Calendar year patterns
    CY_PATTERNS = [
        (re.compile(r"\bCY\s*(?:20)?(\d{2,4})\b", re.IGNORECASE), lambda m: f"CY20{m.group(1)[-2:]}"),
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

        # 0. Check ISO date pattern (e.g., 2024-03-31, 2023-12-31, 31-03-2024)
        iso_match = re.search(r"\b(19\d{2}|20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", text)
        if iso_match:
            year = iso_match.group(1)
            month = int(iso_match.group(2))
            quarter = (month - 1) // 3 + 1
            if "fy" in text.lower() or "fiscal" in text.lower():
                fy_year = year if month <= 3 else str(int(year) + 1)
                fy_q = 4 if month <= 3 else ((month - 4) // 3 + 1)
                return {
                    "raw_text": text,
                    "period_type": "fiscal_quarter",
                    "normalized": f"FY{fy_year}-Q{fy_q}"
                }
            return {
                "raw_text": text,
                "period_type": "calendar_quarter",
                "normalized": f"CY{year}-Q{quarter}"
            }

        # 1. Check Half-Year patterns FIRST (H1/H2/1H/2H) — must precede full-year patterns
        for pattern, formatter in cls.HALF_YEAR_PATTERNS:
            match = pattern.search(text)
            if match:
                res = formatter(match)
                if res:
                    period_type = "fiscal_half" if "FY" in res else "calendar_half"
                    return {
                        "raw_text": text,
                        "period_type": period_type,
                        "normalized": res
                    }

        # 2. Check Partial-Year patterns (9M, 3M, etc.) — must precede full-year patterns
        for pattern, formatter in cls.PARTIAL_YEAR_PATTERNS:
            match = pattern.search(text)
            if match:
                res = formatter(match)
                if res:
                    period_type = "fiscal_partial" if "FY" in res else "calendar_partial"
                    return {
                        "raw_text": text,
                        "period_type": period_type,
                        "normalized": res
                    }

        # 3. Check Fiscal Quarter patterns
        for pattern, formatter in cls.FISCAL_QUARTER_PATTERNS:
            match = pattern.search(text)
            if match:
                res = formatter(match)
                if res:
                    return {
                        "raw_text": text,
                        "period_type": "fiscal_quarter",
                        "normalized": res
                    }

        # 4. Check Calendar Quarter patterns (only if no explicit FY cue)
        if "fy" not in text.lower() and "fiscal" not in text.lower():
            for pattern, formatter in cls.CALENDAR_QUARTER_PATTERNS:
                match = pattern.search(text)
                if match:
                    res = formatter(match)
                    if res:
                        return {
                            "raw_text": text,
                            "period_type": "calendar_quarter",
                            "normalized": res
                        }

        # 5. Check Fiscal Year patterns
        for pattern, formatter in cls.FY_PATTERNS:
            match = pattern.search(text)
            if match:
                res = formatter(match)
                if res:
                    return {
                        "raw_text": text,
                        "period_type": "fiscal_year",
                        "normalized": res
                    }

        # 6. Check Calendar Year patterns (only if no FY or range cues)
        if "fy" not in text.lower() and "fiscal" not in text.lower() and not re.search(r"\b\d{2,4}[-/]\d{2,4}\b", text):
            for pattern, formatter in cls.CY_PATTERNS:
                match = pattern.search(text)
                if match:
                    res = formatter(match)
                    if res:
                        return {
                            "raw_text": text,
                            "period_type": "calendar_year",
                            "normalized": res
                        }

        return {
            "raw_text": text,
            "period_type": "unspecified",
            "normalized": None
        }
