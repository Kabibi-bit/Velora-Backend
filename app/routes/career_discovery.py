import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import CareerDiscoveryResult, Listing
from app.services.career_discovery import score_career_directions, explain_direction_deep, CAREER_DIRECTIONS
 
router = APIRouter(prefix="/career-discovery", tags=["career-discovery"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class DiscoveryAnswersIn(BaseModel):
    user_id: str
    people: int
    data: int
    creative: int
    structure: int
    free_text: str = ""
 
 
@router.post("")
def submit_discovery(payload: DiscoveryAnswersIn, db: Session = Depends(get_db)):
    """Scores the assessment against real stored listings (not just
    static descriptions), and saves the result so it persists.
    """
    answers = {"people": payload.people, "data": payload.data, "creative": payload.creative, "structure": payload.structure, "free_text": payload.free_text}
    listings = db.query(Listing).all()
    all_tags = [l.tags or [] for l in listings]
    directions = score_career_directions(answers, all_tags)
 
    existing = db.query(CareerDiscoveryResult).filter(CareerDiscoveryResult.user_id == payload.user_id).first()
    if existing:
        existing.answers = answers
        existing.directions = directions
    else:
        db.add(CareerDiscoveryResult(user_id=payload.user_id, answers=answers, directions=directions))
    db.commit()
 
    return {"answers": answers, "directions": directions}
 
 
@router.get("/{user_id}")
def get_discovery(user_id: str, db: Session = Depends(get_db)):
    result = db.query(CareerDiscoveryResult).filter(CareerDiscoveryResult.user_id == user_id).first()
    if not result:
        return {"answers": None, "directions": None, "note": "No discovery assessment taken yet."}
    return {"answers": result.answers, "directions": result.directions}
 
 
class ExplainDirectionIn(BaseModel):
    direction_id: str
 
 
@router.post("/{user_id}/explain")
def explain_direction(user_id: str, payload: ExplainDirectionIn, db: Session = Depends(get_db)):
    """On-demand, real Claude explanation for one direction - only
    called when someone actually wants more than the instant score,
    same cost-conscious pattern as the deep match explanation.
    """
    result = db.query(CareerDiscoveryResult).filter(CareerDiscoveryResult.user_id == user_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="No discovery assessment on file - submit one first")
 
    direction = next((d for d in CAREER_DIRECTIONS if d["id"] == payload.direction_id), None)
    if not direction:
        raise HTTPException(status_code=404, detail="Unknown direction id")
 
    explanation = explain_direction_deep(client, direction, result.answers)
    return {"direction_id": payload.direction_id, "explanation": explanation}
 
