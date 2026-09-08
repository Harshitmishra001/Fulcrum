import os
import time
import multiprocessing
import sqlite3
import traceback
from typing import Dict, Any

from src.parser.pdf_chunker_v2 import PDFChunkerV2
from src.extractor.extractor_v2 import FactExtractorV2
from src.db.database_v2 import get_db_connection

def process_job(job_id: str, document_id: str, pdf_path: str, db_path: str, doc_hash: str):
    try:
        # Mark as running
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("UPDATE ingestion_jobs SET status = 'running' WHERE id = ?", (job_id,))
        conn.commit()

        # Step 1: Parse and Chunk
        chunker = PDFChunkerV2(doc_slug=document_id, pdf_path=pdf_path)
        chunks = chunker.chunk_document()
        
        # Save chunks (V1 schema)
        for chunk in chunks:
            if chunk["chunk_type"] == "table_malformed":
                cur.execute("""
                    INSERT OR IGNORE INTO chunks (chunk_id, doc_slug, page, chunk_type, text)
                    VALUES (?, ?, ?, ?, ?)
                """, (chunk["chunk_id"], document_id, chunk["page"], chunk["chunk_type"], "Malformed table quarantined."))
                
                cur.execute("""
                    INSERT INTO extraction_failures (id, chunk_id, reason)
                    VALUES (?, ?, ?)
                """, (f"fail_{chunk['chunk_id']}", chunk["chunk_id"], "Malformed table row/column alignment detected."))
                continue

            cur.execute("""
                INSERT OR IGNORE INTO chunks (chunk_id, doc_slug, page, chunk_type, text)
                VALUES (?, ?, ?, ?, ?)
            """, (chunk["chunk_id"], document_id, chunk["page"], chunk["chunk_type"], chunk["text"]))
        conn.commit()

        # Step 2: Extract Facts
        extractor = FactExtractorV2(db_path=db_path, release_mode=False)
        from src.normalizer.period_normalizer import PeriodNormalizer
        
        for chunk in chunks:
            if chunk["chunk_type"] == "table_malformed": continue
            
            extracted_data = extractor.extract_facts(chunk)
            for fact_data in extracted_data:
                # Format to V1 schema
                period_raw = fact_data.get("period", "")
                norm_res = PeriodNormalizer.normalize(period_raw)
                period_type = norm_res["period_type"]
                period_normalized = norm_res["normalized"]
                
                assertion_type = fact_data.get("claim_basis", "reported")
                if assertion_type == "unknown":
                    assertion_type = "reported"
                entity_val = fact_data.get("entity", "")
                attr_val = fact_data.get("attribute", "")
                fact_id = f"fact_{doc_hash}_{chunk['chunk_id']}_{hash(f'{entity_val}_{attr_val}') % 10000}"
                
                cur.execute("""
                    INSERT OR IGNORE INTO facts (
                        id, extraction_run_id, is_active, entity, attribute, value, unit, period_raw, 
                        period_type, period_normalized, assertion_type, source_doc, source_page, 
                        source_quote, chunk_id, extraction_confidence
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0)
                """, (
                    fact_id, job_id, fact_data.get("entity", ""), fact_data.get("attribute", ""),
                    float(fact_data.get("value", 0)) if str(fact_data.get("value", "")).replace(".","").isdigit() else None,
                    fact_data.get("unit", ""), period_raw, period_type, period_normalized, 
                    assertion_type, document_id, chunk["page"], fact_data.get("source_quote", ""), chunk["chunk_id"]
                ))
        
        conn.commit()
        
        # Mark other runs as inactive for this doc_slug
        cur.execute("UPDATE facts SET is_active = 0 WHERE source_doc = ? AND extraction_run_id != ?", (document_id, job_id))
        conn.commit()

        # Step 3: Run Comparison
        from src.comparison.engine import ComparisonEngine
        engine = ComparisonEngine()
        engine.run_comparison()
        
        cur.execute("UPDATE ingestion_jobs SET status = 'completed' WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Job {job_id} failed: {traceback.format_exc()}")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("UPDATE ingestion_jobs SET status = 'failed' WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()

def start_job(document_id: str, pdf_path: str, db_path: str, doc_hash: str) -> str:
    import uuid
    job_id = str(uuid.uuid4())
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ingestion_jobs (id, document_id, status, parser_version, model_version, prompt_hash)
        VALUES (?, ?, 'pending', 'pdfplumber-v2', 'gpt-4o-mini', 'v2_strict_evidence')
    """, (job_id, document_id))
    conn.commit()
    conn.close()
    
    # Spawn process
    p = multiprocessing.Process(target=process_job, args=(job_id, document_id, pdf_path, db_path, doc_hash))
    p.start()
    
    return job_id
