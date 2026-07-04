"""Curricula routes: list, full detail, delete, plan."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, get_current_user, get_owned_curriculum, require_csrf_header
from app.models.curriculum import CurriculumFull, CurriculumProgress, CurriculumSummary, Module, Plan, Section
from app.services import firestore as fs

router = APIRouter(prefix="/api/curricula", tags=["curricula"])


def _to_summary(data: dict) -> CurriculumSummary:
    """Convert a raw Firestore curriculum document into a `CurriculumSummary` response model.

    Args:
        data (dict): The raw curriculum document fields as stored in Firestore.

    Returns:
        CurriculumSummary: The lightweight, list-view representation of the curriculum
            (no nested modules/sections), with defaults for optional fields.
    """
    return CurriculumSummary(
        id=data["id"],
        owner_uid=data["owner_uid"],
        title=data.get("title", ""),
        user_prompt=data.get("user_prompt", ""),
        emoji=data.get("emoji"),
        status=data.get("status", "researching"),
        overview=data.get("overview", ""),
        progress=CurriculumProgress(**(data.get("progress") or {})),
        conversation_id=data.get("conversation_id", ""),
        tags=data.get("tags", []),
        module_count=data.get("module_count", 0),
        section_count=data.get("section_count", 0),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


@router.get("", response_model=list[CurriculumSummary])
async def list_curricula(user: CurrentUser = Depends(get_current_user)) -> list[CurriculumSummary]:
    """List all curricula owned by the current user.

    Args:
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        list[CurriculumSummary]: Summary (non-nested) representations of every
            curriculum owned by the user.
    """
    items = fs.list_curricula(user.uid)
    return [_to_summary(i) for i in items]


@router.get("/{curriculum_id}", response_model=CurriculumFull)
async def get_curriculum_full(
    curriculum_id: str, user: CurrentUser = Depends(get_current_user)
) -> CurriculumFull:
    """Fetch a curriculum with its modules and sections fully nested.

    Args:
        curriculum_id (str): The Firestore document id of the curriculum to fetch.
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        CurriculumFull: The curriculum with its modules, and each module's sections,
            fully populated.

    Raises:
        HTTPException: 404 if the curriculum does not exist or is not owned by `user`
            (raised by `get_owned_curriculum`).
    """
    curriculum = get_owned_curriculum(curriculum_id, user)

    modules_data = fs.list_modules(curriculum_id)
    modules: list[Module] = []
    for m in modules_data:
        sections_data = fs.list_sections(curriculum_id, m["id"])
        sections = [Section(**s) for s in sections_data]
        modules.append(Module(**{**m, "sections": sections}))

    return CurriculumFull(
        id=curriculum["id"],
        owner_uid=curriculum["owner_uid"],
        title=curriculum.get("title", ""),
        user_prompt=curriculum.get("user_prompt", ""),
        emoji=curriculum.get("emoji"),
        status=curriculum.get("status", "researching"),
        overview=curriculum.get("overview", ""),
        progress=CurriculumProgress(**(curriculum.get("progress") or {})),
        conversation_id=curriculum.get("conversation_id", ""),
        module_count=curriculum.get("module_count", 0),
        section_count=curriculum.get("section_count", 0),
        tags=curriculum.get("tags", []),
        created_at=curriculum["created_at"],
        updated_at=curriculum["updated_at"],
        modules=modules,
    )


@router.delete("/{curriculum_id}", dependencies=[Depends(require_csrf_header)])
async def delete_curriculum(curriculum_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Delete a curriculum (and its subcollections) if owned by the current user.

    Also deletes the linked conversation (and its messages) if one is set — a curriculum
    and its conversation are 1:1, so an orphaned conversation would otherwise linger.
    Requires the `X-Requested-With` CSRF header (enforced by the router-level
    dependency).

    Args:
        curriculum_id (str): The Firestore document id of the curriculum to delete.
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        dict: `{"ok": True}` on success.

    Raises:
        HTTPException: 404 if the curriculum does not exist or is not owned by `user`
            (raised by `get_owned_curriculum`).
    """
    curriculum = get_owned_curriculum(curriculum_id, user)
    fs.delete_curriculum(curriculum_id)
    conversation_id = curriculum.get("conversation_id")
    if conversation_id:
        fs.delete_conversation(conversation_id)
    return {"ok": True}


@router.get("/{curriculum_id}/plan", response_model=Plan)
async def get_plan(curriculum_id: str, user: CurrentUser = Depends(get_current_user)) -> Plan:
    """Fetch the curriculum's current task plan.

    Args:
        curriculum_id (str): The Firestore document id of the curriculum whose plan is
            being fetched.
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        Plan: The curriculum's current task plan (proposed via `propose_task_plan` and
            possibly revised through the HITL approval flow).

    Raises:
        HTTPException: 404 if the curriculum does not exist / is not owned by `user`
            (raised by `get_owned_curriculum`), or if no plan has been proposed yet.
    """
    get_owned_curriculum(curriculum_id, user)
    plan = fs.get_plan(curriculum_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no plan exists for this curriculum")
    return Plan(**plan)
