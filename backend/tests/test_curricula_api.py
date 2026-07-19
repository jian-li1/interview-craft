"""Curricula API: DELETE cascade, PATCH rename/favorite, and list favorite defaulting.

Deleting a curriculum also deletes its conversation doc and messages subcollection —
otherwise the conversation would linger as an orphan (curriculum:conversation is 1:1).
PATCH /api/curricula/{id} renames title/description and/or toggles favorite; a
favorite-only patch intentionally does not bump updated_at.
"""

from __future__ import annotations

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


def _authed_client(client) -> TestClient:
    """Mint a session JWT for uid "uid1" and attach it to the client as a cookie.

    Args:
        client (TestClient): The test client to authenticate in place.

    Returns:
        TestClient: The same client instance, now carrying a valid `ic_session` cookie.
    """
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt("uid1", settings)
    client.cookies.set("ic_session", token)
    return client


def test_delete_curriculum_cascades_to_conversation_and_messages(client, fake_fs):
    """Verify DELETE /api/curricula/{id} removes the curriculum, its linked conversation
    doc, and all of that conversation's messages in one call.
    """
    conv = fake_fs.fs.create_conversation("uid1", "Test chat", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "hello"})
    fake_fs.fs.append_message(conv["id"], {"role": "assistant", "content": "hi there"})

    authed = _authed_client(client)
    response = authed.delete(
        f"/api/curricula/{curriculum['id']}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    assert fake_fs.fs.get_curriculum(curriculum["id"]) is None
    assert fake_fs.fs.get_conversation(conv["id"]) is None
    assert fake_fs.fs.list_messages(conv["id"]) == []


def test_delete_curriculum_without_conversation_id_does_not_error(client, fake_fs):
    """Verify deleting a curriculum with an empty `conversation_id` succeeds without
    raising, since there's no linked conversation to cascade-delete.
    """
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )

    authed = _authed_client(client)
    response = authed.delete(
        f"/api/curricula/{curriculum['id']}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_fs.fs.get_curriculum(curriculum["id"]) is None


def test_delete_curriculum_rejects_non_owner(client, fake_fs):
    """Verify deleting a curriculum owned by a different uid returns 404 and leaves
    both the curriculum and conversation docs untouched (ownership check enforced).
    """
    conv = fake_fs.fs.create_conversation("owner-uid", "Test chat", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "owner-uid", "Test curriculum", "prep me for a SWE interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})

    authed = _authed_client(client)  # authenticated as "uid1", not "owner-uid"
    response = authed.delete(
        f"/api/curricula/{curriculum['id']}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 404
    # Neither doc should have been touched.
    assert fake_fs.fs.get_curriculum(curriculum["id"]) is not None
    assert fake_fs.fs.get_conversation(conv["id"]) is not None


def test_list_curricula_defaults_favorite_false_for_legacy_docs(client, fake_fs):
    """Verify GET list includes `favorite` defaulting to False for docs missing the key."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )
    # Simulate a legacy doc written before the favorite field existed.
    del fake_fs.curricula[curriculum["id"]]["favorite"]

    authed = _authed_client(client)
    response = authed.get("/api/curricula")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["favorite"] is False


def test_patch_curriculum_renames_title_and_description(client, fake_fs):
    """Verify PATCH with title+description returns 200, reflects new values, and bumps updated_at."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Old title", "prep me for a SWE interview", conversation_id=""
    )
    original_updated_at = curriculum["updated_at"]

    authed = _authed_client(client)
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={"title": "New title", "description": "New description"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New title"
    assert body["description"] == "New description"
    stored = fake_fs.fs.get_curriculum(curriculum["id"])
    assert stored["updated_at"] > original_updated_at


def test_patch_curriculum_favorite_only_does_not_bump_updated_at(client, fake_fs):
    """Verify a favorite-only PATCH returns favorite=true but leaves updated_at unchanged."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )
    original_updated_at = curriculum["updated_at"]

    authed = _authed_client(client)
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={"favorite": True},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["favorite"] is True
    stored = fake_fs.fs.get_curriculum(curriculum["id"])
    assert stored["updated_at"] == original_updated_at


def test_patch_curriculum_empty_body_rejected(client, fake_fs):
    """Verify PATCH with an empty body (no fields at all) returns 400."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )

    authed = _authed_client(client)
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 400


def test_patch_curriculum_whitespace_only_title_rejected(client, fake_fs):
    """Verify PATCH with a whitespace-only title returns 400."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )

    authed = _authed_client(client)
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={"title": "   "},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 400


def test_patch_curriculum_title_too_long_rejected(client, fake_fs):
    """Verify PATCH with a title over 100 chars returns 400."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )

    authed = _authed_client(client)
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={"title": "x" * 101},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 400


def test_patch_curriculum_description_too_long_rejected(client, fake_fs):
    """Verify PATCH with a description over 500 chars returns 400."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )

    authed = _authed_client(client)
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={"description": "x" * 501},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 400


def test_patch_curriculum_rejects_non_owner(client, fake_fs):
    """Verify PATCH on another user's curriculum returns 404."""
    curriculum = fake_fs.fs.create_curriculum(
        "owner-uid", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )

    authed = _authed_client(client)  # authenticated as "uid1", not "owner-uid"
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={"title": "New title"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 404


def test_patch_curriculum_requires_csrf_header(client, fake_fs):
    """Verify PATCH without the X-Requested-With header returns 403."""
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=""
    )

    authed = _authed_client(client)
    response = authed.patch(
        f"/api/curricula/{curriculum['id']}",
        json={"title": "New title"},
    )

    assert response.status_code == 403
