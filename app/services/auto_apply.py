"""Real auto-apply logic: drafts an application via Claude, decides
whether it's confident enough to auto-send or needs human review,
and enforces an undo window before anything is considered final.
 
Honest limitation: there is no real mechanism here that actually
submits a form on a real job site -- send_application() marks the
record as "sent" in your own database, it does not reach out to
Adzuna or any employer's website. Building a real submission bot is
a much larger, higher-risk project (site-specific automation, ToS
review per site) intentionally left out of this version.
"""
import os
from datetime import datetime, timedelta
 
CONFIDENCE_THRESHOLD = int(os.getenv("AUTO_APPLY_THRESHOLD", "80"))
UNDO_WINDOW_MINUTES = int(os.getenv("UNDO_WINDOW_MINUTES", "30"))
 
 
def draft_application(anthropic_client, listing: dict, profile: dict) -> str:
    prompt = (
        f"Write a short, tailored cover-letter-style paragraph (120-180 words) "
        f"for this listing: \"{listing['title']}\" at {listing['org']}.\n"
        f"Candidate's goal: \"{profile['northstar']}\"\n"
        f"Candidate's skills: \"{profile.get('skills', '')}\"\n"
        "Be concrete and specific, no generic filler, no placeholder brackets."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
 
def decide_auto_send(confidence_pct: float) -> str:
    """Returns 'approved' (auto-send eligible) or 'pending_review'."""
    return "approved" if confidence_pct >= CONFIDENCE_THRESHOLD else "pending_review"
 
 
def compute_sendable_at() -> datetime:
    """The undo window: even an approved application isn't 'sent' until
    this time passes, giving a window to cancel."""
    return datetime.utcnow() + timedelta(minutes=UNDO_WINDOW_MINUTES)
 
 
def create_application_for_match(db, anthropic_client, user_id: str, listing_id: str):
    """The actual 'accept a match -> draft an application' pipeline,
    shared by both the explicit /applications/accept endpoint and the
    automatic trigger when a user stars a listing via /saved. Returns
    a dict describing the result, or a dict with an 'error' key if it
    couldn't run (e.g. no profile yet, deal-breaker conflict) --
    callers decide whether that's fatal or just skipped silently.
    """
    from app.models.db_models import Profile, Listing, Application
    from app.services.matching import score_listing
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        return {"error": "no_profile"}
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        return {"error": "listing_not_found"}
 
    existing = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.listing_id == listing_id)
        .first()
    )
    if existing:
        return {
            "application_id": str(existing.id),
            "status": existing.status,
            "draft": existing.draft_content,
            "already_existed": True,
        }
 
    profile_dict = {
        "northstar": profile.northstar,
        "final_idea": profile.final_idea or "",
        "skills": profile.skills or "",
        "dealbreakers": profile.dealbreakers or "",
        "priorities": profile.priorities or [],
    }
    listing_dict = {
        "type": listing.type,
        "tags": listing.tags or [],
        "title": listing.title,
        "org": listing.org,
    }
 
    match = score_listing(listing_dict, profile_dict)
    if match is None:
        return {"error": "dealbreaker_conflict"}
 
    draft_text = draft_application(anthropic_client, listing_dict, profile_dict)
    status = decide_auto_send(match["score_pct"])
 
    app_record = Application(
        user_id=user_id,
        listing_id=listing_id,
        draft_content=draft_text,
        confidence_pct=match["score_pct"],
        status=status,
        sendable_at=compute_sendable_at() if status == "approved" else None,
    )
    db.add(app_record)
    db.commit()
    db.refresh(app_record)
 
    return {
        "application_id": str(app_record.id),
        "match_score": match["score_pct"],
        "status": status,
        "draft": draft_text,
        "already_existed": False,
    }
  
