"""Onboarding API + async dashboard prompt-suggestion generation.

Covers: `PUT /api/onboarding` with `onboarding_completed: true` stamps
`suggestions_status: "pending"` and schedules `generate_prompt_suggestions` as a
background task (asserted deterministically by monkeypatching `asyncio.create_task`
rather than racing the real event loop — see the docstring on that test);
`generate_prompt_suggestions` itself, invoked directly against a fake LLM provider,
covers the happy path (persists + emits `suggestions_updated`), malformed JSON, a
fence-wrapped JSON response, and too-few-valid-suggestions, all falling back to
`suggestions_status: None`; and `GET /api/onboarding` surfaces the three new fields.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(fake_fs):
    """Build a `TestClient` against the real app with Firestore calls faked out.

    Args:
        fake_fs: The `fake_fs` fixture from conftest.py, depended on here purely for
            its monkeypatching side effect.

    Returns:
        TestClient: A FastAPI test client wrapping `app.main.app`.
    """
    from app.main import app

    return TestClient(app)


def _authed_client(client, uid: str = "uid1") -> TestClient:
    """Mint a session JWT for `uid` and attach it to the client as a cookie.

    Args:
        client (TestClient): The test client to authenticate in place.
        uid (str): The uid to mint a session for.

    Returns:
        TestClient: The same client instance, now carrying a valid `ic_session` cookie.
    """
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt(uid, settings)
    client.cookies.set("ic_session", token)
    return client


class _FakeLLM:
    """Stand-in `LLMProvider` whose `complete()` returns a scripted string."""

    def __init__(self, response_text: str) -> None:
        """Store the canned response text to return from `complete()`.

        Args:
            response_text (str): The exact string `complete()` will return.
        """
        self.response_text = response_text

    async def complete(self, messages) -> str:  # noqa: ANN001 - matches LLMProvider protocol
        """Return the scripted response regardless of input messages.

        Args:
            messages: Ignored — this fake always returns the same canned text.

        Returns:
            str: The canned `response_text`.
        """
        return self.response_text


# ---------------------------------------------------------------------------
# PUT /api/onboarding — onboarding_completed:true side effect
# ---------------------------------------------------------------------------


def test_put_onboarding_completed_stamps_pending_and_schedules_generation(client, fake_fs, monkeypatch):
    """PUT with onboarding_completed:true must synchronously stamp
    suggestions_status="pending" (visible in this response, no waiting on the LLM) and
    schedule exactly one generation task.

    `asyncio.create_task` is monkeypatched to capture the scheduled coroutine instead of
    letting it actually run, since the real background task's completion timing relative
    to the test thread isn't guaranteed — this test only asserts the route's own
    synchronous behavior (the pending stamp + scheduling), not generation itself (covered
    by the `generate_prompt_suggestions` tests below).
    """
    captured_coros = []

    def fake_create_task(coro, *args, **kwargs):
        """Capture the coroutine without running it; close it to avoid an
        'never awaited' warning, and return a dummy task supporting add_done_callback."""
        captured_coros.append(coro)
        coro.close()

        class _FakeTask:
            def add_done_callback(self, cb):
                pass

        return _FakeTask()

    monkeypatch.setattr("app.api.onboarding.asyncio.create_task", fake_create_task)

    authed = _authed_client(client)
    response = authed.put(
        "/api/onboarding",
        json={"onboarding_completed": True},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["suggestions_status"] == "pending"
    assert body["prompt_suggestions"] is None
    assert body["prompt_placeholder"] is None
    assert len(captured_coros) == 1


def test_put_onboarding_incomplete_does_not_schedule_generation(client, fake_fs, monkeypatch):
    """A PUT that does NOT set onboarding_completed must not touch suggestions_status at
    all or schedule any generation task."""
    captured_coros = []
    monkeypatch.setattr(
        "app.api.onboarding.asyncio.create_task",
        lambda coro, *a, **k: (captured_coros.append(coro), coro.close(), None)[-1],
    )

    authed = _authed_client(client)
    response = authed.put(
        "/api/onboarding",
        json={"bio": "just saving a draft"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert response.json()["suggestions_status"] is None
    assert captured_coros == []


def test_get_onboarding_returns_suggestion_fields(client, fake_fs):
    """GET /api/onboarding surfaces prompt_suggestions/prompt_placeholder/suggestions_status
    once a profile carries them (seeded directly into the fake store here)."""
    fake_fs.profiles["uid1"] = {
        "prompt_suggestions": ["A", "B", "C"],
        "prompt_placeholder": "A placeholder sentence.",
        "suggestions_status": "ready",
    }
    authed = _authed_client(client)

    response = authed.get("/api/onboarding")

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_suggestions"] == ["A", "B", "C"]
    assert body["prompt_placeholder"] == "A placeholder sentence."
    assert body["suggestions_status"] == "ready"


# ---------------------------------------------------------------------------
# generate_prompt_suggestions — direct invocation against a fake LLM
# ---------------------------------------------------------------------------


async def test_generate_prompt_suggestions_happy_path_persists_and_emits(fake_fs, monkeypatch):
    """A well-formed JSON response persists suggestions/placeholder with status "ready"
    and pushes a `suggestions_updated` WS event."""
    from app.services.prompt_suggestions import generate_prompt_suggestions

    fake_fs.profiles["uid1"] = {"synthesized_profile": "A backend engineer profile."}
    scripted = json.dumps(
        {
            "suggestions": ["A", "B", "C", "D", "E"],
            "placeholder": "Senior Backend Engineer interview at a fintech, system design focus.",
        }
    )
    monkeypatch.setattr(
        "app.services.prompt_suggestions.get_llm_provider", lambda *a, **k: _FakeLLM(scripted)
    )
    emitted = []

    async def fake_emit(uid, suggestions, placeholder):
        emitted.append((uid, suggestions, placeholder))

    monkeypatch.setattr("app.services.prompt_suggestions.emit_suggestions_updated", fake_emit)

    await generate_prompt_suggestions("uid1")

    profile = fake_fs.profiles["uid1"]
    assert profile["suggestions_status"] == "ready"
    assert profile["prompt_suggestions"] == ["A", "B", "C", "D", "E"]
    assert profile["prompt_placeholder"].startswith("Senior Backend Engineer")
    assert emitted == [("uid1", profile["prompt_suggestions"], profile["prompt_placeholder"])]


async def test_generate_prompt_suggestions_strips_code_fence(fake_fs, monkeypatch):
    """A ```json ... ``` fenced response (despite the prompt's "no fences" instruction)
    still parses successfully."""
    from app.services.prompt_suggestions import generate_prompt_suggestions

    fake_fs.profiles["uid1"] = {"synthesized_profile": "profile text"}
    fenced = '```json\n{"suggestions": ["A", "B", "C"], "placeholder": "A placeholder."}\n```'
    monkeypatch.setattr("app.services.prompt_suggestions.get_llm_provider", lambda *a, **k: _FakeLLM(fenced))
    monkeypatch.setattr(
        "app.services.prompt_suggestions.emit_suggestions_updated", lambda *a, **k: _noop_coro()
    )

    await generate_prompt_suggestions("uid1")

    profile = fake_fs.profiles["uid1"]
    assert profile["suggestions_status"] == "ready"
    assert profile["prompt_suggestions"] == ["A", "B", "C"]


async def test_generate_prompt_suggestions_malformed_json_falls_back_to_none(fake_fs, monkeypatch):
    """Non-JSON model output must fall back to suggestions_status=None rather than
    leaving the profile stuck on "pending"."""
    from app.services.prompt_suggestions import generate_prompt_suggestions

    fake_fs.profiles["uid1"] = {"suggestions_status": "pending"}
    monkeypatch.setattr(
        "app.services.prompt_suggestions.get_llm_provider", lambda *a, **k: _FakeLLM("not json at all")
    )

    await generate_prompt_suggestions("uid1")

    assert fake_fs.profiles["uid1"]["suggestions_status"] is None


async def test_generate_prompt_suggestions_too_few_valid_falls_back_to_none(fake_fs, monkeypatch):
    """Fewer than 3 valid (non-empty) suggestions must be treated as a failure, falling
    back to suggestions_status=None."""
    from app.services.prompt_suggestions import generate_prompt_suggestions

    fake_fs.profiles["uid1"] = {"suggestions_status": "pending"}
    scripted = json.dumps({"suggestions": ["A", "", "  "], "placeholder": "A placeholder."})
    monkeypatch.setattr(
        "app.services.prompt_suggestions.get_llm_provider", lambda *a, **k: _FakeLLM(scripted)
    )

    await generate_prompt_suggestions("uid1")

    assert fake_fs.profiles["uid1"]["suggestions_status"] is None


async def test_generate_prompt_suggestions_llm_error_falls_back_to_none(fake_fs, monkeypatch):
    """An LLM call that raises must also fall back to suggestions_status=None (never
    leave the profile stuck on "pending")."""
    from app.services.prompt_suggestions import generate_prompt_suggestions

    class _RaisingLLM:
        async def complete(self, messages):  # noqa: ANN001 - matches LLMProvider protocol
            raise RuntimeError("provider unavailable")

    fake_fs.profiles["uid1"] = {"suggestions_status": "pending"}
    monkeypatch.setattr("app.services.prompt_suggestions.get_llm_provider", lambda *a, **k: _RaisingLLM())

    await generate_prompt_suggestions("uid1")

    assert fake_fs.profiles["uid1"]["suggestions_status"] is None


async def _noop_coro(*args, **kwargs):
    """No-op async stand-in for `emit_suggestions_updated` where the emitted payload
    doesn't need inspecting."""
    return None
