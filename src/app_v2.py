from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
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
        with open("required_cases.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
