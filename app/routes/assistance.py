import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import anthropic
 
from app.services.assistance import find_assistance_options
 
router = APIRouter(prefix="/assistance", tags=["assistance"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class AssistanceSearchIn(BaseModel):
    need_description: str
    budget: str
    location_context: str | None = None
 
 
@router.post("/search")
def search_assistance(payload: AssistanceSearchIn):
    if not payload.need_description.strip():
        raise HTTPException(status_code=400, detail="need_description is required")
    if not payload.budget.strip():
        raise HTTPException(status_code=400, detail="budget is required")
    try:
        result = find_assistance_options(client, payload.need_description, payload.budget, payload.location_context or "")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not complete this search just now: {e}")
    return result
 
