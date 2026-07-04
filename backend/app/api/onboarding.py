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
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "agent" / "prompts" / "profile_synthesis.md"
    return path.read_text(encoding="utf-8")


def _to_profile_out(data: dict | None) -> ProfileOut:
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
    """Return the current user's onboarding profile."""
    data = fs.get_profile(user.uid)
    return _to_profile_out(data)


@router.put("", response_model=ProfileOut, dependencies=[Depends(require_csrf_header)])
async def put_onboarding(body: ProfileIn, user: CurrentUser = Depends(get_current_user)) -> ProfileOut:
    """Create/update the current user's onboarding profile."""
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
    persisted, per spec 01 §8.
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
    """Run small-model profile synthesis over the user's onboarding inputs and save it."""
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

    user_settings = fs.get_user(user.uid) or {}
    llm = get_llm_provider((user_settings.get("settings") or {}).get("llm_provider"))

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=_render_input_block(input_block)),
    ]
    synthesized = await llm.complete(messages, small=True)
    synthesized = synthesized.strip()

    fs.upsert_profile(user.uid, {"synthesized_profile": synthesized})
    return SynthesizeProfileOut(synthesized_profile=synthesized)


def _render_input_block(data: dict) -> str:
    lines = []
    for key, value in data.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
