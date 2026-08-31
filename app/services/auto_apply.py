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
 
 
def draft_application(anthropic_client, listing: dict, profile: dict) -> str:
    """A genuinely tailored cover-letter-style paragraph, not a
    generic template with the company name swapped in. The old
    version only ever knew the job title, org, and a raw skills
    string - it never used the actual posting text, the specific
    overlap already identified during scoring, or any roadmap
    context, which is exactly why AI-written cover letters usually
    read like every other AI-written cover letter. Also includes
    explicit anti-fabrication guardrails: this text may be submitted
    to a real employer representing a real person, so inventing a
    specific accomplishment or project they never mentioned isn't
    just bad writing, it's actually misrepresenting them.
    """
    matched_terms = list(dict.fromkeys((listing.get("goal_match_tags") or []) + (listing.get("skill_match_tags") or [])))
    description = (listing.get("description") or "").strip()
    roadmap_alignment = (listing.get("factors") or {}).get("roadmap_alignment")
 
    context_lines = [
        f'Job: "{listing["title"]}" at {listing["org"]}.',
        f'Candidate\'s stated career goal: "{profile["northstar"]}"',
        f'Candidate\'s stated skills: "{profile.get("skills", "")}"',
    ]
    if description:
        context_lines.append(f'The actual job posting text: "{description[:600]}"')
    if matched_terms:
        context_lines.append(f"Specific real overlap already identified between the candidate and this role: {', '.join(matched_terms)}")
    if roadmap_alignment:
        context_lines.append(f'This role specifically advances a stage of the candidate\'s own stated plan: "{roadmap_alignment["title"]}".')
 
    prompt = (
        "\n".join(context_lines) + "\n\n"
        "Write a short, genuinely specific cover-letter-style paragraph (120-180 words) for this application.\n\n"
        "What makes this good, not generic:\n"
        "- Open with something concrete tied to what this specific posting actually says it needs - never a "
        'generic opener like "I am writing to express my interest" or "I am excited to apply for".\n'
        "- Connect the candidate's real stated skills and goal to what THIS role specifically needs - use the "
        "actual overlap identified above rather than just restating a generic skills list.\n"
        "- Never invent a specific accomplishment, project, metric, company name, or experience the "
        "candidate didn't actually state here. This may be submitted to a real employer representing a real "
        "person - vague but honest beats specific but fabricated.\n"
        '- Avoid AI-cover-letter cliches: no "passionate", "dynamic", "leverage my skills", "I am confident '
        'that", "perfect fit", "I believe I would be a great asset". Write like a specific person actually '
        "wrote this, not a template.\n"
        '- No placeholder brackets, no generic filler, no closing like "I look forward to hearing from you" '
        "unless it says something more specific than that.\n\n"
        "Return ONLY the paragraph text, nothing else."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
 
def compute_composite_confidence(match_score_pct: float) -> int:
    """Roadmap alignment used to need a separate bonus here, because
    match_score_pct never reflected it at all - it was purely
    decorative metadata shown alongside a score it had zero
    influence over. Now that matching.py's score_listing() bakes
    roadmap_fit in as a real, graded factor (see roadmap_fit and
    ROADMAP_ALIGNMENT_BONUS's removal), match_score_pct already
    carries that signal honestly. This function is now a clean
    pass-through, kept as its own function so future confidence
    adjustments have one clear place to live.
    """
    return min(100, round(match_score_pct))
 
 
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
    from app.services.matching import score_listing, get_personalized_factor_weights
 
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
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    milestone_dicts = [{"stage": m.target_stage, "title": m.title, "description": m.description} for m in milestones]
 
    match_no_personalization = score_listing(listing_dict, profile_dict, roadmap_milestones=milestone_dicts)
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
    outcome_status_by_listing = {str(o.listing_id): o.status for o in user_outcomes}
    outcome_time_by_listing = {str(o.listing_id): o.updated_at for o in user_outcomes}
    factor_learning_input = [
        {"factors_snapshot": a.factors_snapshot, "outcome_status": outcome_status_by_listing[str(a.listing_id)], "updated_at": outcome_time_by_listing.get(str(a.listing_id))}
        for a in applications_with_snapshots
        if str(a.listing_id) in outcome_status_by_listing
    ]
    factor_weights = get_personalized_factor_weights(factor_learning_input)
    match = score_listing(listing_dict, profile_dict, factor_weights=factor_weights, roadmap_milestones=milestone_dicts) or match_no_personalization
 
    # Roadmap alignment is now a real, graded factor baked directly
    # into score_pct itself (see matching.py's roadmap_fit) - no
    # separate bonus needed here anymore. The old version added a
    # flat +8 on top of a score_pct that never reflected roadmap
    # alignment at all; keeping that bonus now that score_pct
    # genuinely includes it would double-count the same signal.
    composite_confidence = compute_composite_confidence(match["score_pct"])
    counterfactual_confidence = compute_composite_confidence(match_no_personalization["score_pct"])
 
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
        "roadmap_aligned": match["factors"].get("roadmap_alignment") is not None,
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
 
 
def draft_leadership_grounded_outreach(db, anthropic_client, user_id: str, listing_id: str, leadership_research: dict):
    """The leadership-grounded counterpart to draft_outreach_for_match
    above - same storage, same edit/send flow, but instead of a
    generic referral email, this genuinely references what the
    company's real, current senior leadership - not just the CEO -
    has actually, publicly said and prioritized (see
    market_research.research_company_leadership), never a fabricated
    or generic one. If leadership_research found nothing real and
    specific, this is honest about that rather than inventing
    something that sounds plausible - see the returned "grounded"
    flag.
 
    Reuses the exact same OutreachEmail table, contact-guessing, and
    duplicate-check as draft_outreach_for_match, so this shows up in
    the same Workshop list, same edit/send actions - a different way
    of writing the draft, not a parallel system.
    """
    from app.models.db_models import Profile, Listing, OutreachEmail
    from app.services.email_send import guess_contact_emails
 
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
 
    leaders = leadership_research.get("leaders") or []
    priorities_summary = leadership_research.get("priorities_summary") or ""
    grounded = bool(leaders and priorities_summary)
 
    if grounded:
        leader_lines = "\n".join(
            f'- {l.get("name","")} ({l.get("title","")}): ' +
            "; ".join(f'{s.get("theme","")} (from {s.get("source_title","an unnamed source")})' for s in (l.get("statements") or []))
            for l in leaders
        )
        research_block = (
            f"Real, current senior leadership at this company, and things they have genuinely, publicly "
            f"said:\n{leader_lines}\n\n"
            f"An honest synthesis of what this leadership team's real statements actually suggest they're "
            f"prioritizing right now: {priorities_summary}\n\n"
            "Reference this real, synthesized sense of what the company's leadership is actually focused "
            "on right now - or one specific leader's real point if it connects especially well to this "
            "candidate's background - naturally in the email, genuinely connecting it to why this "
            "candidate's real background makes them worth a conversation, not just name-dropping it. Do "
            "not quote anyone's exact original words at length - paraphrase the idea, same as it was "
            "paraphrased above."
        )
    else:
        research_block = (
            "No specific, current public statements from this company's leadership were found - write a "
            "genuine, specific referral email grounded in the candidate's real background and the role "
            "itself, same as normal. Do not invent a leadership quote or a company priority that wasn't "
            "actually found."
        )
 
    prompt = (
        f"A candidate is applying to \"{listing.title}\" at {listing.org} ({listing.type}), "
        f"tags: {', '.join(listing.tags or [])}. Their background: skills \"{profile.skills or ''}\", "
        f"goal \"{profile.northstar}\".\n\n"
        f"{research_block}\n\n"
        "Write a genuine, specific 80-120 word referral outreach email body, plus a short subject line. "
        "Reference the candidate's real skills/goal and the specific role, ask for a short conversation "
        "or referral, no generic flattery. Return ONLY valid JSON with exactly two keys: 'subject' and "
        "'body'. No markdown fences."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=400,
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
        auto_generated=False,
        leadership_grounded=grounded,
        leadership_research_sources=leadership_research.get("sources") or [],
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
        "leadership_grounded": grounded,
        "leaders": [l.get("name") for l in leaders],
    }
 
