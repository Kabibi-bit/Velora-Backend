"""Real evidence of grit and curiosity, grounded in a candidate's
actual behavior and their own words - never a fabricated score.
 
This exists because of a genuine, validated market signal: founders
consistently say the hiring problem isn't finding people with the
right keywords on a resume, it's finding people who actually persist
through hard problems and stay genuinely curious once the job gets
difficult. Almost nothing in mainstream hiring tooling honestly
addresses this, because "grit" and "curiosity" are real psychological
traits that no algorithm can validly score with a number - any tool
that outputs "Grit: 87/100" is making a claim it has no real basis
for, and that kind of pseudo-assessment can do real harm in a hiring
decision.
 
The honest version of this feature: surface real, specific, cited
evidence - a genuine fact about someone's application history, an
actual quote from what they wrote in their own words - and let the
human hiring manager judge it themselves. Two real sources already
exist elsewhere in this app, never built for this purpose until now:
 
1. Persistence: a candidate's real, timestamped outcome history
   (Outcome model) shows whether they kept going after facing
   multiple rejections in a row - a genuinely verifiable behavioral
   fact, not a personality inference.
2. Curiosity: the free-text answer from career_discovery's evidence-
   based survey (what draws them in, what they're proud of) is
   already real, first-person evidence of what someone finds
   genuinely engaging - never generated or inferred, always quoted
   from what the candidate actually wrote.
"""
 
NEGATIVE_STATUSES = {"rejected", "ghosted"}
 
 
def compute_persistence_signal(outcomes: list[dict]) -> dict:
    """A real, deterministic, fully-testable fact about someone's
    application behavior - never a subjective "grit score". Reports
    whether they kept applying, interviewing, or ultimately succeeded
    after facing 2 or more consecutive setbacks in a row. Businesses
    can weigh this evidence themselves; this never claims to measure
    grit as a trait, only reports what someone's real history shows.
 
    outcomes: [{"status": str, "updated_at": datetime}], any order.
    """
    if not outcomes:
        return {
            "total_applications": 0,
            "negative_outcomes": 0,
            "continued_after_setback": False,
            "longest_setback_streak": 0,
        }
 
    sorted_outcomes = sorted(outcomes, key=lambda o: o["updated_at"])
    total = len(sorted_outcomes)
    negative_count = sum(1 for o in sorted_outcomes if o["status"] in NEGATIVE_STATUSES)
 
    continued_after_setback = False
    longest_streak = 0
    current_streak = 0
    for o in sorted_outcomes:
        if o["status"] in NEGATIVE_STATUSES:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            if current_streak >= 2:
                continued_after_setback = True
            current_streak = 0
 
    return {
        "total_applications": total,
        "negative_outcomes": negative_count,
        "continued_after_setback": continued_after_setback,
        "longest_setback_streak": longest_streak,
    }
 
 
def generate_grit_curiosity_evidence(anthropic_client, persistence: dict, free_text: str | None) -> dict:
    """Combines the deterministic persistence fact with a real,
    quote-grounded read of the candidate's own words about what
    genuinely engages them - never a fabricated score for either
    trait. Requires at least one real source to say anything at all;
    honestly declines rather than inventing evidence from nothing.
    """
    has_persistence_data = persistence.get("total_applications", 0) >= 3
    has_text_data = bool(free_text and free_text.strip())
 
    if not has_persistence_data and not has_text_data:
        return {
            "grit_evidence": None,
            "curiosity_evidence": None,
            "note": "Not enough real data yet for either signal - needs at least 3 logged applications for a persistence pattern, or a completed career-discovery survey for a genuine curiosity read.",
        }
 
    context_parts = []
    if has_persistence_data:
        context_parts.append(
            f"Real application history: {persistence['total_applications']} applications logged, "
            f"{persistence['negative_outcomes']} were rejections or no-response, longest consecutive "
            f"streak of setbacks was {persistence['longest_setback_streak']}, and they "
            f"{'did' if persistence['continued_after_setback'] else 'have not yet'} continued applying, "
            "interviewing, or succeeding after a streak of 2 or more setbacks in a row."
        )
    if has_text_data:
        context_parts.append(f"In their own words, describing what they're proud of or what draws them in: \"{free_text}\"")
 
    prompt = (
        "Here is real data about a job candidate:\n\n" + "\n\n".join(context_parts) + "\n\n"
        "Write honest, specific evidence a hiring manager could actually use - not a score, not a "
        "personality label, just what the real data actually shows.\n\n"
        "For grit/persistence: describe ONLY what the application history data literally shows - do not "
        "infer character traits beyond what the numbers support. If there isn't enough data, say so plainly.\n\n"
        "For curiosity: if there's real text, quote a specific short phrase (a few words) from what they "
        "actually wrote and explain what it suggests about what genuinely engages them - never invent or "
        "paraphrase into something they didn't say. If there's no text, say so plainly.\n\n"
        "Return a JSON object with exactly these keys:\n"
        "- grit_evidence: a string with the honest persistence read, or null if there's not enough data\n"
        "- curiosity_evidence: a string with the honest, quote-grounded curiosity read, or null if there's no text\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(text)
    parsed["note"] = None
    return parsed
 
