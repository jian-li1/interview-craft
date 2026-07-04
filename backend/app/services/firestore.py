"""Firestore client + repository functions.

Lazily initializes a single firebase-admin App/Client, supporting either:
- FIRESTORE_EMULATOR_HOST (local dev, no credentials needed), or
- a service-account JSON file referenced by GOOGLE_APPLICATION_CREDENTIALS.

All repository functions are thin, typed wrappers around Firestore calls. They do NOT
perform ownership checks themselves — callers (API routes / tools) are responsible for
verifying `owner_uid == current_user.uid` before invoking mutating or reading calls that
return another user's data. This mirrors spec 01 §5/§8.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from functools import lru_cache
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore

from app.core.config import Settings, get_settings

_APP_NAME = "interviewcraft"


@lru_cache
def get_firestore_client() -> firestore.Client:
    """Return a process-wide Firestore client, initializing firebase-admin lazily.

    Cached so repeated calls reuse the same client/connection pool. Cleared implicitly
    per-process; tests should monkeypatch this function rather than fight the cache.
    """
    settings: Settings = get_settings()

    if settings.firestore_emulator_host:
        # The emulator client just needs the env var set; firebase-admin picks it up.
        os.environ.setdefault("FIRESTORE_EMULATOR_HOST", settings.firestore_emulator_host)

    try:
        app = firebase_admin.get_app(_APP_NAME)
    except ValueError:
        if settings.firestore_emulator_host:
            # Emulator mode: credentials are not verified, project id still required.
            cred = credentials.ApplicationDefault() if not settings.google_application_credentials else None
            app = (
                firebase_admin.initialize_app(
                    cred, {"projectId": settings.firebase_project_id}, name=_APP_NAME
                )
                if cred
                else firebase_admin.initialize_app(
                    options={"projectId": settings.firebase_project_id}, name=_APP_NAME
                )
            )
        elif settings.google_application_credentials:
            cred = credentials.Certificate(settings.google_application_credentials)
            app = firebase_admin.initialize_app(
                cred, {"projectId": settings.firebase_project_id}, name=_APP_NAME
            )
        else:
            # Fall back to application default credentials (e.g. on Cloud Run).
            app = firebase_admin.initialize_app(
                options={"projectId": settings.firebase_project_id}, name=_APP_NAME
            )

    return firestore.client(app)


def new_id() -> str:
    """Generate a new random document id."""
    return uuid.uuid4().hex


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------------------
# users/{uid}
# --------------------------------------------------------------------------------------


def get_user(uid: str) -> dict[str, Any] | None:
    db = get_firestore_client()
    snap = db.collection("users").document(uid).get()
    return snap.to_dict() if snap.exists else None


def upsert_user_login(
    uid: str, email: str, name: str, picture: str | None, google_sub: str
) -> dict[str, Any]:
    """Create the user doc on first login, or refresh last_login_at on subsequent ones."""
    db = get_firestore_client()
    ref = db.collection("users").document(uid)
    snap = ref.get()
    now = utcnow()
    if snap.exists:
        ref.update({"last_login_at": now, "name": name, "picture": picture})
        data = snap.to_dict() or {}
        data.update({"last_login_at": now, "name": name, "picture": picture})
        return data

    data = {
        "email": email,
        "name": name,
        "picture": picture,
        "google_sub": google_sub,
        "created_at": now,
        "last_login_at": now,
        "settings": {"theme": "system", "llm_provider": None, "search_provider": None},
        "onboarding_completed": False,
    }
    ref.set(data)
    return data


def update_user_settings(uid: str, partial: dict[str, Any]) -> dict[str, Any]:
    db = get_firestore_client()
    ref = db.collection("users").document(uid)
    snap = ref.get()
    current = (snap.to_dict() or {}).get("settings", {}) if snap.exists else {}
    merged = {**current, **{k: v for k, v in partial.items() if v is not None}}
    ref.set({"settings": merged}, merge=True)
    return merged


def set_onboarding_completed(uid: str, completed: bool) -> None:
    db = get_firestore_client()
    db.collection("users").document(uid).set({"onboarding_completed": completed}, merge=True)


# --------------------------------------------------------------------------------------
# users/{uid}/profile/main
# --------------------------------------------------------------------------------------


def _profile_ref(uid: str):
    db = get_firestore_client()
    return db.collection("users").document(uid).collection("profile").document("main")


def get_profile(uid: str) -> dict[str, Any] | None:
    snap = _profile_ref(uid).get()
    return snap.to_dict() if snap.exists else None


def upsert_profile(uid: str, fields: dict[str, Any]) -> dict[str, Any]:
    ref = _profile_ref(uid)
    fields = {**fields, "updated_at": utcnow()}
    ref.set(fields, merge=True)
    snap = ref.get()
    return snap.to_dict() or {}


# --------------------------------------------------------------------------------------
# curricula/{id}
# --------------------------------------------------------------------------------------


def create_curriculum(owner_uid: str, title: str, user_prompt: str, conversation_id: str) -> dict[str, Any]:
    db = get_firestore_client()
    cid = new_id()
    now = utcnow()
    data = {
        "owner_uid": owner_uid,
        "title": title,
        "user_prompt": user_prompt,
        "emoji": None,
        "status": "researching",
        "overview": "",
        "progress": {"phase": "intake", "completed_tasks": 0, "total_tasks": 0, "detail": ""},
        "conversation_id": conversation_id,
        "module_count": 0,
        "section_count": 0,
        "tags": [],
        "created_at": now,
        "updated_at": now,
    }
    db.collection("curricula").document(cid).set(data)
    return {"id": cid, **data}


def get_curriculum(curriculum_id: str) -> dict[str, Any] | None:
    db = get_firestore_client()
    snap = db.collection("curricula").document(curriculum_id).get()
    if not snap.exists:
        return None
    return {"id": snap.id, **(snap.to_dict() or {})}


def list_curricula(owner_uid: str) -> list[dict[str, Any]]:
    db = get_firestore_client()
    query = db.collection("curricula").where("owner_uid", "==", owner_uid).order_by(
        "updated_at", direction=firestore.Query.DESCENDING
    )
    return [{"id": doc.id, **(doc.to_dict() or {})} for doc in query.stream()]


def update_curriculum(curriculum_id: str, fields: dict[str, Any]) -> None:
    db = get_firestore_client()
    fields = {**fields, "updated_at": utcnow()}
    db.collection("curricula").document(curriculum_id).set(fields, merge=True)


def delete_curriculum(curriculum_id: str) -> None:
    """Delete a curriculum and all known subcollections (best-effort recursive delete)."""
    db = get_firestore_client()
    curriculum_ref = db.collection("curricula").document(curriculum_id)

    for module_doc in curriculum_ref.collection("modules").stream():
        for section_doc in module_doc.reference.collection("sections").stream():
            section_doc.reference.delete()
        module_doc.reference.delete()

    for note_doc in curriculum_ref.collection("research").stream():
        note_doc.reference.delete()

    curriculum_ref.collection("plan").document("main").delete()
    curriculum_ref.collection("state").document("main").delete()
    curriculum_ref.delete()


# --------------------------------------------------------------------------------------
# curricula/{id}/modules/{moduleId} and nested sections
# --------------------------------------------------------------------------------------


def _modules_ref(curriculum_id: str):
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("modules")


def create_module(curriculum_id: str, module_id: str, fields: dict[str, Any]) -> None:
    _modules_ref(curriculum_id).document(module_id).set(fields)


def get_module(curriculum_id: str, module_id: str) -> dict[str, Any] | None:
    snap = _modules_ref(curriculum_id).document(module_id).get()
    return {"id": snap.id, **(snap.to_dict() or {})} if snap.exists else None


def list_modules(curriculum_id: str) -> list[dict[str, Any]]:
    docs = _modules_ref(curriculum_id).order_by("order").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


def update_module(curriculum_id: str, module_id: str, fields: dict[str, Any]) -> None:
    _modules_ref(curriculum_id).document(module_id).set(fields, merge=True)


def _sections_ref(curriculum_id: str, module_id: str):
    return _modules_ref(curriculum_id).document(module_id).collection("sections")


def create_section(curriculum_id: str, module_id: str, section_id: str, fields: dict[str, Any]) -> None:
    _sections_ref(curriculum_id, module_id).document(section_id).set(fields)


def get_section(curriculum_id: str, module_id: str, section_id: str) -> dict[str, Any] | None:
    snap = _sections_ref(curriculum_id, module_id).document(section_id).get()
    return {"id": snap.id, **(snap.to_dict() or {})} if snap.exists else None


def list_sections(curriculum_id: str, module_id: str) -> list[dict[str, Any]]:
    docs = _sections_ref(curriculum_id, module_id).order_by("order").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


def update_section(curriculum_id: str, module_id: str, section_id: str, fields: dict[str, Any]) -> None:
    _sections_ref(curriculum_id, module_id).document(section_id).set(fields, merge=True)


# --------------------------------------------------------------------------------------
# curricula/{id}/plan/main
# --------------------------------------------------------------------------------------


def _plan_ref(curriculum_id: str):
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("plan").document("main")


def get_plan(curriculum_id: str) -> dict[str, Any] | None:
    snap = _plan_ref(curriculum_id).get()
    return snap.to_dict() if snap.exists else None


def set_plan(curriculum_id: str, fields: dict[str, Any]) -> None:
    _plan_ref(curriculum_id).set(fields, merge=True)


# --------------------------------------------------------------------------------------
# curricula/{id}/research/{noteId}
# --------------------------------------------------------------------------------------


def _research_ref(curriculum_id: str):
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("research")


def create_research_note(curriculum_id: str, fields: dict[str, Any]) -> str:
    note_id = new_id()
    fields = {**fields, "created_at": utcnow()}
    _research_ref(curriculum_id).document(note_id).set(fields)
    return note_id


def list_research_notes(curriculum_id: str) -> list[dict[str, Any]]:
    docs = _research_ref(curriculum_id).order_by("created_at").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


# --------------------------------------------------------------------------------------
# curricula/{id}/state/main
# --------------------------------------------------------------------------------------


def _state_ref(curriculum_id: str):
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("state").document("main")


def get_agent_state(curriculum_id: str) -> dict[str, Any] | None:
    snap = _state_ref(curriculum_id).get()
    return snap.to_dict() if snap.exists else None


def set_agent_state(curriculum_id: str, fields: dict[str, Any]) -> None:
    fields = {**fields, "updated_at": utcnow()}
    _state_ref(curriculum_id).set(fields, merge=True)


# --------------------------------------------------------------------------------------
# conversations/{convId}
# --------------------------------------------------------------------------------------


def create_conversation(owner_uid: str, title: str, curriculum_id: str | None) -> dict[str, Any]:
    db = get_firestore_client()
    conv_id = new_id()
    now = utcnow()
    data = {
        "owner_uid": owner_uid,
        "curriculum_id": curriculum_id,
        "title": title,
        "summary": None,
        "compacted_through": None,
        "token_estimate": 0,
        "created_at": now,
        "updated_at": now,
    }
    db.collection("conversations").document(conv_id).set(data)
    return {"id": conv_id, **data}


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    db = get_firestore_client()
    snap = db.collection("conversations").document(conversation_id).get()
    if not snap.exists:
        return None
    return {"id": snap.id, **(snap.to_dict() or {})}


def list_conversations(owner_uid: str) -> list[dict[str, Any]]:
    db = get_firestore_client()
    query = (
        db.collection("conversations")
        .where("owner_uid", "==", owner_uid)
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
    )
    return [{"id": doc.id, **(doc.to_dict() or {})} for doc in query.stream()]


def update_conversation(conversation_id: str, fields: dict[str, Any]) -> None:
    db = get_firestore_client()
    fields = {**fields, "updated_at": utcnow()}
    db.collection("conversations").document(conversation_id).set(fields, merge=True)


def delete_conversation(conversation_id: str) -> None:
    """Delete a conversation and its `messages` subcollection (best-effort recursive delete)."""
    db = get_firestore_client()
    conversation_ref = db.collection("conversations").document(conversation_id)

    for message_doc in conversation_ref.collection("messages").stream():
        message_doc.reference.delete()

    conversation_ref.delete()


def _messages_ref(conversation_id: str):
    db = get_firestore_client()
    return db.collection("conversations").document(conversation_id).collection("messages")


def append_message(conversation_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Append a message with a fresh monotonic `seq`, returning the stored doc."""
    db = get_firestore_client()
    msg_id = new_id()
    coll = _messages_ref(conversation_id)
    # Determine next seq. Fine for our scale; Firestore transactions could harden this further.
    last = list(coll.order_by("seq", direction=firestore.Query.DESCENDING).limit(1).stream())
    next_seq = (last[0].to_dict().get("seq", 0) + 1) if last else 1
    data = {**fields, "seq": next_seq, "created_at": utcnow()}
    coll.document(msg_id).set(data)
    return {"id": msg_id, **data}


def update_message(conversation_id: str, message_id: str, fields: dict[str, Any]) -> None:
    _messages_ref(conversation_id).document(message_id).set(fields, merge=True)


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    docs = _messages_ref(conversation_id).order_by("seq").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


def list_recent_messages(conversation_id: str, limit: int) -> list[dict[str, Any]]:
    docs = (
        _messages_ref(conversation_id)
        .order_by("seq", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    items = [{"id": d.id, **(d.to_dict() or {})} for d in docs]
    items.reverse()
    return items
