"""User-memory tool: on-demand access to the synthesized profile and structured fields."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agent.tools.base import AgentContext, Tool
from app.services import firestore as fs


class GetUserProfileInput(BaseModel):
    pass


class GetUserProfileTool(Tool):
    name = "get_user_profile"
    description = (
        "Fetch the user's synthesized profile and structured onboarding fields (target "
        "roles, experience level, learning style, timeline, skills, goals). The synthesized "
        "profile is also injected into your system context automatically each turn, so this "
        "tool is mainly useful to re-check structured fields precisely or after the profile "
        "may have changed."
    )
    input_model = GetUserProfileInput

    async def execute(self, input: GetUserProfileInput, ctx: AgentContext) -> dict[str, Any]:
        profile = fs.get_profile(ctx.owner_uid)
        if not profile:
            return {"error": "no profile found for this user"}
        return {
            "synthesized_profile": profile.get("synthesized_profile"),
            "target_roles": profile.get("target_roles", []),
            "experience_level": profile.get("experience_level"),
            "learning_style": profile.get("learning_style"),
            "timeline": profile.get("timeline"),
            "skills": profile.get("skills", []),
            "goals": profile.get("goals"),
            "background": profile.get("background"),
        }
