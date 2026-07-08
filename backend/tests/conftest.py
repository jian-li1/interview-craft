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
    """Provide the process-wide, lru_cache'd application Settings singleton.

    Returns:
        Settings: The pydantic-settings instance produced by `get_settings()`, reading
            from the env vars set at the top of this module.
    """
    return get_settings()


class FakeFirestore:
    """A tiny in-memory stand-in for the subset of `app.services.firestore` used in tests.

    Not a full Firestore emulator — just enough structured storage to exercise API
    routes and agent logic without network/credentials, matching the function
    signatures in app/services/firestore.py.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory collections mirroring the Firestore schema.

        Each attribute below stands in for one Firestore collection/subcollection,
        keyed the same way the real documents would be (by id, or by a composite key
        for subcollections nested under two parents).
        """
        self.users: dict[str, dict[str, Any]] = {}
        self.profiles: dict[str, dict[str, Any]] = {}
        self.curricula: dict[str, dict[str, Any]] = {}
        self.modules: dict[str, dict[str, dict[str, Any]]] = {}
        self.sections: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, dict[str, Any]]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.conversations: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self._seq_counters: dict[str, int] = {}

    def utcnow(self) -> dt.datetime:
        """Return the current UTC timestamp, standing in for `firestore.utcnow`.

        Returns:
            dt.datetime: The current time, timezone-aware in UTC.
        """
        return dt.datetime.now(dt.timezone.utc)

    def new_id(self) -> str:
        """Generate a fake document id, standing in for `firestore.new_id`.

        Returns:
            str: A random 32-character hex string suitable for use as a doc id.
        """
        import uuid

        return uuid.uuid4().hex


@pytest.fixture()
def fake_fs(monkeypatch) -> FakeFirestore:
    """Monkeypatch app.services.firestore's module-level functions with in-memory fakes.

    Mechanism: this fixture builds a `FakeFirestore` in-memory store, defines a closure
    function for every function exported by `app.services.firestore` (matching each
    real function's signature and return shape), and uses `monkeypatch.setattr` to
    replace each real function's module-level attribute with its fake counterpart.
    Because `monkeypatch` patches attributes directly on the shared
    `app.services.firestore` module object, any other module that did `import
    app.services.firestore as fs` (or `from app.services.firestore import x`) and calls
    through it at request time will transparently hit the fakes too — no dependency
    injection is required in application code. `monkeypatch` auto-reverts every patched
    attribute after the test, so no explicit teardown is needed here.

    Args:
        monkeypatch: Pytest's built-in fixture for reversibly patching attributes.

    Returns:
        FakeFirestore: The in-memory store backing the patched functions, so tests can
            both call the app through patched `firestore` functions and inspect/seed
            the store's collections directly.
    """
    store = FakeFirestore()
    import app.services.firestore as fs

    def new_id() -> str:
        """Fake for `firestore.new_id` — delegate to the store's id generator."""
        return store.new_id()

    def utcnow() -> dt.datetime:
        """Fake for `firestore.utcnow` — delegate to the store's clock."""
        return store.utcnow()

    def get_user(uid: str):
        """Fake for `firestore.get_user` — look up a user dict by uid, or None."""
        return store.users.get(uid)

    def upsert_user_login(uid, email, name, picture, google_sub):
        """Fake for `firestore.upsert_user_login` — create or refresh a user on login."""
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
        """Fake for `firestore.update_user_settings` — merge non-None fields in."""
        current = store.users.setdefault(uid, {}).get("settings", {})
        merged = {**current, **{k: v for k, v in partial.items() if v is not None}}
        store.users[uid]["settings"] = merged
        return merged

    def set_onboarding_completed(uid, completed):
        """Fake for `firestore.set_onboarding_completed` — flip the user's flag."""
        store.users.setdefault(uid, {})["onboarding_completed"] = completed

    def get_profile(uid):
        """Fake for `firestore.get_profile` — look up a profile dict by uid, or None."""
        return store.profiles.get(uid)

    def upsert_profile(uid, fields):
        """Fake for `firestore.upsert_profile` — merge fields and stamp `updated_at`."""
        current = store.profiles.get(uid, {})
        current.update(fields)
        current["updated_at"] = store.utcnow()
        store.profiles[uid] = current
        return current

    def create_curriculum(owner_uid, title, user_prompt, conversation_id):
        """Fake for `firestore.create_curriculum` — create a new curriculum record."""
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
        """Fake for `firestore.get_curriculum` — look up a curriculum by id, or None."""
        data = store.curricula.get(curriculum_id)
        return {"id": curriculum_id, **data} if data is not None else None

    def list_curricula(owner_uid):
        """Fake for `firestore.list_curricula` — all curricula owned by `owner_uid`."""
        return [
            {"id": cid, **data}
            for cid, data in store.curricula.items()
            if data.get("owner_uid") == owner_uid
        ]

    def update_curriculum(curriculum_id, fields):
        """Fake for `firestore.update_curriculum` — merge fields, stamp `updated_at`."""
        store.curricula.setdefault(curriculum_id, {}).update(fields)
        store.curricula[curriculum_id]["updated_at"] = store.utcnow()

    def delete_curriculum(curriculum_id):
        """Fake for `firestore.delete_curriculum` — cascade-delete curriculum subtree."""
        store.curricula.pop(curriculum_id, None)
        store.modules.pop(curriculum_id, None)
        store.plans.pop(curriculum_id, None)
        store.sources.pop(curriculum_id, None)
        store.states.pop(curriculum_id, None)

    def create_module(curriculum_id, module_id, fields):
        """Fake for `firestore.create_module` — store a module under its curriculum."""
        store.modules.setdefault(curriculum_id, {})[module_id] = dict(fields)

    def get_module(curriculum_id, module_id):
        """Fake for `firestore.get_module` — look up one module, or None."""
        mods = store.modules.get(curriculum_id, {})
        data = mods.get(module_id)
        return {"id": module_id, **data} if data is not None else None

    def list_modules(curriculum_id):
        """Fake for `firestore.list_modules` — all modules for a curriculum, ordered."""
        mods = store.modules.get(curriculum_id, {})
        items = [{"id": mid, **data} for mid, data in mods.items()]
        return sorted(items, key=lambda m: m.get("order", 0))

    def update_module(curriculum_id, module_id, fields):
        """Fake for `firestore.update_module` — merge fields into an existing module."""
        store.modules.setdefault(curriculum_id, {}).setdefault(module_id, {}).update(fields)

    def create_section(curriculum_id, module_id, section_id, fields):
        """Fake for `firestore.create_section` — store a section under its module."""
        key = (curriculum_id, module_id)
        store.sections.setdefault(key, {})[section_id] = dict(fields)

    def get_section(curriculum_id, module_id, section_id):
        """Fake for `firestore.get_section` — look up one section, or None."""
        key = (curriculum_id, module_id)
        data = store.sections.get(key, {}).get(section_id)
        return {"id": section_id, **data} if data is not None else None

    def list_sections(curriculum_id, module_id):
        """Fake for `firestore.list_sections` — all sections for a module, ordered."""
        key = (curriculum_id, module_id)
        items = [{"id": sid, **data} for sid, data in store.sections.get(key, {}).items()]
        return sorted(items, key=lambda s: s.get("order", 0))

    def update_section(curriculum_id, module_id, section_id, fields):
        """Fake for `firestore.update_section` — merge fields into an existing section."""
        key = (curriculum_id, module_id)
        store.sections.setdefault(key, {}).setdefault(section_id, {}).update(fields)

    def get_plan(curriculum_id):
        """Fake for `firestore.get_plan` — look up the curriculum's plan doc, or None."""
        return store.plans.get(curriculum_id)

    def set_plan(curriculum_id, fields):
        """Fake for `firestore.set_plan` — merge fields into the curriculum's plan doc."""
        store.plans.setdefault(curriculum_id, {}).update(fields)

    def _source_doc_id(url: str) -> str:
        """Mirror `firestore._source_doc_id` — deterministic id from a SHA-256 of the URL."""
        import hashlib

        return hashlib.sha256(url.encode()).hexdigest()[:24]

    def source_exists(curriculum_id, url):
        """Fake for `firestore.source_exists` — True if a source doc exists for this URL."""
        source_id = _source_doc_id(url)
        return source_id in store.sources.get(curriculum_id, {})

    def create_source(curriculum_id, fields):
        """Fake for `firestore.create_source` — save/overwrite a source keyed by URL hash."""
        source_id = _source_doc_id(fields["url"])
        data = {**fields, "created_at": store.utcnow()}
        store.sources.setdefault(curriculum_id, {})[source_id] = data
        return source_id

    def list_sources(curriculum_id):
        """Fake for `firestore.list_sources` — all sources for a curriculum."""
        sources = store.sources.get(curriculum_id, {})
        return [{"id": sid, **data} for sid, data in sources.items()]

    def get_agent_state(curriculum_id):
        """Fake for `firestore.get_agent_state` — look up the persisted state, or None."""
        return store.states.get(curriculum_id)

    def set_agent_state(curriculum_id, fields):
        """Fake for `firestore.set_agent_state` — merge fields, stamp `updated_at`."""
        current = store.states.setdefault(curriculum_id, {})
        current.update(fields)
        current["updated_at"] = store.utcnow()

    def create_conversation(owner_uid, title, curriculum_id):
        """Fake for `firestore.create_conversation` — create a new conversation record."""
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
        """Fake for `firestore.get_conversation` — look up a conversation, or None."""
        data = store.conversations.get(conversation_id)
        return {"id": conversation_id, **data} if data is not None else None

    def list_conversations(owner_uid):
        """Fake for `firestore.list_conversations` — all conversations for a user."""
        return [
            {"id": cid, **data}
            for cid, data in store.conversations.items()
            if data.get("owner_uid") == owner_uid
        ]

    def update_conversation(conversation_id, fields):
        """Fake for `firestore.update_conversation` — merge fields, stamp `updated_at`."""
        store.conversations.setdefault(conversation_id, {}).update(fields)
        store.conversations[conversation_id]["updated_at"] = store.utcnow()

    def delete_conversation(conversation_id):
        """Fake for `firestore.delete_conversation` — remove conversation + messages."""
        store.conversations.pop(conversation_id, None)
        store.messages.pop(conversation_id, None)

    def append_message(conversation_id, fields):
        """Fake for `firestore.append_message` — append with an auto-incremented seq."""
        msgs = store.messages.setdefault(conversation_id, [])
        next_seq = (msgs[-1]["seq"] + 1) if msgs else 1
        msg_id = store.new_id()
        data = {**fields, "seq": next_seq, "created_at": store.utcnow()}
        record = {"id": msg_id, **data}
        msgs.append(record)
        return record

    def update_message(conversation_id, message_id, fields):
        """Fake for `firestore.update_message` — merge fields into an existing message in place."""
        for msg in store.messages.get(conversation_id, []):
            if msg["id"] == message_id:
                msg.update(fields)
                break

    def list_messages(conversation_id):
        """Fake for `firestore.list_messages` — all messages for a conversation, in order."""
        return list(store.messages.get(conversation_id, []))

    def list_recent_messages(conversation_id, limit):
        """Fake for `firestore.list_recent_messages` — the last `limit` messages."""
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
        "source_exists": source_exists,
        "create_source": create_source,
        "list_sources": list_sources,
        "get_agent_state": get_agent_state,
        "set_agent_state": set_agent_state,
        "create_conversation": create_conversation,
        "get_conversation": get_conversation,
        "list_conversations": list_conversations,
        "update_conversation": update_conversation,
        "delete_conversation": delete_conversation,
        "append_message": append_message,
        "update_message": update_message,
        "list_messages": list_messages,
        "list_recent_messages": list_recent_messages,
    }

    for name, fn in fake_functions.items():
        monkeypatch.setattr(fs, name, fn)

    # Modules importing `firestore as fs` elsewhere get the same patched module object
    # since monkeypatch patches attributes on the shared `app.services.firestore` module.
    store.fs = fs
    return store
