"""Background job that scans real listings daily and re-scores them
for every user with an active profile. This is what makes the
"continuous overnight watch" real instead of a UI animation.
"""
import os
import asyncio
 
# Both real search sources (Adzuna for jobs, ScholarshipAPI for
# fellowships) were being queried with exactly ONE hardcoded term on
# every single scan, every time, for the entire life of this app -
# "internship" for jobs, "scholarship" for fellowships. This meant
# entire real career categories - software engineering, marketing,
# sales, data, finance, design - were NEVER pulled from Adzuna at
# all, not because Adzuna doesn't have them (it certainly does), but
# because the app never once asked. This is the backend-native
# version of the exact same coverage gap found and fixed in the
# frontend demo's static listing set - here it's fixed by actually
# querying broadly instead of hardcoding a single term.
JOB_SEARCH_QUERIES = [
    "internship", "software engineer", "product manager", "marketing",
    "data analyst", "sales", "financial analyst", "operations", "ux designer",
    "human resources", "customer success", "healthcare", "legal",
]
SCHOLARSHIP_SEARCH_QUERIES = ["scholarship", "fellowship", "grant"]
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
import anthropic
 
from app.db import SessionLocal
from app.models.db_models import User, Profile, Listing, MatchScore
from app.services.ingestion import (
    fetch_adzuna, normalize_adzuna, dedupe_listings, extract_tags,
    fetch_simplify_internships, parse_simplify_markdown,
    discover_scholarships_via_search, normalize_scholarship_from_search, _scholarship_passes_quality_check,
    fetch_athletic_career_jobs, normalize_athletic_job, ATHLETIC_CAREER_QUERIES,
    check_and_reserve_quota, ADZUNA_DAILY_CALL_LIMIT,
)
from app.services.matching import rank_listings
from app.services.embeddings import generate_embedding
 
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "1440"))  # default: once/day
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
def _profile_to_dict(p: Profile) -> dict:
    from app.services.embeddings import generate_embedding
    goal_text = f"{p.northstar or ''}. {p.final_idea or ''}. Skills: {p.skills or ''}"
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "dealbreakers": p.dealbreakers or "",
        "priorities": p.priorities or [],
        "target_types": p.target_types or [],
        "location_pref": p.location_pref or "",
        "embedding": generate_embedding(goal_text, input_type="query"),
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
        "description": l.description or "",
        "embedding": list(l.embedding) if l.embedding is not None else None,
    }
 
 
def _embed_listing(title: str, description: str, tags: list[str]) -> list[float] | None:
    """Embedded once at ingestion time and cached in the DB - unlike
    the profile embedding (computed fresh per request, since goal text
    changes rarely), re-embedding every listing on every match request
    would be wasteful at scale. Returns None automatically if
    VOYAGE_API_KEY isn't configured - ingestion proceeds exactly as it
    did before this existed, just without the semantic factor.
    """
    text = f"{title}. {description}. Tags: {', '.join(tags or [])}"
    return generate_embedding(text, input_type="document")
 
 
def backfill_missing_embeddings(db: Session, batch_size: int = 100) -> dict:
    """Any listing ingested before VOYAGE_API_KEY was configured has
    embedding=None permanently - the ingestion upsert above (`if
    exists: continue`) skips any listing already in the database by
    source+external_id, so those specific rows are never revisited by
    a normal scan, no matter how many days pass or how many times the
    key gets fixed afterward. Setting up the key correctly today does
    nothing for listings that predate it; this is the only path back
    to a real embedding for them, short of waiting for every one of
    them to naturally expire and get replaced by a fresh listing.
 
    Capped at batch_size per call rather than processing everything
    at once - safe to call repeatedly (each call picks up the next
    batch of still-null rows) rather than risking one very large,
    slow request against a real rate-limited API.
 
    Returns a real count of what happened, not just "done" - honest
    about a real, if unlikely, partial-failure case: a specific
    listing's text triggering an API error while others succeed.
    """
    from app.services.embeddings import is_configured
 
    if not is_configured():
        return {"attempted": 0, "succeeded": 0, "detail": "VOYAGE_API_KEY is not set - nothing to backfill until it's configured."}
 
    candidates = db.query(Listing).filter(Listing.embedding.is_(None)).limit(batch_size).all()
    succeeded = 0
    for listing in candidates:
        embedding = _embed_listing(listing.title, listing.description, listing.tags)
        if embedding is not None:
            listing.embedding = embedding
            succeeded += 1
    db.commit()
    return {"attempted": len(candidates), "succeeded": succeeded, "detail": f"Processed {len(candidates)} listings with no embedding yet; {succeeded} succeeded. Call again to process the next batch if more remain."}
 
 
async def _pull_and_store_new_listings(db: Session):
    """Fetches real listings from two sources - Adzuna for jobs (tagged
    via Claude) and SimplifyJobs for internships (tagged via free
    keyword matching, no AI cost) - and upserts anything new.
 
    Adzuna gets queried once per term in JOB_SEARCH_QUERIES, not once
    overall - a single hardcoded "internship" query meant entire real
    career categories were never being pulled at all, regardless of
    how good the downstream matching got.
 
    Adzuna's real free tier is roughly 1,000 calls a month (about 33
    a day, verified against their actual current documentation) - the
    13 job queries + 6 athletic queries this function can make (19
    total) leave very little headroom for a manual "check now"
    trigger on the same day as the scheduled scan without genuinely
    risking exceeding that real quota. check_and_reserve_quota below
    tracks real daily usage and gracefully limits how many of these
    queries actually run today, rather than blindly firing all 19
    regardless of what's already been consumed.
    """
    stored_count = 0
    total_possible_queries = len(JOB_SEARCH_QUERIES) + len(ATHLETIC_CAREER_QUERIES)
    reserved_calls = check_and_reserve_quota(db, "adzuna", calls_needed=total_possible_queries, daily_limit=ADZUNA_DAILY_CALL_LIMIT)
    # Proportional split, not a hard job-queries-first priority - direct
    # testing showed the hard-priority version completely zeroed out
    # athletic queries any time reserved_calls fell at or below 13 (the
    # job query count), which isn't a rare edge case: it's exactly what
    # happens whenever a manual "check now" trigger runs on the same day
    # the scheduled scan already consumed part of the daily budget - a
    # completely ordinary usage pattern, not an extreme one. Proportional
    # allocation means athletic listings keep getting refreshed at a
    # reduced rate under a constrained budget instead of being the one
    # source that silently stops updating.
    if reserved_calls >= total_possible_queries:
        job_query_budget, athletic_query_budget = len(JOB_SEARCH_QUERIES), len(ATHLETIC_CAREER_QUERIES)
    else:
        job_query_budget = min(round(reserved_calls * len(JOB_SEARCH_QUERIES) / total_possible_queries), reserved_calls)
        athletic_query_budget = reserved_calls - job_query_budget
    if reserved_calls < total_possible_queries:
        print(f"Adzuna daily quota reached or nearly reached - running {reserved_calls} of {total_possible_queries} possible queries today ({job_query_budget} job, {athletic_query_budget} athletic).")
 
    # Source 1: Adzuna, for jobs - queried across every category in
    # JOB_SEARCH_QUERIES, not just one hardcoded term, then merged
    # and deduped by (source, external_id) before any DB writes or
    # paid tag-extraction calls happen on a listing twice.
    #
    # Each query is isolated with its own try/except - confirmed by
    # tracing the real exception path that a single query's failure
    # (a transient network issue, a temporary Adzuna-side error) would
    # otherwise propagate all the way up through this function to
    # run_scan_for_all_users' outer handler, aborting the ENTIRE daily
    # scan: every remaining Adzuna and athletic query, every user's
    # rescoring, and every user's Auto Apply run for that day - not
    # just the one query that actually failed.
    all_adzuna_raw = []
    for q in JOB_SEARCH_QUERIES[:job_query_budget]:
        try:
            all_adzuna_raw.extend(await fetch_adzuna(q))
        except Exception as e:
            print(f"  Adzuna query '{q}' failed, skipping it for today: {e}")
    adzuna_normalized = dedupe_listings([normalize_adzuna(r) for r in all_adzuna_raw])
    for item in adzuna_normalized:
        exists = (
            db.query(Listing)
            .filter(Listing.source == item["source"], Listing.external_id == item["external_id"])
            .first()
        )
        if exists:
            continue
        try:
            tags = await extract_tags(item["description"], anthropic_client)
        except Exception as e:
            print(f"  Tag extraction failed for '{item['title']}', storing with no tags rather than losing it: {e}")
            tags = []
        db.add(Listing(
            source=item["source"], external_id=item["external_id"], title=item["title"],
            org=item["org"], type=item["type"], location=item["location"],
            description=item["description"], tags=tags, deadline=item["deadline"],
            apply_url=item["apply_url"],
            embedding=_embed_listing(item["title"], item["description"], tags),
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
                embedding=_embed_listing(item["title"], item["description"], item["tags"]),
            ))
            stored_count += 1
    except Exception as e:
        print(f"SimplifyJobs ingestion failed (non-fatal, Adzuna results still saved): {e}")
 
    # Source 3: real web-search-grounded scholarship/fellowship
    # discovery - replaces the old ScholarshipAPI integration, which
    # needed replacing for two real, honest reasons: it only ever
    # covered Australia/New Zealand universities (not the US this
    # platform is built around), and separately, its response schema
    # was only ever guessed from public docs, never verified against
    # a real call. This uses the same proven real-search pattern
    # already working elsewhere in this app - every field comes from
    # an actual, current search result, not a guessed field mapping.
    try:
        all_scholarship_raw = []
        for q in SCHOLARSHIP_SEARCH_QUERIES:
            try:
                all_scholarship_raw.extend(await discover_scholarships_via_search(anthropic_client, q))
            except Exception as e:
                print(f"  Scholarship search '{q}' failed, skipping it for today: {e}")
        # Real, visible rejection reasons rather than silently
        # discarding them - the same "make it visible, not silent"
        # principle already applied to candidate match transparency
        # elsewhere in this app.
        accepted_raw = []
        for r in all_scholarship_raw:
            passes, reason = _scholarship_passes_quality_check(r)
            if passes:
                accepted_raw.append(r)
            else:
                print(f"Scholarship quality gate rejected \"{r.get('title', '(no title)')}\": {reason}")
        scholarship_normalized = [normalize_scholarship_from_search(r) for r in accepted_raw]
        scholarship_normalized = dedupe_listings([r for r in scholarship_normalized if r is not None])
        for item in scholarship_normalized:
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
                embedding=_embed_listing(item["title"], item["description"], item["tags"]),
            ))
            stored_count += 1
    except Exception as e:
        print(f"Scholarship discovery failed (non-fatal): {e}")
 
    # Source 4: Athletic-career jobs (coaching, athletic training, sports
    # management) - real data via the same Adzuna connection, just
    # queried with sports-specific terms. See ingestion.py for why this
    # is the honest alternative to a dedicated athletic scholarship API,
    # which doesn't exist as a free public service.
    try:
        raw_athletic = await fetch_athletic_career_jobs(max_queries=athletic_query_budget)
        athletic_normalized = dedupe_listings([normalize_athletic_job(r) for r in raw_athletic])
        for item in athletic_normalized:
            exists = (
                db.query(Listing)
                .filter(Listing.source == item["source"], Listing.external_id == item["external_id"])
                .first()
            )
            if exists:
                continue
            try:
                tags = await extract_tags(item["description"], anthropic_client)
            except Exception as e:
                print(f"  Tag extraction failed for '{item['title']}', storing with no tags rather than losing it: {e}")
                tags = []
            tags = list(set(tags + ["athletics"]))  # ensure it's always discoverable by the athletics filter
            db.add(Listing(
                source=item["source"], external_id=item["external_id"], title=item["title"],
                org=item["org"], type=item["type"], location=item["location"],
                description=item["description"], tags=tags, deadline=item["deadline"],
                apply_url=item["apply_url"],
                embedding=_embed_listing(item["title"], item["description"], tags),
            ))
            stored_count += 1
    except Exception as e:
        print(f"Athletic-career job ingestion failed (non-fatal): {e}")
 
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
    from app.services.auto_apply import create_application_for_match, draft_outreach_for_match
 
    db = SessionLocal()
    try:
        print(f"[{datetime.utcnow().isoformat()}] Starting daily scan...")
        new_count = asyncio.run(_pull_and_store_new_listings(db))
        print(f"Pulled {new_count} new listings.")
 
        # Runs automatically every day rather than depending on a
        # human remembering the manual /system/backfill-embeddings
        # endpoint exists - the self-healing this function offers was
        # real, but genuinely unreachable without that reminder,
        # inconsistent with the rest of this system's design ("fires
        # even if nobody opens the app that day"). Cheap and safe to
        # run daily: capped at 100 rows, a genuine no-op query when
        # there's nothing to backfill. Isolated in its own try/except
        # so a real failure here can never cancel user rescoring or
        # Auto Apply below it, the same isolation already applied to
        # the ingestion loops above.
        try:
            backfill_result = backfill_missing_embeddings(db)
            if backfill_result["attempted"] > 0:
                print(f"Embedding backfill: {backfill_result['detail']}")
        except Exception as e:
            print(f"Embedding backfill failed (non-fatal, rest of the scan continues): {e}")
 
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
                outreach_count = 0
                for listing in ranked:
                    outcome = create_application_for_match(db, anthropic_client, str(user.id), listing["id"], auto_generated=True)
                    if not outcome.get("error") and not outcome.get("already_existed") and outcome.get("status") == "approved":
                        auto_count += 1
 
                    # Auto mode drafts outreach for the same eligible
                    # matches while the user is away - queued in
                    # Workshop, status stays 'drafted' until the user
                    # comes back and explicitly clicks send.
                    outreach_result = draft_outreach_for_match(db, anthropic_client, str(user.id), listing["id"], auto_generated=True)
                    if not outreach_result.get("error") and not outreach_result.get("already_existed"):
                        outreach_count += 1
                print(f"    Auto Apply: {auto_count} new application(s) auto-approved for {user.email}")
                print(f"    Auto Outreach: {outreach_count} new outreach draft(s) queued for {user.email}")
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
 
