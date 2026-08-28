"""Real auto-apply logic: drafts an application via Claude, decides
whether it's confident enough to auto-send or needs human review,
and enforces an undo window before anything is considered final.
 
The confidence decision used to be a single raw match percentage
against a fixed global threshold - that's what wasn't hitting the
mark. It's now a composite score that also rewards a listing for
actually advancing the user's roadmap (not just scoring well on
keywords), and the threshold is per-user and adjustable, not a fixed
env var everyone shares.
 
Honest limitation: there is no real mechanism here that actually
submits a form on a real job site -- send_application() marks the
record as "sent" in your own database, it does not reach out to
Adzuna or any employer's website. Building a real submission bot is
a much larger, higher-risk project (site-specific automation, ToS
review per site) intentionally left out of this version.
"""
import os
from datetime import datetime, timedelta
 
DEFAULT_CONFIDENCE_THRESHOLD = int(os.getenv("AUTO_APPLY_THRESHOLD", "80"))
UNDO_WINDOW_MINUTES = int(os.getenv("UNDO_WINDOW_MINUTES", "30"))
ROADMAP_ALIGNMENT_BONUS = 8  # points added to composite confidence if the listing clearly advances a roadmap stage
 
 
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
 
 
def compute_composite_confidence(match_score_pct: float, roadmap_aligned: bool) -> int:
    """The improved confidence signal: raw match score, boosted if the
    listing clearly advances a specific roadmap stage. A 70%-match
    listing that advances your roadmap is a better auto-send candidate
    than an 82%-match listing that doesn't connect to your plan at all -
    this is what makes the decision actually grounded in the roadmap,
    not just keyword overlap.
    """
    composite = match_score_pct + (ROADMAP_ALIGNMENT_BONUS if roadmap_aligned else 0)
    return min(100, round(composite))
 
 
def decide_auto_send(confidence_pct: float, threshold: int | None = None) -> str:
    """Returns 'approved' (auto-send eligible) or 'pending_review'.
    threshold defaults to the global env setting but should normally
    be the user's own configured threshold from their profile.
    """
    effective_threshold = threshold if threshold is not None else DEFAULT_CONFIDENCE_THRESHOLD
    return "approved" if confidence_pct >= effective_threshold else "pending_review"
 
 
def compute_sendable_at() -> datetime:
    """The undo window: even an approved application isn't 'sent' until
    this time passes, giving a window to cancel."""
    return datetime.utcnow() + timedelta(minutes=UNDO_WINDOW_MINUTES)
 
 
def create_application_for_match(db, anthropic_client, user_id: str, listing_id: str, auto_generated: bool = False):
    """The actual 'accept a match -> draft an application' pipeline,
    shared by the explicit /applications/accept endpoint, the automatic
    trigger when a user stars a listing, and the fully-autonomous Auto
    Apply mode (auto_generated=True) that runs against every eligible
    match in a scan without any manual action. Returns a dict describing
    the result, or a dict with an 'error' key if it couldn't run.
    """
    from app.models.db_models import Profile, Listing, Application, RoadmapMilestone, Outcome
    from app.services.matching import score_listing, compute_roadmap_alignment, get_personalized_factor_weights
 
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
 
    from app.services.embeddings import generate_embedding
    goal_text = f"{profile.northstar or ''}. {profile.final_idea or ''}. Skills: {profile.skills or ''}"
    profile_dict = {
        "northstar": profile.northstar,
        "final_idea": profile.final_idea or "",
        "skills": profile.skills or "",
        "dealbreakers": profile.dealbreakers or "",
        "priorities": profile.priorities or [],
        "location_pref": profile.location_pref or "",
        "embedding": generate_embedding(goal_text, input_type="query"),
    }
    listing_dict = {
        "type": listing.type,
        "tags": listing.tags or [],
        "title": listing.title,
        "org": listing.org,
        "location": listing.location,
        "deadline": listing.deadline.isoformat() if listing.deadline else None,
        "description": listing.description or "",
        "embedding": list(listing.embedding) if listing.embedding is not None else None,
    }
 
    match_no_personalization = score_listing(listing_dict, profile_dict)
    if match_no_personalization is None:
        return {"error": "dealbreaker_conflict"}
 
    # This decision (auto-send or not) is the highest-stakes place for
    # accurate personalized scoring in the whole app - fetch the
    # user's real learned factor weights and apply them here, not
    # just when browsing matches. Computing both the personalized and
    # non-personalized (counterfactual) score lets the self-audit
    # later check whether personalization is actually helping THIS
    # decision, not just moving numbers around on a browse page.
    applications_with_snapshots = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.factors_snapshot.isnot(None))
        .all()
    )
    user_outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    outcome_by_listing = {str(o.listing_id): o.status for o in user_outcomes}
    factor_learning_input = [
        {"factors_snapshot": a.factors_snapshot, "outcome_status": outcome_by_listing[str(a.listing_id)]}
        for a in applications_with_snapshots
        if str(a.listing_id) in outcome_by_listing
    ]
    factor_weights = get_personalized_factor_weights(factor_learning_input)
    match = score_listing(listing_dict, profile_dict, factor_weights=factor_weights) or match_no_personalization
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    milestone_dicts = [{"stage": m.target_stage, "title": m.title, "description": m.description} for m in milestones]
    alignment = compute_roadmap_alignment(listing_dict, milestone_dicts)
    composite_confidence = compute_composite_confidence(match["score_pct"], roadmap_aligned=alignment is not None)
    counterfactual_confidence = compute_composite_confidence(match_no_personalization["score_pct"], roadmap_aligned=alignment is not None)
 
    draft_text = draft_application(anthropic_client, listing_dict, profile_dict)
    user_threshold = profile.auto_apply_threshold if getattr(profile, "auto_apply_threshold", None) else None
    status = decide_auto_send(composite_confidence, threshold=user_threshold)
 
    app_record = Application(
        user_id=user_id,
        listing_id=listing_id,
        draft_content=draft_text,
        confidence_pct=composite_confidence,
        status=status,
        sendable_at=compute_sendable_at() if status == "approved" else None,
        auto_generated=auto_generated,
        factors_snapshot={**match["factors"], "signal_strength": match["signal_strength"], "factors_engaged": match["factors_engaged"], "data_quality": match.get("data_quality")},
        counterfactual_confidence_pct=counterfactual_confidence,
    )
    db.add(app_record)
    db.commit()
    db.refresh(app_record)
 
    return {
        "application_id": str(app_record.id),
        "match_score": match["score_pct"],
        "roadmap_aligned": alignment is not None,
        "composite_confidence": composite_confidence,
        "status": status,
        "draft": draft_text,
        "already_existed": False,
        "auto_generated": auto_generated,
    }
 
 
def draft_outreach_for_match(db, anthropic_client, user_id: str, listing_id: str, auto_generated: bool = False):
    """The Auto mode outreach counterpart to create_application_for_match:
    when Auto is enabled, this runs automatically for eligible matches
    during a scan and DRAFTS a referral outreach email - guessed
    contact address, subject, and body - but never sends it. It lands
    in Workshop with status 'drafted', where the user reviews, can
    edit, and explicitly clicks send. No email leaves the app from
    this function under any circumstance.
    """
    from app.models.db_models import Profile, Listing, OutreachEmail
    from app.services.email_send import guess_contact_emails
    import os
    import anthropic as anthropic_module
 
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
        db.query(OutreachEmail)
        .filter(OutreachEmail.user_id == user_id, OutreachEmail.listing_id == listing_id)
        .first()
    )
    if existing:
        return {"outreach_id": str(existing.id), "status": existing.status, "already_existed": True}
 
    guess = guess_contact_emails(listing.org)
    if not guess.get("candidates"):
        return {"error": "no_contact_guess"}
 
    prompt = (
        f"A candidate is applying to \"{listing.title}\" at {listing.org} ({listing.type}), "
        f"tags: {', '.join(listing.tags or [])}. Their background: skills \"{profile.skills or ''}\", "
        f"goal \"{profile.northstar}\".\n\n"
        "Write a genuine, specific 80-120 word referral outreach email body, plus a short subject "
        "line. Reference the candidate's real skills/goal and the specific role, ask for a short "
        "conversation or referral, no generic flattery. Return ONLY valid JSON with exactly two "
        "keys: 'subject' and 'body'. No markdown fences."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"error": "draft_generation_failed"}
 
    draft = OutreachEmail(
        user_id=user_id,
        listing_id=listing_id,
        to_address=guess["candidates"][0],
        address_verified=False,
        subject=parsed.get("subject", f"Regarding {listing.title}"),
        body=parsed.get("body", ""),
        status="drafted",
        auto_generated=auto_generated,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
 
    return {
        "outreach_id": str(draft.id),
        "to_address": draft.to_address,
        "subject": draft.subject,
        "status": "drafted",
        "already_existed": False,
        "auto_generated": auto_generated,
    }
 
