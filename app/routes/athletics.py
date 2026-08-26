import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import anthropic
 
from app.services.athletics import generate_recruiting_content_plan, research_target_program
 
router = APIRouter(prefix="/athletics", tags=["athletics"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
VALID_DIRECTIONS = {"play-college", "go-pro", "coach", "sports-management"}
 
 
class ContentPlanIn(BaseModel):
    sport: str
    level: str
    career_direction: str
    achievements: str = ""
 
 
@router.post("/content-coach")
def content_coach(payload: ContentPlanIn):
    """Generates real, grounded recruiting content guidance - a
    highlight reel structure, commonly-evaluated skills/metrics for
    this sport and level, specific drills to practice, and a filming
    checklist. Takes the athlete's profile fields directly in the
    request rather than looking one up, since there's no stored
    athlete-profile table on the backend yet - the athlete survey
    data has stayed frontend-only so far, an honest gap rather than
    something silently assumed to exist.
    """
    if payload.career_direction not in VALID_DIRECTIONS:
        raise HTTPException(status_code=400, detail=f"career_direction must be one of {VALID_DIRECTIONS}")
    try:
        plan = generate_recruiting_content_plan(
            client, payload.sport, payload.level, payload.career_direction, payload.achievements
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate a content plan just now: {e}")
    return plan
 
 
class ProgramResearchIn(BaseModel):
    sport: str
    level: str
    program_name: str
 
 
@router.post("/research-program")
def research_program(payload: ProgramResearchIn):
    """The real-search upgrade: gives Claude the actual Anthropic web
    search tool to find and cite genuine, current public information
    about a specific named program, rather than general knowledge.
    Reports plainly when search doesn't turn up anything specific.
    """
    if not payload.program_name.strip():
        raise HTTPException(status_code=400, detail="program_name is required")
    try:
        result = research_target_program(client, payload.sport, payload.level, payload.program_name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not research this program just now: {e}")
    return result
 
