import os
import threading
import sqlite3
import traceback
import uuid
from typing import Dict, Any

from src.parser.pdf_chunker_v2 import PDFChunkerV2
from src.extractor.extractor_v2 import FactExtractorV2

def process_job(job_id: str, document_id: str, pdf_path: str, db_path: str, doc_hash: str):
    try:
        # Mark as running — use a fresh connection per thread
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        cur = conn.cursor()
        cur.execute("UPDATE ingestion_jobs SET status = 'running' WHERE id = ?", (job_id,))
        conn.commit()

        # Step 1: Parse and Chunk
        chunker = PDFChunkerV2(doc_slug=document_id, pdf_path=pdf_path)
        chunks = chunker.chunk_document()
        
        # Save chunks
        for chunk in chunks:
            if chunk["chunk_type"] == "table_malformed":
                try:
                    cur.execute("""
                        INSERT OR IGNORE INTO chunks (chunk_id, doc_slug, page, chunk_type, text)
                        VALUES (?, ?, ?, ?, ?)
                    """, (chunk["chunk_id"], document_id, chunk["page"], chunk["chunk_type"], "Malformed table quarantined."))
                    cur.execute("""
                        INSERT OR IGNORE INTO extraction_failures (id, chunk_id, reason)
                        VALUES (?, ?, ?)
                    """, (f"fail_{chunk['chunk_id']}", chunk["chunk_id"], "Malformed table row/column alignment detected."))
                except Exception:
                    pass
                continue

            try:
                cur.execute("""
                    INSERT OR IGNORE INTO chunks (chunk_id, doc_slug, page, chunk_type, text)
                    VALUES (?, ?, ?, ?, ?)
                """, (chunk["chunk_id"], document_id, chunk["page"], chunk["chunk_type"], chunk["text"]))
            except Exception:
                pass
        conn.commit()

        # Step 2: Extract Facts
        extractor = FactExtractorV2(db_path=db_path, release_mode=False)
        from src.normalizer.period_normalizer import PeriodNormalizer
        
        for chunk in chunks:
            if chunk["chunk_type"] == "table_malformed":
                continue
            
            chunk_dict = {
                "chunk_id": chunk["chunk_id"],
                "document_hash": doc_hash,
                "chunk_hash": chunk["chunk_hash"],
                "page": chunk["page"],
                "chunk_type": chunk["chunk_type"],
                "text": chunk["text"]
            }
            extracted_data = extractor.extract_facts(chunk_dict)

            for fact_data in extracted_data:
                try:
                    fact_id = str(uuid.uuid4())
                    
                    # Safely handle period — LLM may return a string, dict, or None
                    period_raw = fact_data.get("period")
                    if isinstance(period_raw, dict):
                        period_raw = period_raw.get("raw_text") or period_raw.get("normalized") or ""
                    period_raw = str(period_raw).strip() if period_raw else ""
                    
                    if period_raw:
                        norm_res = PeriodNormalizer.normalize(period_raw)
                        period_type = norm_res.get("period_type", "unspecified")
                        period_normalized = norm_res.get("normalized")
                    else:
                        period_type = "unspecified"
                        period_normalized = None
                    
                    assertion_type = fact_data.get("claim_basis") or "reported"
                    if assertion_type == "unknown":
                        assertion_type = "reported"
                    
                    # Safely extract numeric value
                    raw_val = fact_data.get("value")
                    try:
                        value = float(str(raw_val).replace(",", "").replace("%", "").strip()) if raw_val is not None else None
                    except (ValueError, TypeError):
                        value = None

                    cur.execute("""
                        INSERT OR IGNORE INTO facts (
                            id, extraction_run_id, is_active, entity, attribute,
                            value, unit, period_raw, period_type, period_normalized,
                            assertion_type, source_doc, source_page, source_quote,
                            chunk_id, extraction_confidence
                        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        fact_id, job_id,
                        str(fact_data.get("entity") or "Unknown"),
                        str(fact_data.get("attribute") or "Unknown"),
                        value,
                        str(fact_data.get("unit") or ""),
                        period_raw, period_type, period_normalized,
                        assertion_type,
                        document_id, chunk["page"],
                        str(fact_data.get("source_quote") or ""),
                        chunk["chunk_id"], 0.95
                    ))
                except Exception as fact_err:
                    print(f"  Skipping malformed fact: {fact_err}")
                    continue
            
            # Commit after every chunk — prevents write-lock deadlock with extractor cache conn
            conn.commit()
        
        # Deactivate old runs for this document
        cur.execute(
            "UPDATE facts SET is_active = 0 WHERE source_doc = ? AND extraction_run_id != ?",
            (document_id, job_id)
        )
        conn.commit()

        # Step 3: Run Comparison Engine
        from src.comparison.engine import ComparisonEngine
        engine = ComparisonEngine()
        engine.run_comparison()
        
        cur.execute("UPDATE ingestion_jobs SET status = 'completed' WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        print(f"Job {job_id} completed successfully.")

    except Exception as e:
        print(f"Job {job_id} failed: {traceback.format_exc()}")
        try:
            conn2 = sqlite3.connect(db_path, timeout=10.0)
            conn2.execute("UPDATE ingestion_jobs SET status = 'failed' WHERE id = ?", (job_id,))
            conn2.commit()
            conn2.close()
        except Exception:
            pass


def start_job(document_id: str, pdf_path: str, db_path: str, doc_hash: str) -> str:
    job_id = str(uuid.uuid4())
    
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ingestion_jobs (id, document_id, status, parser_version, model_version, prompt_hash)
        VALUES (?, ?, 'pending', 'pdfplumber-v2', 'gpt-4o-mini', 'v2_strict_evidence')
    """, (job_id, document_id))
    conn.commit()
    conn.close()
    
    # Use threading instead of multiprocessing — avoids Windows spawn/freeze issues
    t = threading.Thread(
        target=process_job,
        args=(job_id, document_id, pdf_path, db_path, doc_hash),
        daemon=True
    )
    t.start()
    
    return job_id
