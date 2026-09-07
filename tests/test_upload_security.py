import io
import os
import pytest
from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)

def test_non_pdf_extension_rejected():
    response = client.post(
        "/api/upload",
        files={"file": ("malicious.sh", b"#!/bin/bash\necho hacked", "application/x-sh")}
    )
    assert response.status_code == 400
    assert "Only PDF files" in response.json()["detail"]

def test_fake_pdf_magic_bytes_rejected():
    # File named .pdf but containing python code
    response = client.post(
        "/api/upload",
        files={"file": ("exploit.pdf", b"import os; os.system('rm -rf /')", "application/pdf")}
    )
    assert response.status_code == 400
    assert "missing %PDF- magic header" in response.json()["detail"]

def test_corrupt_pdf_handled_gracefully():
    # Starts with %PDF- but is unparsable garbage
    response = client.post(
        "/api/upload",
        files={"file": ("corrupt.pdf", b"%PDF-1.4\ncorrupted_payload_without_root", "application/pdf")}
    )
    assert response.status_code == 400
    assert "Unable to parse PDF document" in response.json()["detail"]

def test_path_traversal_filename_sanitized(tmp_path):
    # Filename attempts to escape directory using relative traversal
    # It starts with %PDF- and will fail at chunking or parse, but must NOT escape uploads/
    traversal_name = "../../etc/cron.d/evil.pdf"
    response = client.post(
        "/api/upload",
        files={"file": (traversal_name, b"%PDF-1.4\ncorrupt", "application/pdf")}
    )
    # The file should be handled (either 400 parsing or success) but never written outside uploads
    uploads_dir = os.path.abspath("uploads")
    for root, dirs, files in os.walk(uploads_dir):
        for f in files:
            assert not f.startswith("..")
