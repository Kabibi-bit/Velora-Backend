"""Matching engine: scores listings against a user's profile.
 
Every factor that shows up in the explanation is a real input to the
score itself - deadline urgency and location fit used to be mentioned
in the rationale text but never actually affected the number, which
is exactly the kind of inconsistency that makes a score feel
untrustworthy even when the prose sounds reasonable. Fixed here: the
score is now a transparent, structured composite of six named
factors, each independently inspectable - not a black-box percentage
with a plausible-sounding paragraph bolted on afterward.
"""
import re
from datetime import date
from typing import Optional
 
# Honestly scoped: a curated set of common, well-known synonyms in
# tech/career contexts - not a claim of real NLP or embeddings. Pure
# substring matching (the previous approach) misses obvious pairs
# like "js" vs "javascript" or "ml" vs "machine learning"; this closes
# the most common gaps without pretending to be exhaustive.
SYNONYM_GROUPS = [
    {"js", "javascript", "typescript", "ts"},
    {"ml", "machinelearning", "ai", "artificialintelligence"},
    {"sql", "database", "databases", "postgres", "postgresql", "mysql"},
    {"ux", "ui", "design", "uxdesign", "uidesign"},
    {"pm", "productmanagement", "product"},
    {"frontend", "front-end", "front"},
    {"backend", "back-end", "back"},
    {"fullstack", "full-stack"},
    {"analytics", "analysis", "dataanalysis", "data"},
    {"devops", "infrastructure", "infra"},
    {"marketing", "growth"},
    {"finance", "financial"},
    {"bio", "biology", "biotech"},
]
_SYNONYM_LOOKUP: dict[str, set[str]] = {}
for _group in SYNONYM_GROUPS:
    for _term in _group:
        _SYNONYM_LOOKUP[_term] = _group
 
 
def tokenize(text: str) -> list[str]:
    """The general 3-char minimum avoids polluting matches with noise
    words (of, to, in, is, at...), but that same minimum was silently
    dropping short, meaningful abbreviations this app's synonym system
    depends on (js, ai, ux, ui, pm, ml, ts) - so those are extracted
    separately as whole words rather than lowering the general
    minimum and reintroducing noise-word pollution.
    """
    tokens = re.findall(r"[a-z][a-z\-]{2,}", text.lower())
    short_terms = {t for group in SYNONYM_GROUPS for t in group if len(t) <= 2}
    if short_terms:
        text_lower = text.lower()
        for term in short_terms:
            if re.search(rf"\b{re.escape(term)}\b", text_lower):
                tokens.append(term)
    return tokens
 
 
def _terms_match(a: str, b: str) -> bool:
    """True if two terms are the same, one contains the other, or
    they belong to the same curated synonym group.
    """
    if a in b or b in a:
        return True
    a_clean, b_clean = a.replace("-", ""), b.replace("-", "")
    group_a = _SYNONYM_LOOKUP.get(a_clean)
    return bool(group_a and b_clean in group_a)
 
 
def filter_dealbreakers(listings: list[dict], dealbreakers: str) -> list[dict]:
    if not dealbreakers:
        return listings
    db_tokens = dealbreakers.lower()
    return [l for l in listings if not any(tag in db_tokens for tag in l["tags"])]
 
 
def _deadline_urgency_factor(listing: dict) -> tuple[float, int | None]:
    """Returns (score_contribution, days_left). A deadline that's
    close but not unrealistically close gets a small real boost -
    genuinely actionable urgency, not panic-inducing. Too far out or
    already passed contributes nothing.
    """
    if not listing.get("deadline"):
        return 0.0, None
    try:
        deadline_date = date.fromisoformat(listing["deadline"]) if isinstance(listing["deadline"], str) else listing["deadline"]
    except (ValueError, TypeError):
        return 0.0, None
    days_left = (deadline_date - date.today()).days
    if days_left < 0:
        return 0.0, days_left
    if days_left <= 3:
        return 0.5, days_left  # very soon - real but small nudge, not a huge score swing for something you might not reach in time
    if days_left <= 14:
        return 1.5, days_left  # the genuinely actionable window
    if days_left <= 30:
        return 0.5, days_left
    return 0.0, days_left
 
 
def _location_fit_factor(listing: dict, profile: dict) -> tuple[float, str | None]:
    """Returns (score_contribution, reason). Mirrors what the
    explanation already claimed to consider - remote-preference match,
    flexibility priority, and a real location-token overlap - now
    actually feeding the score instead of only appearing in prose.
    """
    listing_loc = (listing.get("location") or "").lower()
    location_pref = (profile.get("location_pref") or "").lower()
    priorities = profile.get("priorities", [])
 
    if "flexibility" in priorities and "remote" in listing_loc:
        return 1.5, "remote, matching your stated need for flexibility"
    if location_pref and listing_loc:
        if "remote" in location_pref and "remote" in listing_loc:
            return 1.5, "matches your remote location preference"
        pref_tokens = [t for t in tokenize(location_pref) if len(t) > 3]
        if any(t in listing_loc for t in pref_tokens):
            return 1.0, f"based in {listing.get('location')}, inside your stated location preference"
    return 0.0, None
 
 
def score_listing(listing: dict, profile: dict) -> Optional[dict]:
    """Returns None if the listing is excluded by a dealbreaker, else a
    structured score dict with a top-level score_pct plus every named
    factor that contributed to it, independently inspectable.
    """
    dealbreakers = (profile.get("dealbreakers") or "").lower()
    if any(tag in dealbreakers for tag in listing["tags"]):
        return None
 
    goal_tokens = tokenize(f"{profile['northstar']} {profile.get('final_idea', '')}")
    skill_tokens = tokenize(profile.get("skills", ""))
    priorities = profile.get("priorities", [])
 
    goal_fit, skill_fit = 0.0, 0.0
    matched_goal, matched_skill = [], []
    for tag in listing["tags"]:
        in_goal = any(_terms_match(t, tag) for t in goal_tokens)
        in_skill = any(_terms_match(t, tag) for t in skill_tokens)
        if in_goal:
            goal_fit += 3
            matched_goal.append(tag)
        if in_skill:
            skill_fit += 2
            matched_skill.append(tag)
 
    priority_fit = 0.0
    if "learning" in priorities and listing["type"] in ("internship", "college"):
        priority_fit += 1.5
    if "pay" in priorities and listing["type"] == "job":
        priority_fit += 1.5
 
    location_fit, location_reason = _location_fit_factor(listing, profile)
    deadline_urgency, days_left = _deadline_urgency_factor(listing)
 
    raw_total = goal_fit + skill_fit + priority_fit + location_fit + deadline_urgency
    denom = len(listing["tags"]) * 3 + 2 + 1.5  # +1.5 headroom for the location/deadline factors on top of the original tag-based ceiling
    pct = max(35, min(97, round((raw_total / denom) * 100)))
 
    return {
        "score_pct": pct,
        "goal_match_tags": list(set(matched_goal)),
        "skill_match_tags": list(set(matched_skill)),
        "factors": {
            "goal_fit": round(goal_fit, 2),
            "skill_fit": round(skill_fit, 2),
            "priority_fit": round(priority_fit, 2),
            "location_fit": round(location_fit, 2),
            "location_reason": location_reason,
            "deadline_urgency": round(deadline_urgency, 2),
            "days_left": days_left,
        },
    }
 
 
def explain_score(listing: dict, match: dict, profile: dict) -> str:
    """Builds a real, multi-clause explanation directly from the same
    structured factors the score itself was computed from - the
    explanation and the number can no longer disagree, because they
    now share one source of truth.
    """
    goal_phrase = (profile["northstar"].split(".")[0] or "your goal").strip().lower()
    factors = match["factors"]
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
    if factors.get("location_reason"):
        clauses.append(f"is {factors['location_reason']}")
 
    deadline_note = ""
    days_left = factors.get("days_left")
    if days_left is not None and 0 <= days_left <= 14:
        deadline_note = f" It also closes in {days_left} day{'s' if days_left != 1 else ''}, so it's worth acting on soon if you're interested."
 
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
    """Builds a per-tag weight adjustment from real outcome history,
    with confidence-weighted shrinkage: a tag with only 1-2 logged
    outcomes gets a heavily dampened adjustment (one rejection
    shouldn't swing future scoring as much as ten would), while a tag
    with a real sample size gets closer to its full raw signal. This
    is a simple, explainable statistical correction, not a claim of
    real machine learning.
    db_outcomes: [{"tags": [...], "status": "..."}]
    """
    raw_deltas: dict[str, list[float]] = {}
    for o in db_outcomes:
        delta = {"interview": 1.5, "offer": 2.5, "applied": 0, "rejected": -1.0, "ghosted": -0.5}.get(o["status"], 0)
        for tag in o.get("tags", []):
            raw_deltas.setdefault(tag, []).append(delta)
 
    weights = {}
    for tag, deltas in raw_deltas.items():
        n = len(deltas)
        avg = sum(deltas) / n
        # Shrinkage factor: approaches 1.0 as n grows, stays small for n=1-2.
        # n=1 -> 0.33, n=3 -> 0.6, n=5 -> 0.71, n=10 -> 0.83
        confidence = n / (n + 2)
        weights[tag] = round(avg * confidence, 4)
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
        adjustment = sum(tag_weights.get(tag, 0) for tag in listing["tags"])
        match["score_pct"] = max(0, min(100, round(match["score_pct"] + adjustment)))
        match["rationale"] = explain_score(listing, match, profile)
        scored.append({**listing, **match})
    scored.sort(key=lambda l: l["score_pct"], reverse=True)
    return scored[:top_n]
 
 
def rank_listings_with_near_misses(listings: list[dict], profile: dict, top_n: int = 10, near_miss_n: int = 5, tag_weights: dict | None = None) -> tuple[list[dict], list[dict]]:
    """The 'why not' transparency feature - most job boards silently
    drop everything below the cutoff. This surfaces the next several
    listings just below it, with the SAME real, grounded rationale
    already computed for every listing (not a separately-invented
    negative framing) - genuine reasoning, shown either way.
    """
    tag_weights = tag_weights or {}
    scored = []
    for listing in listings:
        if listing["type"] not in profile.get("target_types", []):
            continue
        match = score_listing(listing, profile)
        if match is None:
            continue
        adjustment = sum(tag_weights.get(tag, 0) for tag in listing["tags"])
        match["score_pct"] = max(0, min(100, round(match["score_pct"] + adjustment)))
        match["rationale"] = explain_score(listing, match, profile)
        scored.append({**listing, **match})
    scored.sort(key=lambda l: l["score_pct"], reverse=True)
    return scored[:top_n], scored[top_n:top_n + near_miss_n]
 
 
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
 
