"""Background job that scans real listings daily and re-scores them
for every user with an active profile. This is what makes the
"continuous overnight watch" real instead of a UI animation.
"""
import os
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
import anthropic
 
from app.db import SessionLocal
from app.models.db_models import User, Profile, Listing, MatchScore
from app.services.ingestion import (
    fetch_adzuna, normalize_adzuna, dedupe_listings, extract_tags,
    fetch_simplify_internships, parse_simplify_markdown,
    fetch_scholarships, normalize_scholarship,
)
from app.services.matching import rank_listings
 
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "1440"))  # default: once/day
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
def _profile_to_dict(p: Profile) -> dict:
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "dealbreakers": p.dealbreakers or "",
        "priorities": p.priorities or [],
        "target_types": p.target_types or [],
    }
 
 
def _listing_to_dict(l: Listing) -> dict:
    return {
        "id": str(l.id),
        "type": l.type,
        "title": l.title,
        "org": l.org,
        "tags": l.tags or [],
        "location": l.location,
        "deadline": l.deadline.isoformat() if l.deadline else None,
    }
 
 
async def _pull_and_store_new_listings(db: Session, query: str = "internship"):
    """Fetches real listings from two sources - Adzuna for jobs (tagged
    via Claude) and SimplifyJobs for internships (tagged via free
    keyword matching, no AI cost) - and upserts anything new.
    """
    stored_count = 0
 
    # Source 1: Adzuna, for jobs
    raw_results = await fetch_adzuna(query)
    adzuna_normalized = dedupe_listings([normalize_adzuna(r) for r in raw_results])
    for item in adzuna_normalized:
        exists = (
            db.query(Listing)
            .filter(Listing.source == item["source"], Listing.external_id == item["external_id"])
            .first()
        )
        if exists:
            continue
        tags = await extract_tags(item["description"], anthropic_client)
        db.add(Listing(
            source=item["source"], external_id=item["external_id"], title=item["title"],
            org=item["org"], type=item["type"], location=item["location"],
            description=item["description"], tags=tags, deadline=item["deadline"],
            apply_url=item["apply_url"],
        ))
        stored_count += 1
 
    # Source 2: SimplifyJobs, for internships - free, no Claude call
    try:
        markdown_text = await fetch_simplify_internships()
        simplify_listings = parse_simplify_markdown(markdown_text)
        for item in simplify_listings:
            exists = (
                db.query(Listing)
                .filter(Listing.source == item["source"], Listing.external_id == item["external_id"])
                .first()
            )
            if exists:
                continue
            db.add(Listing(
                source=item["source"], external_id=item["external_id"], title=item["title"],
                org=item["org"], type=item["type"], location=item["location"],
                description=item["description"], tags=item["tags"], deadline=item["deadline"],
                apply_url=item["apply_url"],
            ))
            stored_count += 1
    except Exception as e:
        print(f"SimplifyJobs ingestion failed (non-fatal, Adzuna results still saved): {e}")
 
    # Source 3: ScholarshipAPI, for college/fellowship data - no-ops
    # automatically if SCHOLARSHIP_API_KEY isn't set, so this is safe
    # to leave in even before you have a key.
    try:
        raw_scholarships = await fetch_scholarships()
        for raw in raw_scholarships:
            item = normalize_scholarship(raw)
            exists = (
                db.query(Listing)
                .filter(Listing.source == item["source"], Listing.external_id == item["external_id"])
                .first()
            )
            if exists:
                continue
            db.add(Listing(
                source=item["source"], external_id=item["external_id"], title=item["title"],
                org=item["org"], type=item["type"], location=item["location"],
                description=item["description"], tags=item["tags"], deadline=item["deadline"],
                apply_url=item["apply_url"],
            ))
            stored_count += 1
    except Exception as e:
        print(f"ScholarshipAPI ingestion failed (non-fatal): {e}")
 
    db.commit()
    return stored_count
 
 
def run_scan_for_user(db: Session, user_id: str) -> dict:
    """Re-scores current listings for one user and stores the results.
    Used both by the daily scheduled job and the manual /listings/scan/{user_id} route.
    """
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        return {"status": "no active profile", "user_id": user_id}
 
    listings = db.query(Listing).all()
    ranked = rank_listings(
        [_listing_to_dict(l) for l in listings],
        _profile_to_dict(profile),
        top_n=10,
    )
 
    # Determine this user's next scan_cycle number
    last_cycle = (
        db.query(MatchScore.scan_cycle)
        .filter(MatchScore.user_id == user_id)
        .order_by(MatchScore.scan_cycle.desc())
        .first()
    )
    next_cycle = (last_cycle[0] + 1) if last_cycle else 1
 
    for l in ranked:
        db.add(MatchScore(
            user_id=user_id,
            listing_id=l["id"],
            profile_id=profile.id,
            score_pct=l["score_pct"],
            goal_match_tags=l["goal_match_tags"],
            skill_match_tags=l["skill_match_tags"],
            rationale=l["rationale"],
            scan_cycle=next_cycle,
        ))
    db.commit()
 
    return {"status": "scanned", "user_id": user_id, "matches": len(ranked), "cycle": next_cycle}
 
 
def run_scan_for_all_users():
    """The actual daily job: pulls fresh listings once, then re-scores
    every user against the updated listings table. Also runs Auto
    Apply for any user who's enabled it - this is what makes the
    autonomous mode actually autonomous, not just a bigger manual
    button: it fires even if nobody opens the app that day.
    """
    from app.services.auto_apply import create_application_for_match
 
    db = SessionLocal()
    try:
        print(f"[{datetime.utcnow().isoformat()}] Starting daily scan...")
        new_count = asyncio.run(_pull_and_store_new_listings(db))
        print(f"Pulled {new_count} new listings.")
 
        users = db.query(User).join(Profile).filter(Profile.is_current == True).all()  # noqa: E712
        for user in users:
            result = run_scan_for_user(db, str(user.id))
            print(f"  {user.email}: {result}")
 
            profile = (
                db.query(Profile)
                .filter(Profile.user_id == user.id, Profile.is_current == True)  # noqa: E712
                .first()
            )
            if profile and profile.auto_apply_enabled:
                listings = db.query(Listing).all()
                ranked = rank_listings([_listing_to_dict(l) for l in listings], _profile_to_dict(profile), top_n=10)
                auto_count = 0
                for listing in ranked:
                    outcome = create_application_for_match(db, anthropic_client, str(user.id), listing["id"], auto_generated=True)
                    if not outcome.get("error") and not outcome.get("already_existed") and outcome.get("status") == "approved":
                        auto_count += 1
                print(f"    Auto Apply: {auto_count} new application(s) auto-approved for {user.email}")
        print("Daily scan complete.")
    except Exception as e:
        print(f"Scan failed: {e}")
    finally:
        db.close()
 
 
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scan_for_all_users, "interval", minutes=SCAN_INTERVAL_MINUTES)
    scheduler.start()
    return scheduler
 
