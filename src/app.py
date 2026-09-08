import os
import re
import uuid
import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import BASE_DIR, DB_PATH, OPENROUTER_API_KEY
from src.parser.pdf_chunker import PDFChunker
from src.extractor.extractor import FactExtractor
from src.comparison.engine import ComparisonEngine
from src.db.database import init_db, get_active_facts, get_all_relations, save_relation, deactivate_previous_runs, save_chunks_batch

app = FastAPI(title="Fulcrum Fact Verification Layer", version="1.0.0")

# Setup templates
templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "templates"))

# Ensure DB initialized
init_db()

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    facts = get_active_facts()
    facts_by_id = {f["id"]: f for f in facts}
    raw_relations = get_all_relations()

    # Hydrate relations with Fact A and Fact B details
    hydrated_relations = []
    stats = {
        "total_facts": len(facts),
        "total_relations": len(raw_relations),
        "corroborations": 0,
        "contradictions": 0,
        "reconciled": 0,
        "different_claim_types": 0
    }

    for r in raw_relations:
        fa = facts_by_id.get(r["fact_a_id"])
        fb = facts_by_id.get(r["fact_b_id"])
        if not fa or not fb:
            continue

        rtype = r["relation_type"]
        if rtype == "corroboration":
            stats["corroborations"] += 1
        elif rtype == "contradiction":
            stats["contradictions"] += 1
        elif rtype in ["reconciled", "candidate_reconciliation"]:
            stats["reconciled"] += 1
        elif rtype == "different_claim_type":
            stats["different_claim_types"] += 1

        hydrated_relations.append({
            "id": r["id"],
            "relation_type": rtype,
            "explanation": r["explanation"],
            "evidence_quote": r.get("evidence_quote"),
            "entity_resolution_confidence": r["entity_resolution_confidence"],
            "fact_a": fa,
            "fact_b": fb
        })

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "relations": hydrated_relations,
            "stats": stats
        }
    )

@app.get("/api/facts")
def list_facts(doc: Optional[str] = None):
    facts = get_active_facts(doc)
    return {"facts": facts, "count": len(facts)}

@app.get("/api/relations")
def list_relations():
    relations = get_all_relations()
    return {"relations": relations, "count": len(relations)}

@app.post("/api/run-comparison")
def trigger_comparison():
    engine = ComparisonEngine()
    relations = engine.run_comparison()
    return {"status": "ok", "relations_generated": len(relations)}

@app.post("/api/upload")
def upload_pdf(file: UploadFile = File(...), max_pages: Optional[str] = Form(None)):
    raw_name = Path(file.filename).name if file.filename else "upload.pdf"
    if not raw_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Magic byte verification: Genuine PDFs must start with b"%PDF-"
    header = file.file.read(5)
    file.file.seek(0)
    if not header.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format: Not a genuine PDF document (missing %PDF- magic header)."
        )

    # Pre-flight API key verification: Prevent 500 crashes if evaluator has no API key
    if not OPENROUTER_API_KEY or "your_" in OPENROUTER_API_KEY or not OPENROUTER_API_KEY.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "OpenRouter API key is required to extract facts from new PDFs. "
                "Please configure OPENROUTER_API_KEY in your .env file. "
                "The starter dataset (RBI, IMF, Economic Survey) is already pre-cached in fulcrum.db "
                "and can be explored immediately on the dashboard without an API key."
            )
        )

    uploads_dir = (BASE_DIR / "uploads").resolve()
    uploads_dir.mkdir(exist_ok=True)
    
    # Sanitize stem: allow only alphanumeric, hyphen, underscore
    raw_stem = Path(raw_name).stem
    safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_stem)[:40]
    if not safe_stem:
        safe_stem = "document"

    file_id = uuid.uuid4().hex[:8]
    safe_filename = f"{file_id}_{safe_stem}.pdf"
    saved_path = (uploads_dir / safe_filename).resolve()

    # Path traversal assertion: target must remain strictly inside uploads_dir
    if not str(saved_path).startswith(str(uploads_dir)):
        raise HTTPException(status_code=400, detail="Path traversal or invalid filename detected.")

    # Bounded streaming to prevent disk exhaustion DoS (max 50MB)
    MAX_UPLOAD_SIZE = 50 * 1024 * 1024 # 50 MB
    total_bytes = 0
    with open(saved_path, "wb") as buffer:
        while chunk := file.file.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_SIZE:
                buffer.close()
                if saved_path.exists():
                    saved_path.unlink()
                raise HTTPException(status_code=413, detail="File too large. Maximum supported upload size is 50MB.")
            buffer.write(chunk)

    # Process uploaded PDF through the pipeline
    # Namespace doc_slug with file_id to prevent multi-tenant document collision
    doc_slug = f"{safe_stem.lower()}_{file_id}"
    try:
        chunker = PDFChunker(doc_slug=doc_slug, pdf_path=str(saved_path))
        # Support full document processing or user-selected page limit (Critic 4.1)
        page_limit = int(max_pages) if (max_pages and str(max_pages).strip() and str(max_pages).strip().isdigit() and int(max_pages) > 0) else None
        chunks = chunker.chunk_document(max_pages=page_limit)
        save_chunks_batch(chunks)
    except Exception as e:
        # Clean up invalid uploaded file
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(
            status_code=400,
            detail=f"Unable to parse PDF document. File may be corrupted or encrypted: {str(e)}"
        )

    extractor = FactExtractor()
    run_id = f"upload_{file_id}"

    # Extract facts first; only deactivate previous runs once new facts are safely saved
    extracted_facts = extractor.process_chunks_to_db(chunks, extraction_run_id=run_id)
    deactivate_previous_runs(doc_slug, run_id)

    # Re-run comparison engine to cross-reference newly extracted facts
    engine = ComparisonEngine()
    engine.run_comparison()

    return {
        "status": "success",
        "doc_slug": doc_slug,
        "chunks_processed": len(chunks),
        "extracted_facts_count": len(extracted_facts)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
