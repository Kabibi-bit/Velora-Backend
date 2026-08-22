from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Outcome
 
router = APIRouter(prefix="/outcomes", tags=["outcomes"])
 
VALID_STATUSES = {"applied", "interview", "rejected", "ghosted", "offer"}
 
 
class OutcomeIn(BaseModel):
    user_id: str
    listing_id: str
    status: str
 
 
@router.post("")
def log_outcome(payload: OutcomeIn, db: Session = Depends(get_db)):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}")
    outcome = Outcome(user_id=payload.user_id, listing_id=payload.listing_id, status=payload.status)
    db.add(outcome)
    db.commit()
    return {"status": "logged", "outcome_status": payload.status}
 
 
@router.get("/{user_id}")
def get_outcomes(user_id: str, db: Session = Depends(get_db)):
    rows = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    return [{"listing_id": str(r.listing_id), "status": r.status, "updated_at": r.updated_at.isoformat()} for r in rows]
 
 
@router.get("/{user_id}/stats")
def get_outcome_stats(user_id: str, db: Session = Depends(get_db)):
    """Real aggregation backing the dashboard's donut chart and monthly
    target chart - counts by status, and counts by month for the last
    3 months, computed from actual logged outcomes (no mock numbers).
    """
    rows = db.query(Outcome).filter(Outcome.user_id == user_id).all()
 
    by_status = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
 
    by_month = {}
    for r in rows:
        month_key = r.updated_at.strftime("%b")
        by_month[month_key] = by_month.get(month_key, 0) + 1
 
    return {
        "total": len(rows),
        "by_status": by_status,
        "by_month": by_month,
    }
 
