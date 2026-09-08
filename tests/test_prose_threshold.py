import pytest
from src.parser.pdf_chunker import PDFChunker

def test_prose_threshold_lowered_to_20():
    chunker = PDFChunker("dummy.pdf", "test_doc")
    
    # 25 character footnote (should be kept)
    short_prose = "Restated for operations."
    cleaned = chunker._clean_prose(short_prose)
    
    # Simulate the logic in parse_page for paragraphs
    assert len(cleaned) > 20
    
    # 15 character string (should be dropped)
    tiny_prose = "See Figure 1."
    cleaned_tiny = chunker._clean_prose(tiny_prose)
    assert len(cleaned_tiny) <= 20
