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
from datetime import date, datetime
from typing import Optional
from app.services.embeddings import semantic_similarity_factor
 
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
    {"marketing", "growth", "branding", "socialmedia"},
    {"finance", "financial", "accounting"},
    {"bio", "biology", "biotech"},
    {"sales", "businessdevelopment", "accountexecutive", "ae", "bd"},
    {"operations", "ops", "logistics", "supplychain"},
    {"hr", "humanresources", "peopleops", "recruiting", "talentacquisition"},
    {"customersuccess", "customersupport", "clientsuccess", "accountmanagement"},
    {"healthcare", "clinical", "patientcare", "medical"},
    {"legal", "compliance", "paralegal", "regulatory"},
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
 
 
def _has_dealbreaker(tags: list[str], dealbreakers: str) -> bool:
    """Fixed a real false-positive: the previous check was a blind
    substring containment (`tag in dealbreakers_text`), which meant a
    dealbreaker of "javascript" would silently exclude any listing
    tagged "java" - a completely different, unrelated language -
    because "java" is literally a substring of "javascript". Dealbreakers
    are meant to be a precise safety filter; a false-positive here
    means hiding a genuinely good match for no real reason. This uses
    the same word-boundary-respecting tokenizer used everywhere else
    in matching, so "java" and "javascript" are correctly treated as
    distinct terms, not substrings of one another.
    """
    if not dealbreakers:
        return False
    dealbreaker_tokens = set(tokenize(dealbreakers))
    if not dealbreaker_tokens:
        return False
    for tag in tags:
        tag_tokens = set(tokenize(tag)) | {tag.lower().replace("-", "")}
        if dealbreaker_tokens & tag_tokens:
            return True
    return False
 
 
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
        # Remote work is inherently compatible with living anywhere -
        # a real, positive signal even when someone stated a specific
        # city rather than explicitly asking for remote. Smaller than
        # an explicit remote match, since we don't know for certain
        # they'd prefer it over staying near their stated city.
        if "remote" in listing_loc:
            return 0.75, "remote, which works regardless of your location"
    return 0.0, None
 
 
def _description_overlap_factor(listing: dict, goal_tokens: list[str], skill_tokens: list[str], matched_tag_terms: set[str]) -> tuple[float, list[str]]:
    """Real signal from the actual job posting text, not just the
    6-10 tags an earlier ingestion step compressed it down to. Tag
    extraction is inherently lossy - a specific requirement mentioned
    once in a long posting can easily not survive being reduced to a
    handful of tags. This scans the title AND description for goal/
    skill terms that AREN'T already accounted for by a tag match -
    the title is often the single most information-dense field on a
    listing (a real gap existed here where a term appearing only in
    the title, never in tags or description, was completely invisible
    to this factor) - catching real signal the compression step lost,
    without needing a paid AI call for every listing in every scan.
    """
    combined_text = f"{listing.get('title') or ''} {listing.get('description') or ''}".lower()
    if not combined_text.strip():
        return 0.0, []
    desc_tokens = set(tokenize(combined_text))
    found = []
    for term in set(goal_tokens) | set(skill_tokens):
        term_clean = term.replace("-", "")
        if term_clean in matched_tag_terms:
            continue  # already credited via a tag match - avoid double-counting the same signal
        if term in desc_tokens or any(_terms_match(term, d) for d in desc_tokens):
            found.append(term)
    # Capped and weighted lower than a real tag match - this is
    # supplementary signal from a noisier source (free text vs a
    # curated tag), not a replacement for it.
    contribution = min(2.0, len(found) * 0.4)
    return contribution, found[:5]
 
 
def assess_listing_data_quality(listing: dict) -> dict:
    """Every listing gets scored with the same apparent confidence,
    but the underlying data backing that score varies enormously - a
    listing with a real description and 5+ specific tags supports a
    genuinely trustworthy score; one with a 2-word title, no
    description, and 1 generic tag does not, no matter how the math
    comes out. This is honest about that gap instead of letting a
    thin listing produce a falsely confident-looking percentage.
 
    Returns a quality tier and the specific real reasons behind it -
    not a black-box penalty.
    """
    reasons = []
    points = 0
 
    title = (listing.get("title") or "").strip()
    if len(title.split()) >= 3:
        points += 1
    else:
        reasons.append("title is very short")
 
    tags = listing.get("tags") or []
    if len(tags) >= 4:
        points += 2
    elif len(tags) >= 2:
        points += 1
    else:
        reasons.append("very few tags to match against")
 
    description = (listing.get("description") or "").strip()
    if len(description) >= 200:
        points += 2
    elif len(description) >= 50:
        points += 1
    else:
        reasons.append("no real description text - matching relies on tags alone")
 
    if listing.get("location"):
        points += 1
    else:
        reasons.append("no location listed")
 
    if listing.get("deadline"):
        points += 1
    else:
        reasons.append("no deadline listed")
 
    # Max possible: 1 (title) + 2 (tags) + 2 (description) + 1 (location) + 1 (deadline) = 7
    if points >= 6:
        tier = "rich"
    elif points >= 3:
        tier = "adequate"
    else:
        tier = "thin"
 
    return {"tier": tier, "points": points, "max_points": 7, "reasons": reasons}
 
 
def score_listing(listing: dict, profile: dict, factor_weights: dict | None = None) -> Optional[dict]:
    """Returns None if the listing is excluded by a dealbreaker, else a
    structured score dict with a top-level score_pct plus every named
    factor that contributed to it, independently inspectable.
 
    factor_weights, when provided, is the output of
    get_personalized_factor_weights() - real, per-user multipliers
    learned from logged outcomes about which TYPES of signal actually
    predict success for THIS person. Defaults to no personalization
    (every factor at its designed weight) when not provided or when
    there isn't yet enough outcome history to learn from - fully
    backward compatible.
    """
    factor_weights = factor_weights or {}
    if _has_dealbreaker(listing["tags"], profile.get("dealbreakers") or ""):
        return None
 
    goal_tokens = tokenize(f"{profile['northstar']} {profile.get('final_idea', '')}")
    skill_tokens = tokenize(profile.get("skills", ""))
    priorities = profile.get("priorities", [])
 
    goal_fit, skill_fit = 0.0, 0.0
    matched_goal, matched_skill = [], []
    matched_tag_terms = set()
    for tag in listing["tags"]:
        in_goal = any(_terms_match(t, tag) for t in goal_tokens)
        in_skill = any(_terms_match(t, tag) for t in skill_tokens)
        if in_goal:
            goal_fit += 3
            matched_goal.append(tag)
            matched_tag_terms.add(tag.replace("-", ""))
        if in_skill:
            skill_fit += 2
            matched_skill.append(tag)
            matched_tag_terms.add(tag.replace("-", ""))
 
    priority_fit = 0.0
    if "learning" in priorities and listing["type"] in ("internship", "college"):
        priority_fit += 1.5
    if "pay" in priorities and listing["type"] == "job":
        priority_fit += 1.5
 
    location_fit, location_reason = _location_fit_factor(listing, profile)
    deadline_urgency, days_left = _deadline_urgency_factor(listing)
    description_fit, description_terms = _description_overlap_factor(listing, goal_tokens, skill_tokens, matched_tag_terms)
    semantic_fit = semantic_similarity_factor(listing.get("embedding"), profile.get("embedding"))
 
    # Apply personalized weighting - each factor's REAL, learned
    # reliability for this specific person, not a generic default.
    goal_fit *= factor_weights.get("goal_fit", 1.0)
    skill_fit *= factor_weights.get("skill_fit", 1.0)
    priority_fit *= factor_weights.get("priority_fit", 1.0)
    location_fit *= factor_weights.get("location_fit", 1.0)
    deadline_urgency *= factor_weights.get("deadline_urgency", 1.0)
    description_fit *= factor_weights.get("description_fit", 1.0)
    semantic_fit *= factor_weights.get("semantic_fit", 1.0)
 
    raw_total = goal_fit + skill_fit + priority_fit + location_fit + deadline_urgency + description_fit + semantic_fit
    # Headroom only applies for factors that actually earned real
    # points for THIS listing/profile pair, not just ones that
    # theoretically could have - whether title+description text turns
    # into a real contribution depends on this specific profile's
    # terms overlapping it, not just on the text existing. Tying
    # headroom to actual earned contribution (rather than trying to
    # predict potential contribution ahead of time) means no
    # listing/profile pair is ever diluted by a ceiling for a signal
    # that contributed nothing.
    description_headroom = 2.0 if description_fit > 0 else 0.0
    semantic_headroom = 4.0 if semantic_fit > 0 else 0.0
    denom = len(listing["tags"]) * 3 + 2 + 1.5 + description_headroom + semantic_headroom
    pct = max(35, min(97, round((raw_total / denom) * 100)))
 
    # How many INDEPENDENT signals actually agree, not just the
    # magnitude of the total - two listings can land on the same
    # score_pct while one rests on four factors agreeing and the
    # other rests on a single strong tag match. That distinction is
    # real information the percentage alone can't carry.
    factors_engaged = sum(1 for v in (goal_fit, skill_fit, priority_fit, location_fit, deadline_urgency, description_fit, semantic_fit) if v > 0)
    if factors_engaged <= 1:
        signal_strength = "low"
    elif factors_engaged <= 3:
        signal_strength = "moderate"
    else:
        signal_strength = "high"
 
    return {
        "score_pct": pct,
        "goal_match_tags": list(set(matched_goal)),
        "skill_match_tags": list(set(matched_skill)),
        "signal_strength": signal_strength,
        "factors_engaged": factors_engaged,
        "personalized": bool(factor_weights),
        "data_quality": assess_listing_data_quality(listing),
        "factors": {
            "goal_fit": round(goal_fit, 2),
            "skill_fit": round(skill_fit, 2),
            "priority_fit": round(priority_fit, 2),
            "location_fit": round(location_fit, 2),
            "location_reason": location_reason,
            "deadline_urgency": round(deadline_urgency, 2),
            "days_left": days_left,
            "description_fit": round(description_fit, 2),
            "description_terms": description_terms,
            "semantic_fit": semantic_fit,
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
    if factors.get("description_terms"):
        clauses.append(f"also mentions {', '.join(factors['description_terms'][:2])} in the actual posting text, beyond what's captured in its tags")
    if factors.get("semantic_fit", 0) >= 2.0:
        clauses.append("is a strong conceptual match for what you're going for, even beyond the specific words in its listing")
 
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
 
    quality_note = ""
    if match.get("data_quality", {}).get("tier") == "thin":
        quality_note = " Worth knowing: this listing itself has very little real data behind it (a short title, few tags, no real description) - treat this score as a rough starting point, not a confident read."
 
    if not clauses:
        return "Looser fit - no strong overlap with your stated goal, skills, or priorities yet, but worth a glance while broadening this cycle's search." + deadline_note + quality_note
 
    if len(clauses) == 1:
        joined = clauses[0]
    elif len(clauses) == 2:
        joined = f"{clauses[0]}, and {clauses[1]}"
    else:
        joined = ", ".join(clauses[:-1]) + f", and {clauses[-1]}"
 
    return f"This {joined}.{deadline_note}{quality_note}"
 
 
def _recency_decay(days_old: float, half_life_days: float = 90.0) -> float:
    """Exponential decay: an outcome loses half its weight every
    half_life_days. At 90 days, a rejection is worth half of what it
    was on day 1 - your skills, market, and application quality all
    genuinely change over months, so a stale outcome shouldn't hold a
    current score hostage as tightly as a fresh one.
    """
    if days_old < 0:
        days_old = 0
    return 0.5 ** (days_old / half_life_days)
 
 
def get_tag_weights_from_outcomes(db_outcomes: list[dict], as_of: "date | None" = None) -> dict:
    """Builds a per-tag weight adjustment from real outcome history,
    with two real corrections on top of the raw signal:
 
    1. Confidence-weighted shrinkage: a tag with only 1-2 logged
       outcomes gets a heavily dampened adjustment (one rejection
       shouldn't swing future scoring as much as ten would).
    2. Recency decay: an outcome from 6 months ago carries less
       weight than one from last week, since the underlying signal
       (your skills, the market, your application quality) genuinely
       changes over that time.
 
    Both are simple, explainable statistical corrections - not a
    claim of real machine learning.
    db_outcomes: [{"tags": [...], "status": "...", "updated_at": date | None}]
    """
    as_of = as_of or date.today()
    raw_deltas: dict[str, list[float]] = {}
    for o in db_outcomes:
        delta = {"interview": 1.5, "offer": 2.5, "applied": 0, "rejected": -1.0, "ghosted": -0.5}.get(o["status"], 0)
        updated_at = o.get("updated_at")
        decay = 1.0
        if updated_at:
            if isinstance(updated_at, datetime):
                outcome_date = updated_at.date()
            elif isinstance(updated_at, date):
                outcome_date = updated_at
            else:
                outcome_date = date.fromisoformat(str(updated_at)[:10])
            days_old = (as_of - outcome_date).days
            decay = _recency_decay(days_old)
        for tag in o.get("tags", []):
            raw_deltas.setdefault(tag, []).append(delta * decay)
 
    weights = {}
    for tag, deltas in raw_deltas.items():
        n = len(deltas)
        avg = sum(deltas) / n
        # Shrinkage factor: approaches 1.0 as n grows, stays small for n=1-2.
        # n=1 -> 0.33, n=3 -> 0.6, n=5 -> 0.71, n=10 -> 0.83
        confidence = n / (n + 2)
        weights[tag] = round(avg * confidence, 4)
    return weights
 
 
FACTOR_NAMES = ["goal_fit", "skill_fit", "priority_fit", "location_fit", "deadline_urgency", "description_fit", "semantic_fit"]
POSITIVE_STATUSES = {"interview", "offer"}
PRESENTABLE_MIN_SCORE = 50  # well above the 35 floor - genuinely indicates real signal, not just barely-nonzero
PRESENTABLE_MIN_SIGNAL = {"moderate", "high"}  # excludes "low" - a single weak factor clearing the score floor still isn't a real match
 
 
def compute_factor_reliability(applications_with_outcomes: list[dict], as_of: "date | None" = None) -> dict:
    """The genuinely higher-order learning capability: not which TAGS
    predict success for this person (get_tag_weights_from_outcomes
    already covers that), but which TYPES OF SIGNAL do. Maybe this
    person's stated goal text is aspirational and doesn't actually
    predict what they succeed at, while their concrete skills do -
    or maybe semantic similarity is catching real fits that keyword
    matching misses for them specifically. No mainstream job platform
    does this: audits which of its own reasoning signals are actually
    trustworthy, per person, from real logged outcomes.
 
    Applies the same recency decay as get_tag_weights_from_outcomes -
    a pattern from 8 months ago shouldn't hold as much weight as one
    from last week, since the underlying signal (the job market, this
    person's actual skills, how they write applications) genuinely
    changes over that time. Older versions of this function treated
    every outcome as equally current forever, which was a real
    inconsistency with the tag-level learner.
 
    applications_with_outcomes: [{"factors_snapshot": {...},
    "outcome_status": "...", "updated_at": date | datetime | None}]
    Returns: {factor_name: reliability_multiplier}. 1.0 = neutral
    (insufficient data, or this factor performs at baseline).
    Above 1.0 = this factor's presence has genuinely correlated with
    better outcomes for this person, weighted toward their more
    recent history. Below 1.0 = it hasn't.
    """
    as_of = as_of or date.today()
 
    def _decay_for(app: dict) -> float:
        updated_at = app.get("updated_at")
        if not updated_at:
            return 1.0  # no timestamp available - treat as current rather than discard
        outcome_date = updated_at.date() if isinstance(updated_at, datetime) else (updated_at if isinstance(updated_at, date) else date.fromisoformat(str(updated_at)[:10]))
        return _recency_decay((as_of - outcome_date).days)
 
    usable = [a for a in applications_with_outcomes if a.get("factors_snapshot")]
    if len(usable) < 4:
        return {f: 1.0 for f in FACTOR_NAMES}  # too little data to trust any personalization yet
 
    weights = [_decay_for(a) for a in usable]
    total_weight = sum(weights)
    positive_weight = sum(w for a, w in zip(usable, weights) if a["outcome_status"] in POSITIVE_STATUSES)
    baseline_rate = positive_weight / total_weight if total_weight > 0 else 0
    if baseline_rate == 0:
        return {f: 1.0 for f in FACTOR_NAMES}  # no positive outcomes at all yet - nothing to learn a lift from
 
    multipliers = {}
    for factor in FACTOR_NAMES:
        engaged = [(a, w) for a, w in zip(usable, weights) if (a["factors_snapshot"].get(factor) or 0) > 0]
        n = len(engaged)  # raw count still gates the confidence floor - a single very-recent outcome shouldn't look like strong evidence just because its weight is high
        if n < 2:
            multipliers[factor] = 1.0
            continue
        engaged_weight = sum(w for _, w in engaged)
        engaged_positive_weight = sum(w for a, w in engaged if a["outcome_status"] in POSITIVE_STATUSES)
        engaged_rate = engaged_positive_weight / engaged_weight if engaged_weight > 0 else 0
        raw_multiplier = engaged_rate / baseline_rate if baseline_rate > 0 else 1.0
        # Same confidence-weighted shrinkage discipline as the tag
        # learner: a multiplier built from 2 outcomes should barely
        # move from neutral; one built from 15 can move more.
        confidence = n / (n + 3)
        shrunk_multiplier = 1.0 + (raw_multiplier - 1.0) * confidence
        multipliers[factor] = round(max(0.3, min(2.0, shrunk_multiplier)), 3)  # bounded - never zero out or triple-count a factor entirely from heuristic learning alone
    return multipliers
 
 
def get_personalized_factor_weights(db_applications: list[dict]) -> dict:
    """Wraps compute_factor_reliability for the real DB-shaped input:
    applications joined with their eventual outcome status. See the
    route layer for how this join is actually built.
    """
    return compute_factor_reliability(db_applications)
 
 
def audit_personalization_effect(applications_with_outcomes: list[dict]) -> dict:
    """The self-audit no mainstream job platform does: checks whether
    its OWN personalization is actually helping, instead of assuming
    a cleverer-sounding algorithm is automatically a better one. It's
    entirely possible personalized weighting moves scores around
    without making them more accurate for a given person - or even
    makes them worse. This catches that honestly rather than hiding
    behind the appearance of sophistication.
 
    applications_with_outcomes: [{"confidence_pct": float,
    "counterfactual_confidence_pct": float | None, "outcome_status": str}]
 
    Method: a simple calibration-loss comparison (lower is better) -
    for a positive outcome, a well-calibrated score should have been
    high; for a negative outcome, it should have been low. Compares
    total loss for the real (personalized) score against what the
    same application would have scored without personalization,
    restricted to cases where personalization actually moved the
    number meaningfully (otherwise there's nothing to compare).
    """
    POSITIVE_STATUSES = {"interview", "offer"}
 
    def loss(score: float, was_positive: bool) -> float:
        return (100 - score) if was_positive else score
 
    comparable = [
        a for a in applications_with_outcomes
        if a.get("counterfactual_confidence_pct") is not None
        and abs(float(a["confidence_pct"]) - float(a["counterfactual_confidence_pct"])) >= 3
    ]
    if len(comparable) < 4:
        return {"verdict": "insufficient_data", "sample_size": len(comparable), "note": "Not enough applications yet where personalization actually changed the score by a meaningful amount - need at least 4 to draw a real conclusion."}
 
    personalized_loss = sum(loss(float(a["confidence_pct"]), a["outcome_status"] in POSITIVE_STATUSES) for a in comparable) / len(comparable)
    baseline_loss = sum(loss(float(a["counterfactual_confidence_pct"]), a["outcome_status"] in POSITIVE_STATUSES) for a in comparable) / len(comparable)
    improvement = baseline_loss - personalized_loss  # positive = personalization reduced error (helping)
 
    if improvement > 3:
        verdict = "helping"
    elif improvement < -3:
        verdict = "hurting"
    else:
        verdict = "neutral"
 
    return {
        "verdict": verdict,
        "sample_size": len(comparable),
        "personalized_avg_error": round(personalized_loss, 2),
        "baseline_avg_error": round(baseline_loss, 2),
        "improvement": round(improvement, 2),
    }
 
 
def rank_listings(listings: list[dict], profile: dict, top_n: int = 10, tag_weights: dict | None = None, factor_weights: dict | None = None) -> list[dict]:
    """Same quality gate as rank_listings_with_near_misses - never
    pads results with mediocre listings just to hit top_n. This
    matters here as much as the browse view: auto-apply calls this
    to decide what to send applications to, and it should never
    "auto-apply" to something that barely cleared the scoring floor
    just because the count needed filling.
    """
    tag_weights = tag_weights or {}
    scored = []
    for listing in listings:
        if listing["type"] not in profile.get("target_types", []):
            continue
        match = score_listing(listing, profile, factor_weights=factor_weights)
        if match is None:
            continue
        adjustment = sum(tag_weights.get(tag, 0) for tag in listing["tags"])
        match["score_pct"] = max(0, min(100, round(match["score_pct"] + adjustment)))
        match["rationale"] = explain_score(listing, match, profile)
        scored.append({**listing, **match})
    scored.sort(key=lambda l: l["score_pct"], reverse=True)
    presentable = [s for s in scored if s["score_pct"] >= PRESENTABLE_MIN_SCORE and s["signal_strength"] in PRESENTABLE_MIN_SIGNAL]
    return presentable[:top_n]
 
 
 
def rank_listings_with_near_misses(listings: list[dict], profile: dict, top_n: int = 10, near_miss_n: int = 5, tag_weights: dict | None = None, factor_weights: dict | None = None) -> tuple[list[dict], list[dict]]:
    """The 'why not' transparency feature - most job boards silently
    drop everything below the cutoff. This surfaces the next several
    listings just below it, with the SAME real, grounded rationale
    already computed for every listing (not a separately-invented
    negative framing) - genuine reasoning, shown either way.
 
    Matches are gated by real quality, not padded to a fixed count:
    every prior version of this function always returned exactly
    top_n listings, even when the best available option barely
    cleared the scoring floor - showing something mediocre as a
    confident "top match" is the same dishonesty as showing near-
    misses under a falsely negative framing, just in the opposite
    direction. A cycle with only 2 genuinely good matches returns 2,
    not 10 padded down to fill the count. See PRESENTABLE_MIN_SCORE /
    PRESENTABLE_MIN_SIGNAL for the actual bar.
    """
    tag_weights = tag_weights or {}
    scored = []
    for listing in listings:
        if listing["type"] not in profile.get("target_types", []):
            continue
        match = score_listing(listing, profile, factor_weights=factor_weights)
        if match is None:
            continue
        adjustment = sum(tag_weights.get(tag, 0) for tag in listing["tags"])
        match["score_pct"] = max(0, min(100, round(match["score_pct"] + adjustment)))
        match["rationale"] = explain_score(listing, match, profile)
        scored.append({**listing, **match})
    scored.sort(key=lambda l: l["score_pct"], reverse=True)
 
    presentable = [s for s in scored if s["score_pct"] >= PRESENTABLE_MIN_SCORE and s["signal_strength"] in PRESENTABLE_MIN_SIGNAL]
    matches = presentable[:top_n]
 
    # Adaptive, not fixed: when fewer than top_n listings genuinely
    # clear the bar, the person still deserves a full picture of what
    # else is out there - showing more near-misses to make up the
    # shortfall gives them real options to look at, never by lowering
    # the bar for what counts as a "match", only by being more
    # generous about what counts as "worth showing you why it fell
    # short". A cycle with only 2 real matches now shows up to 13
    # honestly-labeled near-misses instead of a fixed 5.
    shortfall = max(0, top_n - len(matches))
    adaptive_near_miss_n = near_miss_n + shortfall
 
    shown_ids = {m["id"] for m in matches}
    near_misses = [s for s in scored if s["id"] not in shown_ids][:adaptive_near_miss_n]
 
    return matches, near_misses
 
 
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
 
 
def generate_deep_personalization_insights(anthropic_client, applications: list[dict]) -> dict:
    """The genuine depth upgrade beyond factor-category reweighting:
    compute_factor_reliability() can tell you "skill_fit predicts
    success 36% better for you" - a real number, but a shallow one.
    It can never say WHICH skills, WHY, or ground that in what
    actually happened, because it only ever sees pre-computed numeric
    tallies, never the real application content.
 
    This reads the actual draft text, the actual listing, and the
    real outcome for each application, and asks Claude to find
    specific, concrete patterns grounded in that real content - not
    generic career advice, and not another number. This is the part
    of personalization that genuinely can't be done by arithmetic.
 
    applications: [{"draft_content": str, "listing_title": str,
    "listing_org": str, "listing_tags": list[str], "outcome_status": str}]
    """
    usable = [a for a in applications if a.get("draft_content") and a.get("outcome_status")]
    if len(usable) < 4:
        return {
            "insights": [],
            "sample_size": len(usable),
            "note": "Not enough applications with both a draft and a logged outcome yet - need at least 4 to find a real pattern in what you've actually written, rather than guessing.",
        }
 
    applications_text = "\n\n".join(
        f"Application {i+1} - to \"{a['listing_title']}\" at {a['listing_org']} (tags: {', '.join(a.get('listing_tags', []))}). "
        f"Outcome: {a['outcome_status']}.\nWhat was actually sent:\n\"{a['draft_content'][:600]}\""
        for i, a in enumerate(usable)
    )
    prompt = (
        f"Here are {len(usable)} real job applications a candidate actually sent, each with what they "
        f"actually wrote and what really happened:\n\n{applications_text}\n\n"
        "Find SPECIFIC, CONCRETE patterns in what was actually written that correlate with the real "
        "outcomes - not generic career advice like 'tailor your resume' or 'follow up promptly'. Look for "
        "things like: specific phrasings, whether achievements were quantified vs described generically, "
        "which topics or skills were emphasized, sentence structure, length, tone, what got left out. "
        "Reference the actual applications by number when you find something. If there's truly no clear "
        "pattern yet, say that honestly rather than inventing one - a small sample size deserves epistemic "
        "humility, not a confident-sounding guess.\n\n"
        "Return a JSON object with exactly these two keys:\n"
        "- insights: an array of 2-4 strings, each a specific, content-grounded finding (or, if genuinely "
        "no pattern exists, a single honest string saying so)\n"
        "- confidence: \"low\", \"moderate\", or \"high\" - how confident this pattern-finding actually is "
        "given the sample size and how consistent the pattern is\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(text)
    parsed["sample_size"] = len(usable)
    parsed["note"] = None
    return parsed
 
 
# Curated, meaningful pairs rather than all 21 combinations of 7
# factors - each pairing tests a genuine hypothesis worth checking,
# not a combinatorial fishing expedition that would mostly return
# noise. Framed as (label, factor_a, factor_b).
INTERACTION_PAIRS = [
    ("skill overlap + conceptual fit", "skill_fit", "semantic_fit"),
    ("stated goal + conceptual fit", "goal_fit", "semantic_fit"),
    ("skill overlap + posting depth", "skill_fit", "description_fit"),
    ("location + timing", "location_fit", "deadline_urgency"),
]
 
 
def compute_factor_interactions(applications_with_outcomes: list[dict]) -> list[dict]:
    """Goes a real step beyond compute_factor_reliability: that
    function can only ever say whether a SINGLE factor category
    predicts success in isolation. It has no way to notice that two
    signals might only work TOGETHER - e.g. real skill overlap might
    only actually predict success when it's paired with genuine
    conceptual fit, and neither alone is enough. This checks for that
    kind of synergy (or, just as honestly, redundancy) directly from
    real outcomes - a statistical concept (interaction effects) that
    even sophisticated platforms rarely expose transparently to users.
 
    Method: for each curated pair (A, B), bucket applications into
    four groups by whether each factor was engaged (>0) or not.
    Compare the real positive rate in the "both engaged" bucket
    against what you'd expect if the two factors' individual lifts
    were purely additive. A meaningfully higher-than-expected rate is
    genuine synergy; meaningfully lower is redundancy/interference.
 
    Returns only pairs with enough real data to say something
    concrete - never guesses from a thin sample.
    """
    usable = [a for a in applications_with_outcomes if a.get("factors_snapshot")]
    if len(usable) < 8:
        return []  # interaction effects need more data than single-factor learning to say anything real - honest to return nothing rather than guess
 
    overall_positive = sum(1 for a in usable if a["outcome_status"] in POSITIVE_STATUSES)
    baseline_rate = overall_positive / len(usable)
 
    findings = []
    for label, factor_a, factor_b in INTERACTION_PAIRS:
        def engaged(a, factor):
            return (a["factors_snapshot"].get(factor) or 0) > 0
 
        both_high = [a for a in usable if engaged(a, factor_a) and engaged(a, factor_b)]
        a_only = [a for a in usable if engaged(a, factor_a) and not engaged(a, factor_b)]
        b_only = [a for a in usable if not engaged(a, factor_a) and engaged(a, factor_b)]
 
        if len(both_high) < 3 or len(a_only) < 2 or len(b_only) < 2:
            continue  # not enough real data in each bucket to say anything concrete about this pair
 
        def positive_rate(apps):
            return sum(1 for a in apps if a["outcome_status"] in POSITIVE_STATUSES) / len(apps)
 
        both_high_rate = positive_rate(both_high)
        a_only_lift = positive_rate(a_only) - baseline_rate
        b_only_lift = positive_rate(b_only) - baseline_rate
        expected_both_high_rate = baseline_rate + a_only_lift + b_only_lift  # purely additive assumption
        synergy = both_high_rate - expected_both_high_rate
 
        # Confidence-shrink by the smallest bucket's sample size - the
        # weakest link in a 3-way comparison, same discipline as
        # every other learned number in this app.
        min_n = min(len(both_high), len(a_only), len(b_only))
        confidence = min_n / (min_n + 4)
        shrunk_synergy = synergy * confidence
 
        if shrunk_synergy >= 0.15:
            findings.append({
                "pair": label, "type": "synergy",
                "both_engaged_rate": round(both_high_rate, 3),
                "expected_if_additive": round(max(0, min(1, expected_both_high_rate)), 3),
                "sample_size": len(both_high),
            })
        elif shrunk_synergy <= -0.15:
            findings.append({
                "pair": label, "type": "redundant",
                "both_engaged_rate": round(both_high_rate, 3),
                "expected_if_additive": round(max(0, min(1, expected_both_high_rate)), 3),
                "sample_size": len(both_high),
            })
 
    return findings
 
