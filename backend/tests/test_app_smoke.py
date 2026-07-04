"""Smoke tests: the app imports and boots, and the health check works with no auth."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_app_imports():
    from app.main import app

    assert app is not None


def test_healthz_no_auth():
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_generates():
    """Sanity check that all routers wire up without raising during schema generation."""
    from app.main import app

    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/healthz" in schema["paths"]
    assert "/api/auth/me" in schema["paths"]
    assert "/api/onboarding" in schema["paths"]
    assert "/api/curricula" in schema["paths"]
    assert "/api/conversations" in schema["paths"]
    assert "/api/settings" in schema["paths"]
