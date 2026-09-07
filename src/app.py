import os
import re
import uuid
import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import BASE_DIR, DB_PATH
from src.parser.pdf_chunker import PDFChunker
from src.extractor.extractor import FactExtractor
from src.comparison.engine import ComparisonEngine
from src.db.database import init_db, get_active_facts, get_all_relations, save_relation

app = FastAPI(title="Fulcrum Fact Verification Layer", version="1.0.0")

# Setup templates
templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "templates"))

# Ensure DB initialized
init_db()

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
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
async def list_facts(doc: Optional[str] = None):
    facts = get_active_facts(doc)
    return {"facts": facts, "count": len(facts)}

@app.get("/api/relations")
async def list_relations():
    relations = get_all_relations()
    return {"relations": relations, "count": len(relations)}

@app.post("/api/run-comparison")
async def trigger_comparison():
    engine = ComparisonEngine()
    relations = engine.run_comparison()
    return {"status": "ok", "relations_generated": len(relations)}

@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
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

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Process uploaded PDF through the pipeline
    doc_slug = safe_stem.lower()
    try:
        chunker = PDFChunker(doc_slug=doc_slug, pdf_path=str(saved_path))
        chunks = chunker.chunk_document(max_pages=10) # process first 10 pages for snappy demo
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
    extracted_facts = extractor.process_chunks_to_db(chunks, extraction_run_id=run_id)

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
