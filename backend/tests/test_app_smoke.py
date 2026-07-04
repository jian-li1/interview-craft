"""Smoke tests: the app imports and boots, and the health check works with no auth."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_app_imports():
    """Verify `app.main.app` can be imported and constructed without raising."""
    from app.main import app

    assert app is not None


def test_healthz_no_auth():
    """Verify the health check endpoint is reachable without auth and returns ok."""
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_generates():
    """Sanity check that all routers wire up without raising during schema generation.

    Fetches `/openapi.json` and asserts that the expected route prefixes from each
    router (health, auth, onboarding, curricula, conversations, settings) are present.
    """
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
