import os
import sqlite3
import json
import uuid
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

_thread_local = threading.local()

# Resolve DB path from environment or config
DB_PATH = os.environ.get("FULCRUM_DB_PATH") or os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent.parent / "fulcrum.db"))


def _create_connection(db_path: str) -> sqlite3.Connection:
    """Creates a new SQLite connection with all required PRAGMAs."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
    except sqlite3.OperationalError:
        pass
    return conn


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Thread-local connection pooling. Custom db_path bypasses pool (for tests)."""
    effective_path = db_path or os.environ.get("FULCRUM_DB_PATH") or DB_PATH
    # Custom path = non-pooled (tests, one-off scripts)
    if db_path:
        return _create_connection(effective_path)
    # Thread-local connection reuse — avoids re-executing PRAGMAs per call
    conn = getattr(_thread_local, 'connection', None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")  # liveness check
            return conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            _thread_local.connection = None
    conn = _create_connection(effective_path)
    _thread_local.connection = conn
    return conn


def init_db(db_path: Optional[str] = None):
    """Initialize the database schema (V1 — compatible with live fulcrum.db)."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Documents table (V2 addition — safe to create even against V1 DB)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        file_hash TEXT UNIQUE NOT NULL,
        filename TEXT NOT NULL,
        ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Jobs / Extraction Runs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ingestion_jobs (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        status TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        model_version TEXT NOT NULL,
        prompt_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Chunks table — V1 schema (matches live fulcrum.db)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_slug TEXT NOT NULL,
        page INTEGER NOT NULL,
        chunk_type TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_page ON chunks (doc_slug, page);")

    # Facts table — V1 schema (matches live fulcrum.db)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS facts (
        id TEXT PRIMARY KEY,
        extraction_run_id TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        entity TEXT NOT NULL,
        attribute TEXT NOT NULL,
        value REAL,
        value_text TEXT,
        unit TEXT,
        period_raw TEXT NOT NULL,
        period_type TEXT NOT NULL,
        period_normalized TEXT,
        assertion_type TEXT NOT NULL,
        source_doc TEXT NOT NULL,
        source_page INTEGER NOT NULL,
        source_quote TEXT NOT NULL,
        chunk_id TEXT NOT NULL,
        extraction_confidence REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Relations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS relations (
        id TEXT PRIMARY KEY,
        fact_a_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
        fact_b_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
        relation_type TEXT NOT NULL,
        explanation TEXT NOT NULL,
        evidence_quote TEXT,
        entity_resolution_confidence REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Extraction failures
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extraction_failures (
        id TEXT PRIMARY KEY,
        chunk_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Extraction cache (LLM response cache keyed by chunk hash)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extraction_cache (
        chunk_hash TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(is_active);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_entity_attr ON facts(entity, attribute, is_active);")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique_pair ON relations(fact_a_id, fact_b_id);")

    conn.commit()
    if db_path:
        conn.close()


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def get_active_facts(doc_filter: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all active facts, optionally filtered by source_doc."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    if doc_filter:
        cursor.execute(
            "SELECT * FROM facts WHERE is_active = 1 AND source_doc = ? ORDER BY source_doc, source_page",
            (doc_filter,)
        )
    else:
        cursor.execute(
            "SELECT * FROM facts WHERE is_active = 1 ORDER BY source_doc, source_page"
        )
    rows = [dict(r) for r in cursor.fetchall()]
    if db_path:
        conn.close()
    return rows


def save_fact(fact_data: Dict[str, Any], extraction_run_id: str, db_path: Optional[str] = None) -> str:
    """Insert a single fact row. Returns the fact ID."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    fact_id = fact_data.get("id") or str(uuid.uuid4())

    period = fact_data.get("period") or {}
    if isinstance(period, str):
        period_raw = period
        period_type = "unspecified"
        period_normalized = None
    else:
        period_raw = period.get("raw_text") or period.get("normalized") or ""
        period_type = period.get("period_type") or "unspecified"
        period_normalized = period.get("normalized")

    raw_val = fact_data.get("value")
    try:
        value = float(str(raw_val).replace(",", "").replace("%", "").strip()) if raw_val is not None else None
    except (ValueError, TypeError):
        value = None

    assertion_type = fact_data.get("assertion_type") or "reported"

    cursor.execute("""
        INSERT OR IGNORE INTO facts (
            id, extraction_run_id, is_active, entity, attribute,
            value, unit, period_raw, period_type, period_normalized,
            assertion_type, source_doc, source_page, source_quote,
            chunk_id, extraction_confidence
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fact_id, extraction_run_id,
        str(fact_data.get("entity") or "Unknown"),
        str(fact_data.get("attribute") or "Unknown"),
        value,
        str(fact_data.get("unit") or ""),
        period_raw, period_type, period_normalized,
        assertion_type,
        str(fact_data.get("source_doc") or ""),
        int(fact_data.get("source_page") or 0),
        str(fact_data.get("source_quote") or ""),
        str(fact_data.get("chunk_id") or ""),
        float(fact_data.get("extraction_confidence") or 0.95)
    ))
    conn.commit()
    if db_path:
        conn.close()
    return fact_id


def save_relation(relation: Dict[str, Any], db_path: Optional[str] = None):
    """Insert a single relation (upsert on conflict).
    
    Canonically orders fact_a_id/fact_b_id so (A,B) and (B,A) deduplicate via UNIQUE index.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    rel_id = relation.get("id") or str(uuid.uuid4())
    # Canonical ordering: smaller ID always goes into fact_a_id to catch reversed duplicates
    fa, fb = relation["fact_a_id"], relation["fact_b_id"]
    if fa > fb:
        fa, fb = fb, fa
    cursor.execute("""
        INSERT OR IGNORE INTO relations (
            id, fact_a_id, fact_b_id, relation_type, explanation,
            evidence_quote, entity_resolution_confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        rel_id, fa, fb,
        relation["relation_type"],
        relation["explanation"],
        relation.get("evidence_quote"),
        float(relation.get("entity_resolution_confidence") or 0.0)
    ))
    conn.commit()
    if db_path:
        conn.close()


def save_relations_batch(relations: List[Dict[str, Any]], db_path: Optional[str] = None):
    """Batch-insert relations (INSERT OR IGNORE to skip existing pairs).
    
    Canonically orders fact_a_id/fact_b_id so reversed pairs deduplicate via UNIQUE index.
    """
    if not relations:
        return
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    rows = []
    for r in relations:
        fa, fb = r["fact_a_id"], r["fact_b_id"]
        if fa > fb:
            fa, fb = fb, fa
        rows.append((
            r.get("id") or str(uuid.uuid4()),
            fa, fb,
            r["relation_type"],
            r["explanation"],
            r.get("evidence_quote"),
            float(r.get("entity_resolution_confidence") or 0.0)
        ))
    cursor.executemany("""
        INSERT OR IGNORE INTO relations (
            id, fact_a_id, fact_b_id, relation_type, explanation,
            evidence_quote, entity_resolution_confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    if db_path:
        conn.close()


def save_chunks_batch(chunks: List[Dict[str, Any]], db_path: Optional[str] = None) -> int:
    """Batch-insert parsed document chunks. Returns number of rows inserted."""
    if not chunks:
        return 0
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    rows = [
        (c["chunk_id"], c["doc_slug"], c["page"], c["chunk_type"], c["text"])
        for c in chunks
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO chunks (chunk_id, doc_slug, page, chunk_type, text)
        VALUES (?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    inserted = cursor.rowcount if len(rows) == 1 else len(rows)
    if db_path:
        conn.close()
    return inserted


def get_chunk_text(chunk_id: str, db_path: Optional[str] = None) -> Optional[str]:
    """Fetch the text of a single chunk by its ID."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT text FROM chunks WHERE chunk_id = ?", (chunk_id,))
    row = cursor.fetchone()
    if db_path:
        conn.close()
    return row[0] if row else None


def get_chunks_by_page(doc_slug: str, page: int, window: int = 0, db_path: Optional[str] = None) -> List[str]:
    """Return list of chunk texts for a given document page.
    
    If window > 0, also returns chunks from adjacent pages within ±window.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT text FROM chunks WHERE doc_slug = ? AND page BETWEEN ? AND ? ORDER BY page",
        (doc_slug, page - window, page + window)
    )
    rows = [r[0] for r in cursor.fetchall()]
    if db_path:
        conn.close()
    return rows


def get_all_chunk_texts(db_path: Optional[str] = None) -> Dict[str, str]:
    """Return a dict mapping chunk_id -> text for ALL chunks (pre-load cache)."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT chunk_id, text FROM chunks")
    result = {row[0]: row[1] for row in cursor.fetchall()}
    if db_path:
        conn.close()
    return result


def get_all_page_chunks(db_path: Optional[str] = None) -> Dict[tuple, List[str]]:
    """Return a dict mapping (doc_slug, page) -> [text, ...] for ALL chunks."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT doc_slug, page, text FROM chunks")
    result: Dict[tuple, List[str]] = {}
    for row in cursor.fetchall():
        key = (row[0], row[1])
        result.setdefault(key, []).append(row[2])
    if db_path:
        conn.close()
    return result


def get_all_relations(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all relations."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM relations ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    if db_path:
        conn.close()
    return rows


def deactivate_previous_runs(source_doc: str, current_run_id: str, db_path: Optional[str] = None):
    """Mark all facts for source_doc except the current run as inactive."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE facts SET is_active = 0 WHERE source_doc = ? AND extraction_run_id != ?",
        (source_doc, current_run_id)
    )
    conn.commit()
    if db_path:
        conn.close()