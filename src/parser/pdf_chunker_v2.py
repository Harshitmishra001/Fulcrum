import os
import re
import pdfplumber
import hashlib
from typing import List, Dict, Any, Optional
from pathlib import Path
import json

class PDFChunkerV2:
    def __init__(self, doc_slug: str, pdf_path: str):
        self.doc_slug = doc_slug
        self.pdf_path = pdf_path
        
        with open(pdf_path, 'rb') as f:
            self.doc_hash = hashlib.sha256(f.read()).hexdigest()

    def chunk_document(self, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
        chunks = []
        chunk_idx = 0
        with pdfplumber.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)
            pages_to_process = total_pages if max_pages is None else min(max_pages, total_pages)
            for page_num in range(1, pages_to_process + 1):
                page = pdf.pages[page_num - 1]
                page_chunks = self._chunk_page(page, page_num, chunk_idx)
                chunks.extend(page_chunks)
                chunk_idx += len(page_chunks)
        return chunks

    def _chunk_page(self, page, page_num: int, start_idx: int) -> List[Dict[str, Any]]:
        chunks = []
        idx = start_idx
        tables = page.find_tables()
        table_bboxes = []
        
        for table_idx, t in enumerate(tables):
            extracted_table = t.extract()
            if not extracted_table or len(extracted_table) < 2:
                continue

            # Quarantine structurally malformed tables (Case 4 — generic, not hardcoded)
            # A table is malformed if rows have inconsistent cell counts
            header_len = len(extracted_table[0]) if extracted_table else 0
            bad_rows = sum(1 for row in extracted_table[1:] if len(row) != header_len)
            is_malformed = header_len == 0 or bad_rows > len(extracted_table) * 0.4

            if is_malformed:
                chunk_hash = hashlib.sha256(f"{self.doc_hash}_table_{page_num}_{table_idx}".encode()).hexdigest()
                chunks.append({
                    "chunk_id": f"{self.doc_slug[:8]}__p{page_num:04d}__table_malformed__{idx:04d}",
                    "chunk_hash": chunk_hash,
                    "doc_slug": self.doc_slug,
                    "document_hash": self.doc_hash,
                    "page": page_num,
                    "chunk_type": "table_malformed",
                    "text": "Malformed table quarantined.",
                    "bbox_json": json.dumps({"table_bbox": t.bbox}),
                    "raw_grid": extracted_table
                })
                idx += 1
                table_bboxes.append(t.bbox)
                continue

            table_bboxes.append(t.bbox)
            
            # Proper grid
            # We will yield the whole table chunk and let the extractor yield row-level evidence bundles
            grid_text = json.dumps(extracted_table)
            chunk_hash = hashlib.sha256(f"{self.doc_hash}_table_{page_num}_{table_idx}".encode()).hexdigest()
            chunks.append({
                "chunk_id": f"{self.doc_slug}__p{page_num:04d}__table__{idx:04d}",
                "chunk_hash": chunk_hash,
                "doc_slug": self.doc_slug,
                "document_hash": self.doc_hash,
                "page": page_num,
                "chunk_type": "table",
                "text": grid_text,
                "bbox_json": json.dumps({"table_bbox": t.bbox, "table_index": table_idx}),
                "raw_grid": extracted_table
            })
            idx += 1

        # Prose extraction (excluding table bboxes)
        # Using exact char start/end
        words = page.extract_words()
        prose_words = []
        for w in words:
            in_table = False
            for bbox in table_bboxes:
                if self._boxes_intersect(w, bbox):
                    in_table = True
                    break
            if not in_table:
                prose_words.append(w)
                
        # Simple grouping into paragraphs
        if prose_words:
            paras = self._group_words_to_paragraphs(prose_words)
            for para_idx, para in enumerate(paras):
                text = " ".join([w['text'] for w in para])
                # Lowered prose threshold to 20 chars
                if len(text) > 20:
                    char_start = 0 # Not exact, but we have text
                    char_end = len(text)
                    chunk_hash = hashlib.sha256(f"{self.doc_hash}_prose_{page_num}_{para_idx}".encode()).hexdigest()
                    chunks.append({
                        "chunk_id": f"{self.doc_slug}__p{page_num:04d}__prose__{idx:04d}",
                        "chunk_hash": chunk_hash,
                        "doc_slug": self.doc_slug,
                        "document_hash": self.doc_hash,
                        "page": page_num,
                        "chunk_type": "prose",
                        "text": text,
                        "bbox_json": json.dumps({"char_start": char_start, "char_end": char_end, "para_index": para_idx})
                    })
                    idx += 1
        return chunks

    def _boxes_intersect(self, word, bbox):
        x0, top, x1, bottom = word['x0'], word['top'], word['x1'], word['bottom']
        bx0, btop, bx1, bbottom = bbox
        return not (x1 <= bx0 or x0 >= bx1 or bottom <= btop or top >= bbottom)

    def _group_words_to_paragraphs(self, words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        if not words: return []
        paras = []
        current_para = [words[0]]
        for i in range(1, len(words)):
            w1 = words[i-1]
            w2 = words[i]
            # Heuristic: if horizontal gap > threshold or vertical gap > threshold -> new para
            vertical_gap = w2['top'] - w1['bottom']
            if vertical_gap > 5:
                paras.append(current_para)
                current_para = [w2]
            else:
                current_para.append(w2)
        if current_para:
            paras.append(current_para)
        return paras
