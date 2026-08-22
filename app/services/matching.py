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
    goal_phrase = (profile["northstar"].split(".")[0] or "your goal").lower()
    if match["goal_match_tags"]:
        return (
            f"Lines up with {goal_phrase} - overlaps on "
            f"{', '.join(match['goal_match_tags'][:2])}."
        )
    if match["skill_match_tags"]:
        return (
            f"Skills match on {', '.join(match['skill_match_tags'][:2])} - "
            f"a reasonable stepping stone."
        )
    return "Looser fit - worth a glance while broadening this cycle's search."
 
 
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
 
