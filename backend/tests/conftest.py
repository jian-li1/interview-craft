"""Shared pytest fixtures: env setup, mocked Firestore, mocked LLM/search providers.

The app reads configuration via `app.core.config.get_settings()` (an lru_cache'd
Settings singleton), and `app.main` builds the FastAPI app at import time. So required
env vars must be set BEFORE anything under `app` is imported anywhere in the test
session. This module is loaded by pytest before test collection imports test modules,
so we set env vars here first.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SESSION_JWT_SECRET", "test-secret-not-for-production-0123456789abcdef")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
os.environ.setdefault("FIREBASE_PROJECT_ID", "interviewcraft-test")
os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-real")
os.environ.setdefault("SEARCH_PROVIDER", "duckduckgo")

import datetime as dt
from typing import Any

import pytest

from app.core.config import get_settings


@pytest.fixture()
def settings():
    return get_settings()


class FakeFirestore:
    """A tiny in-memory stand-in for the subset of `app.services.firestore` used in tests.

    Not a full Firestore emulator — just enough structured storage to exercise API
    routes and agent logic without network/credentials, matching the function
    signatures in app/services/firestore.py.
    """

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.profiles: dict[str, dict[str, Any]] = {}
        self.curricula: dict[str, dict[str, Any]] = {}
        self.modules: dict[str, dict[str, dict[str, Any]]] = {}
        self.sections: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.research_notes: dict[str, dict[str, dict[str, Any]]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.conversations: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self._seq_counters: dict[str, int] = {}

    def utcnow(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    def new_id(self) -> str:
        import uuid

        return uuid.uuid4().hex


@pytest.fixture()
def fake_fs(monkeypatch) -> FakeFirestore:
    """Monkeypatch app.services.firestore's module-level functions with in-memory fakes."""
    store = FakeFirestore()
    import app.services.firestore as fs

    def new_id() -> str:
        return store.new_id()

    def utcnow() -> dt.datetime:
        return store.utcnow()

    def get_user(uid: str):
        return store.users.get(uid)

    def upsert_user_login(uid, email, name, picture, google_sub):
        now = store.utcnow()
        if uid in store.users:
            store.users[uid].update({"last_login_at": now, "name": name, "picture": picture})
            return store.users[uid]
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
        store.users[uid] = data
        return data

    def update_user_settings(uid, partial):
        current = store.users.setdefault(uid, {}).get("settings", {})
        merged = {**current, **{k: v for k, v in partial.items() if v is not None}}
        store.users[uid]["settings"] = merged
        return merged

    def set_onboarding_completed(uid, completed):
        store.users.setdefault(uid, {})["onboarding_completed"] = completed

    def get_profile(uid):
        return store.profiles.get(uid)

    def upsert_profile(uid, fields):
        current = store.profiles.get(uid, {})
        current.update(fields)
        current["updated_at"] = store.utcnow()
        store.profiles[uid] = current
        return current

    def create_curriculum(owner_uid, title, user_prompt, conversation_id):
        cid = store.new_id()
        now = store.utcnow()
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
        store.curricula[cid] = data
        return {"id": cid, **data}

    def get_curriculum(curriculum_id):
        data = store.curricula.get(curriculum_id)
        return {"id": curriculum_id, **data} if data is not None else None

    def list_curricula(owner_uid):
        return [
            {"id": cid, **data}
            for cid, data in store.curricula.items()
            if data.get("owner_uid") == owner_uid
        ]

    def update_curriculum(curriculum_id, fields):
        store.curricula.setdefault(curriculum_id, {}).update(fields)
        store.curricula[curriculum_id]["updated_at"] = store.utcnow()

    def delete_curriculum(curriculum_id):
        store.curricula.pop(curriculum_id, None)
        store.modules.pop(curriculum_id, None)
        store.plans.pop(curriculum_id, None)
        store.research_notes.pop(curriculum_id, None)
        store.states.pop(curriculum_id, None)

    def create_module(curriculum_id, module_id, fields):
        store.modules.setdefault(curriculum_id, {})[module_id] = dict(fields)

    def get_module(curriculum_id, module_id):
        mods = store.modules.get(curriculum_id, {})
        data = mods.get(module_id)
        return {"id": module_id, **data} if data is not None else None

    def list_modules(curriculum_id):
        mods = store.modules.get(curriculum_id, {})
        items = [{"id": mid, **data} for mid, data in mods.items()]
        return sorted(items, key=lambda m: m.get("order", 0))

    def update_module(curriculum_id, module_id, fields):
        store.modules.setdefault(curriculum_id, {}).setdefault(module_id, {}).update(fields)

    def create_section(curriculum_id, module_id, section_id, fields):
        key = (curriculum_id, module_id)
        store.sections.setdefault(key, {})[section_id] = dict(fields)

    def get_section(curriculum_id, module_id, section_id):
        key = (curriculum_id, module_id)
        data = store.sections.get(key, {}).get(section_id)
        return {"id": section_id, **data} if data is not None else None

    def list_sections(curriculum_id, module_id):
        key = (curriculum_id, module_id)
        items = [{"id": sid, **data} for sid, data in store.sections.get(key, {}).items()]
        return sorted(items, key=lambda s: s.get("order", 0))

    def update_section(curriculum_id, module_id, section_id, fields):
        key = (curriculum_id, module_id)
        store.sections.setdefault(key, {}).setdefault(section_id, {}).update(fields)

    def get_plan(curriculum_id):
        return store.plans.get(curriculum_id)

    def set_plan(curriculum_id, fields):
        store.plans.setdefault(curriculum_id, {}).update(fields)

    def create_research_note(curriculum_id, fields):
        note_id = store.new_id()
        data = {**fields, "created_at": store.utcnow()}
        store.research_notes.setdefault(curriculum_id, {})[note_id] = data
        return note_id

    def list_research_notes(curriculum_id):
        notes = store.research_notes.get(curriculum_id, {})
        return [{"id": nid, **data} for nid, data in notes.items()]

    def get_agent_state(curriculum_id):
        return store.states.get(curriculum_id)

    def set_agent_state(curriculum_id, fields):
        current = store.states.setdefault(curriculum_id, {})
        current.update(fields)
        current["updated_at"] = store.utcnow()

    def create_conversation(owner_uid, title, curriculum_id):
        conv_id = store.new_id()
        now = store.utcnow()
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
        store.conversations[conv_id] = data
        store.messages[conv_id] = []
        return {"id": conv_id, **data}

    def get_conversation(conversation_id):
        data = store.conversations.get(conversation_id)
        return {"id": conversation_id, **data} if data is not None else None

    def list_conversations(owner_uid):
        return [
            {"id": cid, **data}
            for cid, data in store.conversations.items()
            if data.get("owner_uid") == owner_uid
        ]

    def update_conversation(conversation_id, fields):
        store.conversations.setdefault(conversation_id, {}).update(fields)
        store.conversations[conversation_id]["updated_at"] = store.utcnow()

    def append_message(conversation_id, fields):
        msgs = store.messages.setdefault(conversation_id, [])
        next_seq = (msgs[-1]["seq"] + 1) if msgs else 1
        msg_id = store.new_id()
        data = {**fields, "seq": next_seq, "created_at": store.utcnow()}
        record = {"id": msg_id, **data}
        msgs.append(record)
        return record

    def list_messages(conversation_id):
        return list(store.messages.get(conversation_id, []))

    def list_recent_messages(conversation_id, limit):
        return list(store.messages.get(conversation_id, []))[-limit:]

    fake_functions = {
        "new_id": new_id,
        "utcnow": utcnow,
        "get_user": get_user,
        "upsert_user_login": upsert_user_login,
        "update_user_settings": update_user_settings,
        "set_onboarding_completed": set_onboarding_completed,
        "get_profile": get_profile,
        "upsert_profile": upsert_profile,
        "create_curriculum": create_curriculum,
        "get_curriculum": get_curriculum,
        "list_curricula": list_curricula,
        "update_curriculum": update_curriculum,
        "delete_curriculum": delete_curriculum,
        "create_module": create_module,
        "get_module": get_module,
        "list_modules": list_modules,
        "update_module": update_module,
        "create_section": create_section,
        "get_section": get_section,
        "list_sections": list_sections,
        "update_section": update_section,
        "get_plan": get_plan,
        "set_plan": set_plan,
        "create_research_note": create_research_note,
        "list_research_notes": list_research_notes,
        "get_agent_state": get_agent_state,
        "set_agent_state": set_agent_state,
        "create_conversation": create_conversation,
        "get_conversation": get_conversation,
        "list_conversations": list_conversations,
        "update_conversation": update_conversation,
        "append_message": append_message,
        "list_messages": list_messages,
        "list_recent_messages": list_recent_messages,
    }

    for name, fn in fake_functions.items():
        monkeypatch.setattr(fs, name, fn)

    # Modules importing `firestore as fs` elsewhere get the same patched module object
    # since monkeypatch patches attributes on the shared `app.services.firestore` module.
    store.fs = fs
    return store
