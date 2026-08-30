"""Turns a person's own real, plain-language account of their
experience into strong resume language - never generates a work
history from scratch.
 
This exists because a resume is fundamentally a claim about
verifiable past experience: real employers, real dates, real things
someone actually did. Nothing else in this app collects that kind of
structured history (Profile.skills is just a loose text string), and
building a "generate my resume" feature on top of a career goal and a
skills string would leave an AI with no real facts to work from -
meaning it would have to invent company names, dates, and
achievements to produce anything resume-shaped at all. That's not a
UX shortfall, it's misrepresenting a real person to a real employer,
and it stays out regardless of how much better it might make the
feature look.
 
The honest version: the person enters their own real work/education/
project history first (ResumeEntry rows - see db_models.py), in their
own words, however rough. This module's only job is to strengthen the
PHRASING of what they actually wrote - stronger verbs, tighter
structure, resume conventions - never to add a fact, metric, or
responsibility they didn't state themselves.
"""
import re
from app.services.matching import tokenize, _terms_match
 
# Common connective/filler words that clear the 4+ character bar but
# aren't genuine skill or domain keywords - without this, a stated
# goal like "become a frontend engineer using JS" surfaces "become",
# "engineer", and "using" as if they were missing skills, which isn't
# actionable advice for anyone reviewing the ATS check.
_STOPWORDS = {
    "become", "engineer", "engineering", "using", "with", "work", "working",
    "want", "goal", "into", "role", "roles", "career", "field", "someone",
    "person", "years", "year", "experience", "focused", "break", "ship",
    "features", "backed", "real", "help", "helping", "make", "making",
    "build", "building", "learn", "learning", "have", "that", "this",
    "from", "about", "their", "them", "they", "very", "more", "most",
}
 
 
def _meaningful_tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if len(t) > 3 and t not in _STOPWORDS}
 
 
def _find_fabricated_numbers(original: str, polished: str) -> list[str]:
    """A real, deterministic safety-net check, not a substitute for
    the prompt's anti-fabrication instructions but a second, testable
    layer on top of it - the same two-layer pattern already used for
    scholarship discovery elsewhere in this app. Flags any digit
    sequence appearing in the polished bullet that appears nowhere in
    the original raw_description - a common shape a fabricated metric
    takes (a specific percentage, dollar figure, or count the person
    never actually stated).
    """
    original_numbers = set(re.findall(r"\d+\.?\d*", original))
    polished_numbers = set(re.findall(r"\d+\.?\d*", polished))
    return sorted(polished_numbers - original_numbers)
 
 
def polish_resume_entry(anthropic_client, entry: dict) -> dict:
    """entry: {entry_type, title, org, start_date, end_date, raw_description}
    all real, user-provided fields. Returns {bullets: [str], flagged_numbers: [str]}.
 
    flagged_numbers is non-empty only when the safety-net check above
    catches a number in the output that wasn't in the input - this
    doesn't silently discard the bullets (a false positive here would
    make the feature less useful for no real safety gain, since the
    person still reviews everything before it becomes their resume),
    it surfaces the flag so the person can verify it themselves before
    trusting it.
    """
    prompt = (
        f"Here is something a real person wrote, in their own words, about something they actually did:\n\n"
        f'Role/title: "{entry["title"]}"' + (f' at {entry["org"]}' if entry.get("org") else "") + "\n"
        f'What they said they did, in their own words: "{entry["raw_description"]}"\n\n'
        "Turn this into 2-4 strong resume bullet points.\n\n"
        "Critical rule, more important than anything else here: you may only strengthen the PHRASING of "
        "what they actually wrote - stronger action verbs, tighter and more concrete language, standard "
        "resume conventions. You may NEVER add a specific number, percentage, dollar amount, team size, "
        "tool, responsibility, or outcome that isn't already stated or clearly implied in what they wrote. "
        "If what they wrote is vague or doesn't include a metric, write a vague-but-honest bullet rather "
        "than inventing a specific one - a real person may submit this to a real employer, and a fabricated "
        "detail here is not a stylistic choice, it's misrepresenting them.\n\n"
        "Return a JSON array of 2-4 bullet point strings, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    bullets = json.loads(text)
    if not isinstance(bullets, list):
        bullets = []
 
    flagged = []
    for bullet in bullets:
        flagged.extend(_find_fabricated_numbers(entry["raw_description"], bullet))
 
    return {"bullets": bullets, "flagged_numbers": sorted(set(flagged))}
 
 
def generate_resume_summary(anthropic_client, profile: dict, entries: list[dict]) -> str:
    """A short professional summary line (1-2 sentences), grounded in
    the person's real stated goal and their real entries - framing
    what's genuinely there, not inventing new facts. Returns an empty
    string if there isn't enough real material to say anything honest.
    """
    if not profile.get("northstar") and not entries:
        return ""
 
    entry_lines = [f'- {e["title"]}' + (f' at {e["org"]}' if e.get("org") else "") for e in entries[:5]]
    prompt = (
        f'Real stated career goal: "{profile.get("northstar", "")}"\n'
        + ("Real experience entries:\n" + "\n".join(entry_lines) + "\n" if entry_lines else "")
        + "\nWrite a single, honest 1-2 sentence professional summary line for a resume, grounded only in "
        "the real goal and entries above. Do not invent skills, years of experience, or achievements not "
        "implied by what's given. No cliches like \"results-driven\" or \"passionate professional\" - write "
        "like a specific, real person, not a template.\n\n"
        "Return ONLY the summary text, nothing else."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
 
def check_ats_alignment(profile: dict, entries: list[dict]) -> dict:
    """Real, deterministic keyword coverage check - does the resume's
    actual content contain genuine overlap with what the person says
    they're targeting? Reuses the exact same synonym-aware, word-
    boundary-safe matching already proven in the core matching engine
    (see matching.py's _terms_match), so a resume that says "js" and
    a stated goal of "javascript" correctly recognize each other -
    not just literal exact-string presence, and not the old unguarded
    substring bug either (this inherits that fix automatically by
    reusing the same function, rather than re-implementing matching
    logic a second time with its own risk of drifting out of sync).
    """
    goal_and_skills = f"{profile.get('northstar', '')} {profile.get('skills', '')}"
    target_tokens = sorted(_meaningful_tokens(goal_and_skills))
    if not target_tokens:
        return {"matched_keywords": [], "missing_keywords": [], "coverage_pct": 0}
 
    resume_text = " ".join(f"{e.get('title', '')} {e.get('raw_description', '')}" for e in entries)
    resume_tokens = set(tokenize(resume_text))
 
    matched, missing = [], []
    for t in target_tokens:
        (matched if any(_terms_match(t, rt) for rt in resume_tokens) else missing).append(t)
 
    coverage_pct = round(len(matched) / len(target_tokens) * 100)
    return {"matched_keywords": matched, "missing_keywords": missing, "coverage_pct": coverage_pct}
 
 
def rank_entries_for_listing(entries: list[dict], listing: dict) -> list[dict]:
    """Which of the person's REAL entries are most worth leading with
    for THIS specific listing - reuses the same synonym-aware term
    matching, applied to real entry content instead of a goal string.
    Never changes what an entry says, only how entries get ordered:
    the honest content stays identical regardless of which job it's
    being tailored for, only the emphasis (order) changes. Returns
    entries sorted by real overlap, each annotated with which of the
    listing's own tags it actually matched.
    """
    listing_tags = listing.get("tags", [])
    scored = []
    for e in entries:
        entry_tokens = set(tokenize(f"{e.get('title', '')} {e.get('raw_description', '')}"))
        matched_tags = [tag for tag in listing_tags if any(_terms_match(tag.lower(), t) for t in entry_tokens)]
        scored.append({**e, "relevance_tags": matched_tags, "relevance_score": len(matched_tags)})
    scored.sort(key=lambda e: e["relevance_score"], reverse=True)
    return scored
 
