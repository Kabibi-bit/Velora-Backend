"""Matching engine: scores listings against a user's profile.
This is a direct port of the logic prototyped in the frontend demo,
now living server-side so it can run on a schedule against real data.
"""
import re
from typing import Optional
 
 
def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z\-]{2,}", text.lower())
 
 
def filter_dealbreakers(listings: list[dict], dealbreakers: str) -> list[dict]:
    if not dealbreakers:
        return listings
    db_tokens = dealbreakers.lower()
    return [l for l in listings if not any(tag in db_tokens for tag in l["tags"])]
 
 
def score_listing(listing: dict, profile: dict) -> Optional[dict]:
    """Returns None if the listing is excluded by a dealbreaker, else a score dict."""
    dealbreakers = (profile.get("dealbreakers") or "").lower()
    if any(tag in dealbreakers for tag in listing["tags"]):
        return None
 
    goal_tokens = tokenize(f"{profile['northstar']} {profile.get('final_idea', '')}")
    skill_tokens = tokenize(profile.get("skills", ""))
    priorities = profile.get("priorities", [])
 
    score = 0.0
    matched_goal, matched_skill = [], []
    for tag in listing["tags"]:
        in_goal = any(t in tag or tag in t for t in goal_tokens)
        in_skill = any(t in tag or tag in t for t in skill_tokens)
        if in_goal:
            score += 3
            matched_goal.append(tag)
        if in_skill:
            score += 2
            matched_skill.append(tag)
 
    if "learning" in priorities and listing["type"] in ("internship", "college"):
        score += 1.5
    if "pay" in priorities and listing["type"] == "job":
        score += 1.5
 
    pct = max(35, min(97, round((score / (len(listing["tags"]) * 3 + 2)) * 100)))
    return {
        "score_pct": pct,
        "goal_match_tags": list(set(matched_goal)),
        "skill_match_tags": list(set(matched_skill)),
    }
 
 
def explain_score(listing: dict, match: dict, profile: dict) -> str:
    """Builds a real, multi-clause explanation from every signal
    already available - not just goal/skill tag overlap. Still free
    and instant (no AI call), but covers priorities, location fit,
    and deadline urgency, so it reads like an actual case for the
    listing rather than a one-line template.
    """
    goal_phrase = (profile["northstar"].split(".")[0] or "your goal").strip().lower()
    clauses = []
 
    if match["goal_match_tags"]:
        clauses.append(f"directly touches {', '.join(match['goal_match_tags'][:2])} from your stated goal of {goal_phrase}")
    if match["skill_match_tags"]:
        clauses.append(f"draws on your existing experience with {', '.join(match['skill_match_tags'][:2])}")
 
    priorities = profile.get("priorities", [])
    if "pay" in priorities and listing["type"] == "job":
        clauses.append("is a full-time role, aligned with pay being a top priority for you")
    if "learning" in priorities and listing["type"] in ("internship", "college"):
        clauses.append("is structured around hands-on learning, which you said matters most right now")
    listing_loc = (listing.get("location") or "").lower()
    if "flexibility" in priorities and "remote" in listing_loc:
        clauses.append("is remote, matching your stated need for flexibility")
 
    location_pref = (profile.get("location_pref") or "").lower()
    if location_pref and listing_loc:
        if "remote" in location_pref and "remote" in listing_loc:
            clauses.append("matches your remote location preference")
        else:
            pref_tokens = [t for t in tokenize(location_pref) if len(t) > 3]
            if any(t in listing_loc for t in pref_tokens):
                clauses.append(f"is based in {listing['location']}, inside your stated location preference")
 
    deadline_note = ""
    if listing.get("deadline"):
        try:
            from datetime import date
            deadline_date = date.fromisoformat(listing["deadline"]) if isinstance(listing["deadline"], str) else listing["deadline"]
            days_left = (deadline_date - date.today()).days
            if 0 <= days_left <= 14:
                deadline_note = f" It also closes in {days_left} day{'s' if days_left != 1 else ''}, so it's worth acting on soon if you're interested."
        except (ValueError, TypeError):
            pass
 
    if not clauses:
        return "Looser fit - no strong overlap with your stated goal, skills, or priorities yet, but worth a glance while broadening this cycle's search." + deadline_note
 
    if len(clauses) == 1:
        joined = clauses[0]
    elif len(clauses) == 2:
        joined = f"{clauses[0]}, and {clauses[1]}"
    else:
        joined = ", ".join(clauses[:-1]) + f", and {clauses[-1]}"
 
    return f"This {joined}.{deadline_note}"
 
 
def get_tag_weights_from_outcomes(db_outcomes: list[dict]) -> dict:
    """Builds a simple per-tag weight adjustment from real outcome history.
    This is a heuristic, not machine learning: tags present in listings
    that led to interviews/offers get boosted; tags from rejections/ghosts
    get slightly penalized. db_outcomes: [{"tags": [...], "status": "..."}]
    """
    weights = {}
    for o in db_outcomes:
        delta = {"interview": 1.5, "offer": 2.5, "applied": 0, "rejected": -1.0, "ghosted": -0.5}.get(o["status"], 0)
        for tag in o.get("tags", []):
            weights[tag] = weights.get(tag, 0) + delta
    return weights
 
 
def rank_listings(listings: list[dict], profile: dict, top_n: int = 10, tag_weights: dict | None = None) -> list[dict]:
    tag_weights = tag_weights or {}
    scored = []
    for listing in listings:
        if listing["type"] not in profile.get("target_types", []):
            continue
        match = score_listing(listing, profile)
        if match is None:
            continue
        # Apply the outcome-based adjustment on top of the base score.
        adjustment = sum(tag_weights.get(tag, 0) for tag in listing["tags"])
        match["score_pct"] = max(0, min(100, round(match["score_pct"] + adjustment)))
        match["rationale"] = explain_score(listing, match, profile)
        scored.append({**listing, **match})
    scored.sort(key=lambda l: l["score_pct"], reverse=True)
    return scored[:top_n]
 
 
def compute_roadmap_alignment(listing: dict, milestones: list) -> dict | None:
    """Fast, free, deterministic alignment between a listing and the
    user's roadmap - tag overlap against each milestone's title and
    description. Shared by /listings/matches (shown on every card)
    and the auto-apply confidence calculation (a listing that clearly
    advances the roadmap is a stronger auto-send candidate than one
    that merely scores well on keywords).
    """
    if not milestones:
        return None
    listing_tags = set(t.lower() for t in listing.get("tags", []))
    best_stage, best_overlap = None, 0
    for m in milestones:
        milestone_text = (m["title"] + " " + m["description"]).lower()
        overlap = sum(1 for tag in listing_tags if tag in milestone_text)
        if overlap > best_overlap:
            best_overlap = overlap
            best_stage = m
    if not best_stage or best_overlap == 0:
        return None
    return {"stage": best_stage["stage"], "title": best_stage["title"], "matched_on": best_overlap}
 
