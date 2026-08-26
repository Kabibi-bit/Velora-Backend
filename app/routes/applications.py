import os
from datetime import date
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import AthleteEvent, AthleteOutreach
from app.services.athletics import generate_recruiting_content_plan, research_target_program, draft_coach_outreach, generate_clip_edit_plan
from app.services.email_send import guess_contact_emails, send_email
 
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
 
 
VALID_EVENT_TYPES = {"tryout", "camp", "combine", "application_deadline", "other"}
VALID_EVENT_STATUSES = {"upcoming", "attended", "passed", "missed"}
 
 
class EventIn(BaseModel):
    user_id: str
    title: str
    org: str | None = None
    event_type: str
    event_date: date | None = None
    roadmap_stage: int | None = None
    roadmap_stage_title: str | None = None
    notes: str | None = None
 
 
@router.post("/events")
def create_event(payload: EventIn, db: Session = Depends(get_db)):
    """Tracks a deadline or trial opportunity - a tryout, camp,
    combine, or application deadline - optionally tied to a specific
    roadmap stage.
    """
    if payload.event_type not in VALID_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"event_type must be one of {VALID_EVENT_TYPES}")
    event = AthleteEvent(
        user_id=payload.user_id, title=payload.title, org=payload.org,
        event_type=payload.event_type, event_date=payload.event_date,
        roadmap_stage=payload.roadmap_stage, roadmap_stage_title=payload.roadmap_stage_title,
        notes=payload.notes,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"event_id": str(event.id), "status": "created"}
 
 
@router.get("/events/{user_id}")
def list_events(user_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(AthleteEvent)
        .filter(AthleteEvent.user_id == user_id)
        .order_by(AthleteEvent.event_date.asc().nullslast())
        .all()
    )
    return [
        {
            "id": str(e.id), "title": e.title, "org": e.org, "event_type": e.event_type,
            "event_date": e.event_date.isoformat() if e.event_date else None,
            "roadmap_stage": e.roadmap_stage, "roadmap_stage_title": e.roadmap_stage_title,
            "status": e.status, "notes": e.notes, "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]
 
 
class EventStatusIn(BaseModel):
    status: str
 
 
@router.post("/events/{event_id}/status")
def update_event_status(event_id: str, payload: EventStatusIn, db: Session = Depends(get_db)):
    if payload.status not in VALID_EVENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_EVENT_STATUSES}")
    event = db.query(AthleteEvent).filter(AthleteEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event.status = payload.status
    db.commit()
    return {"status": "updated", "event_status": event.status}
 
 
@router.delete("/events/{event_id}")
def delete_event(event_id: str, db: Session = Depends(get_db)):
    event = db.query(AthleteEvent).filter(AthleteEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(event)
    db.commit()
    return {"status": "deleted"}
 
 
class CoachOutreachIn(BaseModel):
    user_id: str
    sport: str
    level: str
    career_direction: str
    achievements: str = ""
    target_description: str
    org_name: str
    roadmap_stage: int | None = None
    roadmap_stage_title: str | None = None
 
 
@router.post("/outreach")
def create_outreach(payload: CoachOutreachIn, db: Session = Depends(get_db)):
    """Drafts a real email and cold-call script for reaching a coach or
    staff member, and stores it as a real draft - review/edit/send
    from here, same lifecycle as every other outreach draft in the
    app. Never invents a specific named person - only describes the
    TYPE of contact and gives a real, usable script.
    """
    try:
        drafted = draft_coach_outreach(
            client, payload.sport, payload.level, payload.career_direction,
            payload.achievements, payload.target_description,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate outreach just now: {e}")
 
    guess = guess_contact_emails(payload.org_name)
    if not guess.get("candidates"):
        raise HTTPException(status_code=400, detail="Could not guess a contact address for this program")
 
    outreach = AthleteOutreach(
        user_id=payload.user_id,
        target_description=payload.target_description,
        to_address=guess["candidates"][0],
        address_verified=False,
        subject=drafted["email_subject"],
        body=drafted["email_body"],
        cold_call_script=drafted["cold_call_script"],
        roadmap_stage=payload.roadmap_stage,
        roadmap_stage_title=payload.roadmap_stage_title,
    )
    db.add(outreach)
    db.commit()
    db.refresh(outreach)
    return {
        "outreach_id": str(outreach.id),
        "who_to_contact": drafted["who_to_contact"],
        "how_to_find": drafted["how_to_find"],
        "to_address": outreach.to_address,
        "subject": outreach.subject,
        "body": outreach.body,
        "cold_call_script": outreach.cold_call_script,
        "status": "drafted",
    }
 
 
@router.get("/outreach/{user_id}")
def list_outreach(user_id: str, db: Session = Depends(get_db)):
    rows = db.query(AthleteOutreach).filter(AthleteOutreach.user_id == user_id).order_by(AthleteOutreach.created_at.desc()).all()
    return [
        {
            "id": str(o.id), "target_description": o.target_description, "to_address": o.to_address,
            "subject": o.subject, "body": o.body, "cold_call_script": o.cold_call_script,
            "roadmap_stage": o.roadmap_stage, "roadmap_stage_title": o.roadmap_stage_title,
            "status": o.status, "created_at": o.created_at.isoformat(),
        }
        for o in rows
    ]
 
 
class EditOutreachIn(BaseModel):
    subject: str | None = None
    body: str | None = None
    to_address: str | None = None
 
 
@router.patch("/outreach/{outreach_id}")
def edit_outreach(outreach_id: str, payload: EditOutreachIn, db: Session = Depends(get_db)):
    outreach = db.query(AthleteOutreach).filter(AthleteOutreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    if outreach.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent, cannot edit")
    if payload.subject is not None:
        outreach.subject = payload.subject
    if payload.body is not None:
        outreach.body = payload.body
    if payload.to_address is not None:
        outreach.to_address = payload.to_address
        outreach.address_verified = False
    db.commit()
    return {"status": "updated"}
 
 
@router.post("/outreach/{outreach_id}/send")
def send_outreach(outreach_id: str, db: Session = Depends(get_db)):
    outreach = db.query(AthleteOutreach).filter(AthleteOutreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach draft not found")
    if outreach.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent")
    try:
        send_email(outreach.to_address, outreach.subject, outreach.body)
        outreach.status = "sent"
        db.commit()
        return {"status": "sent", "to_address": outreach.to_address}
    except Exception as e:
        outreach.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Send failed: {e}")
 
 
class ClipEditPlanIn(BaseModel):
    sport: str
    level: str
    career_direction: str
    clips_description: str
 
 
@router.post("/edit-plan")
def edit_plan(payload: ClipEditPlanIn):
    """Not real video editing or processing - there's no video hosting
    infrastructure in this stack. This is a real, specific edit PLAN
    grounded in the athlete's own description of their footage, for
    them to execute in whatever editor they already use.
    """
    if not payload.clips_description.strip():
        raise HTTPException(status_code=400, detail="clips_description is required")
    try:
        plan = generate_clip_edit_plan(
            client, payload.sport, payload.level, payload.career_direction, payload.clips_description
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate an edit plan just now: {e}")
    return plan
 
