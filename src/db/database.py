import os
import sqlite3
import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.config import DB_PATH

def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    effective_path = db_path or os.environ.get("FULCRUM_DB_PATH") or DB_PATH
    conn = sqlite3.connect(effective_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
    except sqlite3.OperationalError:
        pass
    return conn

def init_db(db_path: Optional[str] = None):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    # Facts table
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
        fact_a_id TEXT NOT NULL,
        fact_b_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        explanation TEXT NOT NULL,
        evidence_quote TEXT,
        entity_resolution_confidence REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (fact_a_id) REFERENCES facts(id),
        FOREIGN KEY (fact_b_id) REFERENCES facts(id)
    );
    """)

    # Chunks table: stores complete document text units (prose, tables, footnotes)
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
    
    # Indexes for performance and deduplication
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(is_active);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_doc ON facts(source_doc, is_active);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_entity_attr ON facts(entity, attribute, is_active);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_pair ON relations(fact_a_id, fact_b_id);")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique_pair ON relations(fact_a_id, fact_b_id);")
    
    conn.commit()
    conn.close()

def save_fact(fact_dict: Dict[str, Any], extraction_run_id: str) -> str:
    """Inserts a single fact into the database immediately."""
    conn = get_db_connection()
    cursor = conn.cursor()
    fact_id = fact_dict.get('id') or str(uuid.uuid4())
    
    val = fact_dict.get('value')
    val_num = None
    val_text = None
    if isinstance(val, (int, float)):
        val_num = float(val)
    elif isinstance(val, str):
        try:
            val_num = float(val.replace(',', '').replace('%', '').strip())
        except ValueError:
            val_text = val
    
    period = fact_dict.get('period', {})
    if isinstance(period, str):
        period_raw = period
        period_type = 'unspecified'
        period_norm = None
    else:
        period_raw = period.get('raw_text', '')
        period_type = period.get('period_type', 'unspecified')
        period_norm = period.get('normalized')

    chunk_id = fact_dict.get('chunk_id', '')
    source_page = fact_dict.get('source_page')
    if not source_page and '__p' in chunk_id:
        try:
            source_page = int(chunk_id.split('__')[1][1:])
        except (IndexError, ValueError):
            source_page = 1
    elif not source_page:
        source_page = 1

    cursor.execute("""
    INSERT OR REPLACE INTO facts (
        id, extraction_run_id, is_active, entity, attribute, value, value_text, unit,
        period_raw, period_type, period_normalized, assertion_type,
        source_doc, source_page, source_quote, chunk_id, extraction_confidence
    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fact_id,
        extraction_run_id,
        fact_dict.get('entity', 'Unknown'),
        fact_dict.get('attribute', 'Unknown'),
        val_num,
        val_text,
        fact_dict.get('unit'),
        period_raw,
        period_type,
        period_norm,
        fact_dict.get('assertion_type', 'stated'),
        fact_dict.get('source_doc', ''),
        source_page,
        fact_dict.get('source_quote', ''),
        chunk_id,
        float(fact_dict.get('extraction_confidence', 1.0))
    ))
    conn.commit()
    conn.close()
    return fact_id

def deactivate_previous_runs(source_doc: str, current_run_id: str):
    """Marks older extraction runs for this document as is_active = 0."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE facts SET is_active = 0 
        WHERE source_doc = ? AND extraction_run_id != ?
    """, (source_doc, current_run_id))
    conn.commit()
    conn.close()

def get_active_facts(doc_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all active facts from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if doc_filter:
        cursor.execute("SELECT * FROM facts WHERE is_active = 1 AND source_doc = ? ORDER BY source_page ASC", (doc_filter,))
    else:
        cursor.execute("SELECT * FROM facts WHERE is_active = 1 ORDER BY source_doc, source_page ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def save_relation(rel_dict: Dict[str, Any]) -> str:
    """Saves or updates a relation between two facts without duplicating pairs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if a relation between this pair (in either direction) already exists
    cursor.execute("""
    SELECT id FROM relations 
    WHERE (fact_a_id = ? AND fact_b_id = ?) 
       OR (fact_a_id = ? AND fact_b_id = ?)
    """, (rel_dict['fact_a_id'], rel_dict['fact_b_id'], rel_dict['fact_b_id'], rel_dict['fact_a_id']))
    existing = cursor.fetchone()
    
    rel_id = existing['id'] if existing else (rel_dict.get('id') or str(uuid.uuid4()))
    
    cursor.execute("""
    INSERT OR REPLACE INTO relations (
        id, fact_a_id, fact_b_id, relation_type, explanation, evidence_quote, entity_resolution_confidence
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        rel_id,
        rel_dict['fact_a_id'],
        rel_dict['fact_b_id'],
        rel_dict['relation_type'],
        rel_dict.get('explanation', ''),
        rel_dict.get('evidence_quote'),
        float(rel_dict.get('entity_resolution_confidence', 1.0))
    ))
    conn.commit()
    conn.close()
    return rel_id

def save_relations_batch(relations: List[Dict[str, Any]]) -> int:
    """Saves multiple relations in a single atomic transaction without opening/closing connections repeatedly."""
    if not relations:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    saved_count = 0
    for rel_dict in relations:
        cursor.execute("""
        SELECT id FROM relations 
        WHERE (fact_a_id = ? AND fact_b_id = ?) 
           OR (fact_a_id = ? AND fact_b_id = ?)
        """, (rel_dict['fact_a_id'], rel_dict['fact_b_id'], rel_dict['fact_b_id'], rel_dict['fact_a_id']))
        existing = cursor.fetchone()
        rel_id = existing['id'] if existing else (rel_dict.get('id') or str(uuid.uuid4()))
        cursor.execute("""
        INSERT OR REPLACE INTO relations (
            id, fact_a_id, fact_b_id, relation_type, explanation, evidence_quote, entity_resolution_confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            rel_id,
            rel_dict['fact_a_id'],
            rel_dict['fact_b_id'],
            rel_dict['relation_type'],
            rel_dict.get('explanation', ''),
            rel_dict.get('evidence_quote'),
            float(rel_dict.get('entity_resolution_confidence', 1.0))
        ))
        saved_count += 1
    conn.commit()
    conn.close()
    return saved_count

def get_all_relations() -> List[Dict[str, Any]]:
    """Retrieves all relations."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM relations ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def save_chunks_batch(chunks: List[Dict[str, Any]], db_path: Optional[str] = None) -> int:
    """Saves parsed document chunks into SQLite."""
    if not chunks:
        return 0
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    saved = 0
    for c in chunks:
        cursor.execute("""
        INSERT OR REPLACE INTO chunks (chunk_id, doc_slug, page, chunk_type, text)
        VALUES (?, ?, ?, ?, ?)
        """, (
            c["chunk_id"],
            c.get("doc_slug", "unknown"),
            c.get("page", 1),
            c.get("chunk_type", "prose"),
            c.get("text", "")
        ))
        saved += 1
    conn.commit()
    conn.close()
    return saved

def get_chunk_text(chunk_id: str, db_path: Optional[str] = None) -> Optional[str]:
    """Retrieves full text of a specific chunk by ID."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT text FROM chunks WHERE chunk_id = ?", (chunk_id,))
    row = cursor.fetchone()
    conn.close()
    return row["text"] if row else None

def get_chunks_by_page(doc_slug: str, page: int, window: int = 1, db_path: Optional[str] = None) -> List[str]:
    """Retrieves all chunk texts for a document within +/- window pages."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT text FROM chunks 
    WHERE doc_slug = ? AND page BETWEEN ? AND ?
    ORDER BY page, chunk_id
    """, (doc_slug, page - window, page + window))
    rows = cursor.fetchall()
    conn.close()
    return [r["text"] for r in rows]
