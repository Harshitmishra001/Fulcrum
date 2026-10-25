from contextlib import asynccontextmanager
from typing import Optional
import csv
import io
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import json
import sqlite3
import uuid

from src.config import get_current_db_path, OPENROUTER_API_KEY
from src.db.database import init_db
from src.worker import start_job

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan handler — replaces deprecated @app.on_event('startup')."""
    init_db(get_current_db_path())
    yield


app = FastAPI(title="Fulcrum Fact Verification Layer V2", lifespan=lifespan)
templates = Jinja2Templates(directory="src/templates")


@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse(request=request, name="index_v2.html")


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    # --- Input Validation ---
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    content = await file.read()

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large: max 50MB")

    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid file: missing %PDF- magic header")

    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="OpenRouter API key is required to process new documents. "
                   "The starter dataset (RBI, IMF, Economic Survey) is already pre-cached."
        )

    # Validate that PDF can actually be parsed structurally
    import pdfplumber
    import io
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) == 0:
                raise ValueError("PDF document has no pages")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to parse PDF document. File may be corrupted or encrypted: {str(e)}"
        )

    doc_hash = hashlib.sha256(content).hexdigest()

    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    # Sanitize filename — store by content hash to prevent path traversal
    safe_filename = f"{doc_hash}.pdf"
    file_path = os.path.join(upload_dir, safe_filename)
    with open(file_path, "wb") as f:
        f.write(content)

    db_path = get_current_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT id FROM documents WHERE file_hash = ?", (doc_hash,))
    existing_doc = cur.fetchone()

    if existing_doc:
        doc_id = existing_doc[0]
        cur.execute(
            "SELECT id, status FROM ingestion_jobs WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
            (doc_id,)
        )
        job = cur.fetchone()
        conn.close()
        if job and job[1] in ("completed", "running", "pending"):
            return {"job_id": job[0], "status": job[1], "message": "Document already ingested or processing"}
        else:
            # Previous job failed or missing — start a fresh job
            job_id = start_job(doc_id, file_path, db_path, doc_hash)
            return {"job_id": job_id, "status": "pending", "doc_name": file.filename}
    else:
        doc_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO documents (id, file_hash, filename) VALUES (?, ?, ?)",
            (doc_id, doc_hash, file.filename)
        )
        conn.commit()
        conn.close()

        job_id = start_job(doc_id, file_path, db_path, doc_hash)
        return {"job_id": job_id, "status": "pending", "doc_name": file.filename}


@app.get("/api/job/{job_id}")
def get_job_status(job_id: str):
    conn = sqlite3.connect(get_current_db_path())
    cur = conn.cursor()
    cur.execute("SELECT status FROM ingestion_jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"job_id": job_id, "status": row[0]}


@app.get("/api/facts")
def get_facts():
    conn = sqlite3.connect(get_current_db_path())
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # V1 schema: chunks.chunk_id (PK), chunks.doc_slug
    cur.execute("""
        SELECT f.*, c.text as chunk_text
        FROM facts f
        LEFT JOIN chunks c ON f.chunk_id = c.chunk_id
        WHERE f.is_active = 1
        ORDER BY f.source_doc, f.source_page
    """)
    facts = [dict(r) for r in cur.fetchall()]
    for f in facts:
        if "evidence_type" not in f or not f.get("evidence_type"):
            cid = str(f.get("chunk_id") or "")
            f["evidence_type"] = "table" if "table" in cid else "prose"
    conn.close()
    return {"facts": facts}


@app.get("/api/facts/search")
def search_facts(
    entity: Optional[str] = None,
    attribute: Optional[str] = None,
    doc: Optional[str] = None,
    assertion_type: Optional[str] = None,
    limit: int = 50
):
    conn = sqlite3.connect(get_current_db_path())
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = """
        SELECT f.*, c.text as chunk_text
        FROM facts f
        LEFT JOIN chunks c ON f.chunk_id = c.chunk_id
        WHERE f.is_active = 1
    """
    params = []

    if entity:
        query += " AND LOWER(f.entity) LIKE LOWER(?)"
        params.append(f"%{entity}%")
    if attribute:
        query += " AND LOWER(f.attribute) LIKE LOWER(?)"
        params.append(f"%{attribute}%")
    if doc:
        query += " AND LOWER(f.source_doc) LIKE LOWER(?)"
        params.append(f"%{doc}%")
    if assertion_type:
        query += " AND LOWER(f.assertion_type) = LOWER(?)"
        params.append(assertion_type)

    query += " ORDER BY f.source_doc, f.source_page LIMIT ?"
    params.append(limit)

    cur.execute(query, tuple(params))
    facts = [dict(r) for r in cur.fetchall()]
    for f in facts:
        if "evidence_type" not in f or not f.get("evidence_type"):
            cid = str(f.get("chunk_id") or "")
            f["evidence_type"] = "table" if "table" in cid else "prose"

    conn.close()
    return {"total": len(facts), "facts": facts}



@app.get("/api/relations")
def get_relations():
    conn = sqlite3.connect(get_current_db_path())
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relations ORDER BY created_at DESC")
    relations = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"relations": relations}


@app.get("/api/failures")
def get_failures():
    conn = sqlite3.connect(get_current_db_path())
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    failures = []
    try:
        # V1 schema: chunks.chunk_id (PK), chunks.doc_slug as filename
        cur.execute("""
            SELECT f.id, f.reason, c.page, c.doc_slug as filename
            FROM extraction_failures f
            JOIN chunks c ON f.chunk_id = c.chunk_id
            ORDER BY f.created_at DESC LIMIT 50
        """)
        failures = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching failures: {e}")

    conn.close()
    return {"failures": failures}


@app.get("/api/oracle-cases")
def get_oracle_cases():
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        case_path = os.path.join(base_dir, "required_cases.json")
        if not os.path.exists(case_path):
            case_path = "required_cases.json"
        with open(case_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.get("/api/health")
def get_health():
    db_path = get_current_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM facts WHERE is_active = 1")
        active_facts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM relations")
        total_relations = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM extraction_failures")
        total_failures = cur.fetchone()[0]
        conn.close()
        return {
            "status": "healthy",
            "database": "connected",
            "active_facts": active_facts,
            "total_relations": total_relations,
            "total_failures": total_failures
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected", "error": str(e)}
        )


@app.get("/api/stats")
def get_stats():
    db_path = get_current_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Breakdown of relations by type
        cur.execute("""
            SELECT relation_type, COUNT(*) as count 
            FROM relations 
            GROUP BY relation_type
        """)
        relations_by_type = {row["relation_type"]: row["count"] for row in cur.fetchall()}

        # Breakdown of facts by source document
        cur.execute("""
            SELECT source_doc, COUNT(*) as count 
            FROM facts 
            WHERE is_active = 1 
            GROUP BY source_doc 
            ORDER BY count DESC
        """)
        facts_by_doc = {row["source_doc"]: row["count"] for row in cur.fetchall()}

        # Total counts
        cur.execute("SELECT COUNT(*) FROM facts WHERE is_active = 1")
        total_facts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM relations")
        total_relations = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM extraction_failures")
        total_failures = cur.fetchone()[0]

        conn.close()
        return {
            "total_facts": total_facts,
            "total_relations": total_relations,
            "total_failures": total_failures,
            "relations_by_type": relations_by_type,
            "facts_by_document": facts_by_doc
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate stats: {str(e)}")


@app.get("/api/export/facts")
def export_facts(format: str = "csv"):
    conn = sqlite3.connect(get_current_db_path())
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT f.id, f.entity, f.attribute, f.value, f.unit, 
               f.period_normalized, f.assertion_type, f.source_doc, 
               f.source_page, f.source_quote, f.extraction_confidence, f.created_at
        FROM facts f
        WHERE f.is_active = 1
        ORDER BY f.source_doc, f.source_page
    """)
    facts = [dict(r) for r in cur.fetchall()]
    conn.close()

    if format.lower() == "json":
        return JSONResponse(
            content={"facts": facts},
            headers={"Content-Disposition": 'attachment; filename="fulcrum_facts.json"'}
        )

    output = io.StringIO()
    fieldnames = [
        "id", "entity", "attribute", "value", "unit", 
        "period_normalized", "assertion_type", "source_doc", 
        "source_page", "source_quote", "extraction_confidence", "created_at"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in facts:
        writer.writerow(row)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fulcrum_facts.csv"'}
    )


@app.get("/api/export/relations")
def export_relations(format: str = "csv"):
    conn = sqlite3.connect(get_current_db_path())
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relations ORDER BY created_at DESC")
    relations = [dict(r) for r in cur.fetchall()]
    conn.close()

    if format.lower() == "json":
        return JSONResponse(
            content={"relations": relations},
            headers={"Content-Disposition": 'attachment; filename="fulcrum_relations.json"'}
        )

    output = io.StringIO()
    fieldnames = [
        "id", "fact_a_id", "fact_b_id", "relation_type", 
        "explanation", "evidence_quote", "entity_resolution_confidence", "created_at"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in relations:
        writer.writerow(row)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fulcrum_relations.csv"'}
    )


