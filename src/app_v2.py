from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import hashlib
import os
import json
import sqlite3
import uuid

from src.db.database import init_db
from src.worker import start_job

app = FastAPI(title="Fulcrum Fact Verification Layer V2")
DB_PATH = os.environ.get("FULCRUM_DB_PATH", "fulcrum.db")
templates = Jinja2Templates(directory="src/templates")

@app.on_event("startup")
def on_startup():
    init_db(DB_PATH)

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse(request=request, name="index_v2.html")

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
    doc_hash = hashlib.sha256(content).hexdigest()
    
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{doc_hash}.pdf")
    with open(file_path, "wb") as f:
        f.write(content)
        
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT id FROM documents WHERE file_hash = ?", (doc_hash,))
    existing_doc = cur.fetchone()
    
    if existing_doc:
        doc_id = existing_doc[0]
        cur.execute("SELECT id, status FROM ingestion_jobs WHERE document_id = ? ORDER BY created_at DESC LIMIT 1", (doc_id,))
        job = cur.fetchone()
        conn.close()
        if job:
            return {"job_id": job[0], "status": job[1], "message": "Document already ingested or processing"}
        else:
            job_id = start_job(doc_id, file_path, DB_PATH, doc_hash)
            return {"job_id": job_id, "status": "pending", "doc_name": file.filename}
    else:
        doc_id = str(uuid.uuid4())
        cur.execute("INSERT INTO documents (id, file_hash, filename) VALUES (?, ?, ?)", (doc_id, doc_hash, file.filename))
        conn.commit()
        conn.close()
        
        job_id = start_job(doc_id, file_path, DB_PATH, doc_hash)
        return {"job_id": job_id, "status": "pending", "doc_name": file.filename}

@app.get("/api/job/{job_id}")
def get_job_status(job_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT status FROM ingestion_jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {"job_id": job_id, "status": row[0]}

@app.get("/api/facts")
def get_facts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT f.*, c.text as chunk_text 
        FROM facts f 
        LEFT JOIN chunks c ON f.chunk_id = c.chunk_id 
        WHERE f.is_active = 1
        ORDER BY f.source_doc, f.source_page
    """)
    facts = [dict(r) for r in cur.fetchall()]
    for f in facts:
        if "evidence_type" not in f or not f["evidence_type"]:
            cid = str(f.get("chunk_id") or "")
            f["evidence_type"] = "table" if "table" in cid else "prose"
    conn.close()
    return {"facts": facts}

@app.get("/api/relations")
def get_relations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relations ORDER BY created_at DESC")
    relations = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"relations": relations}

@app.get("/api/failures")
def get_failures():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    failures = []
    try:
        cur.execute("""
            SELECT f.id, f.reason, c.page, c.doc_slug as filename 
            FROM extraction_failures f
            JOIN chunks c ON f.chunk_id = c.chunk_id
            ORDER BY f.created_at DESC LIMIT 50
        """)
        failures = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching failures: {e}")
        pass
    
    conn.close()
    return {"failures": failures}

@app.get("/api/oracle-cases")
def get_oracle_cases():
    try:
        with open("required_cases.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
