import os
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Header
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.rate_limit import rate_limit_by_tier
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import anthropic
from app.services.ai_client import get_client
 
from app.db import get_db
from app.models.db_models import Application
from app.services.auto_apply import (
    draft_application,
    decide_auto_send,
    compute_sendable_at,
    create_application_for_match,
    decide_application_delivery,
)
from app.services.timeutil import utcnow, to_naive_utc
 
_log = logging.getLogger("velora")
 
 
def _applicant_context(db, user_id):
    """Assemble the real applicant data used to fill a web application form for
    Pro auto-submit: a candidate dict (name/email/phone) and, when the user has
    real resume entries, a generated .docx resume file to upload. Returns
    (candidate, resume_path_or_None). resume_path, if returned, is a temp file
    the caller must delete. Never invents data - missing fields stay empty, and
    the submitter safely hands off any form that needs what we don't have."""
    import os as _os
    import tempfile
    from app.models.db_models import Profile, ResumeEntry, User
    user = db.query(User).filter(User.id == user_id).first()
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    email = (user.email if user else "") or ""
    full_name = ((profile.full_name if profile else "") or "").strip()
    phone = ((profile.phone if profile else "") or "").strip()
    first, last = "", ""
    if full_name:
        parts = full_name.split()
        first, last = parts[0], (parts[-1] if len(parts) > 1 else "")
    candidate = {"full_name": full_name, "first_name": first, "last_name": last, "email": email, "phone": phone}
 
    resume_path = None
    try:
        entries = (
            db.query(ResumeEntry)
            .filter(ResumeEntry.user_id == user_id)
            .order_by(ResumeEntry.display_order.asc())
            .all()
        )
        if entries:
            from app.services.resume_docx import generate_resume_document
            polished = [{
                "title": e.title or "",
                "org": e.org or "",
                "dates": " - ".join(x for x in [e.start_date, e.end_date] if x),
                "bullets": [e.raw_description] if e.raw_description else [],
            } for e in entries]
            skills = [s.strip() for s in ((profile.skills if profile else "") or "").replace(",", " ").split() if s.strip()]
            data = generate_resume_document(email, None, polished, skills)
            fd, resume_path = tempfile.mkstemp(suffix=".docx")
            with _os.fdopen(fd, "wb") as fh:
                fh.write(data)
    except Exception as e:
        _log.warning("Could not build a resume file for auto-submit - %s", e)
        resume_path = None
    return candidate, resume_path
router = APIRouter(prefix="/applications", tags=["applications"])
 
 
class AcceptIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("/accept")
def accept_match(payload: AcceptIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """The one-click 'I accept this match' action - this is also what
    fires automatically when a user stars a listing (see /saved in
    saved_listings.py). Computes the real match score, drafts a
    tailored application via Claude, and decides whether it's
    confident enough to queue for auto-send or needs human review.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    verify_token_belongs_to_user(payload.user_id, authorization)
    try:
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
    # Meter this paid AI drafting (was unmetered - it's the primary "apply"/star
    # action, so the highest-traffic gap). Matches the sibling /draft route's cap.
    # Fails open.
    rate_limit_by_tier(db, payload.user_id, "application-draft", per_action_limit=200)
    result = create_application_for_match(db, client, payload.user_id, payload.listing_id)
 
    if result.get("error") == "no_profile":
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if result.get("error") == "listing_not_found":
        raise HTTPException(status_code=404, detail="Listing not found")
    if result.get("error") == "dealbreaker_conflict":
        raise HTTPException(status_code=400, detail="This listing conflicts with one of your stated deal-breakers - not drafting an application for it.")
 
    if result.get("already_existed"):
        result["note"] = "An application for this match already exists - returning it instead of drafting a duplicate."
    else:
        result["note"] = "approved = eligible to auto-send after the undo window; pending_review = needs your explicit approval first"
    return result
 
 
class DraftIn(BaseModel):
    user_id: str
    listing_id: str
    confidence_pct: float = Field(ge=0, le=100)
 
 
@router.post("/draft")
def create_draft(payload: DraftIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    client = get_client()
    if client is None:
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503, detail="AI service is not configured. Please try again later.")
    """Drafts an application and decides auto-send vs review, based on
    the confidence score you pass in (use the score from /listings/matches).
    Kept for manual/testing use - /accept is the real one-click path.
    """
    from app.models.db_models import Profile, Listing, ResumeEntry
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    verify_token_belongs_to_user(payload.user_id, authorization)
    rate_limit_by_tier(db, payload.user_id, "application-draft", per_action_limit=300)
    try:
        uuid_module.UUID(payload.listing_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == payload.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
    listing_dict = {"title": listing.title, "org": listing.org, "tags": listing.tags or []}
    resume_entry_rows = db.query(ResumeEntry).filter(ResumeEntry.user_id == payload.user_id).all()
    resume_entry_dicts = [{"title": e.title, "org": e.org, "raw_description": e.raw_description} for e in resume_entry_rows]
    draft_result = draft_application(client, listing_dict, profile_dict, resume_entry_dicts)
    # A genuine API failure returns {"error": ...} with no "text" key -
    # confirmed this was previously accessed directly without checking,
    # unlike create_application_for_match, which correctly guards
    # against the identical shape from the same function.
    if "error" in draft_result:
        # The service encodes the raw exception in draft_result["error"] (e.g.
        # "draft_generation_failed: <exception>"); log that server-side but return
        # a generic message so the internal detail never reaches the client.
        _log.warning("Application draft failed - %s", draft_result["error"])
        raise HTTPException(status_code=502, detail="Could not generate a draft just now. Please try again.")
    draft_text = draft_result["text"]
    status = decide_auto_send(payload.confidence_pct)
 
    app_record = Application(
        user_id=payload.user_id,
        listing_id=payload.listing_id,
        draft_content=draft_text,
        confidence_pct=payload.confidence_pct,
        status=status,
        sendable_at=compute_sendable_at() if status == "approved" else None,
        draft_flagged_terms=draft_result["flagged_terms"],
        # factors_snapshot intentionally left None here - this fallback
        # endpoint takes confidence_pct directly from the caller rather
        # than computing it via score_listing(), so there's no real
        # factor breakdown to capture. The primary path (/accept, via
        # create_application_for_match) does capture it.
    )
    db.add(app_record)
    db.commit()
    db.refresh(app_record)
 
    return {
        "application_id": str(app_record.id),
        "status": status,
        "draft": draft_text,
        "review_note": "This draft includes a number or timing claim that wasn't in the job posting or your profile - double check it before sending." if draft_result["flagged_terms"] else None,
        "note": "approved = eligible to auto-send after the undo window; pending_review = needs your explicit approval first",
    }
 
 
@router.get("/{user_id}")
def list_applications(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Lists all drafted applications for a user - this is what backs
    the frontend's Workshop page.
    """
    from app.models.db_models import Listing
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    rows = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
        .all()
    )
 
    # Join the real logged outcomes so each application carries its
    # outcome_status. Without this, the frontend - which reads
    # a.outcome_status in ~25 places (outcome badges, calibration, the
    # rejection/ghost autopsy, "any positive" checks) - saw undefined for
    # every logged-in application, because overview/workshop overwrite local
    # state with this response (saveApplications(bApps)). A user who logged an
    # outcome would lose it from the UI on their next visit even though the
    # backend had it the whole time. Keep the most recent outcome per listing.
    from app.models.db_models import Outcome
    outcome_rows = (
        db.query(Outcome)
        .filter(Outcome.user_id == user_id)
        .order_by(Outcome.updated_at.asc())
        .all()
    )
    outcome_status_by_listing = {}
    outcome_time_by_listing = {}
    for o in outcome_rows:  # ascending order -> last write per listing wins (most recent)
        outcome_status_by_listing[str(o.listing_id)] = o.status
        outcome_time_by_listing[str(o.listing_id)] = o.updated_at
 
    return [
        {
            "id": str(a.id),
            "listing_id": str(a.listing_id),
            "listing_title": l.title,
            "listing_org": l.org,
            "status": a.status,
            "confidence_pct": float(a.confidence_pct) if a.confidence_pct else None,
            "draft": a.draft_content,
            "sendable_at": a.sendable_at.isoformat() if a.sendable_at else None,
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            # How/where an accepted application was actually delivered - so the
            # Workshop can honestly show "emailed to <addr>" vs. a web hand-off
            # with the direct apply link, instead of a bare "sent" label.
            "sent_channel": a.sent_channel,
            "sent_to_address": a.sent_to_address,
            "apply_url": l.apply_url,
            "auto_generated": a.auto_generated,
            "created_at": a.created_at.isoformat(),
            "outcome_status": outcome_status_by_listing.get(str(a.listing_id)),
            "outcome_logged_at": outcome_time_by_listing[str(a.listing_id)].isoformat() if outcome_time_by_listing.get(str(a.listing_id)) else None,
            # The frontend overwrites local application state with this response
            # (overview/workshop call saveApplications(bApps)), and its
            # outcome-learned personalization, self-audit, and factor-interaction
            # features read these two off each application:
            # getPersonalizedFactorWeightsJS / getFactorReliabilityDetail /
            # computeFactorInteractions filter on factors_snapshot, and
            # auditPersonalizationEffect needs counterfactual_confidence_pct.
            # Omitting them silently reset ALL of those to "no data" on a logged-in
            # user's next visit even though the backend stored them - the exact
            # hydration-drop already fixed just above for outcome_status.
            # `is not None` (not truthiness) so a genuine 0 counterfactual survives.
            "counterfactual_confidence_pct": float(a.counterfactual_confidence_pct) if a.counterfactual_confidence_pct is not None else None,
            "factors_snapshot": a.factors_snapshot,
        }
        for a, l in rows
    ]
 
 
@router.post("/{application_id}/approve")
def approve_application(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """For applications sitting in pending_review - the human approval step."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    app_record.status = "approved"
    app_record.sendable_at = compute_sendable_at()
    db.commit()
    return {"status": "approved", "sendable_at": app_record.sendable_at.isoformat()}
 
 
@router.post("/{application_id}/send")
def send_application(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Delivers an accepted application for real - only if approved and the
    undo window has passed.
 
    Metis picks the most effective real channel for the listing:
      - "email": the app sends the accepted application to a best-effort
        general company address via Resend (a real email). status -> "sent".
      - "web": an arbitrary job site's form cannot be auto-submitted, so the
        real route is the posting's own apply_url; the finished application is
        handed back for the user to submit there. status -> "ready_to_submit"
        (the user confirms via /mark-submitted once they've actually applied).
 
    It never claims a submission it didn't make, and never emails a fabricated
    named person - only a general, best-effort company address, and only when
    Metis judges a direct email genuinely more effective than the real posting.
    """
    from app.models.db_models import Listing, Profile as Profile_
    from app.services.email_send import send_email
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    # "approved" is a fresh send; "ready_to_submit" is a retry of a delivery that
    # previously fell back to the hand-off (e.g. the user has now granted consent),
    # so allow it to re-attempt without going back through the undo window.
    if app_record.status not in ("approved", "ready_to_submit"):
        raise HTTPException(status_code=400, detail="Application is not approved yet")
    if app_record.status == "approved":
        # Coerce the DB value to naive UTC: sendable_at is TIMESTAMPTZ, so psycopg2
        # reads it back tz-aware, and comparing/subtracting it against the naive
        # utcnow() would raise "can't compare offset-naive and offset-aware datetimes"
        # on real Postgres (it just happens to work if the dev DB returns naive).
        _sendable_at = to_naive_utc(app_record.sendable_at)
        if _sendable_at and utcnow() < _sendable_at:
            remaining = (_sendable_at - utcnow()).seconds // 60
            raise HTTPException(status_code=400, detail=f"Still in undo window - {remaining} minutes left")
 
    # Meter this: send now makes a paid AI call (Metis' channel decision), so an
    # unmetered send would let one token run up an unbounded bill. Matches the
    # sibling draft/accept caps. Fails open (see rate_limit_by_tier).
    rate_limit_by_tier(db, str(app_record.user_id), "application-send", per_action_limit=200)
 
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing_dict = {
        "title": listing.title, "org": listing.org, "type": listing.type,
        "description": listing.description, "apply_url": listing.apply_url,
    }
 
    # Metis decides the most effective real channel. Any failure degrades
    # safely to the honest default - hand the finished application to the user
    # to submit at the real posting - rather than a fabricated or blocked send.
    client = get_client()
    plan = {"channel": "web", "to_address": None, "subject": "", "reasoning": ""}
    if client is not None:
        try:
            plan = decide_application_delivery(client, listing_dict)
        except Exception as e:
            _log.warning("Delivery-channel decision failed, defaulting to web hand-off - %s", e)
 
    def _web_handoff(reasoning: str, email_error: bool = False, pro_only: bool = False, auto_note: str = None, consent_needed: bool = False):
        # The real route is the posting's own form. When it can't be auto-submitted
        # (free tier, no consent, a blocker, or a field we can't safely fill), hand
        # back the finished application + the direct link for the user to submit.
        app_record.status = "ready_to_submit"
        app_record.sent_channel = "web"
        db.commit()
        out = {
            "status": "ready_to_submit", "channel": "web",
            "apply_url": listing.apply_url, "draft_content": app_record.draft_content,
            "reasoning": reasoning,
        }
        if email_error:
            out["email_error"] = True
        if pro_only:
            out["auto_submit_pro_only"] = True
        if consent_needed:
            out["auto_submit_consent_needed"] = True
        if auto_note:
            out["auto_submit_note"] = auto_note
        return out
 
    if plan.get("channel") == "email" and plan.get("to_address"):
        subject = plan.get("subject") or f"Application: {listing.title} at {listing.org}"
        body = (app_record.draft_content or "").strip() or "Please find my application below."
        try:
            send_email(plan["to_address"], subject, body)
        except Exception as e:
            # Real send failed (e.g. Resend not configured). Do NOT mark it
            # sent - fall back to the honest web hand-off so the accepted
            # application is never silently lost or falsely reported as sent.
            _log.warning("Application email send failed, falling back to web hand-off - %s", e)
            return _web_handoff(
                "Couldn't send the email just now, so here's the finished application to submit at the posting directly.",
                email_error=True,
            )
        app_record.status = "sent"
        app_record.sent_at = utcnow()
        app_record.sent_channel = "email"
        app_record.sent_to_address = plan["to_address"]
        db.commit()
        return {
            "status": "sent", "channel": "email",
            "sent_at": app_record.sent_at.isoformat(),
            "to_address": plan["to_address"], "address_is_guess": True,
            "reasoning": plan.get("reasoning", ""),
        }
 
    # Web channel: the real route is the posting's own form. Pro members get a
    # real best-effort browser auto-submission first; free members (and any form
    # that can't be auto-completed safely) get the honest hand-off.
    from app.services.tiers import tier_has_feature, get_user_tier
    reasoning = plan.get("reasoning", "")
    if not tier_has_feature(get_user_tier(db, str(app_record.user_id)), "auto_submit"):
        return _web_handoff(reasoning, pro_only=True)
 
    # Explicit, revocable permission is required before Kaidostar uses the user's
    # personal details to submit an application to an employer on their behalf.
    _profile = (
        db.query(Profile_)
        .filter(Profile_.user_id == app_record.user_id, Profile_.is_current == True)  # noqa: E712
        .first()
    )
    if not (_profile and getattr(_profile, "auto_submit_consent", False)):
        return _web_handoff(reasoning, consent_needed=True,
                            auto_note="Give Kaidostar permission to submit applications for you to turn on automatic submission.")
 
    # Pro/Max + consent: meter, then attempt the real submission. The submitter is
    # safety-first - it aborts on logins/CAPTCHAs or any required field it can't
    # fill, and only reports success on a real confirmation - so this never
    # submits a garbled application, and falls back to the hand-off otherwise.
    rate_limit_by_tier(db, str(app_record.user_id), "application-autosubmit", per_action_limit=40)
    from app.services.application_submit import submit_application_via_browser
    candidate, resume_path = _applicant_context(db, app_record.user_id)
    try:
        result = submit_application_via_browser(
            listing.apply_url, candidate,
            resume_path=resume_path, cover_letter=app_record.draft_content,
        )
    except Exception as e:
        _log.warning("Auto-submit crashed, handing off - %s", e)
        result = {"status": "error", "reason": str(e)}
    finally:
        if resume_path:
            try:
                os.remove(resume_path)
            except Exception:
                pass
 
    if result.get("status") == "submitted":
        app_record.status = "sent"
        app_record.sent_at = utcnow()
        app_record.sent_channel = "web_auto"
        db.commit()
        return {
            "status": "sent", "channel": "web_auto",
            "sent_at": app_record.sent_at.isoformat(),
            "apply_url": listing.apply_url,
            "reasoning": reasoning,
            "auto_submit_note": result.get("reason", ""),
        }
    # Couldn't auto-complete it safely - honest hand-off with the real reason.
    return _web_handoff(reasoning, auto_note=result.get("reason", ""))
 
 
@router.post("/{application_id}/mark-submitted")
def mark_application_submitted(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The user confirms they actually submitted a web-form application at the
    posting's apply_url. Valid from ready_to_submit (or approved, if they went
    straight to the posting) - flips it to sent so the record and outcome
    tracking reflect a genuinely-submitted application, without the app ever
    claiming to have submitted a web form it cannot.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    if app_record.status not in ("ready_to_submit", "approved"):
        raise HTTPException(status_code=400, detail="Application is not ready to submit")
    app_record.status = "sent"
    app_record.sent_at = utcnow()
    if not app_record.sent_channel:
        app_record.sent_channel = "web"
    db.commit()
    return {"status": "sent", "sent_at": app_record.sent_at.isoformat(), "channel": app_record.sent_channel}
 
 
@router.post("/{application_id}/undo")
def undo_application(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    if app_record.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent, cannot undo")
    app_record.status = "undone"
    db.commit()
    return {"status": "undone"}
 
 
@router.get("/{application_id}/explain-outcome")
def explain_outcome(application_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    """The rejection/ghost autopsy - a real, specific comparison of what
    was actually sent against the actual listing, grounded in the real
    outcome logged for it. Requires an outcome to already be logged via
    POST /outcomes for this listing, since there's nothing to analyze
    against otherwise.
    """
    import os
    import anthropic
    from app.models.db_models import Listing, Profile, Outcome
    from app.services.calibration import explain_outcome_deep
    import uuid as uuid_module
 
    try:
        uuid_module.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Application not found")
 
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    verify_token_belongs_to_user(str(app_record.user_id), authorization)
    # Meter this paid AI autopsy (was unmetered). Fails open; shares the
    # "explain-outcome" tier cap, consistent with personalization-insights.
    rate_limit_by_tier(db, str(app_record.user_id), "explain-outcome", per_action_limit=200)
 
    outcome = (
        db.query(Outcome)
        .filter(Outcome.user_id == app_record.user_id, Outcome.listing_id == app_record.listing_id)
        .order_by(Outcome.updated_at.desc())
        .first()
    )
    if not outcome:
        raise HTTPException(status_code=400, detail="No outcome logged for this application yet - log one via POST /outcomes first")
    if outcome.status not in {"rejected", "ghosted"}:
        raise HTTPException(status_code=400, detail="Autopsy is only meaningful for a rejected or ghosted outcome")
 
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == app_record.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not listing or not profile:
        raise HTTPException(status_code=404, detail="Listing or profile not found")
 
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI service is not configured. Please try again later.")
    listing_dict = {"title": listing.title, "org": listing.org, "tags": listing.tags or []}
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
 
    try:
        explanation = explain_outcome_deep(
            client, listing_dict, app_record.draft_content,
            float(app_record.confidence_pct or 0), outcome.status, profile_dict,
        )
    except Exception as e:
        _log.warning("Could not generate this explanation just now - %s", e)
        raise HTTPException(status_code=502, detail="Could not generate this explanation just now. Please try again.")
    return {"application_id": application_id, "outcome_status": outcome.status, "explanation": explanation}
 
 
SAME_COMPANY_CAUTION_THRESHOLD = 3
 
 
@router.get("/{user_id}/company-concentration")
def get_company_concentration(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Surfaces companies the person has applied to enough times that a
    further application starts reading as spray-pattern in an ATS -
    the concrete answer to the documented etiquette line (~2-3
    relevant roles per company is normal; more looks unfocused).
    Counts only genuinely ACTIVE applications (a discarded/undone one
    was never actually sent, so it doesn't count against the line),
    grouped by a normalized org name so trivial formatting
    differences don't split or miss a real repeat. Never blocks
    anything - it's honest awareness the person can act on.
    """
    import uuid as uuid_module
    import re
    from app.models.db_models import Listing
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    rows = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id, Application.status != "undone")
        .all()
    )
 
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())
 
    # Group active applications by normalized org, keeping a real
    # display name (the first genuinely-seen spelling) for each.
    by_company = {}
    for app, listing in rows:
        key = norm(listing.org)
        if not key:
            continue
        if key not in by_company:
            by_company[key] = {"org": listing.org, "count": 0}
        by_company[key]["count"] += 1
 
    cautions = [
        {
            "org": info["org"],
            "count": info["count"],
            "note": f"You already have {info['count']} active applications to {info['org']}. Applying to several roles at one company can read as unfocused in their applicant system - it's often stronger to concentrate on the single best fit here.",
        }
        for info in by_company.values()
        if info["count"] >= SAME_COMPANY_CAUTION_THRESHOLD
    ]
    return {"cautions": cautions}
 
