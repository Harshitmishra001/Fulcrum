"""
Shortcut Audit Trail - Self-Penalization System (Decision 51).
Logs every detected hardcode, magic number, domain-specific heuristic,
and heuristic shortcut to a structured audit log.
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

AUDIT_LOG_PATH = Path(__file__).parent.parent / "audit_trail.jsonl"

logger = logging.getLogger("shortcut_audit")


def log_penalty(component: str, category: str, description: str, severity: str = "WARNING"):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "category": category,
        "description": description,
        "severity": severity
    }
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    logger.warning(f"[PENALTY] {component}: {description}")


def get_audit_summary() -> dict:
    summary = {"total": 0, "by_category": {}, "by_severity": {}}
    if not AUDIT_LOG_PATH.exists():
        return summary
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    summary["total"] += 1
                    cat = entry.get("category", "unknown")
                    sev = entry.get("severity", "unknown")
                    summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1
                    summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
    except Exception:
        pass
    return summary
