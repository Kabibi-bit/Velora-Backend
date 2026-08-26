import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Profile, RoadmapSummary
from app.services.market_research import research_company, generate_interview_prep
 
router = APIRouter(prefix="/market", tags=["market"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class CompanyResearchIn(BaseModel):
    company_name: str
    role_title: str
 
 
@router.post("/research-company")
def research_company_route(payload: CompanyResearchIn):
    if not payload.company_name.strip():
        raise HTTPException(status_code=400, detail="company_name is required")
    try:
        result = research_company(client, payload.company_name, payload.role_title)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not research this company just now: {e}")
    return result
 
 
class InterviewPrepIn(BaseModel):
    user_id: str
    company_name: str
    role_title: str
    company_research: str | None = None
 
 
@router.post("/interview-prep")
def interview_prep_route(payload: InterviewPrepIn, db: Session = Depends(get_db)):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == payload.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    roadmap_summary_row = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == payload.user_id).first()
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
 
    try:
        prep = generate_interview_prep(
            client, payload.company_name, payload.role_title, payload.company_research,
            profile_dict, roadmap_summary_row.summary if roadmap_summary_row else None,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate interview prep just now: {e}")
    return prep
 
