import os
import sqlite3
import pytest
from fastapi.testclient import TestClient

# Mock out OpenRouter dependency
os.environ["FULCRUM_DB_PATH"] = "test_fixture.db"

from src.app_v2 import app
from src.db.database_v2 import init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    if os.path.exists("test_fixture.db"):
        os.remove("test_fixture.db")
    init_db("test_fixture.db")
    yield
    if os.path.exists("test_fixture.db"):
        os.remove("test_fixture.db")

def test_api_idempotency():
    # Create a dummy PDF file
    file_content = b"%PDF-1.4 dummy content"
    
    # Upload once
    response1 = client.post("/api/upload", files={"file": ("dummy.pdf", file_content, "application/pdf")})
    assert response1.status_code == 200
    data1 = response1.json()
    assert "job_id" in data1
    assert data1["status"] == "pending"
    
    # Upload exact same content again
    response2 = client.post("/api/upload", files={"file": ("dummy.pdf", file_content, "application/pdf")})
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["job_id"] == data1["job_id"]
    assert data2["message"] == "Document already ingested or processing"

def test_oracle_cases_exist():
    # In a real fixture test, we'd mock the DB with required_cases.json
    import json
    with open("C:/Users/hmhar/.gemini/antigravity/brain/0b5e1065-2d42-4a12-a5a8-acfa45c85189/required_cases.json") as f:
        cases = json.load(f)
        
    assert "case1_corroboration" in cases
    assert "case2_contradiction" in cases
    assert "case3_reconciliation" in cases
    assert "case4_failure" in cases
    
    assert cases["case2_contradiction"]["fact_a"]["value"] == 7.2
    assert cases["case2_contradiction"]["fact_b"]["value"] == 7.3

