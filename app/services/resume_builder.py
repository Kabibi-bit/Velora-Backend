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
 
