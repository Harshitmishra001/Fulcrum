import os
import re
import pdfplumber
from typing import List, Dict, Any, Optional
from pathlib import Path

class PDFChunker:
    """
    Structural chunker for financial PDFs:
    1. Detects tables vs prose.
    2. Re-attaches table headers to each row/group.
    3. Runs 2 cheap checks for pdfplumber silent failures:
       - Body row cell count matches header cell count.
       - Numeric/year columns parse as numbers for most rows.
    4. Filters out table bounding boxes from prose extraction to avoid duplicates.
    5. Generates chunk_id: '{doc_slug}__p{page:04d}__{type}__{index:04d}'.
    """

    def __init__(self, doc_slug: str, pdf_path: str):
        self.doc_slug = doc_slug
        self.pdf_path = pdf_path

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

        # 1. Find tables on page
        tables = page.find_tables()
        table_bboxes = []

        for t in tables:
            extracted_table = t.extract()
            if not extracted_table or len(extracted_table) < 2:
                continue

            # Check if this table has actual content (not just a 1-row header/title box)
            non_empty_cells = sum(1 for row in extracted_table for cell in row if cell and str(cell).strip())
            if non_empty_cells < 4:
                continue

            table_bboxes.append(t.bbox)
            header_row = [str(c).strip().replace("\n", " ") if c is not None else "" for c in extracted_table[0]]
            body_rows = extracted_table[1:]

            # Validation check 1: body row cell count matches header count
            valid_cell_counts = all(len(r) == len(header_row) for r in body_rows)

            # Validation check 2: columns with numeric header parse as numeric
            valid_numeric_parse = self._validate_numeric_columns(header_row, body_rows)

            if valid_cell_counts and valid_numeric_parse:
                # Valid table -> format table with explicit header
                table_text = self._format_table_chunk(header_row, body_rows)
                chunk_id = f"{self.doc_slug}__p{page_num:04d}__table__{idx:04d}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "doc_slug": self.doc_slug,
                    "page": page_num,
                    "chunk_type": "table",
                    "text": table_text,
                    "extraction_confidence_hint": 1.0
                })
                idx += 1
            else:
                # Fallback to raw text for this table region
                raw_text = "\n".join([" | ".join([str(c) for c in r if c is not None]) for r in extracted_table])
                chunk_id = f"{self.doc_slug}__p{page_num:04d}__rawtable__{idx:04d}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "doc_slug": self.doc_slug,
                    "page": page_num,
                    "chunk_type": "raw_table_fallback",
                    "text": raw_text,
                    "extraction_confidence_hint": 0.5
                })
                idx += 1

        # 2. Extract prose outside of tables
        if table_bboxes:
            # Filter out characters that fall inside table bounding boxes (x0, top, x1, bottom)
            def not_in_tables(obj):
                ox0, otop, ox1, obottom = obj.get("x0", 0), obj.get("top", 0), obj.get("x1", 0), obj.get("bottom", 0)
                for (tx0, ttop, tx1, tbottom) in table_bboxes:
                    # check overlap
                    if not (ox1 < tx0 or ox0 > tx1 or obottom < ttop or otop > tbottom):
                        return False
                return True
            try:
                filtered_page = page.filter(not_in_tables)
                page_text = filtered_page.extract_text() or ""
            except Exception:
                page_text = page.extract_text() or ""
        else:
            page_text = page.extract_text() or ""

        paragraphs = self._split_paragraphs(page_text)
        for para in paragraphs:
            cleaned = self._clean_prose(para)
            if cleaned and len(cleaned) > 60:
                chunk_id = f"{self.doc_slug}__p{page_num:04d}__prose__{idx:04d}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "doc_slug": self.doc_slug,
                    "page": page_num,
                    "chunk_type": "prose",
                    "text": cleaned,
                    "extraction_confidence_hint": 1.0
                })
                idx += 1

        return chunks

    def _validate_numeric_columns(self, header: List[str], rows: List[List[Any]]) -> bool:
        year_pattern = re.compile(r"(20\d\d|\d\d-\d\d|FY|%)", re.IGNORECASE)
        numeric_col_indices = [i for i, h in enumerate(header) if year_pattern.search(h)]
        if not numeric_col_indices:
            return True
        
        parseable_count = 0
        total_checks = 0
        for r in rows:
            for col_idx in numeric_col_indices:
                if col_idx < len(r):
                    val = str(r[col_idx]).replace(",", "").replace("%", "").replace("-", "").strip()
                    total_checks += 1
                    if val == "" or re.search(r"\d", val):
                        parseable_count += 1

        if total_checks == 0:
            return True
        return (parseable_count / total_checks) >= 0.6

    def _format_table_chunk(self, header: List[str], rows: List[List[Any]]) -> str:
        header_line = " | ".join(header)
        sep_line = " | ".join(["---"] * len(header))
        row_lines = []
        for r in rows:
            cleaned_row = [str(c).strip().replace("\n", " ") if c is not None else "" for c in r]
            row_lines.append(" | ".join(cleaned_row))
        return f"TABLE HEADER: {header_line}\n{sep_line}\n" + "\n".join(row_lines)

    def _split_paragraphs(self, text: str) -> List[str]:
        raw_paras = re.split(r"\n\s*\n", text)
        result = []
        for p in raw_paras:
            p_clean = " ".join([line.strip() for line in p.split("\n") if line.strip()])
            if p_clean:
                result.append(p_clean)
        return result

    def _clean_prose(self, text: str) -> str:
        """
        Generic running header and artifact cleaner (Critic 3.2).
        Removes standalone page numbers and short uppercase header lines without document-specific words.
        """
        cleaned = text.strip()
        # 1. Strip standalone page numbers (at start of block, on separate lines, or at end)
        cleaned = re.sub(r"^\s*\d+\s*\n", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\n\s*\d+\s*$", "", cleaned)
        cleaned = re.sub(r"^\s*\d+\s*$", "", cleaned)
        # 2. Strip generic short uppercase running headers at the very start of a page block
        cleaned = re.sub(r"^[A-Z0-9\s,.\-—–/]{4,50}\n(?=[A-Z][a-z])", "", cleaned)
        return cleaned.strip()
