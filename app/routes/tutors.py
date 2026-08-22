"""Tutor marketplace: public application, admin approval (quality
gate), search by skill, and students requesting a tutor for a
specific skill gap identified by their roadmap/matching results.
 
Admin actions (approve/reject) are protected by a simple shared
secret (ADMIN_SECRET env var) rather than a full auth system, since
you're the only admin right now. Set ADMIN_SECRET in Render's
environment variables to any private value you choose.
"""
import os
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Tutor, TutorRequest
 
router = APIRouter(prefix="/tutors", tags=["tutors"])
 
ADMIN_SECRET = os.getenv("ADMIN_SECRET")
 
 
def _require_admin(x_admin_secret: str = Header(default="")):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access required (X-Admin-Secret header)")
 
 
class TutorApplicationIn(BaseModel):
    name: str
    email: EmailStr
    bio: str
    expertise_tags: list[str]
    certifications: list[str] = []
    hourly_rate: float | None = None
 
 
@router.post("/apply")
def apply_as_tutor(payload: TutorApplicationIn, db: Session = Depends(get_db)):
    """Public endpoint - anyone can apply. They start as 'pending'
    and are invisible to students until you approve them.
    """
    existing = db.query(Tutor).filter(Tutor.email == payload.email).first()
    if existing:
        return {"status": "already applied", "tutor_id": str(existing.id), "application_status": existing.application_status}
 
    tutor = Tutor(
        name=payload.name,
        email=payload.email,
        bio=payload.bio,
        expertise_tags=payload.expertise_tags,
        certifications=payload.certifications,
        hourly_rate=payload.hourly_rate,
        application_status="pending",
    )
    db.add(tutor)
    db.commit()
    db.refresh(tutor)
    return {"status": "submitted", "tutor_id": str(tutor.id)}
 
 
@router.get("/pending")
def list_pending_applications(db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    """Admin-only: your review queue."""
    tutors = db.query(Tutor).filter(Tutor.application_status == "pending").all()
    return [
        {
            "id": str(t.id), "name": t.name, "email": t.email, "bio": t.bio,
            "expertise_tags": t.expertise_tags, "certifications": t.certifications,
            "hourly_rate": float(t.hourly_rate) if t.hourly_rate else None,
        }
        for t in tutors
    ]
 
 
class ReviewIn(BaseModel):
    decision: str  # "approved" or "rejected"
    notes: str | None = None
 
 
@router.post("/{tutor_id}/review")
def review_tutor(tutor_id: str, payload: ReviewIn, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    """Admin-only: the actual quality gate for your ecosystem."""
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")
    tutor = db.query(Tutor).filter(Tutor.id == tutor_id).first()
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")
    tutor.application_status = payload.decision
    tutor.application_notes = payload.notes
    db.commit()
    return {"status": payload.decision, "tutor_id": tutor_id}
 
 
@router.get("/search")
def search_tutors(skill: str, db: Session = Depends(get_db)):
    """Public: find APPROVED tutors matching a skill/certificate need.
    Only ever returns approved tutors - this is the quality gate in action.
    """
    tutors = (
        db.query(Tutor)
        .filter(Tutor.application_status == "approved")
        .all()
    )
    matches = [t for t in tutors if any(skill.lower() in tag.lower() for tag in (t.expertise_tags or []))]
    return [
        {
            "id": str(t.id), "name": t.name, "bio": t.bio,
            "expertise_tags": t.expertise_tags, "hourly_rate": float(t.hourly_rate) if t.hourly_rate else None,
        }
        for t in matches
    ]
 
 
class RequestTutorIn(BaseModel):
    user_id: str
    tutor_id: str
    skill_gap: str
    message: str | None = None
 
 
@router.post("/request")
def request_tutor(payload: RequestTutorIn, db: Session = Depends(get_db)):
    tutor = db.query(Tutor).filter(Tutor.id == payload.tutor_id, Tutor.application_status == "approved").first()
    if not tutor:
        raise HTTPException(status_code=404, detail="Approved tutor not found")
    req = TutorRequest(
        user_id=payload.user_id, tutor_id=payload.tutor_id,
        skill_gap=payload.skill_gap, message=payload.message,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"status": "requested", "request_id": str(req.id), "note": "No messaging/scheduling system yet - this just records the request. You'd need to follow up with the tutor's email directly for now."}
 
 
VALID_SESSION_STATUSES = {"accepted", "declined", "completed", "cancelled", "no_show"}
 
 
class SessionStatusIn(BaseModel):
    status: str
 
 
@router.post("/requests/{request_id}/status")
def update_session_status(request_id: str, payload: SessionStatusIn, db: Session = Depends(get_db)):
    """Marks a tutoring session's real outcome - this is what backs
    the tutor dashboard's session donut and monthly target charts.
    """
    if payload.status not in VALID_SESSION_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_SESSION_STATUSES}")
    req = db.query(TutorRequest).filter(TutorRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    req.status = payload.status
    db.commit()
    return {"status": "updated", "new_status": payload.status}
 
 
@router.get("/{tutor_id}/sessions/stats")
def get_session_stats(tutor_id: str, db: Session = Depends(get_db)):
    rows = db.query(TutorRequest).filter(TutorRequest.tutor_id == tutor_id).all()
    by_status = {}
    by_month = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        month_key = r.created_at.strftime("%b")
        by_month[month_key] = by_month.get(month_key, 0) + 1
    return {"total": len(rows), "by_status": by_status, "by_month": by_month}
 
