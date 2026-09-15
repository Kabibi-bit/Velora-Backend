import os
from fastapi import APIRouter, HTTPException, Depends
from app.services.auth import require_valid_token
from pydantic import BaseModel, Field
import anthropic
 
from app.services.assistance import find_assistance_options
from app.services.rate_limit import rate_limit_by_tier
from app.db import get_db
from sqlalchemy.orm import Session
 
router = APIRouter(prefix="/assistance", tags=["assistance"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class AssistanceSearchIn(BaseModel):
    user_id: str | None = None
    need_description: str = Field(max_length=4000)
    budget: str = Field(max_length=200)
    location_context: str | None = Field(default=None, max_length=200)
 
 
@router.post("/search")
def search_assistance(payload: AssistanceSearchIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    if not payload.need_description.strip():
        raise HTTPException(status_code=400, detail="need_description is required")
    if not payload.budget.strip():
        raise HTTPException(status_code=400, detail="budget is required")
    if payload.user_id:
        rate_limit_by_tier(db, payload.user_id, "company-research", per_action_limit=100)
    try:
        result = find_assistance_options(client, payload.need_description, payload.budget, payload.location_context or "")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not complete this search just now: {e}")
    return result
 
