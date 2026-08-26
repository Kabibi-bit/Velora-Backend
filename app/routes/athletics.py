import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import anthropic
 
from app.services.athletics import generate_recruiting_content_plan
 
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
 
