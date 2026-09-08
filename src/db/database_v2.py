import os
import sqlite3
import json
import uuid
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

_thread_local = threading.local()

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
    effective_path = db_path or os.environ.get("FULCRUM_DB_PATH", "fulcrum_v2_candidate.db")
    if db_path:
        return _create_connection(effective_path)
    conn = getattr(_thread_local, 'connection', None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            _thread_local.connection = None
    conn = _create_connection(effective_path)
    _thread_local.connection = conn
    return conn

def init_db(db_path: Optional[str] = None):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    # Documents
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

    # Chunks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_hash TEXT NOT NULL,
        page INTEGER NOT NULL,
        chunk_type TEXT NOT NULL,
        text TEXT NOT NULL,
        bbox_json TEXT
    );
    """)

    # Extraction Failures (Case 4)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extraction_failures (
        id TEXT PRIMARY KEY,
        chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        reason TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Extraction Cache
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extraction_cache (
        id TEXT PRIMARY KEY,
        document_hash TEXT NOT NULL,
        chunk_hash TEXT NOT NULL,
        prompt_hash TEXT NOT NULL,
        model_identifier TEXT NOT NULL,
        raw_response TEXT NOT NULL,
        UNIQUE(document_hash, chunk_hash, prompt_hash, model_identifier)
    );
    """)

    # Facts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS facts (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
        is_active INTEGER NOT NULL DEFAULT 1,
        
        -- Semantic Fingerprint Data
        entity TEXT NOT NULL,
        attribute TEXT NOT NULL,
        canonical_entity TEXT,
        canonical_metric_family TEXT,
        value REAL,
        value_text TEXT,
        unit TEXT,
        period_raw TEXT NOT NULL,
        period_normalized TEXT,
        claim_basis TEXT,
        vintage TEXT,
        scope TEXT,
        semantic_fingerprint TEXT NOT NULL,
        
        -- Evidence Data
        chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        evidence_type TEXT NOT NULL,
        source_quote TEXT,
        evidence_bundle TEXT,
        evidence_fingerprint TEXT NOT NULL,
        
        extraction_confidence REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        -- Fingerprinting logic to prevent duplicates
        UNIQUE(job_id, semantic_fingerprint, evidence_fingerprint)
    );
    """)

    # Relations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS relations (
        id TEXT PRIMARY KEY,
        fact_a_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
        fact_b_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
        relation_type TEXT NOT NULL,
        explanation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()

if __name__ == "__main__":
    init_db()
