import os
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.services.auth import require_valid_token
from pydantic import BaseModel, Field
import anthropic
from app.services.ai_client import get_client
 
from app.services.assistance import find_assistance_options
from app.services.rate_limit import rate_limit_by_tier
from app.db import get_db
from sqlalchemy.orm import Session
 
_log = logging.getLogger("velora")
router = APIRouter(prefix="/assistance", tags=["assistance"])
 
 
class AssistanceSearchIn(BaseModel):
    user_id: str | None = None
    need_description: str = Field(max_length=4000)
    budget: str = Field(max_length=200)
    location_context: str | None = Field(default=None, max_length=200)
 
 
@router.post("/search")
def search_assistance(payload: AssistanceSearchIn, db: Session = Depends(get_db), _auth: dict = Depends(require_valid_token)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    if not payload.need_description.strip():
        raise HTTPException(status_code=400, detail="need_description is required")
    if not payload.budget.strip():
        raise HTTPException(status_code=400, detail="budget is required")
    if payload.user_id:
        rate_limit_by_tier(db, payload.user_id, "company-research", per_action_limit=100)
    try:
        result = find_assistance_options(client, payload.need_description, payload.budget, payload.location_context or "")
    except Exception as e:
        _log.warning("Could not complete this search just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not complete this search just now. Please try again.")
    return result
 
