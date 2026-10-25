import pytest
from fastapi.testclient import TestClient
from src.app_v2 import app

client = TestClient(app)

def test_export_facts_csv():
    """Verifies that GET /api/export/facts returns a valid CSV with correct attachment header."""
    res = client.get("/api/export/facts?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "fulcrum_facts.csv" in res.headers.get("content-disposition", "")
    lines = res.text.strip().split("\n")
    assert len(lines) >= 1  # Header row + data
    header = lines[0].strip().split(",")
    assert "entity" in header
    assert "attribute" in header
    assert "value" in header

def test_export_facts_json():
    """Verifies that GET /api/export/facts?format=json returns valid JSON facts list."""
    res = client.get("/api/export/facts?format=json")
    assert res.status_code == 200
    data = res.json()
    assert "facts" in data
    assert isinstance(data["facts"], list)

def test_export_relations_csv():
    """Verifies that GET /api/export/relations returns a valid CSV file."""
    res = client.get("/api/export/relations?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "fulcrum_relations.csv" in res.headers.get("content-disposition", "")
    lines = res.text.strip().split("\n")
    assert len(lines) >= 1
    header = lines[0].strip().split(",")
    assert "relation_type" in header
    assert "fact_a_id" in header

def test_export_relations_json():
    """Verifies that GET /api/export/relations?format=json returns valid JSON relations."""
    res = client.get("/api/export/relations?format=json")
    assert res.status_code == 200
    data = res.json()
    assert "relations" in data
    assert isinstance(data["relations"], list)
