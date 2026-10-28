import pytest
from fastapi.testclient import TestClient
from src.app_v2 import app

client = TestClient(app)

def test_openapi_schema_endpoint():
    """Verifies that /openapi.json contains title, version 2.1.0, and defined tags."""
    res = client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert schema["info"]["title"] == "Fulcrum Fact Verification Layer"
    assert schema["info"]["version"] == "2.1.0"
    tags = [t["name"] for t in schema.get("tags", [])]
    assert "Ingestion" in tags
    assert "Facts" in tags
    assert "Relations" in tags
    assert "Export" in tags
    assert "System" in tags

def test_docs_ui_endpoint():
    """Verifies that /docs Swagger UI loads successfully."""
    res = client.get("/docs")
    assert res.status_code == 200
    assert "swagger-ui" in res.text.lower() or "html" in res.text.lower()

def test_export_invalid_format_returns_400():
    """Critic check: Exporting with unsupported format returns clean 400 error."""
    res_facts = client.get("/api/export/facts?format=xml")
    assert res_facts.status_code == 400
    assert "Unsupported format" in res_facts.json()["detail"]

    res_rel = client.get("/api/export/relations?format=parquet")
    assert res_rel.status_code == 400
    assert "Unsupported format" in res_rel.json()["detail"]

def test_search_facts_limit_bounds_validation():
    """Critic check: Fact search enforces bounds on limit parameter."""
    res_low = client.get("/api/facts/search?limit=0")
    assert res_low.status_code == 400
    assert "Limit must be between 1 and 500" in res_low.json()["detail"]

    res_high = client.get("/api/facts/search?limit=9999")
    assert res_high.status_code == 400
    assert "Limit must be between 1 and 500" in res_high.json()["detail"]
