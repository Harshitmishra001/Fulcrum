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
        
        # Save chunks
        for chunk in chunks:
            if chunk["chunk_type"] == "table_malformed":
                cur.execute("""
                    INSERT OR IGNORE INTO chunks (id, document_id, chunk_hash, page, chunk_type, text, bbox_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (chunk["chunk_id"], document_id, chunk["chunk_hash"], chunk["page"], chunk["chunk_type"], chunk["text"], chunk["bbox_json"]))
                
                cur.execute("""
                    INSERT INTO extraction_failures (id, chunk_id, reason)
                    VALUES (?, ?, ?)
                """, (f"fail_{chunk['chunk_id']}", chunk["chunk_id"], "Malformed table row/column alignment detected."))
                continue

            cur.execute("""
                INSERT OR IGNORE INTO chunks (id, document_id, chunk_hash, page, chunk_type, text, bbox_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (chunk["chunk_id"], document_id, chunk["chunk_hash"], chunk["page"], chunk["chunk_type"], chunk["text"], chunk["bbox_json"]))
        conn.commit()

        # Step 2: Extract Facts
        extractor = FactExtractorV2(db_path=db_path, release_mode=False) # Allow API calls if not in cache
        
        for chunk in chunks:
            if chunk["chunk_type"] == "table_malformed": continue
            
            extracted_data = extractor.extract_facts(chunk)
            for fact_data in extracted_data:
                # We need to compute fingerprints here and save
                semantic_fingerprint = f"{fact_data.get('entity')}_{fact_data.get('attribute')}_{fact_data.get('period')}_{fact_data.get('value')}"
                evidence_fingerprint = f"{doc_hash}_{chunk['chunk_id']}"
                
                # Default values
                fact_id = f"fact_{doc_hash}_{chunk['chunk_id']}_{len(semantic_fingerprint)}"
                
                cur.execute("""
                    INSERT OR IGNORE INTO facts (
                        id, job_id, entity, attribute, value, unit, period_raw, 
                        claim_basis, vintage, scope, semantic_fingerprint,
                        chunk_id, evidence_type, source_quote, evidence_fingerprint, extraction_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fact_id, job_id, fact_data.get("entity", ""), fact_data.get("attribute", ""),
                    float(fact_data.get("value", 0)) if str(fact_data.get("value", "")).replace(".","").isdigit() else None,
                    fact_data.get("unit", ""), fact_data.get("period", ""), fact_data.get("claim_basis", "unknown"),
                    fact_data.get("vintage"), fact_data.get("scope"), semantic_fingerprint,
                    chunk["chunk_id"], "prose" if chunk["chunk_type"] == "prose" else "table",
                    fact_data.get("source_quote"), evidence_fingerprint, 1.0
                ))
        
        # Step 3: Run Comparison (Skipped for brevity in worker, usually run per document batch or fully)
        # Ideally, we call the Comparison Engine V2 here.
        
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
