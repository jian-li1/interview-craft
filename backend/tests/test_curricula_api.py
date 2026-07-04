"""Curricula API: DELETE /api/curricula/{id} cascades to the linked conversation.

Deleting a curriculum also deletes its conversation doc and messages subcollection —
otherwise the conversation would linger as an orphan (curriculum:conversation is 1:1).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(fake_fs):
    from app.main import app

    return TestClient(app)


def _authed_client(client) -> TestClient:
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt("uid1", settings)
    client.cookies.set("ic_session", token)
    return client


def test_delete_curriculum_cascades_to_conversation_and_messages(client, fake_fs):
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
