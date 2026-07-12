"""Onboarding routes: profile CRUD, resume upload parsing, AI profile synthesis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.core.deps import CurrentUser, enforce_rate_limit, get_current_user, require_csrf_header
from app.models.profile import ProfileIn, ProfileOut, ResumeUploadOut, SynthesizeProfileOut
from app.services import firestore as fs
from app.services.llm.base import ChatMessage
from app.services.llm.factory import get_llm_provider
from app.services.resume_parser import ResumeParsingError, parse_resume

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _load_profile_synthesis_prompt() -> str:
    """Load the profile-synthesis system prompt markdown file from disk.

    Reads fresh from disk on every call (no caching) since this is only invoked on the
    relatively rare `/synthesize` request, not a hot path.

    Returns:
        str: The full contents of `app/agent/prompts/profile_synthesis.md`, used as the
            system prompt for the small-model profile synthesis call.
    """
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "agent" / "prompts" / "profile_synthesis.md"
    return path.read_text(encoding="utf-8")


def _to_profile_out(data: dict | None) -> ProfileOut:
    """Convert a raw Firestore profile document into the API's `ProfileOut` response model.

    Args:
        data (dict | None): The raw profile document fields as stored in Firestore, or
            None if the user has no profile document yet.

    Returns:
        ProfileOut: The public-facing profile representation, with every field defaulted
            so a missing/partial document still produces a valid response.
    """
    data = data or {}
    return ProfileOut(
        bio=data.get("bio", ""),
        background=data.get("background", ""),
        target_roles=data.get("target_roles", []),
        experience_level=data.get("experience_level", "entry"),
        skills=data.get("skills", []),
        goals=data.get("goals", ""),
        learning_style=data.get("learning_style", ""),
        timeline=data.get("timeline", ""),
        onboarding_completed=data.get("onboarding_completed", False),
        resume_filename=data.get("resume_filename"),
        resume_text=data.get("resume_text"),
        synthesized_profile=data.get("synthesized_profile"),
        updated_at=data.get("updated_at"),
    )


@router.get("", response_model=ProfileOut)
async def get_onboarding(user: CurrentUser = Depends(get_current_user)) -> ProfileOut:
    """Return the current user's onboarding profile.

    Args:
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        ProfileOut: The user's onboarding profile, with defaults for any missing fields
            (including a brand-new user with no profile document yet).
    """
    data = fs.get_profile(user.uid)
    return _to_profile_out(data)


@router.put("", response_model=ProfileOut, dependencies=[Depends(require_csrf_header)])
async def put_onboarding(body: ProfileIn, user: CurrentUser = Depends(get_current_user)) -> ProfileOut:
    """Create/update the current user's onboarding profile.

    Requires the `X-Requested-With` CSRF header (enforced by the router-level
    dependency). If `body.onboarding_completed` is set, also flips the separate
    `onboarding_completed` flag on the user doc so dashboard routing can key off it.

    Args:
        body (ProfileIn): The full set of onboarding fields submitted by the client.
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        ProfileOut: The updated profile as persisted.
    """
    data = fs.upsert_profile(user.uid, body.model_dump())
    if body.onboarding_completed:
        fs.set_onboarding_completed(user.uid, True)
    return _to_profile_out(data)


@router.post("/resume", response_model=ResumeUploadOut, dependencies=[Depends(require_csrf_header)])
async def upload_resume(
    file: UploadFile, user: CurrentUser = Depends(get_current_user)
) -> ResumeUploadOut:
    """Parse an uploaded resume (pdf/docx/txt, <=5MB) in-memory and store extracted text.

    Never writes the raw file to disk; only the extracted text and original filename are
    persisted, per spec 01 §8. Requires the `X-Requested-With` CSRF header (enforced by
    the router-level dependency).

    Args:
        file (UploadFile): The uploaded resume file (pdf, docx, or txt).
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        ResumeUploadOut: The stored filename and the extracted plain-text content.

    Raises:
        HTTPException: 400 if the file fails to parse (wrong type, corrupt content, or
            exceeds the size cap) — see `ResumeParsingError` from `resume_parser`.
    """
    try:
        raw_bytes = await file.read()
        text = parse_resume(raw_bytes, filename=file.filename or "resume", content_type=file.content_type)
    except ResumeParsingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    fs.upsert_profile(user.uid, {"resume_filename": file.filename, "resume_text": text})
    return ResumeUploadOut(resume_filename=file.filename or "resume", resume_text=text)


@router.post("/synthesize", response_model=SynthesizeProfileOut, dependencies=[Depends(require_csrf_header)])
async def synthesize_profile(
    user: CurrentUser = Depends(get_current_user),
) -> SynthesizeProfileOut:
    """Run profile synthesis over the user's onboarding inputs and save it.

    Requires the `X-Requested-With` CSRF header (enforced by the router-level
    dependency) and is subject to the shared agent rate limit since it triggers an LLM
    call. Always uses the server default model (first `OPENAI_MODEL` entry — see
    `get_llm_provider()`/`Settings.default_model`); there is no per-user provider
    override anymore, since model selection moved to per-conversation composer chips.

    Args:
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        SynthesizeProfileOut: The synthesized profile summary text, already persisted to
            the user's profile document.

    Raises:
        HTTPException: 429 if the caller has exceeded the agent rate limit (raised by
            `enforce_rate_limit`).
    """
    enforce_rate_limit(user)

    profile = fs.get_profile(user.uid) or {}
    system_prompt = _load_profile_synthesis_prompt()

    input_block = {
        "bio": profile.get("bio", ""),
        "background": profile.get("background", ""),
        "target_roles": profile.get("target_roles", []),
        "experience_level": profile.get("experience_level", ""),
        "skills": profile.get("skills", []),
        "goals": profile.get("goals", ""),
        "learning_style": profile.get("learning_style", ""),
        "timeline": profile.get("timeline", ""),
        "resume_text": profile.get("resume_text") or "",
    }

    # Server default model — no per-user override anymore (see docstring above).
    llm = get_llm_provider()

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=_render_input_block(input_block)),
    ]
    synthesized = await llm.complete(messages)
    synthesized = synthesized.strip()

    fs.upsert_profile(user.uid, {"synthesized_profile": synthesized})
    return SynthesizeProfileOut(synthesized_profile=synthesized)


def _render_input_block(data: dict) -> str:
    """Render a flat dict of profile fields as a simple `key: value` text block.

    Used to build the user-turn content sent to the LLM for profile synthesis — a plain
    text block keeps the prompt simple rather than requiring the model to parse JSON.

    Args:
        data (dict): Flat mapping of onboarding field names to their values.

    Returns:
        str: A newline-separated string of `"{key}: {value}"` lines.
    """
    lines = []
    for key, value in data.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
