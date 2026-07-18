"""Firestore client + repository functions.

Lazily initializes a single firebase-admin App/Client, supporting either:
- FIRESTORE_EMULATOR_HOST (local dev, no credentials needed), or
- a service-account JSON file referenced by GOOGLE_APPLICATION_CREDENTIALS.

All repository functions are thin, typed wrappers around Firestore calls. They do NOT
perform ownership checks themselves — callers (API routes / tools) are responsible for
verifying `owner_uid == current_user.uid` before invoking mutating or reading calls that
return another user's data. This mirrors spec 01 §5/§8.

Also hosts `register_curriculum_listener`, a small listener registry fired after every
curriculum write — the change signal backing `/ws/dashboard` (see `app/ws/dashboard.py`
and spec 01 §7b). Kept here rather than importing anything from `app.ws` so this module
stays free of WS-layer imports.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import uuid
from functools import lru_cache
from typing import Any, Callable

import firebase_admin
from firebase_admin import credentials, firestore

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_APP_NAME = "interview-blueprint"

# Listener registry for the dashboard WS broker (app/ws/dashboard.py). Kept here (not
# imported from app.ws) to preserve this module's WS-import-free repo-layer purity —
# app/ws/dashboard.py registers itself at import time instead. Each listener is called
# synchronously as fn(curriculum_id, owner_uid_or_None) right after a curriculum write;
# owner_uid is None when the write site doesn't have it cheaply on hand (the subscriber
# re-fetches the doc to learn it).
_curriculum_listeners: list[Callable[[str, str | None], None]] = []


def register_curriculum_listener(fn: Callable[[str, str | None], None]) -> None:
    """Register a callback to be invoked after every curriculum document write.

    Args:
        fn (Callable[[str, str | None], None]): Called as `fn(curriculum_id,
            owner_uid_or_None)` after `create_curriculum`/`update_curriculum`/
            `delete_curriculum`. Exceptions raised by `fn` are caught and logged at
            debug level by the call sites, never propagated to the caller of the
            firestore write.
    """
    _curriculum_listeners.append(fn)


def _notify_curriculum_listeners(curriculum_id: str, owner_uid: str | None) -> None:
    """Fire every registered curriculum listener, isolating failures per-listener.

    Args:
        curriculum_id (str): The curriculum document id that was just written.
        owner_uid (str | None): The curriculum's owner uid if cheaply known at the
            write site, else None (the listener can look it up itself).
    """
    for fn in _curriculum_listeners:
        try:
            fn(curriculum_id, owner_uid)
        except Exception:
            # A listener error must never break the actual Firestore write it followed.
            logger.debug("curriculum listener raised", exc_info=True)


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
    """Generate a new random document id.

    Returns:
        str: A 32-character hex string derived from a random UUID4, suitable for use as
            a Firestore document id.
    """
    return uuid.uuid4().hex


def utcnow() -> dt.datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Centralizing this avoids naive-datetime bugs when writing timestamp fields to
    Firestore, which expects timezone-aware values.

    Returns:
        datetime.datetime: The current instant in UTC, with tzinfo set.
    """
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------------------
# users/{uid}
# --------------------------------------------------------------------------------------


def get_user(uid: str) -> dict[str, Any] | None:
    """Fetch a `users/{uid}` document.

    No ownership check is performed here; callers must ensure `uid` matches the
    requesting user before returning this data to a client.

    Args:
        uid (str): The Firebase Auth uid identifying the user document.

    Returns:
        dict[str, Any] | None: The user document fields, or None if it doesn't exist.
    """
    db = get_firestore_client()
    snap = db.collection("users").document(uid).get()
    return snap.to_dict() if snap.exists else None


def upsert_user_login(
    uid: str, email: str, name: str, picture: str | None, google_sub: str
) -> dict[str, Any]:
    """Create the user doc on first login, or refresh last_login_at on subsequent ones.

    Args:
        uid (str): The Firebase Auth uid to key the `users/{uid}` document on.
        email (str): The user's email address from the verified Google ID token.
        name (str): The user's display name from the verified Google ID token.
        picture (str | None): URL of the user's profile picture, if provided by Google.
        google_sub (str): The Google account's stable subject identifier, stored only
            on first creation (never overwritten on subsequent logins).

    Returns:
        dict[str, Any]: The resulting user document fields (freshly created, or the
            existing document merged with the refreshed login/name/picture fields).
    """
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
        # Model/search provider selection moved to per-conversation composer chips (see
        # conversations/{convId}.selected_model/search_provider) — no longer here.
        "settings": {"theme": "system"},
        "onboarding_completed": False,
    }
    ref.set(data)
    return data


def update_user_settings(uid: str, partial: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial settings update into `users/{uid}.settings`.

    An explicit None value for a key means "clear this override back to the server
    default": that key is deleted from the stored settings map (via
    `firestore.DELETE_FIELD`) rather than being written as null. Keys with non-None
    values merge in as usual. Keys the caller omits entirely are left untouched — the
    `settings` API route already filters those out via `exclude_unset=True` before
    calling this function.

    Args:
        uid (str): The Firebase Auth uid identifying the user document.
        partial (dict[str, Any]): Settings fields to merge in; a None value clears that
            key back to the server default instead of storing a null.

    Returns:
        dict[str, Any]: The fully merged settings dict now stored on the user document,
            with any explicitly-cleared keys absent.
    """
    db = get_firestore_client()
    ref = db.collection("users").document(uid)
    snap = ref.get()
    current = (snap.to_dict() or {}).get("settings", {}) if snap.exists else {}
    # Split the partial into real updates vs. explicit clears (None) so each can be
    # applied with the right Firestore semantics in a single merge write.
    updates = {k: v for k, v in partial.items() if v is not None}
    cleared = [k for k, v in partial.items() if v is None]
    # DELETE_FIELD actually removes the field from the document (unlike writing None).
    write_payload = {**updates, **{k: firestore.DELETE_FIELD for k in cleared}}
    ref.set({"settings": write_payload}, merge=True)
    # Compute the resulting in-memory dict to return: apply updates, then drop cleared keys.
    merged = {k: v for k, v in {**current, **updates}.items() if k not in cleared}
    return merged


def set_onboarding_completed(uid: str, completed: bool) -> None:
    """Set the `onboarding_completed` flag on a user document.

    Args:
        uid (str): The Firebase Auth uid identifying the user document.
        completed (bool): Whether the user has finished the onboarding wizard.
    """
    db = get_firestore_client()
    db.collection("users").document(uid).set({"onboarding_completed": completed}, merge=True)


# --------------------------------------------------------------------------------------
# users/{uid}/profile/main
# --------------------------------------------------------------------------------------


def _profile_ref(uid: str):
    """Return the document reference for `users/{uid}/profile/main`.

    Args:
        uid (str): The Firebase Auth uid owning the profile subcollection.

    Returns:
        google.cloud.firestore.DocumentReference: Reference to the singleton profile doc.
    """
    db = get_firestore_client()
    return db.collection("users").document(uid).collection("profile").document("main")


def get_profile(uid: str) -> dict[str, Any] | None:
    """Fetch the synthesized user profile doc (agent memory layer) for a user.

    No ownership check is performed here; callers must verify the requesting user owns
    `uid` before returning this data.

    Args:
        uid (str): The Firebase Auth uid owning the profile.

    Returns:
        dict[str, Any] | None: The profile document fields, or None if it doesn't exist.
    """
    snap = _profile_ref(uid).get()
    return snap.to_dict() if snap.exists else None


def upsert_profile(uid: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Merge fields into the user's profile doc, stamping `updated_at`.

    Args:
        uid (str): The Firebase Auth uid owning the profile.
        fields (dict[str, Any]): Profile fields to merge into the existing document.

    Returns:
        dict[str, Any]: The full profile document after the merge, re-read from Firestore.
    """
    ref = _profile_ref(uid)
    fields = {**fields, "updated_at": utcnow()}
    ref.set(fields, merge=True)
    snap = ref.get()
    return snap.to_dict() or {}


# --------------------------------------------------------------------------------------
# curricula/{id}
# --------------------------------------------------------------------------------------


def create_curriculum(owner_uid: str, title: str, user_prompt: str, conversation_id: str) -> dict[str, Any]:
    """Create a new `curricula/{id}` document in the initial "researching" state.

    Args:
        owner_uid (str): The Firebase Auth uid of the curriculum's owner.
        title (str): Initial working title for the curriculum (may later be revised via
            the `set_curriculum_title` tool).
        user_prompt (str): The original user prompt that kicked off this curriculum.
        conversation_id (str): The id of the conversation driving this curriculum's
            agent run.

    Returns:
        dict[str, Any]: The newly created curriculum document, including its `id`.
    """
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
    # Owner is already known here, so pass it straight through (no extra read needed).
    _notify_curriculum_listeners(cid, owner_uid)
    return {"id": cid, **data}


def get_curriculum(curriculum_id: str) -> dict[str, Any] | None:
    """Fetch a curriculum document by id.

    No ownership check is performed here; callers must verify `owner_uid` on the
    returned document matches the requesting user before exposing it.

    Args:
        curriculum_id (str): The curriculum document id.

    Returns:
        dict[str, Any] | None: The curriculum fields (with `id` included), or None if
            no such document exists.
    """
    db = get_firestore_client()
    snap = db.collection("curricula").document(curriculum_id).get()
    if not snap.exists:
        return None
    return {"id": snap.id, **(snap.to_dict() or {})}


def list_curricula(owner_uid: str) -> list[dict[str, Any]]:
    """List all curricula owned by a user, most recently updated first.

    Args:
        owner_uid (str): The Firebase Auth uid to filter curricula by.

    Returns:
        list[dict[str, Any]]: Curriculum documents (each with `id` included), ordered by
            `updated_at` descending.
    """
    db = get_firestore_client()
    query = db.collection("curricula").where("owner_uid", "==", owner_uid).order_by(
        "updated_at", direction=firestore.Query.DESCENDING
    )
    return [{"id": doc.id, **(doc.to_dict() or {})} for doc in query.stream()]


def update_curriculum(curriculum_id: str, fields: dict[str, Any]) -> None:
    """Merge fields into a curriculum document, stamping `updated_at`.

    No ownership check is performed here; callers must verify the requesting user owns
    the curriculum before calling this.

    Args:
        curriculum_id (str): The curriculum document id to update.
        fields (dict[str, Any]): Fields to merge into the existing document.
    """
    db = get_firestore_client()
    fields = {**fields, "updated_at": utcnow()}
    db.collection("curricula").document(curriculum_id).set(fields, merge=True)
    # Owner is unknown here (fields may not include it); the dashboard WS subscriber
    # re-fetches the doc itself to learn it.
    _notify_curriculum_listeners(curriculum_id, None)


def delete_curriculum(curriculum_id: str) -> None:
    """Delete a curriculum and all known subcollections (best-effort recursive delete).

    Firestore does not cascade-delete subcollections automatically, so this walks each
    known subcollection (`modules` with nested `sections`, `sources`, `plan`, `state`)
    and deletes documents individually before deleting the curriculum doc itself. No
    ownership check is performed here; callers must verify the requesting user owns the
    curriculum before calling this.

    Args:
        curriculum_id (str): The curriculum document id to delete, along with all of its
            subcollections.
    """
    db = get_firestore_client()
    curriculum_ref = db.collection("curricula").document(curriculum_id)

    # Read owner_uid BEFORE deleting so the post-delete listener notification can still
    # target the right user's dashboard sockets (the doc is gone by the time we notify).
    pre_delete_snap = curriculum_ref.get()
    owner_uid = (pre_delete_snap.to_dict() or {}).get("owner_uid") if pre_delete_snap.exists else None

    for module_doc in curriculum_ref.collection("modules").stream():
        for section_doc in module_doc.reference.collection("sections").stream():
            section_doc.reference.delete()
        module_doc.reference.delete()

    for source_doc in curriculum_ref.collection("sources").stream():
        source_doc.reference.delete()

    curriculum_ref.collection("plan").document("main").delete()
    curriculum_ref.collection("state").document("main").delete()
    curriculum_ref.delete()
    _notify_curriculum_listeners(curriculum_id, owner_uid)


# --------------------------------------------------------------------------------------
# curricula/{id}/modules/{moduleId} and nested sections
# --------------------------------------------------------------------------------------


def _modules_ref(curriculum_id: str):
    """Return the collection reference for `curricula/{curriculum_id}/modules`.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        google.cloud.firestore.CollectionReference: Reference to the modules subcollection.
    """
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("modules")


def create_module(curriculum_id: str, module_id: str, fields: dict[str, Any]) -> None:
    """Create (overwrite) a module document under a curriculum.

    Args:
        curriculum_id (str): The parent curriculum document id.
        module_id (str): The id to assign to the new module document.
        fields (dict[str, Any]): The full module document fields to write.
    """
    _modules_ref(curriculum_id).document(module_id).set(fields)


def get_module(curriculum_id: str, module_id: str) -> dict[str, Any] | None:
    """Fetch a single module document.

    Args:
        curriculum_id (str): The parent curriculum document id.
        module_id (str): The module document id.

    Returns:
        dict[str, Any] | None: The module fields (with `id` included), or None if it
            doesn't exist.
    """
    snap = _modules_ref(curriculum_id).document(module_id).get()
    return {"id": snap.id, **(snap.to_dict() or {})} if snap.exists else None


def list_modules(curriculum_id: str) -> list[dict[str, Any]]:
    """List all modules under a curriculum, in their defined display order.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        list[dict[str, Any]]: Module documents (each with `id` included), ordered by the
            `order` field ascending.
    """
    docs = _modules_ref(curriculum_id).order_by("order").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


def update_module(curriculum_id: str, module_id: str, fields: dict[str, Any]) -> None:
    """Merge fields into an existing module document.

    Args:
        curriculum_id (str): The parent curriculum document id.
        module_id (str): The module document id to update.
        fields (dict[str, Any]): Fields to merge into the existing document.
    """
    _modules_ref(curriculum_id).document(module_id).set(fields, merge=True)


def _sections_ref(curriculum_id: str, module_id: str):
    """Return the collection reference for a module's nested `sections` subcollection.

    Args:
        curriculum_id (str): The parent curriculum document id.
        module_id (str): The parent module document id.

    Returns:
        google.cloud.firestore.CollectionReference: Reference to the sections subcollection.
    """
    return _modules_ref(curriculum_id).document(module_id).collection("sections")


def create_section(curriculum_id: str, module_id: str, section_id: str, fields: dict[str, Any]) -> None:
    """Create (overwrite) a section document under a module.

    Args:
        curriculum_id (str): The top-level curriculum document id.
        module_id (str): The parent module document id.
        section_id (str): The id to assign to the new section document.
        fields (dict[str, Any]): The full section document fields to write.
    """
    _sections_ref(curriculum_id, module_id).document(section_id).set(fields)


def get_section(curriculum_id: str, module_id: str, section_id: str) -> dict[str, Any] | None:
    """Fetch a single section document.

    Args:
        curriculum_id (str): The top-level curriculum document id.
        module_id (str): The parent module document id.
        section_id (str): The section document id.

    Returns:
        dict[str, Any] | None: The section fields (with `id` included), or None if it
            doesn't exist.
    """
    snap = _sections_ref(curriculum_id, module_id).document(section_id).get()
    return {"id": snap.id, **(snap.to_dict() or {})} if snap.exists else None


def list_sections(curriculum_id: str, module_id: str) -> list[dict[str, Any]]:
    """List all sections under a module, in their defined display order.

    Args:
        curriculum_id (str): The top-level curriculum document id.
        module_id (str): The parent module document id.

    Returns:
        list[dict[str, Any]]: Section documents (each with `id` included), ordered by
            the `order` field ascending.
    """
    docs = _sections_ref(curriculum_id, module_id).order_by("order").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


def update_section(curriculum_id: str, module_id: str, section_id: str, fields: dict[str, Any]) -> None:
    """Merge fields into an existing section document.

    Args:
        curriculum_id (str): The top-level curriculum document id.
        module_id (str): The parent module document id.
        section_id (str): The section document id to update.
        fields (dict[str, Any]): Fields to merge into the existing document.
    """
    _sections_ref(curriculum_id, module_id).document(section_id).set(fields, merge=True)


# --------------------------------------------------------------------------------------
# curricula/{id}/plan/main
# --------------------------------------------------------------------------------------


def _plan_ref(curriculum_id: str):
    """Return the document reference for `curricula/{curriculum_id}/plan/main`.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        google.cloud.firestore.DocumentReference: Reference to the singleton plan doc
            used by the `propose_task_plan` HITL flow.
    """
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("plan").document("main")


def get_plan(curriculum_id: str) -> dict[str, Any] | None:
    """Fetch the task plan document proposed by the agent for a curriculum.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        dict[str, Any] | None: The plan document fields, or None if no plan has been
            proposed yet.
    """
    snap = _plan_ref(curriculum_id).get()
    return snap.to_dict() if snap.exists else None


def set_plan(curriculum_id: str, fields: dict[str, Any]) -> None:
    """Merge fields into the curriculum's task plan document.

    Args:
        curriculum_id (str): The parent curriculum document id.
        fields (dict[str, Any]): Plan fields to merge into the existing document (e.g.
            tasks, approval status).
    """
    _plan_ref(curriculum_id).set(fields, merge=True)


# --------------------------------------------------------------------------------------
# curricula/{id}/sources/{sourceId}
# --------------------------------------------------------------------------------------


def _source_doc_id(url: str) -> str:
    """Derive a deterministic source document id from its URL.

    Keying the doc id on a hash of the URL (rather than a random id) means the same
    URL can never be saved twice for a curriculum — a second `save_sources` call for an
    already-saved URL just overwrites the identical doc, so `source_exists` can cheaply
    detect duplicates by id lookup alone.

    Args:
        url (str): The source URL to derive an id from.

    Returns:
        str: The first 24 hex characters of the URL's SHA-256 digest.
    """
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def _sources_ref(curriculum_id: str):
    """Return the collection reference for `curricula/{curriculum_id}/sources`.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        google.cloud.firestore.CollectionReference: Reference to the sources
            subcollection — pinned wholesale into the LLM's working memory every
            iteration (see `memory/manager.py`'s `build_sources_memory_block`), unlike
            the old research-notes subcollection which was pulled on demand via tools.
    """
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("sources")


def source_exists(curriculum_id: str, url: str) -> bool:
    """Check whether a source for `url` has already been saved for this curriculum.

    Args:
        curriculum_id (str): The parent curriculum document id.
        url (str): The source URL to check.

    Returns:
        bool: True if a source document already exists at the URL's derived doc id.
    """
    return _sources_ref(curriculum_id).document(_source_doc_id(url)).get().exists


def create_source(curriculum_id: str, fields: dict[str, Any]) -> str:
    """Save a source under its URL-derived doc id, stamping `created_at`.

    Args:
        curriculum_id (str): The parent curriculum document id.
        fields (dict[str, Any]): Source fields to store; must include `url` (used to
            derive the doc id). Also expected to include the agent-written `summary`
            (the only part injected into working memory) alongside the full
            `content_markdown` (persisted as citation evidence, retrievable by
            re-fetching the URL).

    Returns:
        str: The generated (deterministic) id of the source document.
    """
    source_id = _source_doc_id(fields["url"])
    fields = {**fields, "created_at": utcnow()}
    _sources_ref(curriculum_id).document(source_id).set(fields)
    return source_id


def list_sources(curriculum_id: str) -> list[dict[str, Any]]:
    """List all saved sources for a curriculum in creation order.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        list[dict[str, Any]]: Source documents (each with `id` included), ordered by
            `created_at` ascending.
    """
    docs = _sources_ref(curriculum_id).order_by("created_at").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


# --------------------------------------------------------------------------------------
# curricula/{id}/state/main
# --------------------------------------------------------------------------------------


def _state_ref(curriculum_id: str):
    """Return the document reference for `curricula/{curriculum_id}/state/main`.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        google.cloud.firestore.DocumentReference: Reference to the singleton agent
            working-state doc, used to persist ReAct loop state across HITL pauses/resumes.
    """
    db = get_firestore_client()
    return db.collection("curricula").document(curriculum_id).collection("state").document("main")


def get_agent_state(curriculum_id: str) -> dict[str, Any] | None:
    """Fetch the persisted agent working-state doc for a curriculum's ReAct loop.

    Args:
        curriculum_id (str): The parent curriculum document id.

    Returns:
        dict[str, Any] | None: The agent state fields, or None if no run has persisted
            state yet.
    """
    snap = _state_ref(curriculum_id).get()
    return snap.to_dict() if snap.exists else None


def set_agent_state(curriculum_id: str, fields: dict[str, Any]) -> None:
    """Merge fields into the agent working-state doc, stamping `updated_at`.

    Called when the ReAct loop pauses (e.g. for `propose_task_plan` or
    `request_user_input`) so the run can be resumed on the next WS frame.

    Args:
        curriculum_id (str): The parent curriculum document id.
        fields (dict[str, Any]): State fields to merge into the existing document.
    """
    fields = {**fields, "updated_at": utcnow()}
    _state_ref(curriculum_id).set(fields, merge=True)


# --------------------------------------------------------------------------------------
# conversations/{convId}
# --------------------------------------------------------------------------------------


def create_conversation(
    owner_uid: str,
    title: str,
    curriculum_id: str | None,
    selected_model: str | None = None,
    search_provider: str | None = None,
) -> dict[str, Any]:
    """Create a new `conversations/{id}` document.

    Args:
        owner_uid (str): The Firebase Auth uid of the conversation's owner.
        title (str): Initial title for the conversation.
        curriculum_id (str | None): The curriculum this conversation drives, if any (a
            conversation can exist briefly before a curriculum is created).
        selected_model (str | None): Already-RESOLVED model id to seed the conversation
            with (e.g. from the dashboard prompt box's chip); the route layer resolves
            against `resolve_model` before calling this, so this is stored verbatim.
            None leaves the field unset, falling back to `Settings.default_model`.
        search_provider (str | None): Already-RESOLVED search provider name to seed the
            conversation with, analogous to `selected_model`. None leaves the field
            unset, falling back to `DEFAULT_SEARCH_PROVIDER`.

    Returns:
        dict[str, Any]: The newly created conversation document, including its `id`.
    """
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
        # Composer chip selections — unset until the user picks (or a WS frame
        # persists) a value; see Conversation model docstring. May also be seeded here
        # at creation time from the dashboard prompt box's chips.
        "selected_model": selected_model,
        "search_provider": search_provider,
        "created_at": now,
        "updated_at": now,
    }
    db.collection("conversations").document(conv_id).set(data)
    return {"id": conv_id, **data}


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    """Fetch a conversation document by id.

    No ownership check is performed here; callers must verify `owner_uid` on the
    returned document matches the requesting user before exposing it.

    Args:
        conversation_id (str): The conversation document id.

    Returns:
        dict[str, Any] | None: The conversation fields (with `id` included), or None if
            no such document exists.
    """
    db = get_firestore_client()
    snap = db.collection("conversations").document(conversation_id).get()
    if not snap.exists:
        return None
    return {"id": snap.id, **(snap.to_dict() or {})}


def list_conversations(owner_uid: str) -> list[dict[str, Any]]:
    """List all conversations owned by a user, most recently updated first.

    Args:
        owner_uid (str): The Firebase Auth uid to filter conversations by.

    Returns:
        list[dict[str, Any]]: Conversation documents (each with `id` included), ordered
            by `updated_at` descending.
    """
    db = get_firestore_client()
    query = (
        db.collection("conversations")
        .where("owner_uid", "==", owner_uid)
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
    )
    return [{"id": doc.id, **(doc.to_dict() or {})} for doc in query.stream()]


def update_conversation(conversation_id: str, fields: dict[str, Any]) -> None:
    """Merge fields into a conversation document, stamping `updated_at`.

    No ownership check is performed here; callers must verify the requesting user owns
    the conversation before calling this.

    Args:
        conversation_id (str): The conversation document id to update.
        fields (dict[str, Any]): Fields to merge into the existing document.
    """
    db = get_firestore_client()
    fields = {**fields, "updated_at": utcnow()}
    db.collection("conversations").document(conversation_id).set(fields, merge=True)


def delete_conversation(conversation_id: str) -> None:
    """Delete a conversation and its `messages` subcollection (best-effort recursive delete).

    No ownership check is performed here; callers must verify the requesting user owns
    the conversation before calling this.

    Args:
        conversation_id (str): The conversation document id to delete, along with all
            of its messages.
    """
    db = get_firestore_client()
    conversation_ref = db.collection("conversations").document(conversation_id)

    for message_doc in conversation_ref.collection("messages").stream():
        message_doc.reference.delete()

    conversation_ref.delete()


def _messages_ref(conversation_id: str):
    """Return the collection reference for `conversations/{conversation_id}/messages`.

    Args:
        conversation_id (str): The parent conversation document id.

    Returns:
        google.cloud.firestore.CollectionReference: Reference to the messages subcollection.
    """
    db = get_firestore_client()
    return db.collection("conversations").document(conversation_id).collection("messages")


def append_message(conversation_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Append a message with a fresh monotonic `seq`, returning the stored doc.

    Args:
        conversation_id (str): The parent conversation document id.
        fields (dict[str, Any]): Message fields to store (role, content, etc.).

    Returns:
        dict[str, Any]: The stored message document, including its generated `id`,
            assigned `seq`, and `created_at` timestamp.
    """
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
    """Merge fields into an existing message document.

    Args:
        conversation_id (str): The parent conversation document id.
        message_id (str): The message document id to update.
        fields (dict[str, Any]): Fields to merge into the existing document.
    """
    _messages_ref(conversation_id).document(message_id).set(fields, merge=True)


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    """List all messages in a conversation in chronological order.

    Args:
        conversation_id (str): The parent conversation document id.

    Returns:
        list[dict[str, Any]]: Message documents (each with `id` included), ordered by
            `seq` ascending.
    """
    docs = _messages_ref(conversation_id).order_by("seq").stream()
    return [{"id": d.id, **(d.to_dict() or {})} for d in docs]


def list_recent_messages(conversation_id: str, limit: int) -> list[dict[str, Any]]:
    """List the most recent messages in a conversation, in chronological order.

    Fetches the last `limit` messages by querying in descending `seq` order (cheapest
    way to get the tail of the conversation) and then reverses the result back into
    chronological order for callers.

    Args:
        conversation_id (str): The parent conversation document id.
        limit (int): Maximum number of most-recent messages to return.

    Returns:
        list[dict[str, Any]]: Up to `limit` message documents (each with `id` included),
            ordered by `seq` ascending (oldest of the recent batch first).
    """
    docs = (
        _messages_ref(conversation_id)
        .order_by("seq", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    items = [{"id": d.id, **(d.to_dict() or {})} for d in docs]
    items.reverse()
    return items
