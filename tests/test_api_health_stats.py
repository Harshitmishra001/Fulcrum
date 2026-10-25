import pytest
from fastapi.testclient import TestClient
from src.app_v2 import app

client = TestClient(app)

def test_api_health_endpoint():
    """Verifies that GET /api/health returns 200 with operational database status."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "active_facts" in data
    assert "total_relations" in data
    assert "total_failures" in data
    assert isinstance(data["active_facts"], int)
    assert isinstance(data["total_relations"], int)

def test_api_stats_endpoint():
    """Verifies that GET /api/stats returns breakdown by relation type and source doc."""
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_facts" in data
    assert "total_relations" in data
    assert "total_failures" in data
    assert "relations_by_type" in data
    assert "facts_by_document" in data
    assert isinstance(data["relations_by_type"], dict)
    assert isinstance(data["facts_by_document"], dict)
