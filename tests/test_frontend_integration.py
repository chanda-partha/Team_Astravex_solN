"""Automated integration tests for Frontend UI and CORS middleware."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_cors_headers():
    response = client.options("/optimize-energy", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    assert response.headers.get("access-control-allow-origin") in ["*", "http://localhost:3000"]


def test_ui_endpoint():
    response = client.get("/ui")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "GridWise AI" in response.text


def test_sample_cases_endpoint():
    response = client.get("/samples/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")
    assert response.status_code == 200
    data = response.json()
    assert "cases" in data
    assert len(data["cases"]) == 10
