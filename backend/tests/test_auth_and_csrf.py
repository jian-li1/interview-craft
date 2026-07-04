"""Auth-required routes reject requests with no session cookie (401), and mutating
routes reject requests missing the X-Requested-With CSRF header (403) even if the
CSRF check would otherwise run before auth.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(fake_fs):
    """Build a `TestClient` against the real app with Firestore calls faked out.

    Args:
        fake_fs: The `fake_fs` fixture from conftest.py, depended on here purely for
            its monkeypatching side effect (so any route the client hits during a test
            uses the in-memory Firestore fakes instead of real credentials).

    Returns:
        TestClient: A FastAPI test client wrapping `app.main.app`.
    """
    from app.main import app

    return TestClient(app)


AUTH_REQUIRED_GET_ROUTES = [
    "/api/auth/me",
    "/api/onboarding",
    "/api/curricula",
    "/api/curricula/some-id",
    "/api/curricula/some-id/plan",
    "/api/conversations",
    "/api/conversations/some-id/messages",
    "/api/settings",
]


@pytest.mark.parametrize("path", AUTH_REQUIRED_GET_ROUTES)
def test_get_routes_require_auth(client, path):
    """Verify each auth-required GET route rejects a request with no session cookie (401)."""
    response = client.get(path)
    assert response.status_code == 401


def test_delete_curriculum_without_csrf_header_rejected(client):
    """DELETE declares require_csrf_header as a route-level dependency, which FastAPI
    resolves before the function-parameter get_current_user dependency, so a request
    with neither the cookie nor the CSRF header gets 403 (CSRF checked first).
    """
    response = client.delete("/api/curricula/some-id")
    assert response.status_code == 403


def test_delete_curriculum_with_csrf_header_but_no_auth_rejected(client):
    """With the CSRF header present but no session cookie, auth now fails -> 401."""
    response = client.delete(
        "/api/curricula/some-id", headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert response.status_code == 401


def test_put_onboarding_without_csrf_header_rejected(client):
    """Verify PUT /api/onboarding without the CSRF header is rejected with 403."""
    response = client.put("/api/onboarding", json={})
    assert response.status_code == 403


def test_put_onboarding_with_csrf_header_but_no_auth_rejected(client):
    """Verify PUT /api/onboarding with the CSRF header but no session cookie gets 401."""
    response = client.put(
        "/api/onboarding", json={}, headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert response.status_code == 401


def test_google_login_without_csrf_header_rejected(client):
    """POST /api/auth/google is a mutating route; missing X-Requested-With -> 403."""
    response = client.post("/api/auth/google", json={"id_token": "whatever"})
    assert response.status_code == 403


def test_logout_without_csrf_header_rejected(client):
    """Verify POST /api/auth/logout without the CSRF header is rejected with 403."""
    response = client.post("/api/auth/logout")
    assert response.status_code == 403


def test_put_settings_without_csrf_header_rejected_even_when_authenticated(client, monkeypatch):
    """Even with a valid session cookie, a mutating route without the CSRF header is rejected.

    Fixtures:
        monkeypatch: Unused directly here; present to match pytest's standard fixture
            injection (no monkeypatching is actually performed in this test body).
    """
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt("test-uid", settings)
    client.cookies.set("ic_session", token)

    response = client.put("/api/settings", json={"theme": "dark"})
    assert response.status_code == 403


def test_put_settings_with_csrf_header_and_auth_succeeds(client):
    """Verify PUT /api/settings succeeds (200) when both CSRF header and session cookie
    are present, and that the updated theme is reflected in the response body.
    """
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt("test-uid", settings)
    client.cookies.set("ic_session", token)

    response = client.put(
        "/api/settings",
        json={"theme": "dark"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    assert response.json()["theme"] == "dark"


def test_invalid_session_cookie_rejected(client):
    """Verify a malformed/invalid `ic_session` cookie value is rejected with 401."""
    client.cookies.set("ic_session", "not-a-valid-jwt")
    response = client.get("/api/auth/me")
    assert response.status_code == 401
