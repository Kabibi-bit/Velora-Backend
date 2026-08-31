import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import OutreachEmail, Listing
from app.services.auto_apply import draft_outreach_for_match
from app.services.email_send import send_email
 
router = APIRouter(prefix="/outreach", tags=["outreach"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class DraftIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("/draft")
def draft_outreach(payload: DraftIn, db: Session = Depends(get_db)):
    """The 'Find a contact' action - drafts a referral email straight
    into Workshop instead of showing it inline. Never sends anything.
    """
    result = draft_outreach_for_match(db, client, payload.user_id, payload.listing_id, auto_generated=False)
    if result.get("error") == "no_profile":
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if result.get("error") == "listing_not_found":
        raise HTTPException(status_code=404, detail="Listing not found")
    if result.get("error") == "no_contact_guess":
        raise HTTPException(status_code=400, detail="Could not guess a contact address for this company")
    if result.get("error") == "draft_generation_failed":
        raise HTTPException(status_code=502, detail="Could not generate a draft just now - try again")
    return result
 
 
class DraftLeadershipGroundedIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("/draft-leadership-grounded")
def draft_leadership_grounded_outreach_endpoint(payload: DraftLeadershipGroundedIn, db: Session = Depends(get_db)):
    """Researches the company's real, current senior leadership - not
    just the CEO, but other genuine current executives too - and what
    they've actually, recently said and prioritized publicly, then
    drafts an outreach email grounded in that real, synthesized view
    - instead of a generic referral request every other applicant
    could send. Two real web-search-backed steps, not one call
    pretending to be simple: research first, then drafting, so a
    genuine "nothing specific was found" result from the first step
    honestly shapes what the second step writes, rather than the
    draft inventing something that sounds plausible.
    """
    from app.services.market_research import get_or_research_company_leadership
    from app.services.auto_apply import draft_leadership_grounded_outreach
    from app.models.db_models import Listing
 
    listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    try:
        leadership_research = get_or_research_company_leadership(db, client, listing.org)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not research the company's leadership just now: {e}")
 
    result = draft_leadership_grounded_outreach(db, client, payload.user_id, payload.listing_id, leadership_research)
    if result.get("error") == "no_profile":
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if result.get("error") == "listing_not_found":
        raise HTTPException(status_code=404, detail="Listing not found")
    if result.get("error") == "no_contact_guess":
        raise HTTPException(status_code=400, detail="Could not guess a contact address for this company")
    if result.get("error") == "draft_generation_failed":
        raise HTTPException(status_code=502, detail="Could not generate a draft just now - try again")
    return {
        **result,
        "priorities_summary": leadership_research.get("priorities_summary") or "",
        "leadership_research_sources": leadership_research.get("sources") or [],
    }
 
 
@router.get("/leadership-research/{listing_id}")
def get_leadership_research(listing_id: str, db: Session = Depends(get_db)):
    """A standalone view of the company research itself, not tied to
    drafting an email - so a candidate can genuinely understand what
    a company's real leadership seems to be prioritizing before
    deciding whether to reach out at all, not just see it buried
    inside a drafted message afterward.
    """
    from app.services.market_research import get_or_research_company_leadership
    from app.models.db_models import Listing
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    try:
        return get_or_research_company_leadership(db, client, listing.org)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not research this company's leadership just now: {e}")
 
 
@router.get("/{user_id}")
def list_outreach(user_id: str, db: Session = Depends(get_db)):
    """Lists every outreach email (drafted or sent) for Workshop -
    both auto-generated (while Auto mode was running) and manually
    requested via 'Find a contact'.
    """
    rows = (
        db.query(OutreachEmail, Listing)
        .join(Listing, OutreachEmail.listing_id == Listing.id)
        .filter(OutreachEmail.user_id == user_id)
        .order_by(OutreachEmail.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(o.id),
            "listing_id": str(o.listing_id),
            "listing_title": l.title,
            "listing_org": l.org,
            "to_address": o.to_address,
            "address_verified": o.address_verified,
            "subject": o.subject,
            "body": o.body,
            "status": o.status,
            "auto_generated": o.auto_generated,
            "created_at": o.created_at.isoformat(),
        }
        for o, l in rows
    ]
 
 
class EditOutreachIn(BaseModel):
    subject: str | None = None
    body: str | None = None
    to_address: str | None = None
 
 
@router.patch("/{outreach_id}")
def edit_outreach(outreach_id: str, payload: EditOutreachIn, db: Session = Depends(get_db)):
    """Lets the user edit a drafted email in Workshop before sending."""
    outreach = db.query(OutreachEmail).filter(OutreachEmail.id == outreach_id).first()
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
        outreach.address_verified = False  # editing the address resets verification status
    db.commit()
    return {"status": "updated"}
 
 
@router.post("/{outreach_id}/send")
def send_outreach(outreach_id: str, db: Session = Depends(get_db)):
    """The one real send action - fires only when explicitly called,
    which the frontend only does from a user clicking Send in
    Workshop. Never called automatically by any scan or Auto cycle.
    """
    outreach = db.query(OutreachEmail).filter(OutreachEmail.id == outreach_id).first()
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
 
 
@router.post("/send-all/{user_id}")
def send_all_pending(user_id: str, db: Session = Depends(get_db)):
    """The 'Send all pending outreach' bulk action for Workshop - still
    a single, explicit, human-triggered click, just covering everything
    queued at once instead of one at a time.
    """
    pending = db.query(OutreachEmail).filter(OutreachEmail.user_id == user_id, OutreachEmail.status == "drafted").all()
    results = []
    for outreach in pending:
        try:
            send_email(outreach.to_address, outreach.subject, outreach.body)
            outreach.status = "sent"
            results.append({"id": str(outreach.id), "status": "sent"})
        except Exception as e:
            outreach.status = "failed"
            results.append({"id": str(outreach.id), "status": "failed", "error": str(e)})
    db.commit()
    return {"results": results, "total": len(results)}
 
