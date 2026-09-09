import json
import sqlite3
import os
import hashlib
from typing import List, Dict, Any, Optional
from openai import OpenAI
from src.config import LLM_BASE_URL, OPENROUTER_API_KEY, LLM_MODEL
from src.shortcut_audit import log_penalty

PROMPT_VERSION = "v2_strict_evidence"

EXTRACTION_SYSTEM_PROMPT = """You are a precision fact extractor.
Extract meaningful macro/financial facts from the provided text or JSON table.

Output a JSON object containing a "facts" array of dictionaries. For tables, yield one dict per numeric cell.
Example format:
{
  "facts": [
    {
      "entity": "Name of the entity/subject",
      "attribute": "Name of the metric (e.g. Real GDP Growth)",
      "value": 6.5,
      "unit": "percent",
      "period": "FY2025",
      "claim_basis": "reported",
      "vintage": "first advance estimates",
      "scope": "consolidated",
      "evidence_type": "prose",
      "source_quote": "Exact text containing the value and period"
    }
  ]
}

Each dict MUST have:
"entity": Name of the entity/subject.
"attribute": Name of the metric (e.g. "Real GDP Growth", "Current Account Deficit").
"value": numeric value ONLY (e.g., 6.5). If not numeric, drop it.
"unit": "percent", "USD billion", etc.
"period": e.g. "FY2025", "Q1 FY25".
"claim_basis": MUST be one of: ["reported", "official_estimate", "revised_estimate", "provisional", "budget", "forecast", "target", "unknown"].
"vintage": Explicit string from text indicating vintage (e.g., "first advance estimates"). MUST exist in text, or null.
"scope": e.g. "consolidated", "standalone", or null.

EVIDENCE BUNDLE:
"evidence_type": "prose" or "table".
If prose:
  "source_quote": MUST be exactly present in the text containing the value and period.
If table:
  "row_label": The exact row label text.
  "col_header": The exact column header text.

If you cannot extract a valid metric with a numeric value, return {"facts": []}.
"""

class FactExtractorV2:
    def __init__(self, db_path: str, release_mode: bool = False):
        self.db_path = db_path
        self.release_mode = release_mode
        self.client = OpenAI(base_url=LLM_BASE_URL, api_key=OPENROUTER_API_KEY)
        self.prompt_hash = hashlib.sha256(EXTRACTION_SYSTEM_PROMPT.encode()).hexdigest()
        self.model = LLM_MODEL

    def _get_cached_response(self, document_hash: str, chunk_hash: str) -> Optional[str]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT raw_response FROM extraction_cache
            WHERE document_hash=? AND chunk_hash=? AND prompt_hash=? AND model_identifier=?
        """, (document_hash, chunk_hash, self.prompt_hash, self.model))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

    def _set_cached_response(self, document_hash: str, chunk_hash: str, response: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO extraction_cache 
            (id, document_hash, chunk_hash, prompt_hash, model_identifier, raw_response)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(hashlib.sha256(f"{document_hash}{chunk_hash}".encode()).hexdigest()), 
              document_hash, chunk_hash, self.prompt_hash, self.model, response))
        conn.commit()
        conn.close()

    def extract_facts(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        if chunk["chunk_type"] == "table_malformed":
            return [] # Skip extraction for quarantined tables

        raw_resp = self._get_cached_response(chunk["document_hash"], chunk["chunk_hash"])
        
        if not raw_resp:
            if self.release_mode:
                raise ValueError(f"Cache miss in release mode for chunk {chunk['chunk_hash']}")
            
            try:
                content_text = chunk["text"]
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": f"<document>\n{content_text}\n</document>"}
                    ],
                    response_format={"type": "json_object"} if "gpt" in self.model else None,
                    temperature=0.0
                )
                raw_resp = completion.choices[0].message.content
                self._set_cached_response(chunk["document_hash"], chunk["chunk_hash"], raw_resp)
            except Exception as e:
                print(f"Extraction API failed: {e}")
                return []

        try:
            # Strip markdown block quotes if present
            clean_resp = raw_resp.strip()
            if clean_resp.startswith("```json"):
                clean_resp = clean_resp[7:]
            if clean_resp.endswith("```"):
                clean_resp = clean_resp[:-3]
            
            data = json.loads(clean_resp)
            if isinstance(data, dict) and "result" in data and isinstance(data["result"], list):
                return data["result"]
            if isinstance(data, dict):
                data = data.get("facts", []) or data.get("data", []) or [data]
                
            return [d for d in data if isinstance(d, dict) and "value" in d]
        except Exception as e:
            # Log the failure to the database
            try:
                conn = sqlite3.connect(self.db_path)
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO extraction_failures (id, chunk_id, reason)
                    VALUES (?, ?, ?)
                """, (f"fail_json_{chunk['chunk_id']}", chunk["chunk_id"], f"LLM returned malformed JSON or failed parsing: {str(e)}"))
                conn.commit()
                conn.close()
            except Exception as db_e:
                print(f"Failed to log extraction failure: {db_e}")
            return []
