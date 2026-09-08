from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import hashlib
import os
import sqlite3
import uuid

from src.db.database_v2 import init_db
from src.worker import start_job

app = FastAPI(title="Fulcrum Fact Verification Layer V2")
DB_PATH = os.environ.get("FULCRUM_DB_PATH", "fulcrum_v2_candidate.db")
templates = Jinja2Templates(directory="src/templates")

@app.on_event("startup")
def on_startup():
    init_db(DB_PATH)

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse("index_v2.html", {"request": request})

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
    cur.execute("SELECT * FROM facts WHERE is_active = 1 LIMIT 100")
    facts = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"facts": facts}

@app.get("/api/relations")
def get_relations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relations LIMIT 100")
    relations = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"relations": relations}

@app.get("/api/failures")
def get_failures():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT f.id, f.reason, c.page, d.filename 
        FROM extraction_failures f
        JOIN chunks c ON f.chunk_id = c.id
        JOIN documents d ON c.document_id = d.id
        ORDER BY f.created_at DESC LIMIT 50
    """)
    failures = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"failures": failures}
